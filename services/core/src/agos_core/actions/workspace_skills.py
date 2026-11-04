"""Each workspace's own skills, as its Hermes has them.

A workspace's skills live in ONE folder of its Hermes root: its Co-Founder's local
skill folder `<root>/skills/agos-library/<name>/` (engine/library.py copies_dir).
- The Co-Founder (the root's default profile) reads them as its own local skills and
  changes them with Hermes's skill_manage (the owner's edits and the Co-Founder's
  update_skill cards alike: one ledger, one Undo).
- Every member profile of the workspace (team agents, the people it is shared
  with) reads that same folder through its `skills.external_dirs`: what the
  Co-Founder changes is what the whole team reads at its next session. Hermes treats
  an external folder as read-only for them (the guard refuses their skill_manage
  there), so only the Co-Founder and the owner change a workspace's skills.
- The folders every workspace shares are AGOS's own skills (/task) and the Brain's.
- Off in the workspace = in each of its profiles' `skills.disabled`.

AGOS's row of a skill (library_items, workspace_id set) keeps only what Hermes's
folder doesn't: a display name the owner gave it and where it came from (a hub
identifier, an imported text's hash). No workspace sees or changes another's
skills; "Copy from another workspace" makes an independent copy.

This module is a compatibility facade: the code lives in actions/services/library/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.library.skill_folders import (
    log as log,
    FOLDER as FOLDER,
    folder as folder,
    skill_dir as skill_dir,
    existing_dir as existing_dir,
    shared_dirs as shared_dirs,
    external_dirs as external_dirs,
    names as names,
    agos_owned as agos_owned,
    hidden as hidden,
    shown as shown,
    pairs as pairs,
    head as head,
    stored as stored,
    definition as definition,
    never_written as never_written,
    _row as _row,
    _home as _home,
)
from agos_core.actions.services.library.skill_writes import (
    _write as _write,
    applied as applied,
    create as create,
    save as save,
    rewrite_shipped as rewrite_shipped,
    ensure_shipped as ensure_shipped,
    curator_archive as curator_archive,
    delete as delete,
)
from agos_core.actions.services.library.skill_copies import (
    add_missing_files as add_missing_files,
    _copy as _copy,
    duplicate as duplicate,
    CopyableSkill as CopyableSkill,
    copyable as copyable,
    copy_from as copy_from,
    on_this_machine as on_this_machine,
    import_from_machine as import_from_machine,
)
from agos_core.actions.services.library.skills_hub import (
    _hub as _hub,
    search_web as search_web,
    SCAN_BLOCKED as SCAN_BLOCKED,
    SCAN_BLOCKED_STATUS as SCAN_BLOCKED_STATUS,
    Installed as Installed,
    install_web as install_web,
    Update as Update,
    _HUB_CHECK_S as _HUB_CHECK_S,
    _HUB as _HUB,
    _hub_changed as _hub_changed,
    check_updates as check_updates,
    apply_update as apply_update,
    read_ahead as read_ahead,
)
# isort: on
