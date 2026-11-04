"""The sandbox broker (engine/sandboxd.py): each workspace's gateway talks to its
own filtered Docker socket, and only sandbox work for THAT workspace goes through.
The integration tests run the real daemon in-process against a fake Docker daemon
on a unix socket, so every rule is proved over real HTTP framing; the docker CLI
itself is pointed at the proxy where it is installed."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import pytest
from sandboxd_rig import (
    IMAGE_ID,
    LABEL,
    NEW_ID,
    OWN_ID,
    PROFILE,
    Rig,
    _create_body,
    _policy,
    _read_response,
    _request,
    _rig,
)

from agos_core.engine import sandboxd, sandboxd_http
from agos_core.engine.sandboxd import (
    Route,
    prepare_create,
    route,
    validate_create,
    validate_exec,
)


# ---- the routing table ---------------------------------------------------------
def test_the_routes_hermes_needs_are_allowed_and_nothing_else() -> None:
    assert route("GET", "/_ping") == Route("pass")
    assert route("HEAD", "/v1.51/_ping") == Route("pass")
    assert route("GET", "/v1.51/version") == Route("pass")
    assert route("GET", "/info") == Route("pass")
    assert route("GET", "/v1.51/images/agos-sandbox:1/json") == Route("image", "agos-sandbox:1")
    assert route("POST", "/v1.51/images/create?fromImage=x").kind == "pull"
    assert route("GET", "/v1.51/containers/json?filters=%7B%7D").kind == "list"
    assert route("POST", "/v1.51/containers/create?name=hermes-1").kind == "create"
    for verb in ("start", "stop", "restart", "kill", "wait", "resize", "attach"):
        assert route("POST", f"/v1.51/containers/abc/{verb}") == Route("scoped", "abc")
    for verb in ("json", "logs", "top", "stats", "archive"):
        assert route("GET", f"/v1.51/containers/abc/{verb}") == Route("scoped", "abc")
    assert route("PUT", "/v1.51/containers/abc/archive?path=/x") == Route("scoped", "abc")
    assert route("DELETE", "/v1.51/containers/abc?v=1") == Route("scoped", "abc")
    assert route("POST", "/v1.51/containers/abc/exec") == Route("exec_create", "abc")
    assert route("POST", "/v1.51/exec/e1/start") == Route("exec_scoped", "e1")
    assert route("GET", "/v1.51/exec/e1/json") == Route("exec_scoped", "e1")
    # Everything else is refused: the raw power endpoints most of all.
    for method, path in (
        ("POST", "/v1.51/networks/create"),
        ("POST", "/v1.51/volumes/create"),
        ("POST", "/v1.51/images/build"),
        ("POST", "/v1.51/commit"),
        ("GET", "/v1.51/events"),
        ("POST", "/v1.51/containers/abc/update"),
        ("POST", "/v1.51/containers/prune"),
        ("GET", "/v1.51/containers/abc/export"),
        ("POST", "/v1.51/plugins/pull"),
        ("POST", "/v1.51/swarm/init"),
        ("GET", "/v1.51/secrets"),
    ):
        assert route(method, path).kind == "deny", path


def test_a_checked_container_ref_is_pinned_to_its_full_id() -> None:
    """The upstream target is rebuilt from the decoded segments, the container
    segment being the full id that was checked."""
    request = sandboxd_http.parse_head(
        b"POST /v1.51/containers/own/archive?path=%2Fx HTTP/1.1\r\nHost: d\r\n\r\n"
    )
    pinned = ("containers", OWN_ID, *request.segments[2:])
    assert request.target(pinned) == f"/v1.51/containers/{OWN_ID}/archive?path=%2Fx"


# ---- create validation -----------------------------------------------------------
def test_a_real_hermes_create_body_passes(tmp_path: Path) -> None:
    assert validate_create(_create_body(tmp_path), _policy(tmp_path)) is None


def test_create_refuses_privilege_and_foreign_paths(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    (tmp_path / "other-ws").mkdir()

    def refused(**over: object) -> str:
        why = validate_create(_create_body(tmp_path, **over), policy)
        assert why is not None, over
        return why

    def with_host(**host_over: object) -> dict[str, object]:
        body = _create_body(tmp_path)
        host = dict(body["HostConfig"])  # type: ignore[call-overload]
        host.update(host_over)
        body["HostConfig"] = host
        return body

    assert "image" in refused(Image="ubuntu:latest")
    assert "label" in refused(Labels={"hermes-agent": "1", "hermes-profile": "other-ws"})
    assert "hermes-agent" in refused(Labels={"hermes-profile": LABEL})
    for host_over, needle in (
        ({"Privileged": True}, "Privileged"),
        ({"Binds": ["/etc:/host-etc"]}, "not this workspace's"),
        ({"Binds": [f"{tmp_path}/other-ws:/x"]}, "not this workspace's"),
        ({"Binds": [f"{tmp_path}/nowhere:/x"]}, "does not exist"),
        ({"Binds": [str(tmp_path / "shared") + ":/x"]}, "not this workspace's"),  # rw of ro grant
        ({"Binds": [str(tmp_path / "files") + ":/x:rw,rshared"]}, "bind option"),
        ({"CapAdd": ["SYS_ADMIN"]}, "CapAdd"),
        ({"CapAdd": ["CAP_NET_ADMIN"]}, "CapAdd"),
        ({"PidMode": "host"}, "PidMode"),
        ({"IpcMode": "host"}, "IpcMode"),
        ({"UTSMode": "host"}, "UTSMode"),
        ({"UsernsMode": "host"}, "UsernsMode"),
        ({"CgroupnsMode": "host"}, "CgroupnsMode"),
        ({"NetworkMode": "host"}, "network"),
        ({"NetworkMode": "agos-net-agos-beta"}, "network"),
        ({"Devices": [{"PathOnHost": "/dev/sda"}]}, "Devices"),
        ({"DeviceRequests": [{"Driver": "nvidia"}]}, "DeviceRequests"),
        ({"VolumesFrom": ["other"]}, "VolumesFrom"),
        ({"Links": ["a:b"]}, "Links"),
        ({"PortBindings": {"80/tcp": [{}]}}, "PortBindings"),
        ({"PublishAllPorts": True}, "PublishAllPorts"),
        ({"Mounts": [{"Type": "bind", "Source": "/", "Target": "/host"}]}, "Mounts"),
        ({"SecurityOpt": ["seccomp=unconfined"]}, "SecurityOpt"),
        ({"SecurityOpt": ["apparmor=unconfined"]}, "SecurityOpt"),
        ({"MaskedPaths": []}, "MaskedPaths"),
        ({"ReadonlyPaths": []}, "ReadonlyPaths"),
        ({"CgroupParent": "/x"}, "CgroupParent"),
        ({"RestartPolicy": {"Name": "always"}}, "RestartPolicy"),
        ({"ExtraHosts": ["evil:1.2.3.4"]}, "ExtraHosts"),
        ({"Sysctls": {"net.ipv4.ip_forward": "1"}}, "Sysctls"),
        ({"Runtime": "sysbox-runc"}, "Runtime"),
        ({"OomKillDisable": True}, "OomKillDisable"),
        ({"SomethingNew": {"x": 1}}, "not a sandbox option"),
    ):
        why = validate_create(with_host(**host_over), policy)
        assert why is not None and needle in why, (host_over, why)
    # An ro bind of an ro grant is fine; so is one of the workspace's own folders.
    ok = with_host(Binds=[str(tmp_path / "shared") + ":/shared/x:ro"])
    assert validate_create(ok, policy) is None
    # A bind source symlinking out of the workspace is caught by realpath.
    link = tmp_path / "files" / "jump"
    link.symlink_to("/etc")
    why = validate_create(with_host(Binds=[f"{link}:/x"]), policy)
    assert why is not None and "not this workspace's" in why
    # A sandbox, bound or not, runs only on the workspace's own network (or none):
    # the default bridge would bypass its egress proxy. Only the cgroup probe
    # (test below) may use the default network.
    unbound = _create_body(tmp_path)
    host = dict(unbound["HostConfig"])  # type: ignore[call-overload]
    host["Binds"] = []
    for mode in ("default", "bridge", ""):
        host["NetworkMode"] = mode
        unbound["HostConfig"] = dict(host)
        why = validate_create(unbound, policy)
        assert why is not None and "network" in why, mode
    assert validate_exec({"Privileged": True}) is not None
    assert validate_exec({"Cmd": ["sh"]}) is None


def test_the_cgroup_probe_gets_this_workspaces_label(tmp_path: Path) -> None:
    """Hermes's `docker run --rm <image> sleep 0` probe sends no labels: the proxy
    labels it as this workspace's, so its own start/wait pass the ownership check;
    a body naming ANOTHER workspace's label is never relabelled."""
    policy = _policy(tmp_path)
    probe = {
        "Image": "agos-sandbox:desktop",
        "Cmd": ["sleep", "0"],
        "HostConfig": {"AutoRemove": True, "NanoCpus": 500000000, "Memory": 67108864},
    }
    why, body = prepare_create(probe, policy)
    assert why is None
    assert isinstance(body, dict)
    labels = body["Labels"]
    assert isinstance(labels, dict) and labels["hermes-profile"] == LABEL
    foreign = {**probe, "Labels": {"hermes-profile": "agos-beta-x"}}
    why, _ = prepare_create(foreign, policy)
    assert why is not None and "not this workspace's" in why
    # Hermes names its containers hermes-<hex>; anything else is refused.
    assert prepare_create(_create_body(tmp_path), policy, "hermes-1a2b3c")[0] is None
    bad, _ = prepare_create(_create_body(tmp_path), policy, "agos-mcp-link-x-y")
    assert bad is not None and "name" in bad


