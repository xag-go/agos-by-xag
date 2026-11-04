"""The one-time rename of the Manager into the Co-Founder (step 44) in the files AGOS
writes into the workspaces' Hermes roots.

The database side is migration 126 (its table, its settings key, its DM's title, the
Office look's key). Outside it, AGOS wrote the old name into:
- the root's SOUL.md: the markers around the Co-Founder's view of the workspace (the
  view itself is written again from today's text once the markers are current);
- each member's SOUL.md: the line saying who leads the team;
- the step-32 snapshot file in the backups folder (`manager-actions-before-step32.json`,
  which the rows of `cofounder_actions` point at: migration 126 moves those).
Safe to repeat: a finished move finds nothing to change.
"""

from __future__ import annotations

import json
import logging

from agos_core.context import Core
from agos_core.engine import identity

log = logging.getLogger("agos.cofounder_move")

OLD_SNAPSHOTS = "manager-actions-before-step32.json"


def _move_snapshots(core: Core) -> bool:
    """The step-32 snapshot file under its new name (entries of both kept when the
    new one exists already); False when there is no old file."""
    from agos_core.actions import backups, cofounder_actions

    try:
        folder = backups.backup_dir(core)
    except Exception:
        log.exception("backup folder not usable: the step-32 snapshot file keeps its name")
        return False
    old = folder / OLD_SNAPSHOTS
    if not old.is_file():
        return False
    new = folder / cofounder_actions.SNAPSHOTS_FILE
    if new.is_file():
        try:
            have = json.loads(new.read_text())
            more = json.loads(old.read_text())
        except (OSError, ValueError):
            have, more = [], []
        known = {int(m["id"]) for m in have if isinstance(m, dict) and "id" in m}
        have += [m for m in more if isinstance(m, dict) and int(m.get("id", -1)) not in known]
        tmp = new.with_name(f".{new.name}.tmp")
        tmp.write_text(json.dumps(have, ensure_ascii=False, indent=1))
        tmp.chmod(0o600)
        tmp.replace(new)
        old.unlink()
    else:
        old.rename(new)
    return True


def move_old_manager_name(core: Core) -> dict[str, int]:
    """Returns {"souls": files rewritten, "snapshots": 1 when the file moved}."""
    from agos_core.actions import engine as engine_actions
    from agos_core.actions import hermes_config as hc
    from agos_core.db.workspaces import list_workspaces

    counts = {"souls": 0, "snapshots": 0}
    engine = core.engine
    if engine is not None:
        for w in list_workspaces(core.db, include_archived=True):
            if not hc.has_root(core, w.id):
                continue
            root = engine.profile_home(w.id)
            homes = [root, *sorted(p.parent for p in (root / "profiles").glob("*/SOUL.md"))]
            touched = [home for home in homes if identity.rename_old_lead(home)]
            counts["souls"] += len(touched)
            if root in touched:
                # The view's own text names the Co-Founder now: written again.
                try:
                    engine_actions.refresh_cofounder_view(core, w.id)
                except Exception:
                    log.exception("the Co-Founder's view of %s not written again", w.id)
    if _move_snapshots(core):
        counts["snapshots"] = 1
    if any(counts.values()):
        log.info("Manager renamed to Co-Founder in the roots' files: %s", counts)
    return counts
