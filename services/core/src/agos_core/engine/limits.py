"""Account limits from Hermes (the same numbers Hermes's /usage shows). Cached for
a minute so the pages stay fast; never guessed.

- Codex, Copilot, Nous: Hermes's own `hermes usage --provider <p> --json`
  (H: hermes_cli/subcommands/usage.py, a stable documented JSON document).
- Claude: a script in Hermes's venv, because Hermes misreads Claude's numbers: it
  scales any `utilization` <= 1 as a fraction (H: agent/account_usage.py
  `_fetch_anthropic_account_usage` passes `fraction=True` to `_usage_windows`), so
  "1% used" shows as 100%. The script reads Anthropic's `limits` list (whole
  percents) first, and runs per home — the shared home, then each root — until
  one holds the login (`_claude_homes`: the sign-in lives in a workspace root's
  own pool, and a home without it answers empty at no request cost).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import agos_core.engine.hermes as _hermes_engine
from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

PROVIDERS = ("anthropic", "openai-codex", "copilot", "nous")
LABELS = {
    "anthropic": "Claude",
    "openai-codex": "OpenAI (Codex)",
    "copilot": "GitHub Copilot",
    "nous": "Nous Portal",
}
WARN_AT = 80.0

# Claude: Anthropic's usage answer has an explicit `limits` list with whole
# percents (the list claude.ai's Usage page shows, incl. per-model weeks). Hermes
# reads the older `utilization` field and treats any value <= 1 as a fraction,
# so "1% used" showed as 100%. We read `limits` first; if it is missing we take
# `utilization` as the percent it is.
_SCRIPT = r"""
import json

LABELS = {"session": "Current session", "weekly_all": "This week"}


def claude_windows():
    from agent import account_usage as au
    from agent.anthropic_credentials import _is_oauth_token, resolve_anthropic_token
    token = (resolve_anthropic_token() or "").strip()
    if not token or not _is_oauth_token(token):
        return None
    def ask(token):
        return au._get_json(
            "https://api.anthropic.com/api/oauth/usage",
            {"Authorization": f"Bearer {token}", "Accept": "application/json",
             "Content-Type": "application/json", "anthropic-beta": "oauth-2025-04-20",
             "User-Agent": "claude-code/2.1.0"},
            timeout=15.0,
        )

    try:
        payload = ask(token)
    except Exception as error:
        # The saved login expired (nobody used Claude for hours): Hermes's pool
        # renews it under its own cross-process lock, as before an API call.
        if "401" not in str(error):
            raise
        from agent.credential_pool import load_pool
        entry = load_pool("anthropic").select()
        fresh = (getattr(entry, "access_token", None) or "").strip()
        if not fresh or fresh == token:
            raise
        payload = ask(fresh)
    windows = []
    for item in payload.get("limits") or []:
        if not isinstance(item, dict) or not isinstance(item.get("percent"), (int, float)):
            continue
        kind = str(item.get("kind") or "")
        label = LABELS.get(kind)
        if label is None:
            model = (((item.get("scope") or {}).get("model") or {}).get("display_name"))
            label = f"{model} this week" if model and item.get("group") == "weekly" else kind.replace("_", " ").capitalize()
        windows.append({"label": label, "used": float(item["percent"]),
                        "reset": item.get("resets_at"), "detail": None})
    if windows:
        return windows
    for key, label in (("five_hour", "Current session"), ("seven_day", "This week"),
                       ("seven_day_opus", "Opus this week"), ("seven_day_sonnet", "Sonnet this week")):
        w = payload.get(key) or {}
        if isinstance(w.get("utilization"), (int, float)):
            windows.append({"label": label, "used": float(w["utilization"]),
                            "reset": w.get("resets_at"), "detail": None})
    return windows or None


out = []
# One request only: Anthropic rate-limits this endpoint (429).
try:
    windows = claude_windows()
except Exception:
    out.append({"provider": "anthropic", "unavailable": True})
else:
    if windows:
        out.append({"provider": "anthropic", "windows": windows, "details": []})
print("AGOS-JSON " + json.dumps(out))
"""


@dataclass(frozen=True)
class Window:
    label: str
    used_percent: float | None
    reset_at: str | None


@dataclass(frozen=True)
class Account:
    provider: str
    label: str
    windows: list[Window]
    details: list[str]

    @property
    def warning(self) -> bool:
        return any((w.used_percent or 0) >= WARN_AT for w in self.windows)


_cache: dict[str, tuple[float, list[Account]]] = {}


CLI_PROVIDERS = ("openai-codex", "copilot", "nous")  # Hermes's `hermes usage --json`


def account_limits(
    engine: EngineConfig, python: str, max_age: float = 60, *, kept: bool = False
) -> list[Account]:
    """Each logged-in provider's limits as Hermes reads them, kept `max_age` s.
    `kept`: the page, whose numbers move all the time: older ones come at once
    and are read again behind it (one read at a time); a decision (account_pause)
    always gets numbers younger than `max_age`."""
    if kept:
        hit = _cache.get(str(engine.hermes_home))
        if hit is not None and time.monotonic() - hit[0] >= max_age:
            _read_behind(engine, python, max_age)
            return hit[1]
    return _limits_now(engine, python, max_age)


def forget() -> None:
    """A login came or went (Settings → Models): the next view of the limits asks
    Hermes again instead of showing the last numbers (another provider's, or none)."""
    _cache.clear()


_behind: set[str] = set()
_behind_lock = threading.Lock()


def _read_behind(engine: EngineConfig, python: str, max_age: float) -> None:
    from agos_core.engine import read_cache

    key = str(engine.hermes_home)
    with _behind_lock:
        if key in _behind:
            return
        _behind.add(key)

    def run() -> None:
        try:
            _limits_now(engine, python, max_age)
        finally:
            with _behind_lock:
                _behind.discard(key)

    read_cache.submit(run)


def read_ahead(core: Any) -> None:
    """After the core starts (engine/read_ahead.py): the first read of the limits."""
    from agos_core.engine.models import hermes_python

    if core.engine is None:
        return
    try:
        python = hermes_python(core.engine.settings)
    except (RuntimeError, OSError):
        return
    account_limits(core.engine.settings, python)


def _limits_now(engine: EngineConfig, python: str, max_age: float = 60) -> list[Account]:
    key = str(engine.hermes_home)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1 + len(CLI_PROVIDERS)) as pool:
        claude = pool.submit(_claude, engine, python)
        others = [pool.submit(_hermes_usage, engine, p) for p in CLI_PROVIDERS]
        rows = [*claude.result(), *(row for f in others if (row := f.result()) is not None)]
    return _remember(key, rows)


