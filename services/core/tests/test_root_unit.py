"""A root's gateway unit name, cached per folder (engine/root_unit.py)."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import FakeRunner

from agos_core.config import EngineConfig


@pytest.mark.parametrize(
    "copied",
    [
        {
            "unit": "hermes-gateway-11ve0000.service",
            "home": "/home/agos/agos-data/hermes/agos-shop",
        },
        {"unit": "hermes-gateway-11ve0000.service"},  # written by an AGOS before this fix
    ],
)
def test_a_root_copied_from_elsewhere_asks_hermes_its_own_unit_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, copied: dict[str, str]
) -> None:
    """Ops VM: staging restores live's roots, marker included; its core then took
    live's cached unit name, rewrote live's gateway unit to staging's root, and
    `agos staging down --purge` deleted live's gateway. A cached name counts only
    for the very folder it was asked for."""
    import subprocess
    from types import SimpleNamespace

    from agos_core.engine import hermes as hermes_engine
    from agos_core.engine.hermes import ROOT_MARKER, HermesEngine

    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="stg-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner=FakeRunner(tmp_path / ".hermes"),
    )
    root = engine.root("shop")
    root.mkdir(parents=True)
    (root / ROOT_MARKER).write_text(json.dumps({"id": "shop", **copied}))
    engine._judge_argv = ["/bin/py", "-c", hermes_engine.JUDGE_RUN]
    asked: list[str] = []

    def run(argv: Any, **kw: Any) -> Any:
        asked.append(str(kw["env"]["HERMES_HOME"]))
        return SimpleNamespace(returncode=0, stdout="AGOS-UNIT hermes-gateway-0570000\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert engine.service_unit("shop").name == "hermes-gateway-0570000.service"
    assert asked == [str(root)]
    kept = json.loads((root / ROOT_MARKER).read_text())
    assert kept["id"] == "shop" and kept["home"] == str(root.resolve())
    assert engine.service_unit("shop").name == "hermes-gateway-0570000.service"
    assert len(asked) == 1  # asked once, then kept for this folder
