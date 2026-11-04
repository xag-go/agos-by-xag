"""The CI gate's own inputs stay true (docs/CI.md).

- every file in conftest.HERMES_FILES exists, so the `hermes` marker never names a
  file that was renamed away (its tests would then run, and fail, on GitHub);
- the layer, file-size and function-complexity ratchets pass, so the local chain
  catches a new layer break, an oversized file or a function grown too complex before
  the PR does.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import conftest
import pytest

CORE = Path(__file__).resolve().parents[1]
REPO = CORE.parents[1]


def test_every_hermes_marked_file_exists() -> None:
    missing = sorted(
        name for name in conftest.HERMES_FILES if not (CORE / "tests" / name).is_file()
    )
    assert missing == [], f"tests/conftest.py HERMES_FILES names files that are gone: {missing}"


def test_no_new_layer_break() -> None:
    spec = importlib.util.spec_from_file_location(
        "layer_ratchet", CORE / "scripts/layer_ratchet.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    counts, _ = module.scan()
    base = json.loads((CORE / "layer-baseline.json").read_text())["pairs"]
    grew = [
        f"[{name}] {pair}: {n}"
        for name, pairs in counts.items()
        for pair, n in pairs.items()
        if n > base.get(name, {}).get(pair, 0)
    ]
    assert grew == [], "new layer breaks (python scripts/layer_ratchet.py --list):\n" + "\n".join(
        grew
    )


def test_no_new_oversized_file() -> None:
    script = REPO / "scripts/ci/file_size.py"
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _complexity(part: str) -> subprocess.CompletedProcess[str]:
    script = REPO / "scripts/ci/complexity.py"
    return subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--part", part], capture_output=True, text=True, check=False
    )


def test_no_function_got_more_complex() -> None:
    done = _complexity("python")
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(
    not (REPO / "apps/web/node_modules").is_dir() or shutil.which("pnpm") is None,
    reason="the web part needs apps/web's node_modules and pnpm",
)
def test_no_web_function_got_more_complex() -> None:
    done = _complexity("web")
    assert done.returncode == 0, done.stdout + done.stderr


# Repo scripts outside services/core that the docs tell people to run (docs/compliance/dora.md):
# held to the core's ruff rules and format, which CI runs only inside services/core.
LINTED_SCRIPTS = ["scripts/dora.py"]


@pytest.mark.parametrize("args", [["check"], ["format", "--check"]], ids=["check", "format"])
def test_the_repo_scripts_pass_the_cores_ruff(args: list[str]) -> None:
    ruff = Path(sys.executable).with_name("ruff")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(ruff), *args, "--config", str(CORE / "pyproject.toml"), *LINTED_SCRIPTS],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
