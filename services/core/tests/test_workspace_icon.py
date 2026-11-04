"""The workspace icon: the picture on a workspace's tile (storage/workspace_icon.py,
the icon endpoints of api/workspaces.py). Fixture shape: tests/test_automations.py."""

import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.storage import workspace_icon

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


def png(width: int = 1, height: int = 1) -> bytes:
    """A real (tiny) PNG: the sniff reads the signature only, the test keeps it honest."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


WEBP = b"RIFF" + struct.pack("<I", 12) + b"WEBP" + b"VP8 " + b"\x00" * 8
GIF = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00;"
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, str]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        core.engine.runner = FakeRunner(hermes_home)
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        yield client, core, ws


def put(client: TestClient, ws: str, data: bytes, mime: str = "application/octet-stream") -> Any:
    return client.put(f"/workspaces/{ws}/icon", content=data, headers={"content-type": mime})


def record(client: TestClient, ws: str) -> dict[str, Any]:
    found: dict[str, Any] = client.get(f"/workspaces/{ws}").json()
    return found


def test_a_png_is_kept_and_served_and_the_record_carries_its_stamp(env: Any) -> None:
    client, core, ws = env
    assert record(client, ws)["icon"] is None
    assert client.get(f"/workspaces/{ws}/icon").status_code == 404
    r = put(client, ws, png(), "text/plain")  # the type is read from the bytes, not the header
    assert r.status_code == 204, r.text
    got = client.get(f"/workspaces/{ws}/icon")
    assert got.status_code == 200
    assert got.content == png()
    assert got.headers["content-type"] == "image/png"
    assert got.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in got.headers
    stamp = record(client, ws)["icon"]
    assert isinstance(stamp, str) and stamp.isdigit()
    listed = {w["id"]: w["icon"] for w in client.get("/workspaces").json()}
    assert listed[ws] == stamp
    # Beside the chat attachments, in the workspace's own folder.
    where = workspace_icon.folder(core.layout, ws)
    assert where == core.layout.workspaces / ws / "files" / ".agos"
    assert (where / "icon.png").is_file()
    assert not list(where.glob(".*.tmp"))


def test_a_new_type_replaces_the_old_file(env: Any) -> None:
    client, core, ws = env
    assert put(client, ws, png()).status_code == 204
    before = record(client, ws)["icon"]
    assert put(client, ws, WEBP).status_code == 204
    where = workspace_icon.folder(core.layout, ws)
    assert (where / "icon.webp").is_file()
    assert not (where / "icon.png").exists()
    got = client.get(f"/workspaces/{ws}/icon")
    assert got.headers["content-type"] == "image/webp" and got.content == WEBP
    assert record(client, ws)["icon"] != before


def test_delete_removes_it_and_is_idempotent(env: Any) -> None:
    client, _core, ws = env
    assert put(client, ws, png()).status_code == 204
    assert client.delete(f"/workspaces/{ws}/icon").status_code == 204
    assert client.get(f"/workspaces/{ws}/icon").status_code == 404
    assert record(client, ws)["icon"] is None
    assert client.delete(f"/workspaces/{ws}/icon").status_code == 204


def test_other_types_are_refused_with_415(env: Any) -> None:
    client, core, ws = env
    r = put(client, ws, GIF, "image/gif")
    assert r.status_code == 415
    assert "PNG, JPEG, WebP or SVG" in r.json()["detail"]
    assert put(client, ws, b"", "image/png").status_code == 415
    assert workspace_icon.find(core.layout, ws) is None


def test_a_picture_over_1_mib_is_refused_with_413(env: Any) -> None:
    client, core, ws = env
    data = png() + b"\x00" * (workspace_icon.MAX_BYTES + 1 - len(png()))
    assert len(data) == workspace_icon.MAX_BYTES + 1
    r = put(client, ws, data, "image/png")
    assert r.status_code == 413
    assert workspace_icon.find(core.layout, ws) is None
    # Exactly the limit is fine.
    assert put(client, ws, data[:-1], "image/png").status_code == 204


def test_an_svg_is_served_fenced_and_one_with_a_script_is_refused(env: Any) -> None:
    client, core, ws = env
    scripted = SVG.replace(b"<rect", b"<SCRIPT>alert(1)</SCRIPT><rect")
    r = put(client, ws, scripted, "image/svg+xml")
    assert r.status_code == 415
    assert "script" in r.json()["detail"]
    assert workspace_icon.find(core.layout, ws) is None
    assert put(client, ws, b'\n  <?xml version="1.0"?>' + SVG, "image/svg+xml").status_code == 204
    got = client.get(f"/workspaces/{ws}/icon")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/svg+xml"
    assert got.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    assert got.headers["x-content-type-options"] == "nosniff"


def test_a_jpeg_is_kept_as_icon_jpg(env: Any) -> None:
    client, core, ws = env
    assert put(client, ws, b"\xff\xd8\xff\xe0" + b"\x00" * 16).status_code == 204
    assert (workspace_icon.folder(core.layout, ws) / "icon.jpg").is_file()
    assert client.get(f"/workspaces/{ws}/icon").headers["content-type"] == "image/jpeg"


def test_another_workspace_id_is_404(env: Any) -> None:
    client, _core, _ws = env
    assert put(client, "nowhere", png()).status_code == 404
    assert client.get("/workspaces/nowhere/icon").status_code == 404
    assert client.delete("/workspaces/nowhere/icon").status_code == 404
    assert client.get("/workspaces/Not%20An%20Id/icon").status_code == 404
