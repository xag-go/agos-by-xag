"""Settings → Health → Secrets check: where a key sits where it shouldn't (ADR 0023).

The owner runs it himself (no schedule); the workspace Co-Founder runs the same
check from a chat (agos_action secrets_check), for its own workspace only:
workspaces are closed off from each other, so it never sees another one's findings.
It only reads: nothing is changed, and no value is ever shown, only the key's kind
and its last 4 characters, and where it is.

1. Keys in chat history: every message Hermes kept in each workspace's Hermes root
   (the root's and each member's state.db, opened read-only) whose text Hermes's own
   masking would change (agent/redact.py redact_sensitive_text, run in Hermes's
   runtime by hermes_plugin/agos_guard/keys.py `scan`, one run per root). Messages
   from before his own messages were masked (engine/owner_keys.py) are found here.
2. Keys in logs: each root's and member's logs/*.log, the same test; file + count.
3. Wrong permissions: secret files (.env, auth.json, .credentials.json, *.token,
   master.key, *.agosb, .agos-tool-keys.json) that others than AGOS's user may read
   (not 600), and the folders holding them (AGOS's system/ and backups folders,
   each workspace's Hermes root) not 700.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.engine.guard_files import KEYS_SCRIPT
from agos_core.engine.hermes import with_runtime
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway import process as hermes_process

log = logging.getLogger("agos.secrets_check")

SECRET_FILES = {".env", "auth.json", ".credentials.json", "master.key", ".agos-tool-keys.json"}
SECRET_SUFFIXES = (".token", ".agosb")
# Never walked: dependency envs, checkouts and caches hold no secret file of AGOS's.
_PRUNE = {
    "node_modules",
    ".git",
    "installs",
    "__pycache__",
    "site-packages",
    ".venv",
    "venv",
    "sandboxes",
    "audio_cache",
    "image_cache",
}
_SCAN_S = 900.0
_MARK = "AGOS-KEYS "


def _mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.lstat().st_mode)
    except OSError:
        return None


def _secret_file(name: str) -> bool:
    return name in SECRET_FILES or name.endswith(SECRET_SUFFIXES)


def _bad_files(top: Path) -> list[dict[str, str]]:
    """Secret files under `top` that others may read (no symlink followed)."""
    out: list[dict[str, str]] = []
    if not top.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE]
        for name in filenames:
            if not _secret_file(name):
                continue
            path = Path(dirpath) / name
            mode = _mode(path)
            if mode is not None and stat.S_ISREG(path.lstat().st_mode) and mode & 0o077:
                out.append({"path": str(path), "mode": f"{mode:o}", "want": "600"})
    return out


def _bad_folder(path: Path) -> list[dict[str, str]]:
    mode = _mode(path)
    if mode is None or not path.is_dir() or not mode & 0o077:
        return []
    return [{"path": str(path), "mode": f"{mode:o}", "want": "700"}]


def _workspaces(core: Core, workspace_id: str | None) -> list[Any]:
    from agos_core.db.workspaces import list_workspaces

    return [w for w in list_workspaces(core.db) if workspace_id is None or w.id == workspace_id]


def _scan_root(core: Core, root: Path) -> dict[str, Any]:
    """keys.py `scan` of one root in Hermes's runtime (its masking decides)."""
    from agos_core.engine.models import hermes_python

    engine = core.engine
    assert engine is not None
    off_loop("hermes secrets check")
    done = hermes_process.run_process(
        [hermes_python(engine.settings), str(KEYS_SCRIPT), "scan", str(root)],
        timeout=hermes_wait(_SCAN_S),
        env=with_runtime({"HOME": str(engine.settings.host_home), "PATH": "/usr/bin:/bin"}),
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith(_MARK)]
    if done.returncode != 0 or not lines:
        raise RuntimeError(f"The engine's runtime ended with {done.returncode}")
    found: dict[str, Any] = json.loads(lines[-1][len(_MARK) :])
    return found


