"""Every typed error code has plain words for someone who is not a developer: what
happened and what to do (domain/errors.py, docs/errors.md), and the API's error
bodies carry them (`code` + `help`)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.api import error_bodies
from agos_core.domain.errors import TEXTS, ErrorCode, code_for_status, help_for
from agos_core.hermes_gateway import errors as gateway_errors

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs" / "errors.md"
SRC = REPO / "services" / "core" / "src" / "agos_core"


def test_every_code_has_plain_words_and_a_next_step() -> None:
    assert set(TEXTS) == set(ErrorCode)
    for code, text in TEXTS.items():
        assert text.means.endswith(".") and text.what_to_do.endswith((".", ")")), code
        # For a non-developer: no Python, HTTP or stack talk.
        for word in ("exception", "traceback", "HTTP", "stack", "None", "null", "500"):
            assert word not in text.means + text.what_to_do, (code, word)


def test_every_hermes_gateway_code_is_a_typed_code() -> None:
    found = {
        cls.code
        for _, cls in inspect.getmembers(gateway_errors, inspect.isclass)
        if issubclass(cls, gateway_errors.EngineError)
    }
    assert found and found <= {c.value for c in ErrorCode}


def test_every_code_the_core_writes_in_an_error_body_is_typed() -> None:
    """A literal `"code": "..."` next to a `"detail"` in the core's error bodies."""
    known = {c.value for c in ErrorCode}
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        for match in re.finditer(r'"detail":[^\n]*\n?[^\n]*"code": "([A-Za-z_]+)"', text):
            assert match.group(1) in known, (path, match.group(1))


def test_docs_list_every_code_with_the_same_next_step() -> None:
    docs = DOCS.read_text()
    flat = " ".join(docs.split())
    for code, text in TEXTS.items():
        assert f"### `{code.value}`" in docs, f"docs/errors.md has no section for {code}"
        assert " ".join(text.what_to_do.split()) in flat, code
        assert " ".join(text.means.split()) in flat, code


def test_a_status_gets_its_code_when_the_error_named_none() -> None:
    assert code_for_status(404) is ErrorCode.NOT_FOUND
    assert code_for_status(409) is ErrorCode.CONFLICT
    assert code_for_status(418) is ErrorCode.INVALID_REQUEST
    assert code_for_status(500) is ErrorCode.INTERNAL_ERROR
    assert ActionError("x", 503).code is ErrorCode.SERVICE_UNAVAILABLE
    assert ActionError("x", 409, code=ErrorCode.HERMES_FAILED).code is ErrorCode.HERMES_FAILED
    assert NotFoundError("The card").code is ErrorCode.NOT_FOUND
    assert help_for("nope") == ""


def _app() -> FastAPI:
    app = FastAPI()
    for exc, handler in error_bodies.error_handlers().items():
        app.add_exception_handler(exc, handler)

    @app.get("/gone")
    async def gone() -> None:
        raise NotFoundError("The card")

    @app.get("/busy")
    async def busy() -> None:
        raise ActionError("An update is running.", 409)

    @app.get("/odd")
    async def odd() -> None:
        raise ValueError("bad date")

    return app


def test_the_api_error_body_carries_the_code_and_what_to_do() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    gone = client.get("/gone")
    assert gone.status_code == 404
    assert gone.json() == {
        "detail": "The card no longer exists.",
        "code": "not_found",
        "help": TEXTS[ErrorCode.NOT_FOUND].what_to_do,
    }
    busy = client.get("/busy").json()
    assert busy["code"] == "conflict" and busy["help"] == TEXTS[ErrorCode.CONFLICT].what_to_do
    odd = client.get("/odd")
    assert odd.status_code == 400
    assert odd.json()["code"] == "invalid_value"
    assert odd.json()["help"] == TEXTS[ErrorCode.INVALID_VALUE].what_to_do
