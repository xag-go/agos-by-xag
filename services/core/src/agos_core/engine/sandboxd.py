"""agos-sandboxd: one *filtered* Docker socket per workspace (ADR 0025, step 4).

Every workspace's Hermes gateway gets `DOCKER_HOST=unix://<run>/agos-sandboxd/
<profile>/docker.sock` and its cage (engine/cage.py) hides the real Docker socket.
This daemon owns the real socket on their behalf and forwards ONLY what Hermes's
docker terminal backend needs (tools/environments/docker.py — the docker CLI over
the Docker HTTP API), with the workspace's own policy enforced:

- ping/version/info; image inspect/pull of the workspace's sandbox image(s) only;
- container create: image, name, labels, binds (its own folders only), network,
  caps and every privilege field validated (`validate_create`); the broker stamps
  its own owner label, callers set only hermes-* labels;
- everything by container id (start/stop/kill/wait/inspect/logs/top/stats/attach/
  resize/archive/exec/rm) only on containers created through THIS socket (the
  broker's owner label; containers older than the broker by their Hermes label),
  and the forwarded path names the container by the full id that was checked;
- exec start/resize/inspect only for execs of those containers;
- container list only with the workspace's own label filter;
- each route takes only its known query parameters;
- anything else: 403 JSON, logged as a security event (stderr = the journal, and
  JSON lines in --events).

HTTP is strict and canonical (engine/sandboxd_http.py, RFC 9112): a request that is
not exactly well-formed HTTP/1.1 gets 400 and the connection is closed; nothing the
client wrote is forwarded as is — the broker writes its own request upstream (fixed
headers, its own framing, the re-serialised body), one upstream connection per
request. Exec/attach are hijacked HTTP (101): after the upgrade that one client
connection and that one upstream connection are spliced.

Stdlib only (asyncio over unix sockets): it is run by the system python from AGOS's
own systemd user unit (engine/cage.py unit_text), as the same AGOS user, OUTSIDE
the gateways' walls and cages. Policies are JSON files (one per workspace, written
by engine/hermes.py through engine/cage.py); the folder is rescanned so a new workspace needs no
restart, and each request re-reads its policy so a changed grant applies at once.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import importlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING


def _sibling(name: str) -> ModuleType:
    """engine/<name>.py: the package import, or (run as `python3 -I sandboxd.py`,
    no agos_core on the path) the sibling file itself."""
    try:
        return importlib.import_module(f"agos_core.engine.{name}")
    except ImportError:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / (name + ".py"))
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


if TYPE_CHECKING:
    from agos_core.engine import sandboxd_http as http
    from agos_core.engine import sandboxd_rules as rules
else:
    http = _sibling("sandboxd_http")
    rules = _sibling("sandboxd_rules")
BadRequest = http.BadRequest
# The create rules live in engine/sandboxd_rules.py; these names stay importable here.
Policy = rules.Policy
POLICY_SUFFIX = rules.POLICY_SUFFIX
PROFILE_LABEL = rules.PROFILE_LABEL
OWNER_LABEL = rules.OWNER_LABEL
load_policy = rules.load_policy
prepare_create = rules.prepare_create
validate_create = rules.validate_create
validate_exec = rules.validate_exec
_FULL_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_IMAGE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}")


@dataclass(frozen=True)
class Route:
    """What to do with one request: a decision and what it needs."""

    kind: str  # pass | create | exec_create | list | scoped | exec_scoped | image | pull | deny
    target: str = ""
    reason: str = ""
    # The query parameters this call may carry, the body it takes (none | json |
    # tar) and whether it is a hijacked stream (exec start, attach).
    params: frozenset[str] = field(default=frozenset(), compare=False)
    body: str = field(default="none", compare=False)
    hijack: bool = field(default=False, compare=False)


_P = frozenset
_CONTAINER_POST = {
    "start": _P({"detachKeys"}),
    "stop": _P({"t", "signal"}),
    "restart": _P({"t", "signal"}),
    "kill": _P({"signal"}),
    "wait": _P({"condition"}),
    "resize": _P({"h", "w"}),
    "attach": _P({"stream", "stdin", "stdout", "stderr", "logs", "detachKeys"}),
    "pause": _P(),
    "unpause": _P(),
}
_CONTAINER_GET = {
    "json": _P({"size"}),
    "logs": _P({"follow", "stdout", "stderr", "since", "until", "timestamps", "tail", "details"}),
    "top": _P({"ps_args"}),
    "stats": _P({"stream", "one-shot"}),
    "changes": _P(),
    "archive": _P({"path"}),
}


def route_segments(method: str, s: tuple[str, ...]) -> Route:
    """The decision for METHOD + decoded path segments (version stripped)."""
    if s == ("_ping",) and method in ("GET", "HEAD"):
        return Route("pass")
    if s in (("version",), ("info",)) and method == "GET":
        return Route("pass")
    if method == "GET" and len(s) >= 3 and s[0] == "images" and s[-1] == "json":
        return Route("image", "/".join(s[1:-1]), params=_P({"manifests", "platform"}))
    if method == "POST" and s == ("images", "create"):
        return Route("pull", params=_P({"fromImage", "tag", "platform"}))
    if method == "GET" and s == ("containers", "json"):
        return Route("list", params=_P({"all", "limit", "size", "filters"}))
    if method == "POST" and s == ("containers", "create"):
        return Route("create", params=_P({"name", "platform"}), body="json")
    if len(s) in (2, 3) and s[0] == "containers" and _REF_RE.fullmatch(s[1]):
        ref, verb = s[1], s[2] if len(s) == 3 else ""
        if not verb and method == "DELETE":
            return Route("scoped", ref, params=_P({"v", "force"}))
        if verb == "exec" and method == "POST":
            return Route("exec_create", ref, body="json")
        if method == "POST" and verb in _CONTAINER_POST:
            return Route(
                "scoped", ref, params=_CONTAINER_POST[verb], body="json", hijack=verb == "attach"
            )
        if method == "GET" and verb in _CONTAINER_GET:
            return Route("scoped", ref, params=_CONTAINER_GET[verb])
        if method == "HEAD" and verb == "archive":
            return Route("scoped", ref, params=_P({"path"}))
        if method == "PUT" and verb == "archive":
            return Route(
                "scoped", ref, params=_P({"path", "noOverwriteDirNonDir", "copyUIDGID"}), body="tar"
            )
    if len(s) == 3 and s[0] == "exec" and _REF_RE.fullmatch(s[1]):
        if method == "POST" and s[2] == "start":
            return Route("exec_scoped", s[1], body="json", hijack=True)
        if method == "POST" and s[2] == "resize":
            return Route("exec_scoped", s[1], params=_P({"h", "w"}))
        if method == "GET" and s[2] == "json":
            return Route("exec_scoped", s[1])
    path = "/" + "/".join(s)
    return Route("deny", reason=f"{method} {path} is not part of running this workspace's sandbox")


def route(method: str, target: str) -> Route:
    """The decision for `METHOD target`; a non-canonical target is refused."""
    try:
        _, segments, _ = http.parse_target(target)
    except BadRequest as error:
        return Route("deny", reason=error.reason)
    return route_segments(method, segments)


def _filters_with_own_label(query: str, labels: frozenset[str]) -> str | None:
    """The query string, provided its label filter already pins one of this
    workspace's labels (Hermes's docker backend always filters by its own
    hermes-profile); None when it does not."""
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    try:
        filters = json.loads(params.get("filters", ["{}"])[0])
    except ValueError:
        return None
    raw = filters.get("label", {}) if isinstance(filters, dict) else {}
    entries = list(raw) if isinstance(raw, (dict, list)) else []
    if any(str(e) == f"{PROFILE_LABEL}={label}" for e in entries for label in labels):
        return query
    return None


def _created(value: object) -> float:
    """Docker's `Created` (RFC 3339, nanoseconds) as epoch seconds; 0 when unreadable."""
    try:
        stamp = datetime.datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0.0
    return stamp.replace(tzinfo=datetime.UTC).timestamp()


