"""Settings → Access → "Use AGOS from other devices" with a fake `tailscale` on
PATH (tests/fake_tailscale.py): never the real one, which would change this
machine's own Tailscale."""

from __future__ import annotations

import getpass
import json
import stat
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.actions import remote_access
from agos_core.api.app import create_app
from agos_core.config import Settings

FAKE = Path(__file__).with_name("fake_tailscale.py")


class Tailnet:
    """The fake's state file, and the calls it got."""

    def __init__(self, folder: Path) -> None:
        self.file = folder / "tailscale-state.json"
        self.bin = folder / "bin"
        self.set()

    def set(self, **values: Any) -> None:
        data = self.read()
        data.update(values)
        self.file.write_text(json.dumps(data))

    def read(self) -> dict[str, Any]:
        try:
            data: dict[str, Any] = json.loads(self.file.read_text())
        except FileNotFoundError:
            data = {}
        return data

    def calls(self) -> list[list[str]]:
        path = self.file.with_name(self.file.name + ".calls")
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def install(self) -> None:
        self.bin.mkdir(exist_ok=True)
        wrapper = self.bin / "tailscale"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def tailnet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Tailnet]:
    net = Tailnet(tmp_path)
    net.bin.mkdir()
    # Only the fake's folder: the real `tailscale` of this machine is never found.
    monkeypatch.setenv("PATH", str(net.bin))
    monkeypatch.setenv("FAKE_TAILSCALE_STATE", str(net.file))
    monkeypatch.setattr(remote_access, "_KNOWN_PLACES", ())
    monkeypatch.setattr(remote_access, "SERVE_WAIT_S", 2.0)
    yield net
    remote_access._stop_login(remote_access._PENDING)
    remote_access._PENDING = None


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as test_client:
        test_client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield test_client


def saved(tmp_path: Path) -> dict[str, Any] | None:
    path = tmp_path / "data" / "system" / "remote-access.json"
    return json.loads(path.read_text()) if path.exists() else None


def until(client: TestClient, state: str, seconds: float = 10) -> dict[str, Any]:
    end = time.monotonic() + seconds
    while True:
        body: dict[str, Any] = client.get("/remote-access").json()
        if body["state"] == state or time.monotonic() > end:
            return body
        time.sleep(0.2)


def test_not_installed_shows_the_one_install_command(client: TestClient, tailnet: Tailnet) -> None:
    body = client.get("/remote-access").json()
    assert body["state"] == "not-installed"
    assert "isn't installed" in body["message"]
    assert body["command"] == "curl -fsSL https://tailscale.com/install.sh | sh"
    activated = client.post("/remote-access/activate", json={"port": 3000}).json()
    assert activated["state"] == "not-installed"


def test_installed_but_off_says_off_and_runs_nothing_but_status(
    client: TestClient, tailnet: Tailnet
) -> None:
    tailnet.install()
    assert client.get("/remote-access").json()["state"] == "off"
    assert all(c[0] != "up" and c[0] != "serve" for c in tailnet.calls())


def test_the_service_not_running_shows_how_to_start_it(
    client: TestClient, tailnet: Tailnet
) -> None:
    tailnet.install()
    tailnet.set(daemon=False)
    body = client.post("/remote-access/activate", json={}).json()
    assert body["state"] == "no-daemon"
    assert body["command"] == "sudo systemctl enable --now tailscaled"


def test_no_operator_shows_the_one_line_fix(
    client: TestClient, tailnet: Tailnet, tmp_path: Path
) -> None:
    tailnet.install()
    tailnet.set(operator=False)
    body = client.post("/remote-access/activate", json={"port": 3000}).json()
    assert body["state"] == "needs-operator"
    assert body["command"] == f"sudo tailscale set --operator={getpass.getuser()}"
    assert saved(tmp_path) is None


