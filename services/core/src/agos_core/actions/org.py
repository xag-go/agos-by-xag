"""The org chart's health (Step 51, F06): each member's chain of command up to the
Co-Founder, and whether a lead above it keeps its team from moving.

Read from Hermes only: who reports to whom is each member profile's
`ui_meta.agos.reports_to` (actions/team.py), on / off the team is Hermes's
`gateway.parked` marker, a lead whose profile is gone is a missing one, and a lead's
stuck cards come from Hermes's board (actions/blocked.py attention, the read the
view does anyway). Nothing is stored: every view derives it, like Paperclip's
agent-eligibility org-chain health (packages/shared/src/agent-eligibility.ts),
where a paused / terminated / missing ancestor or a loop freezes the subtree.

A team is stalled when a lead above a member is:
- paused (off the team: Hermes's gateway doesn't serve it, its cards never run);
- missing (its reports_to names a profile that is gone);
- stuck (it has cards that need attention: blocked with nobody moving);
- in a loop (reports_to through others comes back to itself: never written by
  AGOS, see team.checked_reports_to, but a hand-edited profile could).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agos_core.context import Core

WHY_WORDS = {
    "paused": "is paused",
    "missing": "has no profile any more",
    "stuck": "has stuck cards",
    "loop": "is in a reporting loop",
}


@dataclass(frozen=True)
class Person:
    name: str
    title: str
    lead: str  # "" = the Co-Founder
    on: bool


@dataclass(frozen=True)
class Stall:
    lead: str
    why: str  # paused | missing | stuck | loop
    lead_title: str = ""

    def words(self) -> str:
        who = self.lead_title or f"@{self.lead}"
        return f"{who} {WHY_WORDS.get(self.why, self.why)}"


@dataclass(frozen=True)
class Health:
    people: dict[str, Person]
    chains: dict[str, list[str]]  # member -> its leads, nearest first (Co-Founder left out)
    stalls: dict[str, Stall]  # member -> the nearest lead that stalls it
    stuck: dict[str, int] = field(default_factory=dict)  # lead -> its stuck cards

    def teams(self) -> dict[str, list[str]]:
        """Each stalling lead -> the members it stalls (sorted)."""
        out: dict[str, list[str]] = {}
        for member, stall in sorted(self.stalls.items()):
            out.setdefault(stall.lead, []).append(member)
        return out


def people(core: Core, workspace_id: str) -> dict[str, Person]:
    """Every member profile (on the team or paused), from its profile.yaml and its
    parked marker only (no SOUL, no config): cheap on every view."""
    from agos_core.actions import team
    from agos_core.engine import library as lib
    from agos_core.engine import profile_meta

    out: dict[str, Person] = {}
    for name in team._profile_names(core, workspace_id):
        where = team.home(core, workspace_id, name)
        if where is None:
            continue
        meta = profile_meta.read(where)
        out[name] = Person(
            name=name,
            title=profile_meta.display_name(meta) or lib.readable_title(name),
            lead=lib.reports_to(profile_meta.agos(meta).get("reports_to")),
            on=not profile_meta.parked(where),
        )
    return out


def chain_of(leads: Mapping[str, str], name: str) -> tuple[list[str], bool]:
    """A member's leads up to the Co-Founder, nearest first, and whether the walk
    came back on itself (a loop). The Co-Founder ("") is never listed."""
    out: list[str] = []
    seen = {name}
    walk = leads.get(name, "")
    while walk:
        if walk in seen:
            return out, True
        out.append(walk)
        seen.add(walk)
        walk = leads.get(walk, "")
    return out, False


def derive(found: Mapping[str, Person], stuck: Mapping[str, int] | None = None) -> Health:
    """Every member's chain and the nearest lead that stalls it (pure)."""
    stuck = dict(stuck or {})
    leads = {n: p.lead for n, p in found.items()}
    chains: dict[str, list[str]] = {}
    stalls: dict[str, Stall] = {}
    for name in found:
        chain, loop = chain_of(leads, name)
        chains[name] = chain
        for lead in chain:
            person = found.get(lead)
            why = (
                "missing"
                if person is None
                else "paused"
                if not person.on
                else "stuck"
                if stuck.get(lead)
                else ""
            )
            if why:
                stalls[name] = Stall(lead, why, person.title if person else "")
                break
        else:
            if loop:
                lead = chain[-1] if chain else name
                stalls[name] = Stall(lead, "loop", found[lead].title if lead in found else "")
    return Health(dict(found), chains, stalls, {k: v for k, v in stuck.items() if v})