@dataclass(frozen=True)
class _Owner:
    checked: float
    owner: str
    profile_label: str
    created: float


class Sandboxd:
    """The daemon: one unix socket per policy file, all forwarding to `docker_socket`."""

    def __init__(
        self, *, sockets_dir: Path, policies_dir: Path, docker_socket: Path, events_file: Path
    ) -> None:
        self.sockets_dir = sockets_dir
        self.policies_dir = policies_dir
        self.docker_socket = docker_socket
        self.events_file = events_file
        self.servers: dict[str, asyncio.Server] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        # full container id -> who owns it; ids are never reused.
        self._owner_cache: dict[str, _Owner] = {}

    # ---- lifecycle ------------------------------------------------------
    async def run(self) -> None:
        self.sockets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.sockets_dir.chmod(0o700)
        self.policies_dir.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                await self.rescan()
                await asyncio.sleep(2)
        finally:
            self.close()

    async def rescan(self) -> None:
        """Serve every policy file; drop sockets whose policy is gone."""
        wanted = {
            p.name.removesuffix(POLICY_SUFFIX) for p in self.policies_dir.glob(f"*{POLICY_SUFFIX}")
        }
        for profile in sorted(wanted - set(self.servers)):
            folder = self.sockets_dir / profile
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            folder.chmod(0o700)
            sock = folder / "docker.sock"
            with contextlib.suppress(FileNotFoundError):
                sock.unlink()

            def accept(
                r: asyncio.StreamReader, w: asyncio.StreamWriter, profile: str = profile
            ) -> None:
                task = asyncio.ensure_future(self.handle(profile, r, w))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

            server = await asyncio.start_unix_server(accept, path=str(sock), limit=http.HEAD_LIMIT)
            sock.chmod(0o600)
            self.servers[profile] = server
            self.event(profile, "serving", str(sock))
        for profile in sorted(set(self.servers) - wanted):
            self.servers.pop(profile).close()
            with contextlib.suppress(OSError):
                (self.sockets_dir / profile / "docker.sock").unlink()
            self.event(profile, "stopped", "policy removed")

    def close(self) -> None:
        """Stops listening and drops every open connection (never waits on a client:
        a kept-alive docker CLI connection would hold Server.wait_closed forever)."""
        for server in self.servers.values():
            server.close()
        self.servers.clear()
        for task in list(self._tasks):
            task.cancel()

    def event(self, profile: str, kind: str, detail: str, status: int = 0) -> None:
        record: dict[str, object] = {
            "ts": round(time.time(), 3),
            "profile": profile,
            "event": kind,
            "detail": detail,
        }
        if kind == "denied":
            record["security"] = True
            record["status"] = status or 403
        line = json.dumps(record)
        prefix = "agos-sandboxd SECURITY " if kind == "denied" else "agos-sandboxd "
        print(prefix + line, file=sys.stderr, flush=True)
        with contextlib.suppress(OSError), self.events_file.open("a") as handle:
            handle.write(line + "\n")

    # ---- per-connection -------------------------------------------------
    async def handle(
        self, profile: str, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                try:
                    request = await http.read_head(client_r)
                    if request is None:
                        return
                    try:
                        policy = load_policy(self.policies_dir / f"{profile}{POLICY_SUFFIX}")
                    except (OSError, ValueError):
                        await http.respond(client_w, 403, "this workspace has no sandbox policy")
                        return
                    if not await self.one_request(policy, request, client_r, client_w):
                        return
                except BadRequest as error:
                    # Framing can't be trusted past this point: answer and hang up.
                    self.event(profile, "denied", f"bad request: {error.reason}", error.status)
                    await http.respond(client_w, error.status, error.reason, close=True)
                    return
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            client_w.close()

    async def one_request(
        self,
        policy: Policy,
        request: http.Request,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
    ) -> bool:
        """Handles one request; True when the client connection can carry another."""
        method = request.method
        decision = route_segments(method, request.segments)
        deny: str | None = None
        body: bytes | None = None
        segments = request.segments
        if decision.kind == "deny":
            deny = decision.reason
        elif bad := [k for k, _ in request.query if k not in decision.params]:
            deny = f"query parameter {bad[0]!r} is refused on {method} {request.path}"
        elif decision.body == "none" and request.has_body:
            raise BadRequest(f"{method} {request.path} takes no body")
        parsed: object = None
        if deny is None and decision.body == "json":
            body = await http.read_body(client_r, request, http.JSON_LIMIT)
            parsed = http.json_body(body)
            body = json.dumps(parsed).encode() if parsed is not None else b""
        if deny is not None:
            pass
        elif decision.kind == "image" and decision.target not in policy.images:
            deny = f"image {decision.target!r} is not this workspace's sandbox image"
        elif decision.kind == "pull":
            name, tag = request.param("fromImage"), request.param("tag")
            pulled = f"{name}:{tag}" if tag else name
            if pulled not in policy.images:
                deny = f"pull of {pulled!r} is not this workspace's sandbox image"
        elif decision.kind == "list":
            query = urllib.parse.urlencode(request.query)
            if _filters_with_own_label(query, policy.labels) is None:
                deny = "listing needs this workspace's own hermes-profile label filter"
        elif decision.kind == "create":
            image = parsed.get("Image") if isinstance(parsed, dict) else None
            also = await self._image_aliases(policy, image)
            deny, parsed = prepare_create(parsed, policy, request.param("name"), also)
            body = json.dumps(parsed).encode()
        elif decision.kind == "exec_create":
            deny = validate_exec(parsed)
            if deny is None:
                deny, cid = await self._foreign(policy, decision.target)
                segments = ("containers", cid, *segments[2:])
        elif decision.kind == "scoped":
            deny, cid = await self._foreign(policy, decision.target)
            segments = ("containers", cid, *segments[2:])
        elif decision.kind == "exec_scoped":
            if parsed is not None and not isinstance(parsed, dict):
                deny = "exec start body is not an object"
            else:
                deny = await self._exec_foreign(policy, decision.target)

        if deny is not None:
            self.event(policy.profile, "denied", f"{method} {request.path}: {deny}")
            drained = body is not None or not request.has_body
            if not drained:
                with contextlib.suppress(BadRequest):
                    await http.read_body(client_r, request, http.JSON_LIMIT)
                    drained = True
            await http.respond(client_w, 403, deny, close=not drained or request.closes)
            return drained and not request.closes
        return await self._forward(
            request, decision, request.target(segments), body, client_r, client_w
        )

    # ---- upstream helpers ----------------------------------------------
    async def _upstream(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_unix_connection(str(self.docker_socket))

    async def _upstream_json(self, path: str) -> tuple[int, object]:
        """An inspect asked of the real daemon; (502, None) when it can't answer
        (the check then fails closed)."""
        try:
            reader, writer = await self._upstream()
        except OSError:
            return 502, None
        try:
            writer.write(http.request_bytes("GET", path))
            await writer.drain()
            raw = await asyncio.wait_for(http.read_to_eof(reader), timeout=30)
        except (OSError, TimeoutError):
            return 502, None
        finally:
            writer.close()
        head, _, rest = raw.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0].split()
        status = int(status_line[1]) if len(status_line) > 1 and status_line[1].isdigit() else 502
        if b"transfer-encoding: chunked" in head.lower():
            rest = http.unchunk(rest)
        try:
            return status, json.loads(rest or b"null")
        except ValueError:
            return status, None

    async def _image_id(self, ref: str) -> str:
        status, data = await self._upstream_json(
            f"/images/{urllib.parse.quote(ref, safe='/:@')}/json"
        )
        return str(data.get("Id") or "") if status == 200 and isinstance(data, dict) else ""

    async def _image_aliases(self, policy: Policy, image: object) -> frozenset[str]:
        """{image} when a name that is not one of the policy's (an id, a digest, a
        registry alias) resolves to the very image id an allowed name has."""
        if not isinstance(image, str) or image in policy.images:
            return frozenset()
        if not _IMAGE_REF_RE.fullmatch(image) or not (wanted := await self._image_id(image)):
            return frozenset()
        for allowed in sorted(policy.images):
            if await self._image_id(allowed) == wanted:
                return frozenset({image})
        return frozenset()

    async def _foreign(self, policy: Policy, ref: str) -> tuple[str | None, str]:
        """(None, its full id) when `ref` is a container created through this
        workspace's socket; else (the refusal, ref)."""
        cached = self._owner_cache.get(ref) if _FULL_ID_RE.match(ref) else None
        if cached and time.monotonic() - cached.checked < 10:
            cid, owner = ref, cached
        else:
            status, data = await self._upstream_json(f"/containers/{urllib.parse.quote(ref)}/json")
            if status == 404:
                return f"no such container: {ref}", ref
            if status != 200 or not isinstance(data, dict):
                return f"container {ref} could not be checked (docker said {status})", ref
            cid = str(data.get("Id") or "")
            if not _FULL_ID_RE.match(cid):
                return f"container {ref} has no id", ref
            labels = (data.get("Config") or {}).get("Labels") or {}
            owner = _Owner(
                checked=time.monotonic(),
                owner=str(labels.get(OWNER_LABEL) or ""),
                profile_label=str(labels.get(PROFILE_LABEL) or ""),
                created=_created(data.get("Created")),
            )
            if len(self._owner_cache) > 512:
                self._owner_cache.clear()
            self._owner_cache[cid] = owner
        if owner.owner == policy.profile and owner.profile_label in policy.labels:
            return None, cid
        legacy = (
            not owner.owner
            and owner.profile_label in policy.labels
            and 0 < owner.created < policy.legacy_before
        )
        if legacy:
            return None, cid
        return f"container {ref} was not created through this workspace's socket", ref

    async def _exec_foreign(self, policy: Policy, exec_id: str) -> str | None:
        status, data = await self._upstream_json(f"/exec/{urllib.parse.quote(exec_id)}/json")
        if status == 404:
            return f"no such exec: {exec_id}"
        if status != 200 or not isinstance(data, dict):
            return f"exec {exec_id} could not be checked (docker said {status})"
        container = str(data.get("ContainerID") or "")
        if not container:
            return f"exec {exec_id} has no container"
        return (await self._foreign(policy, container))[0]

    # ---- forwarding -----------------------------------------------------
    async def _forward(
        self,
        request: http.Request,
        decision: Route,
        target: str,
        body: bytes | None,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
    ) -> bool:
        """The broker's own request upstream, on a connection of its own."""
        # Not Django: the bytes go to the Docker socket, rebuilt from checked fields.
        # nosemgrep: python.django.security.injection.request-data-write.request-data-write
        method = request.method
        upgrade = decision.hijack and request.wants_upgrade
        try:
            up_r, up_w = await self._upstream()
        except OSError:
            await http.respond(client_w, 502, "the Docker socket is not answering", close=True)
            return False
        try:
            if decision.body == "tar":
                up_w.write(
                    http.request_bytes(
                        method,
                        target,
                        content_type="application/x-tar",
                        length=None if request.chunked else request.length,
                        chunked=request.chunked,
                    )
                )
                async for piece in http.iter_body(client_r, request, http.STREAM_LIMIT):
                    up_w.write(
                        f"{len(piece):x}\r\n".encode() + piece + b"\r\n"
                        if request.chunked
                        else piece
                    )
                    await up_w.drain()
                if request.chunked:
                    up_w.write(b"0\r\n\r\n")
            else:
                sized = body is not None or method in ("POST", "PUT")
                up_w.write(
                    http.request_bytes(
                        method,
                        target,
                        content_type="application/json" if body else "",
                        length=len(body or b"") if sized else None,
                        upgrade=upgrade,
                    )
                    + (body or b"")
                )
            await up_w.drain()
            kept = await http.relay_response(method, up_r, up_w, client_r, client_w, hijack=upgrade)
            return kept and not request.closes
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return False
        finally:
            up_w.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "agos-sandboxd").splitlines()[0])
    parser.add_argument("--sockets", required=True, type=Path)
    parser.add_argument("--policies", required=True, type=Path)
    parser.add_argument("--docker", type=Path, default=Path("/run/docker.sock"))
    parser.add_argument("--events", type=Path, default=Path("/dev/stderr"))
    args = parser.parse_args(argv)
    os.umask(0o077)  # sockets and folders: this user only, from the first byte
    daemon = Sandboxd(
        sockets_dir=args.sockets,
        policies_dir=args.policies,
        docker_socket=args.docker,
        events_file=args.events,
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
