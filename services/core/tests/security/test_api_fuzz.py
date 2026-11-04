"""API fuzzing of the core with Schemathesis, against its own openapi.json.

Nightly only (`AGOS_FUZZ=1`, schemathesis added with `uv run --with`; see the job
`security-scans` in .github/workflows/nightly-hermes.yml), skipped everywhere else.
The core runs in this process behind tests/security/fuzz_rig.py (fake Hermes/Docker,
no real subprocess, no outbound connection), so nothing on the machine is touched. A
few operations that act on the machine itself are left out (`SKIP`).

Each generated request is checked for one thing: no 500 (an exception no handler
mapped; a 502/503 only says the rig has no Hermes, which is right here). Calls are
chained through real rows: every create (a POST on a collection that answers an id)
is called first with generated valid input (`pool`), and the operations under it
(read, update, delete, its sub-resources) get that real id in most cases.

Run locally: `AGOS_FUZZ=1 uv run --with schemathesis==4.32.7 pytest -p no:xdist
tests/security/test_api_fuzz.py` (AGOS_FUZZ_EXAMPLES=N per operation, default 25).
"""

from __future__ import annotations

import os
import random
import re
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("AGOS_FUZZ") != "1":
    pytest.skip("API fuzzing runs in the nightly only (AGOS_FUZZ=1)", allow_module_level=True)

schemathesis = pytest.importorskip("schemathesis")
hypothesis = pytest.importorskip("hypothesis")
from security import fuzz_hooks  # noqa: E402
from security.fuzz_rig import Rig, serve  # noqa: E402

EXAMPLES = int(os.environ.get("AGOS_FUZZ_EXAMPLES", "25"))
PORT = int(os.environ.get("AGOS_FUZZ_PORT", "9731"))
# Acts on the machine itself (its own update, backups, remote access, a whole import):
# fuzzing them proves nothing about the API and only slows the run down.
SKIP = (
    "/agos-update/run",
    "/hermes-update/run",
    "/backups/run",
    "/backups/rehearse",
    "/remote-access/activate",
    "/remote-access/off",
    "/import",
)
RIG: dict[str, Rig] = {}
# Where real ids come from: the creates (POST on a collection, answering an id) whose
# ids feed every operation under them: create -> read -> update -> delete on a real row.
TRIES = int(os.environ.get("AGOS_FUZZ_CREATE_TRIES", "30"))
_PARAM = re.compile(r"{(\w+)}")


@pytest.fixture(scope="module")
def rig(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Rig]:
    with serve(tmp_path_factory.mktemp("fuzz"), PORT) as running:
        RIG["rig"] = running
        yield running


@pytest.fixture(scope="module")
def api_schema(rig: Rig) -> Any:
    spec = Path(__file__).resolve().parents[2] / "openapi.json"
    loaded = schemathesis.openapi.from_path(str(spec))
    loaded.config.update(base_url=rig.base, headers=dict(rig.headers))
    return loaded.exclude(path=list(SKIP))


@pytest.fixture(scope="module")
def pool(api_schema: Any, rig: Rig) -> dict[str, str]:
    """{create path: a real id it answered} (the rig's workspace in the path)."""
    made: dict[str, str] = {}
    for path, methods in api_schema.raw_schema["paths"].items():
        if (
            "post" not in methods
            or path.endswith("}")
            or set(_PARAM.findall(path)) - {"workspace_id"}
        ):
            continue
        if path == "/workspaces" or path in SKIP:
            continue  # the rig's own workspace is the one; SKIP acts on the machine
        found = _create(api_schema[path]["POST"], rig)
        if found is not None:
            made[path] = found
    return made


def _create(operation: Any, rig: Rig) -> str | None:
    strategy = operation.as_strategy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Hypothesis: .example() outside a test
        for _ in range(TRIES):
            case = strategy.example()
            if "workspace_id" in (case.path_parameters or {}):
                case.path_parameters["workspace_id"] = rig.workspace
            answer = case.call(base_url=rig.base, headers=dict(rig.headers))
            if 200 <= answer.status_code < 300:
                body = answer.json() if answer.content else None
                if isinstance(body, dict) and body.get("id") not in (None, ""):
                    return str(body["id"])
    return None


def _real_ids(path: str, made: dict[str, str]) -> dict[str, str]:
    """{path parameter: real id} for the creates this operation sits under."""
    out: dict[str, str] = {}
    for create, made_id in made.items():
        if path.startswith(create + "/{"):
            out[_PARAM.match(path[len(create) + 1 :]).group(1)] = made_id  # type: ignore[union-attr]
    return out


def test_creates_give_real_ids_to_the_operations_under_them(pool: dict[str, str]) -> None:
    # The chained part of the fuzzing is real only when the creates work on the rig.
    print(f"creates that answered a real id: {len(pool)}: {sorted(pool)}")
    assert len(pool) >= 8, f"only {len(pool)} creates answered an id: {sorted(pool)}"


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()  # type: ignore[untyped-decorator]
@hypothesis.settings(  # type: ignore[untyped-decorator]
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(hypothesis.HealthCheck),
)
def test_no_operation_answers_a_server_error(case: Any, pool: dict[str, str]) -> None:
    running = RIG["rig"]
    params = case.path_parameters or {}
    if "workspace_id" in params and running.workspace and random.random() < 0.7:  # noqa: S311
        # Most cases hit the real workspace and the rows made in it (`pool`), so
        # handlers run past the 404 on real data.
        params["workspace_id"] = running.workspace
        for name, made_id in _real_ids(case.operation.path, pool).items():
            params[name] = made_id
    case.call_and_validate(
        base_url=running.base, headers=dict(running.headers), checks=[fuzz_hooks.check()]
    )