def stuck_from_attention(
    core: Core, workspace_id: str, attention: Mapping[str, Any]
) -> dict[str, int]:
    """Each member's cards that need attention (blocked with nobody moving: the
    Inbox's own derivation, actions/blocked.py), by member name."""
    by_profile = _profile_names(core, workspace_id)
    out: dict[str, int] = {}
    for state in attention.values():
        if state.get("state") != "needs_attention":
            continue
        member = by_profile.get(str(state.get("assignee") or ""))
        if member:
            out[member] = out.get(member, 0) + 1
    return out


def _profile_names(core: Core, workspace_id: str) -> dict[str, str]:
    """Hermes's assignee name (a-<name>) -> the member's name."""
    from agos_core.actions import team

    return {f"{team.PREFIX}{n}": n for n in team._profile_names(core, workspace_id)}


def health(core: Core, workspace_id: str, stuck: Mapping[str, int] | None = None) -> Health:
    return derive(people(core, workspace_id), stuck)


def chain_line(core: Core, workspace_id: str, name: str) -> str:
    """Who a member reports to, for its SOUL.md."""
    found = people(core, workspace_id)
    chain, _loop = chain_of({n: p.lead for n, p in found.items()}, name)
    if not chain:
        return "You report to the Co-Founder."
    names = [f"{found[n].title} (@{n})" if n in found else f"@{n}" for n in chain]
    if len(names) == 1:
        return f"You report to {names[0]}, who reports to the Co-Founder."
    return f"You report to {names[0]}; above: {', '.join(names[1:])}, then the Co-Founder."


def member_view(h: Health, name: str) -> dict[str, Any]:
    """What the web shows for one member: its chain and its stall."""
    stall = h.stalls.get(name)
    return {
        "chain": [
            {"name": n, "title": h.people[n].title if n in h.people else n}
            for n in h.chains.get(name, [])
        ],
        "stalled": (
            {"lead": stall.lead, "why": stall.why, "words": stall.words()} if stall else None
        ),
        "stalls": sorted(m for m, s in h.stalls.items() if s.lead == name),
        "stuckCards": h.stuck.get(name, 0),
    }


def inbox_item(h: Health) -> dict[str, Any] | None:
    """The owner's ONE Inbox item for every stalled team (None: none stalled). Its
    key changes with what stalls whom, so a dismissed one comes back on a change."""
    teams = h.teams()
    if not teams:
        return None
    import hashlib

    lines = []
    for _lead, members in sorted(teams.items()):
        stall = next(h.stalls[m] for m in members)
        under = ", ".join(f"@{m}" for m in members)
        lines.append(f"{stall.words()}: {under} can't move.")
    stamp = hashlib.sha256(
        "|".join(
            f"{lead}:{h.stalls[ms[0]].why}:{','.join(ms)}" for lead, ms in sorted(teams.items())
        ).encode()
    ).hexdigest()[:12]
    count = sum(len(m) for m in teams.values())
    return {
        "key": f"chain:{stamp}",
        "title": f"Team stalled: {count} member{'s' if count != 1 else ''} under a lead that can't lead",
        "lines": lines,
        "leads": [
            {
                "lead": lead,
                "why": h.stalls[members[0]].why,
                "words": h.stalls[members[0]].words(),
                "members": members,
            }
            for lead, members in sorted(teams.items())
        ],
    }
