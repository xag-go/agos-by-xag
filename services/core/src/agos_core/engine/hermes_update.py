"""Checking for and installing a new Hermes release: Hermes's own `update`.

AGOS adds no updater of its own. `hermes update --plan --channel stable` names the
release Hermes would install (`hermes_cli/update_inventory.py` `print_update_plan`,
pinned in the contract), AGOS's contract checker says whether AGOS still fits that
release (engine/hermes_contract.py on a temporary git worktree — the way
scripts/hermes-upgrade-check.sh does it by hand, docs/hermes-upgrade.md), and
`hermes update` installs it. AGOS's part is the owner's button, the order of the
steps around the install (backups, gateways stopped, every root prepared, gateways
back — docs/hermes-upgrade.md section 2, the tested order), and the report he sees.

Nothing here touches AGOS's own code or data: if the new release makes a feature of
AGOS's section A redundant, that is a code change the owner asks for in chat; the
check's report lists what's new so he can.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from agos_core.engine.hermes import EngineError, HermesEngine, with_runtime
from agos_core.engine.loop_guard import off_loop

# Hermes's own words, pinned in the contract (engine/hermes_contract.py "hermes.update"):
# the version banner (hermes_cli/banner.py `_version_line`) and the plan's Install line
# (hermes_cli/update_inventory.py `print_update_plan`).
_VERSION = re.compile(r"Hermes Agent v(\S+).*?\blocal ([0-9a-f]{7,40})", re.S)
_PLAN = re.compile(r"Install:\s+git \(v(\S+?)(?:\s+@\s+([0-9a-f]{7,40}))?\)")
CHANNEL = "stable"

# The source checkout `hermes update` updates (docs/hermes-upgrade.md: the install at
# ~/.local/bin/hermes is that checkout's launcher). EngineConfig.hermes_src overrides.
DEFAULT_SRC = "~/.hermes/hermes-agent"


@dataclass(frozen=True)
class Release:
    version: str
    sha: str


@dataclass(frozen=True)
class Check:
    """One `Check Update` press: what is installed, what the channel offers,
    whether AGOS fits it, and what's new in it."""

    current: Release
    target: Release | None  # None: already on the channel's release
    fits: bool | None = None  # None when target is None
    report: str = ""  # the contract checker's findings when it doesn't fit
    news: list[str] = field(default_factory=list)  # the release's commit subjects


def source_dir(engine: HermesEngine) -> Path:
    src = getattr(engine.settings, "hermes_src", None)
    return Path(src) if src else Path(DEFAULT_SRC).expanduser()


def _git(engine: HermesEngine, repo: Path, *args: str, timeout: float = 120) -> str:
    off_loop("hermes source git")
    return engine.runner.run(
        ["git", "-C", str(repo), *args],
        timeout=timeout,
        env=with_runtime({"GIT_TERMINAL_PROMPT": "0"}),
    )


def installed(engine: HermesEngine) -> Release:
    """What `hermes --version` answers (hermes_cli/banner.py's line)."""
    off_loop("hermes --version")
    text = engine.runner.run([engine.settings.hermes_bin, "--version"], timeout=300)
    found = _VERSION.search(text)
    if not found:
        raise EngineError("Hermes didn't say its version.")
    return Release(version=found.group(1), sha=found.group(2))


def offered(engine: HermesEngine) -> Release | None:
    """The release `hermes update --plan --channel stable` would install (read only);
    None when it is the installed one."""
    off_loop("hermes update --plan")
    text = engine.runner.run(
        [engine.settings.hermes_bin, "update", "--plan", "--channel", CHANNEL],
        timeout=600,
    )
    found = _PLAN.search(text)
    if not found or not found.group(2):
        return None  # not a git install, or no release named: nothing to offer
    target = Release(version=found.group(1), sha=found.group(2))
    current = installed(engine)
    if current.sha.startswith(target.sha) or target.sha.startswith(current.sha):
        return None
    return target


def fits(engine: HermesEngine, target: Release) -> tuple[bool, str]:
    """Does AGOS still fit the target Hermes? The contract checker on the target's
    source, checked out into a temporary git worktree of the installed checkout —
    the installed Hermes is never switched (scripts/hermes-upgrade-check.sh)."""
    from agos_core.engine import hermes_contract

    repo = source_dir(engine)
    _git(engine, repo, "fetch", "--quiet", "origin", "--tags", timeout=600)
    sha = _git(engine, repo, "rev-parse", "--verify", f"{target.sha}^{{commit}}").strip()
    tmp = tempfile.mkdtemp(prefix="agos-update-check.")
    tree = Path(tmp) / "hermes"
    try:
        _git(engine, repo, "worktree", "add", "--quiet", "--detach", str(tree), sha)
        findings = hermes_contract.check(tree)
        broken = [f for f in findings if not f.ok]
        return not broken, hermes_contract.report(findings, tree)
    finally:
        import contextlib

        with contextlib.suppress(EngineError):
            _git(engine, repo, "worktree", "remove", "--force", str(tree))
        with contextlib.suppress(EngineError):
            _git(engine, repo, "worktree", "prune")


