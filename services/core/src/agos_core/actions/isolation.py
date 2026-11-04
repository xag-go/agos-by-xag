"""Workspace isolation (the cage around each workspace's gateway, ADR 0025) as the
owner sees it: the attention lines on Settings → Server & backup and the section of
`agos doctor` (actions/diagnostics.py).

Owns: the words and the read of the cage's state for those two places. Must not:
decide whether a gateway is caged (engine/cage.py `enabled` does) or run bwrap for
Settings (the page reads what the engine already knows; only `agos doctor` checks).
"""

from __future__ import annotations

import contextlib
from typing import Any

from agos_core.engine import cage, sandbox_broker
from agos_core.hermes_gateway.errors import EngineError

__all__ = ["OFF_WARNING", "REFUSED_WARNING", "report_lines", "warnings"]

OFF_WARNING = (
    "Workspace isolation is OFF (AGOS_SANDBOXD=off): every workspace's agents can reach "
    "this machine's Docker, which is as good as full control of the server. Remove "
    "AGOS_SANDBOXD=off from the agos-core service and restart AGOS to turn it back on."
)
REFUSED_WARNING = (
    "Workspace isolation can't be built on this machine (cage_refused), so workspaces' "
    "agents don't start. Run agos doctor on the server: it says why and the exact fix "
    "(docs/troubleshooting.md)."
)


def warnings(core: Any) -> list[str]:
    """The attention lines Settings → Server & backup shows (OpsWarnings), from what
    the engine already knows: nothing on a machine whose cage works."""
    engine = getattr(core, "engine", None)
    if engine is None:
        return []
    found = sandbox_broker.state(engine)
    if found == "off":
        return [OFF_WARNING]
    if found == "refused":
        return [REFUSED_WARNING]
    return []


def _gateways(engine: Any) -> tuple[int, int]:
    """(caged, all) gateways of this AGOS's roots, by their drop-ins. A drop-in
    whose unit file is gone (a deleted workspace's leftover) is not a gateway."""
    units = engine.settings.host_home / ".config" / "systemd" / "user"
    roots = f"{engine.settings.roots_dir}/"
    caged = total = 0
    for conf in sorted(units.glob("*.service.d/agos-runtime.conf")):
        if not (units / conf.parent.name.removesuffix(".d")).is_file():
            continue
        with contextlib.suppress(OSError):
            text = conf.read_text()
            if roots in text:
                total += 1
                caged += '"bwrap"' in text
    return caged, total


def report_lines(core: Any) -> list[str]:
    """`agos doctor`'s section: the mode, bwrap, a real check of the cage (bwrap is
    run once when this engine has not run it yet) and the gateways caged."""
    lines = ["### Workspace isolation (the gateways' cage)", ""]
    engine = getattr(core, "engine", None)
    if engine is None:
        return [*lines, "- engine: none (no gateway to cage)", ""]
    mode = engine.settings.sandboxd
    lines += [
        f"- mode: {mode}" + (" (AGOS_SANDBOXD=off, the owner's choice)" if mode == "off" else ""),
        f"- bwrap: {'installed' if cage.available() else 'missing'}",
    ]
    if mode == "off":
        lines.append("- cage: OFF: gateways keep the real Docker socket")
    else:
        try:
            engine.sandboxd_on()
            lines.append("- cage: ok")
        except EngineError as error:
            lines.append(f"- cage: REFUSED ({cage.CODE}): {error}")
    caged, total = _gateways(engine)
    lines += [f"- gateways caged: {caged} of {total}", ""]
    return lines