def test_the_list_filter_must_pin_this_workspaces_label() -> None:
    labels = frozenset([LABEL])
    own = urllib.parse.urlencode(
        {
            "filters": json.dumps(
                {"label": {f"hermes-profile={LABEL}": True, "hermes-agent=1": True}}
            )
        }
    )
    assert sandboxd._filters_with_own_label(own, labels) is not None
    listform = urllib.parse.urlencode(
        {"all": "1", "filters": json.dumps({"label": [f"hermes-profile={LABEL}"]})}
    )
    assert sandboxd._filters_with_own_label(listform, labels) is not None
    for bad in (
        "",
        urllib.parse.urlencode({"filters": json.dumps({"label": {"hermes-agent=1": True}})}),
        urllib.parse.urlencode({"filters": json.dumps({"label": {"hermes-profile=other": True}})}),
        urllib.parse.urlencode({"filters": "not-json"}),
        urllib.parse.urlencode({"filters": json.dumps(["hermes-profile=x"])}),
    ):
        assert sandboxd._filters_with_own_label(bad, labels) is None, bad


# ---- the daemon over real sockets (tests/sandboxd_rig.py) --------------------


def test_the_proxy_forwards_sandbox_work_and_refuses_everything_else(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        status, body = await _request(rig.sock, "GET", "/_ping")
        assert (status, body) == (200, b"OK")
        status, _ = await _request(rig.sock, "GET", "/v1.51/version")
        assert status == 200
        # A legitimate Hermes create goes through and reaches Docker unchanged.
        create = json.dumps(_create_body(tmp_path)).encode()
        status, body = await _request(
            rig.sock, "POST", "/v1.51/containers/create?name=hermes-1", create
        )
        assert status == 201 and NEW_ID.encode() in body
        assert rig.fake.created and rig.fake.created[0]["Image"] == "agos-sandbox:desktop"
        # Its own container: inspect, start, logs (chunked), exec, exec start (hijack).
        status, _ = await _request(rig.sock, "GET", "/v1.51/containers/own/json")
        assert status == 200
        status, _ = await _request(rig.sock, "POST", "/v1.51/containers/own/start")
        assert status == 204
        # The forwarded call names the checked full id, never the raw name.
        assert f"POST /v1.51/containers/{OWN_ID}/start" in rig.fake.requests
        status, body = await _request(rig.sock, "GET", "/v1.51/containers/own/logs?stdout=1")
        assert status == 200 and b"hello" in body
        status, body = await _request(
            rig.sock, "POST", "/v1.51/containers/own/exec", json.dumps({"Cmd": ["sh"]}).encode()
        )
        assert status == 201 and b"e-own" in body
        # The listing passes only with the workspace's own label filter.
        own_filter = urllib.parse.urlencode(
            {"filters": json.dumps({"label": {f"hermes-profile={LABEL}": True}})}
        )
        status, _ = await _request(rig.sock, "GET", f"/v1.51/containers/json?{own_filter}")
        assert status == 200
        status, body = await _request(rig.sock, "GET", "/v1.51/containers/json")
        assert status == 403
        # Foreign or unlabelled container: inspect/exec/stop all refused; so is a
        # privileged create, a foreign bind, a network create, and a foreign pull.
        for method, target, payload in (
            ("GET", "/v1.51/containers/foreign/json", None),
            ("POST", "/v1.51/containers/foreign/stop", b"{}"),
            ("POST", "/v1.51/containers/foreign/exec", json.dumps({"Cmd": ["sh"]}).encode()),
            ("GET", "/v1.51/containers/bare/json", None),
            ("POST", "/v1.51/containers/bare/exec", json.dumps({"Cmd": ["sh"]}).encode()),
            ("POST", "/v1.51/exec/e-foreign/start", b"{}"),
            ("POST", "/v1.51/networks/create", b"{}"),
            ("POST", "/v1.51/images/create?fromImage=ubuntu&tag=latest", b""),
            (
                "POST",
                "/v1.51/containers/create",
                json.dumps(_create_body(tmp_path, HostConfig={"Privileged": True})).encode(),
            ),
            (
                "POST",
                "/v1.51/containers/create",
                json.dumps(
                    _create_body(
                        tmp_path, HostConfig={"Binds": ["/etc:/host-etc"], "NetworkMode": "none"}
                    )
                ).encode(),
            ),
        ):
            status, body = await _request(rig.sock, method, target, payload)
            assert status == 403, (target, status, body)
            assert b"agos-sandboxd" in body
        # Nothing forbidden ever reached Docker (the inspect of foreign/bare is the check).
        assert not any("networks" in r or "ubuntu" in r for r in rig.fake.requests)
        assert len(rig.fake.created) == 1
        # Every refusal is a security event.
        events = (rig.base / "events.jsonl").read_text().splitlines()
        denied = [json.loads(e) for e in events if json.loads(e)["event"] == "denied"]
        assert len(denied) >= 11
        assert all(d.get("security") for d in denied)
        # The pull of the workspace's own image is allowed through (fake answers 500:
        # it does not implement it, which proves the proxy forwarded it).
        status, _ = await _request(
            rig.sock, "POST", "/v1.51/images/create?fromImage=agos-sandbox&tag=desktop", b""
        )
        assert status == 500
        assert any("/images/create" in r for r in rig.fake.requests)

    asyncio.run(_rig(scenario, tmp_path))


def test_one_connection_carries_a_refusal_then_an_allowed_request(tmp_path: Path) -> None:
    """The docker CLI keeps its connection alive: a 403 must not wedge it."""

    async def scenario(rig: Rig) -> None:
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            writer.write(b"GET /v1.51/containers/foreign/json HTTP/1.1\r\nHost: d\r\n\r\n")
            await writer.drain()
            status, body = await _read_response(reader)
            assert status == 403 and b"agos-sandboxd" in body
            writer.write(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            await writer.drain()
            status, body = await _read_response(reader)
            assert (status, body) == (200, b"OK")
        finally:
            writer.close()

    asyncio.run(_rig(scenario, tmp_path))


def test_smuggled_framing_is_refused(tmp_path: Path) -> None:
    """A request with both Content-Length and Transfer-Encoding could carry a second,
    unchecked request behind the first: refused outright."""

    async def scenario(rig: Rig) -> None:
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            writer.write(
                b"POST /v1.51/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n"
            )
            await writer.drain()
            status, body = await _read_response(reader)
            assert status == 400 and b"agos-sandboxd" in body
            assert await asyncio.wait_for(reader.read(), timeout=5) == b""  # hung up
        finally:
            writer.close()
        assert not any("create" in r for r in rig.fake.requests)

    asyncio.run(_rig(scenario, tmp_path))


def test_the_exec_stream_is_spliced_after_the_upgrade(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            payload = json.dumps({"Detach": False, "Tty": False}).encode()
            writer.write(
                b"POST /v1.51/exec/e-own/start HTTP/1.1\r\nHost: docker\r\n"
                b"Connection: Upgrade\r\nUpgrade: tcp\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            assert b"101" in head.split(b"\r\n", 1)[0]
            writer.write(b"stdin-bytes")
            await writer.drain()
            echoed = await asyncio.wait_for(reader.read(), timeout=5)
            assert echoed == b"ECHO:stdin-bytes"
        finally:
            writer.close()

    asyncio.run(_rig(scenario, tmp_path))


def test_a_removed_policy_takes_the_socket_down(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        assert rig.sock.exists()
        (rig.base / "p" / f"{PROFILE}.policy.json").unlink()
        await rig.daemon.rescan()
        assert not rig.sock.exists()

    asyncio.run(_rig(scenario, tmp_path))


@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker CLI")
def test_the_real_docker_cli_accepts_the_proxy(tmp_path: Path) -> None:
    """`docker version` (the CLI's own HTTP client) against the proxy backed by the
    fake daemon: proves the framing satisfies a real client."""

    async def scenario(rig: Rig) -> None:
        def cli() -> subprocess.CompletedProcess[str]:
            return subprocess.run(  # noqa: S603 - the installed docker CLI, fixed argv
                [
                    shutil.which("docker") or "docker",
                    "--host",
                    f"unix://{rig.sock}",
                    "version",
                    "--format",
                    "{{.Server.APIVersion}}",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )

        done = await asyncio.get_running_loop().run_in_executor(None, cli)
        assert done.returncode == 0, done.stderr
        assert "1.51" in done.stdout

    asyncio.run(_rig(scenario, tmp_path))


# ---- strict HTTP (RFC 9112): what Docker's lenient Go parser must never see -------
def test_the_head_is_refused_unless_it_is_canonical_http() -> None:
    """Docker's Go parser accepts a bare LF as a line end, skips chunk extensions
    and folds header case: any request the proxy reads differently is refused."""
    parse = sandboxd_http.parse_head
    ok = parse(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
    assert ok.method == "GET" and ok.segments == ("_ping",)
    for raw in (
        # A bare LF inside a header value: Docker would read TWO lines (the smuggle).
        b"GET /_ping HTTP/1.1\r\nHost: d\nX-Evil: 1\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost: d\rX: 1\r\n\r\n",  # a bare CR
        b"GET /_ping HTTP/1.1\r\nHost: d\x00\r\n\r\n",  # NUL
        b"GET /_ping HTTP/1.1\r\nHost: d\x0b\r\n\r\n",  # other control bytes
        b"GET /_ping HTTP/1.1\r\nHost: d\r\n\tfolded\r\n\r\n",  # obs-fold
        b"GET /_ping HTTP/1.1\r\nHost: d\r\n Host: e\r\n\r\n",  # obs-fold by space
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nHost: e\r\n\r\n",  # duplicate header
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nContent-Length: 2\r\ncontent-length: 2\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nTransfer-Encoding: gzip\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nTransfer-Encoding: chunked, chunked\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nContent-Length: +2\r\n\r\n",  # not a plain number
        b"GET /_ping HTTP/1.1\r\nHost: d\r\nContent-Length: 0x2\r\n\r\n",
        b"GET /_ping HTTP/1.1\r\nHost : d\r\n\r\n",  # space before the colon
        b"GET /_ping HTTP/1.1\r\nHost; d\r\n\r\n",  # no colon at all
        b"GET /_ping HTTP/1.0\r\nHost: d\r\n\r\n",  # not HTTP/1.1
        b"GET /_ping HTTP/1.1\r\n\r\n",  # no Host
        b"GET  /_ping HTTP/1.1\r\nHost: d\r\n\r\n",  # double space in the request line
        b"GET /_p\xc3\xa9ing HTTP/1.1\r\nHost: d\r\n\r\n",  # non-ASCII target
        b"TRACE /_ping HTTP/1.1\r\nHost: d\r\n\r\n",  # unknown method
        ("GET /_ping HTTP/1.1\r\nHost: d\r\n" + "X-Big: " + "a" * 9000 + "\r\n\r\n").encode(),
        (
            "GET /_ping HTTP/1.1\r\nHost: d\r\n"
            + "".join(f"X-{i}: 1\r\n" for i in range(80))
            + "\r\n"
        ).encode(),  # too many headers
    ):
        with pytest.raises(sandboxd.BadRequest):
            parse(raw)


def test_the_target_is_decoded_once_and_sneaky_paths_are_refused() -> None:
    parse = sandboxd_http.parse_target
    version, segments, query = parse("/v1.51/containers/own/archive?path=%2Fetc")
    assert version == "v1.51" and segments == ("containers", "own", "archive")
    assert query == (("path", "/etc"),)
    assert parse("/_ping") == ("", ("_ping",), ())
    for target in (
        "/v1.51/containers/own%2F..%2Fsecrets/json",  # %2F: an escaped slash
        "/v1.51/containers/..%2Fsecrets/json",
        "/v1.51/containers/x%5Cy/json",  # %5C: an escaped backslash
        "/v1.51/containers\\x/json",  # a raw backslash
        "/v1.51/containers/../secrets",  # dot-dot
        "/v1.51/containers/./x/json",  # a '.' segment
        "/v1.51//containers/x/json",  # an empty segment
        "/v1.51/containers/x/json/",  # a trailing empty segment
        "/v1.51/containers/%2e%2e/json",  # escaped dot-dot
        "/v1.51/containers/a%00b/json",  # an escaped NUL
        "/v1.51/containers/a%c3%a9/json",  # escaped non-ASCII
        "/v1.51/containers/a%zz/json",  # a broken escape
        "/v2.0/_ping",  # not a Docker API version the broker knows
        "/v1.999/_ping",
        "/v1.51/_ping?x=1&x=2",  # a duplicate query key
        "/v1.51/_ping?a%2Fb=1",  # a query key that is not a parameter name
        "relative/path",
    ):
        with pytest.raises(sandboxd.BadRequest):
            parse(target)
    # Unknown query parameters on a known route are refused by the router's allowlist.
    assert sandboxd.route_segments("GET", ("containers", "json")).params == frozenset(
        {"all", "limit", "size", "filters"}
    )


def test_create_refuses_case_folded_duplicates_and_foreign_labels(tmp_path: Path) -> None:
    """Go's JSON decoder matches field names case-insensitively (last one wins):
    a body saying HostConfig twice in different case runs as the one the proxy
    did not check. And callers can set only hermes-* labels, so nobody can stamp
    another workspace's owner label."""
    policy = _policy(tmp_path)
    body = _create_body(tmp_path)
    sneaky = {**body, "hostconfig": {"Privileged": True}}
    why, _ = prepare_create(sneaky, policy)
    assert why is not None and "twice" in why
    host = dict(body["HostConfig"])  # type: ignore[call-overload]
    host["privileged"] = True
    why = validate_create({**body, "HostConfig": host}, policy)
    assert why is not None and "privileged" in why
    labels = dict(body["Labels"])  # type: ignore[call-overload]
    labels["agos-sandboxd-owner"] = "agos-beta"
    why, _ = prepare_create({**body, "Labels": labels}, policy)
    assert why is not None and "hermes-" in why
    assert validate_exec({"privileged": True}) is not None
    assert validate_exec({"Cmd": ["sh"], "cmd": ["sh"]}) is not None
    # The broker's own stamp names this workspace.
    why, stamped = prepare_create(_create_body(tmp_path), policy)
    assert why is None and isinstance(stamped, dict)
    stamped_labels = stamped["Labels"]
    assert isinstance(stamped_labels, dict)
    assert stamped_labels["agos-sandboxd-owner"] == policy.profile


def test_create_refuses_volumes_bad_tmpfs_and_non_string_fields(tmp_path: Path) -> None:
    policy = _policy(tmp_path)

    def why_of(**over: object) -> str | None:
        return validate_create(_create_body(tmp_path, **over), policy)

    def host_over(**over: object) -> dict[str, object]:
        body = _create_body(tmp_path)
        body["HostConfig"] = {**body["HostConfig"], **over}  # type: ignore[dict-item]
        return body

    assert (w := why_of(Volumes={"/data": {}})) and "Volumes" in w
    assert (w := why_of(SomethingTop={"x": 1})) and "SomethingTop" in w
    for tmpfs, needle in (
        ({"/tmp": "rw,exec,suid"}, "suid"),  # noqa: S108 - container spec, not a host path
        ({"/tmp": "rw,size=1g,mode=777,uid=0,gid=0,foo=bar"}, "foo=bar"),  # noqa: S108
        ({"relative": "rw"}, "relative"),
        ({"/": "rw"}, "'/'"),
        ({"/tmp/../etc": "rw"}, "/tmp/../etc"),  # noqa: S108
        ([], "not an object"),
    ):
        w = validate_create(host_over(Tmpfs=tmpfs), policy)
        assert w is not None and needle in w, (tmpfs, w)
    for binds, needle in (
        ([{"x": 1}], "list of strings"),
        ([f"{tmp_path / 'files'}:/workspace/../../etc"], "bind target"),
        ([f"{tmp_path / 'files'}:rel"], "bind target"),
        (["files:/workspace"], "host:container"),
        (["/:/host:ro"], "not this workspace's"),
    ):
        w = validate_create(host_over(Binds=binds), policy)
        assert w is not None and needle in w, (binds, w)
    assert (w := validate_create(host_over(CapAdd=[1]), policy)) and "list of strings" in w
    assert (w := validate_create(host_over(CapAdd=["cap_sys_admin"]), policy)) and "CapAdd" in w
    assert (
        w := validate_create(host_over(RestartPolicy={"Name": "no", "Nope": 1}), policy)
    ) and "RestartPolicy" in w
    nc: dict[str, object] = {"EndpointsConfig": {"agos-net-agos-beta": {}}}
    assert (w := why_of(NetworkingConfig=nc)) and "network" in w
    assert (w := why_of(NetworkingConfig={"Extra": 1})) and "NetworkingConfig" in w
    # The checked bind is forwarded by its realpath, not the raw (symlinkable) path.
    link = tmp_path / "entry"
    link.symlink_to(tmp_path / "files")
    why, body = prepare_create(
        _create_body(tmp_path, HostConfig={"Binds": [f"{link}:/workspace"], "NetworkMode": "none"}),
        _policy(tmp_path),
    )
    assert why is None and isinstance(body, dict)
    host_cfg = body["HostConfig"]
    assert isinstance(host_cfg, dict)
    assert host_cfg["Binds"][0] == f"{(tmp_path / 'files').resolve()}:/workspace"


# ---- the daemon: strict framing, rebuilt upstream requests, pinned ownership -------
def test_a_smuggling_shaped_head_gets_400_and_the_connection_is_closed(tmp_path: Path) -> None:
    """A head Docker would read as two requests (bare LF, duplicate length...) is
    answered 400 and the connection is dropped before anything reaches Docker."""

    async def scenario(rig: Rig) -> None:
        for raw in (
            b"GET /_ping HTTP/1.1\r\nHost: d\nGET /v1.51/networks HTTP/1.1\r\n\r\n",
            b"POST /v1.51/containers/create HTTP/1.1\r\nHost: d\r\n"
            b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
            b"POST /v1.51/containers/create HTTP/1.1\r\nHost: d\r\n"
            b"Transfer-Encoding: gzip, chunked\r\n\r\n",
            b"GET /v1.51/containers/own%2F..%2Fx/json HTTP/1.1\r\nHost: d\r\n\r\n",
        ):
            reader, writer = await asyncio.open_unix_connection(str(rig.sock))
            try:
                writer.write(raw)
                await writer.drain()
                status, body = await _read_response(reader)
                assert status in (400, 403) and b"agos-sandboxd" in body, raw
                assert await asyncio.wait_for(reader.read(), timeout=5) == b""
            finally:
                writer.close()
        assert rig.fake.requests == []
        events = [json.loads(e) for e in (rig.base / "events.jsonl").read_text().splitlines()]
        assert sum(1 for e in events if e["event"] == "denied" and e.get("security")) >= 4

    asyncio.run(_rig(scenario, tmp_path))


def test_a_chunked_body_with_extensions_or_trailers_is_refused(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        for payload in (
            b"2;ext=1\r\n{}\r\n0\r\n\r\n",  # a chunk extension
            b"0002\r\n{}\r\n0\r\n\r\n" + b"",  # ok size, then trailers below
        ):
            reader, writer = await asyncio.open_unix_connection(str(rig.sock))
            try:
                writer.write(
                    b"POST /v1.51/containers/create HTTP/1.1\r\nHost: d\r\n"
                    b"Transfer-Encoding: chunked\r\n\r\n" + payload
                )
                await writer.drain()
                status, _ = await _read_response(reader)
                if payload.startswith(b"2;"):
                    assert status == 400
            finally:
                writer.close()
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            writer.write(
                b"POST /v1.51/containers/create HTTP/1.1\r\nHost: d\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\nX-Trailer: 1\r\n\r\n"
            )
            await writer.drain()
            status, _ = await _read_response(reader)
            assert status == 400
        finally:
            writer.close()
        assert not any("create" in r for r in rig.fake.requests)

    asyncio.run(_rig(scenario, tmp_path))


def test_nothing_the_client_sent_is_forwarded_but_the_checked_body(tmp_path: Path) -> None:
    """The upstream request is the broker's own: fixed Host, no client header
    survives, the body is the re-serialised JSON that was validated, and every
    request takes a fresh upstream connection (no upstream reuse to poison)."""

    async def scenario(rig: Rig) -> None:
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            create = json.dumps(_create_body(tmp_path)).encode()
            writer.write(
                b"POST /v1.51/containers/create?name=hermes-1 HTTP/1.1\r\n"
                b"Host: sneaky.example\r\nX-Evil: yes\r\nAuthorization: Bearer x\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(create)}\r\n\r\n".encode()
                + create
            )
            await writer.drain()
            status, _ = await _read_response(reader)
            assert status == 201
            writer.write(b"GET /_ping HTTP/1.1\r\nHost: d\r\n\r\n")
            await writer.drain()
            status, _ = await _read_response(reader)
            assert status == 200
        finally:
            writer.close()
        create_head = next(h for h in rig.fake.heads if b"containers/create" in h)
        assert b"X-Evil" not in create_head and b"Authorization" not in create_head
        assert b"sneaky" not in create_head
        assert b"Host: docker\r\n" in create_head
        assert b"Connection: close" in create_head
        # The forwarded body is the broker's own serialisation of what it checked,
        # with its owner stamp; the created container carries it.
        assert rig.fake.created[0]["Labels"]["agos-sandboxd-owner"] == PROFILE  # type: ignore[index]
        # One upstream connection per forwarded request: the two calls above never
        # shared one (the create's 201 ends with Connection: close upstream).
        assert rig.fake.connections >= 2

    asyncio.run(_rig(scenario, tmp_path))


def test_by_id_calls_pass_only_for_containers_created_through_this_socket(
    tmp_path: Path,
) -> None:
    """The owner label pins a container to the socket that created it: a container
    someone labelled with this workspace's hermes-profile but created elsewhere
    (docker CLI as the user, another tool) is still refused; only containers from
    before the broker (no owner label, old Created) are adopted by label."""

    async def scenario(rig: Rig) -> None:
        status, _ = await _request(rig.sock, "GET", "/v1.51/containers/own/json")
        assert status == 200
        status, _ = await _request(rig.sock, "GET", "/v1.51/containers/legacy/json")
        assert status == 200  # created 2020, before the broker: adopted
        status, body = await _request(rig.sock, "GET", "/v1.51/containers/spoof/json")
        assert status == 403 and b"socket" in body  # right label, wrong creator
        status, _ = await _request(rig.sock, "POST", "/v1.51/containers/spoof/stop", b"{}")
        assert status == 403
        status, _ = await _request(
            rig.sock, "POST", "/v1.51/containers/spoof/exec", json.dumps({"Cmd": ["sh"]}).encode()
        )
        assert status == 403

    asyncio.run(_rig(scenario, tmp_path))


def test_the_image_may_be_named_by_id_or_alias_resolving_to_the_allowed_one(
    tmp_path: Path,
) -> None:
    async def scenario(rig: Rig) -> None:
        for image in (IMAGE_ID, "docker.io/library/agos-sandbox:desktop"):
            create = json.dumps(_create_body(tmp_path, Image=image)).encode()
            status, _ = await _request(
                rig.sock, "POST", "/v1.51/containers/create?name=hermes-1", create
            )
            assert status == 201, image
        # ubuntu:latest resolves to a DIFFERENT id: refused.
        create = json.dumps(_create_body(tmp_path, Image="ubuntu:latest")).encode()
        status, body = await _request(
            rig.sock, "POST", "/v1.51/containers/create?name=hermes-1", create
        )
        assert status == 403 and b"image" in body

    asyncio.run(_rig(scenario, tmp_path))


def test_unknown_query_parameters_and_stray_bodies_are_refused(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        status, body = await _request(rig.sock, "GET", "/v1.51/containers/own/json?size=1&evil=1")
        assert status == 403 and b"query parameter" in body
        # A GET with a body on a bodyless route is a framing lie: 400, hang up.
        reader, writer = await asyncio.open_unix_connection(str(rig.sock))
        try:
            writer.write(
                b"GET /v1.51/containers/own/json HTTP/1.1\r\nHost: d\r\n"
                b"Content-Length: 4\r\n\r\nevil"
            )
            await writer.drain()
            status, _ = await _read_response(reader)
            assert status == 400
        finally:
            writer.close()

    asyncio.run(_rig(scenario, tmp_path))


def test_put_archive_streams_through_with_the_brokers_own_framing(tmp_path: Path) -> None:
    async def scenario(rig: Rig) -> None:
        payload = b"TARBYTES" * 4
        status, _ = await _request(
            rig.sock, "PUT", "/v1.51/containers/own/archive?path=%2Fworkspace", payload
        )
        assert status == 200
        head = next(h for h in rig.fake.heads if b"/archive" in h)
        assert f"/containers/{OWN_ID}/archive".encode() in head
        assert rig.fake.bodies[-1] == payload

    asyncio.run(_rig(scenario, tmp_path))
