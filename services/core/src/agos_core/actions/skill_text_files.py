"""The text files of a skill that Hermes's skill_manage writes (moved out of
actions/workspace_skills.py)."""

from __future__ import annotations

from pathlib import Path

# The folders of a skill Hermes's skill_manage writes files in (H:
# tools/skill_manager_tool.py ALLOWED_SUBDIRS); any other file of a copied skill
# is copied beside them (add_missing_files).
HERMES_FILE_DIRS = ("references", "templates", "scripts", "assets")


def text_files(found: Path) -> dict[str, str]:
    """The skill's text files Hermes's skill_manage takes (the rest: add_missing_files)."""
    from agos_core.actions.team_files import skill_files

    return {
        rel: body
        for rel, body in skill_files(found).items()
        if rel.split("/", 1)[0] in HERMES_FILE_DIRS
    }