def _env(engine: EngineConfig) -> dict[str, str]:
    return _hermes_engine.with_runtime({"HOME": str(engine.host_home), "PATH": "/usr/bin:/bin"})


def _claude_homes(engine: EngineConfig) -> list[Path]:
    """The homes that may hold the Claude login, the shared home first. The
    sign-in lives in each workspace root's own credential pool (one account
    everywhere), and only Hermes may read its stores — so the probe simply runs
    Hermes's script IN each home (HERMES_HOME) until one answers. A home with no
    login answers empty without any Anthropic request, so the endpoint is still
    asked at most once."""
    roots = sorted(p for p in engine.roots_dir.glob("*") if (p / "config.yaml").is_file())
    return [engine.hermes_home, *roots]


def _claude(engine: EngineConfig, python: str) -> list[dict[str, Any]]:
    for home in _claude_homes(engine):
        env = _env(engine)
        env["HERMES_HOME"] = str(home)
        try:
            off_loop("hermes usage limits")
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [python, "-c", _SCRIPT],
                capture_output=True,
                text=True,
                timeout=hermes_wait(40),
                env=env,
                check=False,
                cwd=str(Path(python).parent.parent.parent),
            )
            hermes_contract.ran(done)
            lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")]
            rows: list[dict[str, Any]] = json.loads(lines[-1][len("AGOS-JSON ") :]) if lines else []
        except (OSError, subprocess.TimeoutExpired, ValueError):
            rows = []
        if rows:
            return rows  # the login's home (its windows, or its one failure)
    return []


def _hermes_usage(engine: EngineConfig, provider: str) -> dict[str, Any] | None:
    """Hermes's own `hermes usage --provider <p> --json` (exit 1: no login for it,
    no usage endpoint, or the fetch failed)."""
    try:
        off_loop("hermes usage")
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [engine.hermes_bin, "usage", "--provider", provider, "--json"],
            capture_output=True,
            text=True,
            timeout=hermes_wait(40),
            env=_env(engine),
            check=False,
        )
        doc = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        doc = None
    if not isinstance(doc, dict):
        return None
    windows = [
        {
            "label": w.get("label"),
            "used": w.get("used_percent"),
            "reset": w.get("resets_at"),
            "detail": w.get("detail"),
        }
        for w in doc.get("windows") or []
        if isinstance(w, dict)
    ]
    if not windows and doc.get("unavailable_reason"):
        return None
    return {
        "provider": provider,
        "windows": windows,
        "details": [str(d) for d in doc.get("details") or []][:4],
    }


# The last good numbers per account: when a provider says "try later" (rate
# limit, network), the page keeps showing them instead of dropping the account.
_last_good: dict[str, dict[str, Account]] = {}


def _remember(key: str, rows: list[dict[str, Any]]) -> list[Account]:
    last = _last_good.setdefault(key, {})
    fresh = _accounts([r for r in rows if not r.get("unavailable")])
    for account in fresh:
        last[account.provider] = account
    result = list(fresh)
    for r in rows:
        if r.get("unavailable") and str(r["provider"]) in last:
            result.append(_still_true(last[str(r["provider"])]))
    order = {p: i for i, p in enumerate(PROVIDERS)}
    result.sort(key=lambda a: order.get(a.provider, len(order)))
    _cache[key] = (time.monotonic(), result)
    return result


def _still_true(account: Account) -> Account:
    """Kept numbers of a window whose reset time has passed are wrong (the page
    showed yesterday's 88% all day): those show nothing until a fresh read."""
    from datetime import UTC, datetime

    def reset(w: Window) -> bool:
        try:
            at = datetime.fromisoformat(str(w.reset_at))
        except ValueError:
            return False
        return (at if at.tzinfo else at.replace(tzinfo=UTC)) <= datetime.now(UTC)

    return Account(
        provider=account.provider,
        label=account.label,
        windows=[
            Window(w.label, None, None) if w.reset_at and reset(w) else w for w in account.windows
        ],
        details=account.details,
    )


def _accounts(rows: list[dict[str, Any]]) -> list[Account]:
    return [
        Account(
            provider=r["provider"],
            label=LABELS.get(r["provider"], r["provider"]),
            windows=[
                Window(
                    label=str(w["label"]),
                    used_percent=float(w["used"]) if w.get("used") is not None else None,
                    reset_at=w.get("reset"),
                )
                for w in r.get("windows") or []
            ],
            details=[str(d) for d in r.get("details") or []],
        )
        for r in rows
    ]
