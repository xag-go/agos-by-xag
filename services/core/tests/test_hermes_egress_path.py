"""The egress proxy's script is mounted from engine/egress_proxy.py wherever the code
that starts it lives (it moved out of engine/hermes.py into its package)."""

from pathlib import Path
from typing import Any

from agos_core.engine import network as net
from agos_core.engine.hermes import HermesEngine


class _Docker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.settings = type("S", (), {"sandbox_image": "agos-sandbox:test"})()

    def _docker(self, *args: str, timeout: float = 60) -> str:
        self.calls.append(args)
        return ""


def test_the_proxy_mounts_the_engines_own_script() -> None:
    fake: Any = _Docker()
    HermesEngine.ensure_proxy(fake)
    run = next(c for c in fake.calls if c[0] == "run")
    mount = run[run.index("-v") + 1]
    source = Path(mount.split(":", 1)[0])
    assert mount.endswith(":/agos/egress_proxy.py:ro")
    assert source.is_file()
    assert source == (Path(net.__file__).with_name("egress_proxy.py")).resolve()
