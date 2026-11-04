"""#46: a chat hidden in AGOS is archived through Hermes's own public route
`PATCH /api/sessions/{id}` on the root's gateway (gateway/platforms/api_server.py
_handle_patch_session), a member's under `/p/<member>/` with that member's key; no
in-runtime SessionDB script."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from agos_core.config import EngineConfig
from agos_core.engine.hermes import EngineError, HermesEngine


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []
        self.known = {"s-1", "s-2"}
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_PATCH(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                gateway.calls.append(
                    (self.command, self.path, self.headers.get("Authorization", ""), body)
                )
                sid = self.path.rsplit("/", 1)[-1]
                code = 200 if sid in gateway.known else 404
                data = json.dumps({"session": {"id": sid, **body}}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def gateway() -> Iterator[_Gateway]:
    g = _Gateway()
    yield g
    g.server.shutdown()


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermesEngine:
    monkeypatch.undo()  # the real archive_sessions, not conftest's stand-in
    return HermesEngine(
        EngineConfig(
            hermes_bin="hermes",
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        egress=False,
    )


def _homes(tmp_path: Path, port: int) -> tuple[Path, Path]:
    root = tmp_path / "roots" / "ws1"
    member = root / "profiles" / "agos-ws1--writer"
    member.mkdir(parents=True)
    (root / ".env").write_text(f"API_SERVER_PORT={port}\nAPI_SERVER_KEY=root-key\n")
    (member / ".env").write_text("API_SERVER_KEY=member-key\n")
    return root, member


def test_a_cofounders_chat_is_archived_by_hermess_patch_route(
    engine: HermesEngine, gateway: _Gateway, tmp_path: Path
) -> None:
    root, _ = _homes(tmp_path, gateway.port)
    assert engine.archive_sessions(root, ["s-1", "nope"], True) == ["s-1"]
    assert gateway.calls[0] == (
        "PATCH",
        "/api/sessions/s-1",
        "Bearer root-key",
        {"archived": True},
    )
    assert gateway.calls[1][1] == "/api/sessions/nope"
    assert engine.archive_sessions(root, ["s-2"], False) == ["s-2"]
    assert gateway.calls[-1][3] == {"archived": False}


def test_a_members_chat_goes_under_its_profile_prefix_with_its_own_key(
    engine: HermesEngine, gateway: _Gateway, tmp_path: Path
) -> None:
    _, member = _homes(tmp_path, gateway.port)
    assert engine.archive_sessions(member, ["s-1"], True) == ["s-1"]
    _, path, auth, _ = gateway.calls[0]
    assert (path, auth) == ("/p/agos-ws1--writer/api/sessions/s-1", "Bearer member-key")


def test_a_gateway_that_does_not_answer_is_an_engine_error(
    engine: HermesEngine, tmp_path: Path
) -> None:
    root, _ = _homes(tmp_path, 1)  # nothing listens on port 1
    with pytest.raises(EngineError):
        engine.archive_sessions(root, ["s-1"], True)


def test_no_in_runtime_archive_script_is_left() -> None:
    import agos_core.engine.hermes as hermes

    assert not hasattr(hermes, "_ARCHIVE")