def test_logged_out_gives_the_login_link_then_serves_and_saves_once_logged_in(
    client: TestClient, tailnet: Tailnet, tmp_path: Path
) -> None:
    tailnet.install()
    tailnet.set(dns_name="agos-box.tail1234.ts.net", login="Owner@Example.com")
    body = client.post("/remote-access/activate", json={"port": 3123}).json()
    assert body["state"] == "waiting-login"
    assert body["loginUrl"] == "https://login.tailscale.com/a/fake123"
    assert saved(tmp_path) is None
    # The card polls while the owner logs in.
    assert client.get("/remote-access").json()["state"] == "waiting-login"
    tailnet.set(logged_in=True)
    body = until(client, "on")
    assert body["state"] == "on", body
    assert body["address"] == "https://agos-box.tail1234.ts.net"
    assert body["user"] == "owner@example.com"
    assert tailnet.read()["serving"] == "3123"
    assert ["serve", "--bg", "3123"] in tailnet.calls()
    kept = saved(tmp_path)
    assert kept is not None
    assert kept["host"] == "agos-box.tail1234.ts.net"
    assert kept["user"] == "owner@example.com" and kept["alsoAllow"] == []
    # Polling again changes nothing and serves nothing more.
    serves = sum(1 for c in tailnet.calls() if c[:2] == ["serve", "--bg"])
    assert client.get("/remote-access").json()["state"] == "on"
    assert sum(1 for c in tailnet.calls() if c[:2] == ["serve", "--bg"]) == serves


def test_already_logged_in_turns_on_at_once(
    client: TestClient, tailnet: Tailnet, tmp_path: Path
) -> None:
    tailnet.install()
    tailnet.set(logged_in=True)
    body = client.post("/remote-access/activate", json={"port": 3000}).json()
    assert body["state"] == "on"
    assert not any(c[0] == "up" for c in tailnet.calls())  # no new login
    assert saved(tmp_path) is not None


def test_https_not_turned_on_gives_its_link_then_finishes(
    client: TestClient, tailnet: Tailnet, tmp_path: Path
) -> None:
    tailnet.install()
    tailnet.set(logged_in=True, https=False)
    body = client.post("/remote-access/activate", json={"port": 3000}).json()
    assert body["state"] == "needs-https"
    assert body["loginUrl"] == "https://login.tailscale.com/f/serve?node=fake"
    assert saved(tmp_path) is None
    tailnet.set(https=True)
    assert until(client, "on")["state"] == "on"


def test_something_else_served_on_the_address_is_not_replaced(
    client: TestClient, tailnet: Tailnet, tmp_path: Path
) -> None:
    tailnet.install()
    other = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}}
    tailnet.set(logged_in=True, serve_status={"Web": {"agos-box.tail1234.ts.net:443": other}})
    body = client.post("/remote-access/activate", json={"port": 3000}).json()
    assert body["state"] == "error" and "8080" in body["message"]
    assert "serving" not in tailnet.read() and saved(tmp_path) is None


def test_also_allow_and_turn_off(client: TestClient, tailnet: Tailnet, tmp_path: Path) -> None:
    tailnet.install()
    refused = client.put("/remote-access/also-allow", json={"logins": ["a@b.c"]})
    assert refused.status_code == 400  # not on yet
    tailnet.set(logged_in=True)
    client.post("/remote-access/activate", json={"port": 3000})
    bad = client.put("/remote-access/also-allow", json={"logins": ["not a login"]})
    assert bad.status_code == 400 and "isn't a Tailscale login" in bad.json()["detail"]
    body = client.put(
        "/remote-access/also-allow",
        json={"logins": [" Sis@Gmail.com ", "sis@gmail.com", "owner@example.com", ""]},
    ).json()
    assert body["alsoAllow"] == ["sis@gmail.com"]
    kept = saved(tmp_path)
    assert kept is not None and kept["alsoAllow"] == ["sis@gmail.com"]
    # Activate again keeps the extra login.
    assert client.post("/remote-access/activate", json={}).json()["alsoAllow"] == ["sis@gmail.com"]
    off = client.post("/remote-access/off").json()
    assert off["state"] == "off" and off["warning"] == ""
    assert saved(tmp_path) is None
    assert "serving" not in tailnet.read()
    assert ["serve", "--https=443", "off"] in tailnet.calls()
    assert client.get("/remote-access").json()["state"] == "off"


def test_on_but_tailscale_logged_out_later_warns(client: TestClient, tailnet: Tailnet) -> None:
    tailnet.install()
    tailnet.set(logged_in=True)
    client.post("/remote-access/activate", json={})
    tailnet.set(logged_in=False)
    body = client.get("/remote-access").json()
    assert body["state"] == "on" and "isn't connected" in body["warning"]
