"""A webhook's signing secret AGOS made while it saved the automation (its page's
save, the Co-Founder's create / update), kept for the owner to see ONCE.

The webhook's own dialog shows a secret it makes in its answer (actions/hooks.py
`new_secret`). A secret made anywhere else used to be thrown away: every delivery
was then refused (401) until he made a new one (read-vs-act review M9). Now it is
kept here, sealed with AGOS's master key (data/system/hook-secrets.json, 0600),
until he shows it in the dialog (`secretWaiting` on the webhook; POST
.../hook/secret, owner only), or the webhook's secret changes or goes. Never in a
plain read of the automation, so never in an agent's answer.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Any

FILE = "hook-secrets.json"
_SEAL = "automation.webhook_signing"
_lock = threading.Lock()


def _file(core: Any) -> Path:
    return Path(core.settings.data_dir) / "system" / FILE


def _read(core: Any) -> dict[str, str]:
    try:
        found = json.loads(_file(core).read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}


def _write(core: Any, kept: dict[str, str]) -> None:
    path = _file(core)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(kept, handle)
    tmp.replace(path)


def _key(workspace_id: str, automation_id: int) -> str:
    return f"{workspace_id}:{int(automation_id)}"


def keep(core: Any, workspace_id: str, automation_id: int, secret: str) -> None:
    from agos_core.security.secrets import encrypt_secret

    sealed = encrypt_secret(core.master_key, secret, _SEAL)
    with _lock:
        kept = _read(core)
        kept[_key(workspace_id, automation_id)] = sealed
        _write(core, kept)


def waiting(core: Any, workspace_id: str, automation_id: int) -> bool:
    return _key(workspace_id, automation_id) in _read(core)


def drop(core: Any, workspace_id: str, automation_id: int) -> None:
    with _lock:
        kept = _read(core)
        if kept.pop(_key(workspace_id, automation_id), None) is not None:
            with contextlib.suppress(OSError):
                _write(core, kept)


def take(core: Any, workspace_id: str, automation_id: int) -> str:
    """The secret, once ("" = none waits): it is dropped as it is shown."""
    from agos_core.security.secrets import decrypt_secret

    with _lock:
        kept = _read(core)
        sealed = kept.pop(_key(workspace_id, automation_id), "")
        if not sealed:
            return ""
        _write(core, kept)
    return decrypt_secret(core.master_key, sealed, _SEAL)