def whats_new(engine: HermesEngine, target: Release, limit: int = 30) -> list[str]:
    """The target's commit subjects since the installed release (newest first)."""
    repo = source_dir(engine)
    current = installed(engine)
    try:
        text = _git(engine, repo, "log", "--oneline", "--no-merges", f"{current.sha}..{target.sha}")
    except EngineError:
        return []
    lines = [line.split(" ", 1)[-1] for line in text.splitlines() if line.strip()]
    return lines[:limit]


def check(engine: HermesEngine) -> Check:
    """Everything one press of Check Update learns, read-only."""
    current = installed(engine)
    target = offered(engine)
    if target is None:
        return Check(current=current, target=None)
    ok, report = fits(engine, target)
    return Check(
        current=current,
        target=target,
        fits=ok,
        report="" if ok else report,
        news=whats_new(engine, target),
    )


# ---------------------------------------------------------------------------
# The install itself (docs/hermes-upgrade.md section 2, the tested order).
# Each step raises EngineError with a message safe to show.


def backup_roots(engine: HermesEngine, homes: list[Path], into: Path) -> list[Path]:
    """`hermes backup` of the shared home and of every root, before anything moves
    (newer Hermes migrates its stores; these restore with `hermes import`)."""
    into.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    out = into / "shared.zip"
    off_loop("hermes backup")
    engine.runner.run(
        [engine.settings.hermes_bin, "backup", "--output", str(out), "--keep", "0"],
        timeout=1800,
    )
    written.append(out)
    for home in homes:
        out = into / f"root-{home.name}.zip"
        off_loop("hermes backup")
        engine.runner.run(
            [engine.settings.hermes_bin, "backup", "--output", str(out), "--keep", "0"],
            timeout=1800,
            env=with_runtime({"HERMES_HOME": str(home)}),
        )
        written.append(out)
    return written


def install(engine: HermesEngine, target: Release) -> None:
    """`hermes update` to the checked release; a channel that moved on lands pinned
    (checkout --detach + `hermes pm repair`, docs/hermes-upgrade.md 2c)."""
    off_loop("hermes update")
    engine.runner.run(
        [
            engine.settings.hermes_bin,
            "update",
            "--channel",
            CHANNEL,
            "--yes",
            "--no-gateway-restart",
        ],
        timeout=3600,
    )
    now = installed(engine)
    if now.sha.startswith(target.sha) or target.sha.startswith(now.sha):
        return
    repo = source_dir(engine)
    _git(engine, repo, "checkout", "--detach", target.sha, timeout=600)
    off_loop("hermes pm repair")
    engine.runner.run([engine.settings.hermes_bin, "pm", "repair"], timeout=3600)
    now = installed(engine)
    if not (now.sha.startswith(target.sha) or target.sha.startswith(now.sha)):
        raise EngineError(f"Hermes is at {now.version} after the update, not {target.version}.")


def roll_back_code(engine: HermesEngine, before: Release) -> None:
    """Back to the release that ran before — only while no gateway ran the new code
    (then its stores haven't moved; docs/hermes-upgrade.md section 3)."""
    repo = source_dir(engine)
    _git(engine, repo, "checkout", "--detach", before.sha, timeout=600)
    off_loop("hermes pm repair")
    engine.runner.run([engine.settings.hermes_bin, "pm", "repair"], timeout=3600)


def prepare_home(engine: HermesEngine, home: Path) -> None:
    """A home's first run on the new code, done now so a failure shows now, not at
    the owner's next message: the dependency env (`--version`) and `config check`
    (docs/hermes-upgrade.md 2d). The memory plugin Hermes can't install behind the
    gateway's wall is actions/memory_plugin.ensure's job — the one place that
    names it (actions/hermes_update runs it beside this)."""
    env = with_runtime({"HERMES_HOME": str(home)})
    off_loop("hermes --version")
    engine.runner.run([engine.settings.hermes_bin, "--version"], timeout=1800, env=env)
    off_loop("hermes config check")
    engine.runner.run([engine.settings.hermes_bin, "config", "check"], timeout=600, env=env)
