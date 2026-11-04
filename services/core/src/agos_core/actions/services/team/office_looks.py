"""How each agent of a workspace looks in the Office (pet, colour, desk item): AGOS's
own rows (app_settings `office.<workspace>`). Every agent starts on its own default
look until one is saved; the owner's page and the Co-Founder's `set_office_look`
both save through `save_look`.

Must not: store what an agent is doing (that comes live from Hermes: the board and
the chats), or know about HTTP (api/office.py maps it).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agos_core.actions.errors import NotFoundError
from agos_core.actions.workers import Team, team
from agos_core.actions.workspaces import require_workspace
from agos_core.db.app_settings import get_setting, set_setting

__all__ = [
    "COLOURS",
    "ITEMS",
    "PETS",
    "Colour",
    "DeskItem",
    "OfficeLook",
    "Pet",
    "look_of",
    "looks",
    "names",
    "save_look",
]

Pet = Literal["none", "cat", "dog", "rabbit", "bird", "fish"]
Colour = Literal["indigo", "teal", "amber", "rose", "violet", "slate", "lime", "sky"]
DeskItem = Literal["plant", "lamp", "books", "trophy", "coffee", "none"]

COLOURS: tuple[str, ...] = ("indigo", "teal", "amber", "rose", "violet", "sky", "lime", "slate")
PETS: tuple[str, ...] = ("cat", "dog", "rabbit", "bird", "fish")
ITEMS: tuple[str, ...] = ("plant", "lamp", "books", "coffee", "trophy")


class OfficeLook(BaseModel):
    # The Office page's body too (api/office.py): checked the same way for both.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    pet: Pet = "none"
    pet_name: str = Field(default="", max_length=24)
    colour: Colour = "indigo"
    item: DeskItem = "plant"


def _key(workspace_id: str) -> str:
    return f"office.{workspace_id}"


def _default(index: int) -> OfficeLook:
    """Every agent starts different: its own colour, a pet for every other one."""
    return OfficeLook(
        pet=PETS[index % len(PETS)] if index % 2 == 0 else "none",  # type: ignore[arg-type]
        colour=COLOURS[index % len(COLOURS)],  # type: ignore[arg-type]
        item=ITEMS[index % len(ITEMS)],  # type: ignore[arg-type]
    )


def names(core: object, workspace_id: str, of: Team | None = None) -> list[str]:
    """ "cofounder" (the workspace's Co-Founder), then the members by their agent name."""
    t = of if of is not None else team(core, workspace_id)  # type: ignore[arg-type]
    return ["cofounder", *(m.name for m in t.members if m.name)]


def looks(core: object, workspace_id: str, of: Team | None = None) -> dict[str, OfficeLook]:
    """Each agent's look (`of`: the team, when the caller has read it already)."""
    saved = get_setting(core.db, _key(workspace_id), {})  # type: ignore[attr-defined]
    saved = saved if isinstance(saved, dict) else {}
    found: dict[str, OfficeLook] = {}
    for i, name in enumerate(names(core, workspace_id, of)):
        raw = saved.get(name)
        try:
            found[name] = OfficeLook.model_validate(raw) if isinstance(raw, dict) else _default(i)
        except ValueError:
            found[name] = _default(i)
    return found


def look_of(core: Any, workspace_id: str, member: str) -> dict[str, Any]:
    """One agent's look as the Office shows it (its default until one is saved)."""
    require_workspace(core, workspace_id)
    if member not in names(core, workspace_id):
        raise NotFoundError("This agent")
    return looks(core, workspace_id)[member].model_dump()


def save_look(core: Any, workspace_id: str, member: str, look: dict[str, Any]) -> None:
    """The owner's page and the Co-Founder's action: checked as the page's own body."""
    require_workspace(core, workspace_id)
    if member not in names(core, workspace_id):
        raise NotFoundError("This agent")
    body = OfficeLook.model_validate(look)
    saved = get_setting(core.db, _key(workspace_id), {})
    saved = saved if isinstance(saved, dict) else {}
    saved[member] = body.model_copy(update={"pet_name": body.pet_name.strip()}).model_dump()
    set_setting(core.db, _key(workspace_id), saved)
