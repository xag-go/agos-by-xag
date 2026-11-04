"""Resource limits for each workspace's Hermes gateway (systemd user units).

One runaway gateway (a prompt-injected agent looping, a leaking library) must not
take the machine and every other workspace with it (threat model T18). The limits
land in AGOS's own drop-in (`engine/hermes.py _runtime_dropin`), systemd's way to
set properties on a unit Hermes owns; the user manager applies MemoryHigh/
MemoryMax/TasksMax to cgroups it already controls (cpu, memory and pids are
delegated to user slices on systemd ≥ 240), so no privilege is needed.

Defaults scale to the machine: MemoryMax is a quarter of RAM clamped to
[1 GiB, 4 GiB], MemoryHigh is three quarters of that (the kernel reclaims hard
above High and kills above Max), TasksMax is 512 (a gateway runs ~80 threads;
its Kanban/cron workers live in their own transient scopes with Hermes's own
MemoryMax, outside this count). The owner overrides with AGOS_GATEWAY_MEMORY_MAX_MB,
AGOS_GATEWAY_MEMORY_HIGH_MB, AGOS_GATEWAY_TASKS_MAX, or turns everything off with
AGOS_GATEWAY_LIMITS=off. The sandbox containers have their own limits (Hermes's
terminal.container_cpu/memory/disk defaults plus its --pids-limit,
tools/environments/docker.py; checked by tests/test_hermes_contract.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TASKS_MAX = 512
MEMORY_MAX_FLOOR_MB = 1024
MEMORY_MAX_CEILING_MB = 4096


class LimitsError(ValueError):
    """An override that isn't a whole number of MB (or tasks)."""


@dataclass(frozen=True)
class GatewayLimits:
    """What goes into the drop-in; 0 means `no line for it`."""

    memory_high_mb: int
    memory_max_mb: int
    tasks_max: int


def machine_memory_mb() -> int:
    """This machine's RAM in MB (0 when the kernel doesn't say)."""
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 0


def scaled(total_mb: int) -> GatewayLimits:
    """The defaults for a machine with `total_mb` of RAM."""
    quarter = total_mb // 4 if total_mb > 0 else MEMORY_MAX_CEILING_MB
    memory_max = min(max(quarter, MEMORY_MAX_FLOOR_MB), MEMORY_MAX_CEILING_MB)
    return GatewayLimits(
        memory_high_mb=memory_max * 3 // 4,
        memory_max_mb=memory_max,
        tasks_max=TASKS_MAX,
    )


def _override(source: dict[str, str], name: str, instead: int) -> int:
    raw = (source.get(name) or "").strip()
    if not raw:
        return instead
    if not raw.isdigit():
        raise LimitsError(f"{name} must be a whole number")
    return int(raw)


def from_env(source: dict[str, str], total_mb: int | None = None) -> GatewayLimits | None:
    """The limits AGOS runs with: the scaled defaults, each overridable;
    AGOS_GATEWAY_LIMITS=off turns them all off (None: no lines at all)."""
    switch = (source.get("AGOS_GATEWAY_LIMITS") or "auto").strip().lower()
    if switch == "off":
        return None
    if switch != "auto":
        raise LimitsError("AGOS_GATEWAY_LIMITS must be 'auto' or 'off'")
    base = scaled(machine_memory_mb() if total_mb is None else total_mb)
    high = _override(source, "AGOS_GATEWAY_MEMORY_HIGH_MB", base.memory_high_mb)
    maximum = _override(source, "AGOS_GATEWAY_MEMORY_MAX_MB", base.memory_max_mb)
    if maximum and not source.get("AGOS_GATEWAY_MEMORY_HIGH_MB", "").strip():
        high = min(high, maximum * 3 // 4)
    return GatewayLimits(
        memory_high_mb=high,
        memory_max_mb=maximum,
        tasks_max=_override(source, "AGOS_GATEWAY_TASKS_MAX", base.tasks_max),
    )


def dropin_lines(limits: GatewayLimits | None) -> list[str]:
    """The [Service] lines for the gateway drop-in (after its Environment lines)."""
    if limits is None:
        return []
    lines = [
        "# One runaway gateway must not take the machine (docs/adr/0025):",
        "# reclaimed hard above High, killed above Max, forks capped.",
        "MemoryAccounting=yes",
        "TasksAccounting=yes",
    ]
    if limits.memory_high_mb:
        lines.append(f"MemoryHigh={limits.memory_high_mb}M")
    if limits.memory_max_mb:
        lines.append(f"MemoryMax={limits.memory_max_mb}M")
    if limits.tasks_max:
        lines.append(f"TasksMax={limits.tasks_max}")
    return lines