def run(core: Core, workspace_id: str | None = None) -> dict[str, Any]:
    """The findings: every workspace (the owner's page), or one (its Co-Founder)."""
    engine = core.engine
    shown = _workspaces(core, workspace_id)
    roots = (
        [(w, engine.root(w.id)) for w in shown if (engine.root(w.id) / "config.yaml").is_file()]
        if engine is not None
        else []
    )
    chats: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    not_checked: list[str] = []
    more = 0
    if engine is None and shown:
        not_checked.append("The engine isn't available here: chat history and logs not checked.")

    def one(item: tuple[Any, Path]) -> tuple[Any, dict[str, Any] | None, str]:
        w, root = item
        try:
            return w, _scan_root(core, root), ""
        except (OSError, RuntimeError, ValueError, hermes_process.SubprocessError) as error:
            log.info("secrets check of %s not done: %s", w.id, error)
            return w, None, str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for w, found, error in pool.map(one, roots):
            if found is None:
                not_checked.append(f"{w.name}: the engine couldn't check it ({error[:120]})")
                continue
            where = {"workspace_id": w.id, "workspace": w.name}
            chats += [{**where, **c} for c in found.get("chats", [])]
            more += max(0, int(found.get("chats_total", 0)) - len(found.get("chats", [])))
            logs += [{**where, **entry} for entry in found.get("logs", [])]
            not_checked += [f"{w.name}: {e}" for e in found.get("errors", [])]
    permissions = _permissions(core, workspace_id, [root for _w, root in roots])
    problems = len(chats) + more + len(logs) + len(permissions)
    return {
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "problems": problems,
        "chats": chats,
        "chats_more": more,
        "logs": logs,
        "permissions": permissions,
        "not_checked": not_checked,
    }


def _permissions(core: Core, workspace_id: str | None, roots: list[Path]) -> list[dict[str, str]]:
    from agos_core.storage.layout import workspace_paths

    layout = core.layout
    if workspace_id is not None:
        places = [*roots, workspace_paths(layout, workspace_id).root]
        out = [f for place in places for f in _bad_files(place)]
        return out + [f for root in roots for f in _bad_folder(root)]
    from agos_core.actions.backups import backup_dir

    try:
        backups = backup_dir(core)
    except Exception:  # noqa: BLE001 - a misplaced backup folder is the backup page's to say
        backups = None
    tops = [layout.root, *(p for p in roots if layout.root not in p.parents)]
    if backups is not None:
        tops.append(backups)
    out = [f for top in tops for f in _bad_files(top)]
    folders = [layout.system, layout.root / "backups", *roots]
    if backups is not None:
        folders.append(backups)
    return out + [f for folder in folders for f in _bad_folder(folder)]


def as_text(found: dict[str, Any], limit: int = 6000) -> str:
    """The findings in short, for the Co-Founder's answer (never a value)."""
    if not found["problems"] and not found["not_checked"]:
        return "Secrets check: 0 problems."
    lines = [f"Secrets check: {found['problems']} problem(s)."]
    if found["chats"]:
        lines.append(
            "Keys in chat history (tell the owner to replace each key, then ask to purge):"
        )
        for c in found["chats"]:
            session = c.get("session") or c.get("source") or "a chat"
            lines.append(
                f"- {c['kind']} ending {c['last4'] or '?'} · {c['workspace']} · {session}"
                f" · {c['role']} · {(c.get('at') or '')[:10]}"
            )
        if found["chats_more"]:
            lines.append(f"- and {found['chats_more']} more")
    if found["logs"]:
        lines.append("Keys in logs:")
        lines += [f"- {e['workspace']} {e['file']}: {e['count']} line(s)" for e in found["logs"]]
    if found["permissions"]:
        lines.append("Wrong permissions:")
        lines += [
            f"- {p['path']}: {p['mode']} (should be {p['want']})" for p in found["permissions"]
        ]
    if found["not_checked"]:
        lines.append("Not checked: " + "; ".join(found["not_checked"]))
    return "\n".join(lines)[:limit]
