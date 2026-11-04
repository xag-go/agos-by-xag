"""agos_core/shared/: pure code the core and the agos-guard plugin share.

The core imports it from agos_core.shared (never from the plugin, which runs inside
Hermes); the plugin keeps a byte-for-byte copy beside its own files.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

from agos_core.engine import guard_files
from agos_core.hermes_plugin import agos_guard
from agos_core.hermes_plugin.agos_guard import bridge_core, keys, stt_gemini
from agos_core.shared import guard_contract

CORE = Path(__file__).resolve().parent.parent
SHARED = CORE / "src" / "agos_core" / "shared"
PLUGIN = CORE / "src" / "agos_core" / "hermes_plugin" / "agos_guard"


def test_every_shared_module_has_its_copy_in_the_plugin() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(CORE / "scripts" / "sync_shared.py"), "--check"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout
    assert (PLUGIN / "guard_contract.py").read_bytes() == (
        SHARED / "guard_contract.py"
    ).read_bytes()


def test_shared_modules_import_only_the_standard_library() -> None:
    """A copy inside Hermes has no agos_core, and a file the plugin loads by path has
    no package: no agos_core import, no relative import."""
    for path in SHARED.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path.name}: relative import"
                assert (
                    node.module is None
                    or node.module == "__future__"
                    or (node.module.split(".")[0] in sys.stdlib_module_names)
                ), f"{path.name}: imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in sys.stdlib_module_names, alias.name


def test_the_plugin_reads_the_same_names() -> None:
    assert agos_guard.POLICY_FILE == guard_contract.POLICY_FILE
    assert agos_guard.ACTIONS == guard_contract.ACTIONS
    assert bridge_core.AGOS_BUTTONS == guard_contract.AGOS_BUTTONS
    assert stt_gemini.NAME == guard_contract.STT_NAME
    assert stt_gemini.DEFAULT_MODEL == guard_contract.STT_DEFAULT_MODEL
    # keys.py also runs as a script in Hermes's runtime (it imports nothing): its own
    # words must stay the shared ones.
    assert keys.NOTE == guard_contract.KEY_NOTE


def test_the_core_runs_the_plugins_own_keys_script() -> None:
    assert Path(keys.__file__).resolve() == guard_files.KEYS_SCRIPT
    assert Path(agos_guard.__file__).resolve().parent == guard_files.PLUGIN_SOURCE


def test_bridge_core_loaded_by_file_finds_its_copy() -> None:
    """Hermes may load the bridge's parts by path, with no package (agos_guard._sibling)."""
    name = "agos_guard_bridge_core_shared_probe"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "bridge_core.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        assert module.AGOS_BUTTONS == guard_contract.AGOS_BUTTONS
    finally:
        sys.modules.pop(name, None)
