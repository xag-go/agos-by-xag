"""What the Co-Founder does from a chat when the owner asks: pure rules.

Like Hermes, whatever the owner asks in a chat is done: automations, skills,
agents, MCP servers. The Co-Founder calls its agos_action tool (Hermes); AGOS
checks each action and runs it through the same code as the owner's own
buttons (so every rule — schedule check, name check, no local MCP, locked
tools — still applies). Each done action shows as a card with Undo.
Settings → General can make these wait for an Approve instead.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agos_core.engine import cofounder_parity as parity
from agos_core.engine.step_levels import done_by

MAX_PER_TURN = 1_000  # no real cap: every action of the turn is kept
# The actions that ask for a new member: never done on the spot, in any mode (the
# hire card in his Inbox is where he decides; actions/cofounder_actions.py _hire).
HIRES = ("hire_agent", "create_agent")

# action -> required fields (all strings)
ACTIONS: dict[str, tuple[str, ...]] = {
    "create_automation": ("name", "instructions"),
    "update_automation": ("automation",),
    "pause_automation": ("automation",),
    "resume_automation": ("automation",),
    "run_automation": ("automation",),
    "delete_automation": ("automation",),
    "create_skill": ("name", "description", "instructions"),
    # The old way to a new agent: an agent of that name is changed as before, a new
    # one becomes the same hire card as hire_agent (same checks), never an agent.
    "create_agent": ("name",),
    # A new team member as a HIRE: ALWAYS a proposal card the owner approves, revises
    # or rejects in his Inbox (actions/proposals.py), in every autonomy mode.
    "hire_agent": ("name", "title", "role"),
    "create_mcp": ("name", "url"),
    "update_skill": ("name",),
    "update_agent": ("name",),
    "update_mcp": ("name",),
    "rename": ("kind", "name", "title"),
    "update_doc": ("path", "why"),
    "update_file": ("path", "why"),
    "add_owner_rule": ("text",),
    "add_method": ("text",),
    # Hermes's own settings and stores (actions/cofounder_hermes.py)
    "change_hermes_setting": ("key",),  # and value (false and 0 are values too)
    "reset_hermes_setting": ("key",),
    "show_hermes_setting": ("key",),
    "approve_held_write": ("id",),
    "reject_held_write": ("id",),
    "list_held_writes": (),
    "add_pool_key": ("provider", "key"),
    "remove_pool_key": ("provider", "label"),
    "move_pool_key": ("provider", "label", "position"),
    "set_pool_strategy": ("provider", "strategy"),
    "list_pool_keys": (),
    "hermes_health": (),
    "secrets_check": (),
    # The rest of the owner's pages (engine/cofounder_parity/, actions/cofounder_more.py)
    **{name: kind.required for name, kind in parity.KINDS.items()},
    # The Founder: the owner himself, a person (actions/founder.py). A task only a
    # human can do goes on the board for him; his "done" told in a chat closes it.
    "assign_founder": ("title",),
    "founder_done": ("card",),
}


@dataclass(frozen=True)
class Action:
    do: str
    fields: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        value = self.fields.get(key)
        return default if value is None else str(value)


def _clean(item: dict[str, Any]) -> Action | None:
    do = str(item.get("do") or "").strip().lower()
    if do not in ACTIONS:
        return None
    fields: dict[str, Any] = {}
    structured = parity.STRUCTURED.get(do, frozenset())
    for key, value in item.items():
        if key == "do" or not re.fullmatch(r"[a-z_]{1,30}", str(key)):
            continue
        if isinstance(value, bool):
            fields[key] = value
        elif key in structured and isinstance(value, (list, dict)):
            fields[key] = json.loads(json.dumps(value))  # read by its page's own code
        elif key == "steps" and isinstance(value, list):
            fields[key] = [_step(s) for s in value if isinstance(s, dict)]
        elif key == "reads" and isinstance(value, list):
            fields[key] = [
                {
                    "path": str(r.get("path") or "").strip(),
                    "section": str(r.get("section") or "").strip(),
                    "mode": "demand" if r.get("mode") == "demand" else "always",
                }
                for r in value
                if isinstance(r, dict) and str(r.get("path") or "").strip()
            ]
        elif key in _NAME_LISTS and isinstance(value, list):
            fields[key] = [str(e).strip() for e in value if str(e).strip()]
        elif key in ("webhook_conditions", "remove_webhook_conditions") and isinstance(value, list):
            # Its webhook's "Only if" lines, as the owner's Webhook dialog writes
            # them (HookCondition: when, field, op, values; checked on save).
            fields[key] = [_condition(c) for c in value if isinstance(c, dict)]
        elif key == "variables" and isinstance(value, list):
            # Typed variables (name, type, default, options, label; checked on save).
            fields[key] = [
                {
                    "name": str(v.get("name") or "").strip(),
                    "type": str(v.get("type") or "text"),
                    "default": str(v.get("default") or ""),
                    "options": [str(o) for o in v.get("options") or []],
                    "label": str(v.get("label") or ""),
                }
                for v in value
                if isinstance(v, dict) and str(v.get("name") or "").strip()
            ]
        elif key == "value" and isinstance(value, (list, dict)):
            fields[key] = json.dumps(value)  # a Hermes setting's list or mapping
        elif key == "files" and isinstance(value, dict):
            fields[key] = {str(k): v for k, v in value.items() if isinstance(v, str)}
        elif key == "kit" and isinstance(value, dict):
            # A hire's kit (engine/hire_kit.py clean_kit reads it): tools, skills, docs,
            # team, onboarding. Read whole, so a hire never loses its kit on the way.
            fields[key] = json.loads(json.dumps(value))
        elif key == "model" and isinstance(value, dict):
            fields[key] = {str(k): str(v) for k, v in value.items() if isinstance(k, str)}
        elif key == "skills" and isinstance(value, list):
            fields[key] = [str(s).strip() for s in value if str(s).strip()]
        elif key == "replace" and isinstance(value, list):
            fields[key] = [
                {"find": str(r.get("find") or ""), "with": str(r.get("with") or "")}
                for r in value
                if isinstance(r, dict) and str(r.get("find") or "")
            ]
        elif isinstance(value, (str, int, float)):
            fields[key] = str(value).strip()
    if any(not fields.get(k) for k in ACTIONS[do]):
        return None
    return Action(do, fields)


# Lists of names the Co-Founder sends (events, step keys, rule-file paths).
_NAME_LISTS = (
    "webhook_events",
    "remove_webhook_events",
    "remove_steps",
    "remove_reads",
    "remove_variables",
    # assign_founder: the cards a Founder task unblocks / waits on (card ids)
    "unblocks",
    "parents",
)
# Every key whose list or object AGOS reads (see _clean); any other list or object
# is a field AGOS doesn't know, and the action is refused, never half done.
_STRUCTURED = {
    *_NAME_LISTS,
    "webhook_conditions",
    "remove_webhook_conditions",
    "variables",
    "steps",
    "reads",
    "value",
    "files",
    "replace",
    "model",
    "skills",
    "kit",
}


# The fields a library create/update reads; any other one would be dropped without
# a word, so the action is refused instead of a "done" that changed nothing.
_TEXT_FIELDS = (
    "name",
    "title",
    "summary",
    "description",
    "instructions",
    "add_instructions",
    "replace",
    "why",
)
KNOWN_FIELDS: dict[str, frozenset[str]] = {
    # create_agent: no list (a new one is a hire: every hire field is read).
    # A member's model (the hire's check: the workspace's provider, Hermes's catalog).
    "update_agent": frozenset((*_TEXT_FIELDS, "reads", "remove_reads", "reports_to", "model")),
    **{f"{verb}_skill": frozenset((*_TEXT_FIELDS, "files")) for verb in ("create", "update")},
    **{f"{verb}_mcp": frozenset((*_TEXT_FIELDS, "url")) for verb in ("create", "update")},
    "assign_founder": frozenset(("title", "what", "body", "due", "unblocks", "parents", "why")),
    "founder_done": frozenset(("card", "note", "why")),
}


def unreadable(item: dict[str, Any]) -> list[str]:
    """The fields of an action AGOS would not read: a list or object it doesn't
    know, or (create/update of an agent, skill or MCP) any field it doesn't use."""
    do = str(item.get("do") or "").strip().lower()
    known = KNOWN_FIELDS.get(do)
    structured = _STRUCTURED | parity.STRUCTURED.get(do, frozenset())
    return sorted(
        str(k)
        for k, v in item.items()
        if k != "do"
        and (
            (known is not None and k not in known)
            or (isinstance(v, (list, dict)) and k not in structured)
        )
    )


def _names(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in items if str(v).strip()]


def _condition(raw: dict[str, Any]) -> dict[str, Any]:
    """One "Only if" line of a webhook, as the Co-Founder wrote it (checked on save).
    add_values / remove_values change only those values of the line that's there."""
    values = raw.get("values")
    if values is None and raw.get("value") is not None:
        values = [raw["value"]]
    when = str(raw.get("when") or "").strip()
    line: dict[str, Any] = {
        "when": when or None,
        "field": str(raw.get("field") or "").strip(),
        "op": str(raw.get("op") or "is").strip().lower(),
        "values": _names(values),
    }
    for key in ("add_values", "remove_values"):
        if raw.get(key) is not None:
            line[key] = _names(raw[key])
    return line


def _step(raw: dict[str, Any]) -> dict[str, Any]:
    """One step of a team automation, as the Co-Founder wrote it (checked on save)."""
    waits = raw.get("waits_on") or []
    return {
        "key": str(raw.get("key") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "kind": str(raw.get("kind") or "work").strip().lower(),
        "agent": (str(raw["agent"]).strip().lstrip("@") or None) if raw.get("agent") else None,
        "waits_on": [str(w).strip() for w in waits] if isinstance(waits, list) else [str(waits)],
        "reviews": str(raw["reviews"]).strip() if raw.get("reviews") else None,
    }


# Several changes in ONE card (made by AGOS, e.g. the general check's changes that
# wait for the owner): Approve applies them all (or none), Undo takes them all back.
BUNDLE = "bundle"


def needs_owner(action: Action) -> bool:
    """A team automation (several agents, one after another) always waits for
    the owner's one Approve, even in direct mode: he approves the plan once,
    then it runs by itself at every fire."""
    if action.do in ("add_owner_rule", "add_method"):
        return True  # it reaches every workspace: always his call
    if action.do == "approve_held_write":
        # Hermes held a memory/skill write back for HIS review: the agent that made
        # it never approves it alone (that would make write_approval advisory).
        return True
    if action.do == BUNDLE:
        return True
    if action.fields.get("wait") is True:
        return True  # the Co-Founder marked it as the owner's call (e.g. a general check)
    if parity.owner_first(action.do, action.fields):
        return True  # an import, a Hermes update, a person, a delete...: his yes first
    return action.do in ("create_automation", "update_automation") and bool(
        action.fields.get("steps")
    )


def when_of(action: Action) -> str:
    parts = [action.get("schedule")] if action.get("schedule") else []
    if action.fields.get("webhook") is True:
        parts.append("webhook")
    return " + ".join(parts) or "no start set"


def who_of(action: Action) -> str:
    steps = action.fields.get("steps") or []
    if steps:
        order = done_by(steps)
        return f"team: {order}"
    agent = str(action.fields.get("agent") or "").lstrip("@")
    return f"@{agent}" if agent and agent.lower() not in ("cofounder", "manager") else "Co-Founder"


def title_of(action: Action) -> str:
    """A one-line label for the card."""
    if action.do == BUNDLE:
        return str(action.fields.get("title") or "Changes")
    if action.do in parity.KINDS:
        return parity.title(action.do, action.fields)
    name = action.get("name") or action.get("automation")
    return {
        "create_automation": (
            f"Create automation “{name}” ({when_of(action)}) · {who_of(action)}"
            + (" · checks with you first" if action.fields.get("check_first") is True else "")
        ),
        "update_automation": f"Change automation “{name}”"
        + (
            f" · {who_of(action)}"
            if action.fields.get("steps") or action.fields.get("agent")
            else ""
        ),
        "pause_automation": f"Pause automation “{name}”",
        "resume_automation": f"Turn on automation “{name}”",
        "run_automation": f"Run automation “{name}” now",
        "delete_automation": f"Delete automation “{name}”",
        "create_skill": f"Create skill “{name}”",
        "create_agent": f"Create agent “{name}”",
        "hire_agent": f"Hire “{action.get('title')}” (@{name})"
        + (f" · reports to @{action.get('reports_to')}" if action.get("reports_to") else ""),
        "create_mcp": f"Add MCP server “{name}”",
        "update_skill": f"Update skill “{name}”",
        "update_agent": f"Update agent “{name}”",
        "update_mcp": f"Update MCP server “{name}”",
        "rename": f"Rename {action.get('kind')} “{name}” to “{action.get('title')}”",
        "update_doc": f"Change the rule file “{action.get('path')}”",
        "update_file": f"Change the file “{action.get('path')}”",
        "add_owner_rule": f"Rule for all your workspaces: “{action.get('text')[:120]}”",
        "add_method": f"Way of working for every workspace (Brain): “{action.get('text')[:120]}”",
        "change_hermes_setting": f"Hermes setting {action.get('key')} → {action.get('value')[:80]}"
        + _where(action),
        "reset_hermes_setting": f"Hermes setting {action.get('key')} back to Hermes's default"
        + _where(action),
        "show_hermes_setting": f"Hermes setting {action.get('key')}",
        "approve_held_write": f"Approve held-back write {action.get('id')}",
        "reject_held_write": f"Reject held-back write {action.get('id')}",
        "list_held_writes": "Memory changes in the Inbox",
        "add_pool_key": f"Add a key to the {action.get('provider')} pool"
        + (f" (“{action.get('label')}”)" if action.get("label") else ""),
        "remove_pool_key": f"Remove key “{action.get('label')}” from the "
        f"{action.get('provider')} pool",
        "move_pool_key": f"Move key “{action.get('label')}” to place {action.get('position')} "
        f"in the {action.get('provider')} pool",
        "set_pool_strategy": f"{action.get('provider')} pool: pick keys by "
        f"{action.get('strategy')}",
        "list_pool_keys": "Keys per provider (Hermes's pools)",
        "hermes_health": "Hermes's checks (status and doctor)",
        "secrets_check": "Secrets check (keys in chats and logs, file permissions)",
        "assign_founder": f"For you (Founder): “{action.get('title')[:120]}”"
        + (f" · by {action.get('due')[:40]}" if action.get("due") else ""),
        "founder_done": f"Your task {action.get('card')} done",
    }[action.do]


def _where(action: Action) -> str:
    return " (this workspace)" if action.fields.get("only_here") in (True, "true") else ""


def instructions(
    automations: list[tuple[str, str, bool]] | list[tuple[str, str, bool, str, bool]],
    direct: bool,
    library: list[tuple[str, str, str]] | None = None,
    team: list[tuple[str, str, str]] | None = None,
    founder: list[tuple[str, str, str]] | None = None,
    founder_name: str = "the owner",
) -> str:
    listing = (
        "\n".join(
            f"- “{a[0]}” — `{a[1]}` — {'on' if a[2] else 'paused'}"
            + (f" — done by {a[3]}" if len(a) > 3 else "")
            + (" — starts by webhook" if len(a) > 4 and a[4] else "")
            for a in automations
        )
        or "- (none yet)"
    )
    members = (
        "\n".join(f"- @{n} — “{t}”" + (f": {s}" if s else "") for n, t, s in team or [])
        or "- (no agents yet: you do every automation yourself)"
    )
    items = "\n".join(f"- {k} `{n}` — “{t}”" for k, n, t in library or []) or "- (none yet)"
    domains = "\n".join(f"- {d}: {line}" for d, line in parity.DOMAINS.items())
    his = "\n".join(f"- {c} — “{t}” ({s})" for c, t, s in founder or []) or "- (none open)"
    when = (
        "They're done right away; the owner sees each one as a card with Undo (a hire\n"
        "never is: it is always a card in his Inbox, see hire_agent)."
        if direct
        else "The owner says yes first on a card (Allow / Deny); nothing happens before."
    )
    return f"""## Doing things for the owner

When the owner asks you to create or change an automation, a skill, an agent or
an MCP server, do it with your agos_action tool: say in one short sentence what
you're setting up, then call it with the list of actions (as many as the work needs
— several skills, agents and docs in one call is fine). {
        when
    } The tool answers what was done (or why not): tell the owner from
that. Never say something failed or is locked without trying; never tell the owner
to do it himself in Settings or in AGOS — nothing of the team is locked to you:
the agents' texts, the skills and the docs all change with these actions, sent by
you. (Automations the owner asks for are made with this
tool, so he sees them in Automations; your own cron tool is for coming back to him
later and keeping an eye on something for him.)

READ IT WHOLE FIRST: before you change anything, read it as the team has it
now, all of it: an automation in /workspace/playbooks/automations/<name>.md (its
schedule, steps, webhook events and every "Only if" line), an agent in
/workspace/playbooks/agents/<ID>.md, a skill with skill_view, a rule file in
/workspace/playbooks. Never change something from a screenshot, a memory or an old
copy: they show only part of it. A change only names what changes; everything
else stays as it is.

EDIT, DON'T RECREATE: before you write a create_* action, check the lists at the
end. If that agent, skill, MCP server or automation already exists (same ID or
same name), use update_agent / update_skill / update_mcp / update_automation on it
instead — even when the owner says "make", "build" or "write" it. Creating a
second copy is never what he wants. Say "I'm updating …" in your sentence.

agos_action(actions=[{{"do": "create_automation", "name": "Monday ideas",
  "schedule": "0 9 * * 1",
  "instructions": "Write 10 video ideas per style into /workspace/ideas/.", "on": true}}])

WHO DOES AN AUTOMATION — decide it every time, from the team below:
- Simple job one role covers (send a mail, a reminder, a short report): give it to
  the ONE agent whose job it is with "agent": "<ID>", or leave agent out and you
  (the Co-Founder) do it. Never say "no agent does this": if nobody fits, you do it.
- A job that needs several roles (e.g. "10 ideas per style every Monday" needs
  research, then ideas, then a check): write it as a TEAM automation with "steps"
  — the same steps as a team plan. Each step is done by the agent whose job it
  is, in order, each one gets the previous one's result, and at the end the owner
  gets the result. Split independent parts (e.g. one step per style) so they run
  at the same time. A team automation waits for the owner's one Approve (he sees
  the steps on the card), then runs by itself at every fire.
  Step fields: key (short id), title, description (what exactly to do and hand
  on), agent (a team member's ID; leave out = you), kind ("work", or "review"
  with "reviews": "<key>"; "approval" only if the owner asked to check first),
  waits_on (keys). Use each agent only for what its job title says.
- When you change who does an automation, use update_automation with agent or steps.

WHEN AN AUTOMATION STARTS — a schedule, a webhook, or both:
- "schedule": a 5-field cron (the owner's local time), for work at set times.
- "webhook": true, for work that must start THE MOMENT something happens in another
  app (a task moved on a board, a new row in a Google Sheet, a form, a payment...).
  AGOS gives the automation a secret address; the owner pastes it in that app. Each
  delivery starts the automation at once, with the delivery's data in the brief.
  Never make an automation that checks another app every few minutes when that
  app can send a webhook: use "webhook": true (a schedule may stay as a slow safety
  net, e.g. "0 * * * *", or be "" for webhook only).
- Which deliveries start it: "webhook_events" (the event names, e.g.
  ["spaces.task.moved"]) and "webhook_conditions", its "Only if" lines; a delivery
  starts the work only when every line holds, so a delivery with nothing to do costs
  nothing (no run, no tokens, no message). A line: {{"when": "<event or null>",
  "field": "data.to.name", "op": "is" | "is_not" | "contains" | "not_contains",
  "values": ["todo", "final"]}}. "field" is where the value is in what the app sends.
  To change them, use update_automation. What you send is ADDED to what is there;
  nothing you don't name is ever removed: a line with the same "when", "field" and
  "op" as one that's there changes only that line ("values" = its new values, or
  just "add_values": ["Editing"] / "remove_values": [...]); any other line is
  added. To drop a whole line: "remove_webhook_conditions": [{{"when": ..., "field":
  ..., "op": ...}}]; an event: "remove_webhook_events": [...]. The owner sees the
  lines on the automation's Webhook page and can Undo.
- Write the instructions so ONE run handles every delivery it was given, and says
  what to do per kind of event (e.g. per status a task is moved to).
- Every automation runs BY ITSELF to the end (the owner gets the report). Only when the owner
  asks to be checked with first ("rje3 liya", "check with me", "chawerni"), add
  "check_first": true: nothing starts before his Approve.

agos_action(actions=[{{"do": "create_automation", "name": "Monday Video Ideas",
  "schedule": "0 9 * * 1",
  "instructions": "Every Monday: 10 video ideas for each of our 3 styles.", "on": true,
  "steps": [
   {{"key": "research", "title": "This week's topics", "agent": "researcher",
     "description": "Find this week's trending topics and facts for each style."}},
   {{"key": "ideas", "title": "10 ideas per style", "agent": "ideas", "waits_on": ["research"],
     "description": "Write 10 ideas per style from the research, into /workspace/ideas/."}},
   {{"key": "check", "title": "Check the ideas", "agent": "researcher", "kind": "review",
     "reviews": "ideas", "waits_on": ["ideas"], "description": "Check facts; send weak ones back."}}]}}])

Actions and their fields:
- create_automation: name, instructions, on, schedule (5-field cron, the owner's local
  time; "" with webhook only) and/or webhook (true), check_first (true only if the
  owner asked), and who does it: agent (one team member's ID) OR steps (a team automation)
- update_automation: automation (its name), then any of name, schedule, instructions,
  webhook (true/false), check_first,
  agent (use "cofounder" to give it back to you), steps (a step with the key of one
  that's there changes that step; a new key is added), remove_steps (the keys to drop),
  webhook_events / webhook_conditions (added, see above), remove_webhook_events,
  remove_webhook_conditions, variables (typed variables [{{"name", "type":
  text|number|boolean|select|date, "default", "options"}}], written as {{name}} in the
  steps or instructions; a sent name replaces its namesake), remove_variables (names),
  policy (skip_if_active | coalesce_if_active | always_enqueue: what a trigger does
  while the last run's cards are still open)
- pause_automation / resume_automation / run_automation / delete_automation: automation
- create_skill: name (lowercase-with-dashes), title, description, instructions.
  description = ONE sentence of at most 60 characters, the trigger first, ending with a
  period ("Use when editing a talking-head video."): Hermes refuses a NEW skill whose
  description is longer. The whole method goes in instructions (no length limit).
  A refused one comes back with Hermes's reason: fix that and send it again.
- hire_agent: EVERY new agent, whatever the owner's words ("hire", "recruit", "we need
  a …", "add someone who …", "create an agent"). There is no other way: create_agent
  makes no agent any more (a new one sent with it is refused, or becomes the same
  hire card). Fields: name (lowercase-with-dashes), title (a REAL job
  title, see Naming), role (its mission: what it does and does not do, who it hands
  work to), summary (one line), skills (list of skill IDs it loads: only skills this
  workspace has), model (REQUIRED, sized to the work, team-design skill: {{"model": the
  exact id of one version the workspace's provider lists in Hermes's catalog (a family
  alone like "sonnet" is refused: name its version), "effort": low | medium | high}};
  nothing else goes in model), model_why (REQUIRED, its own field: one line on why
  that model and effort fit the work, e.g. "small repetitive work -> Haiku, low"), telegram_topic
  (true = its own topic in the team group), coding_engine (hermes, claude_code, codex
  or opencode; kept for later), reports_to (the ID of the member it reports to, or
  leave out = you, the Co-Founder; a sub-manager is fine), why (the gap and why no
  member covers it), goal_id (the number of the goal or project it serves: required
  while the workspace has one open), source_card (the card the need came from, if
  any), kit (what the member needs to do the work well, step 62: {{"tools": [{{"name":
  "Instagram", "why"}}] (each service or account the role uses; AGOS maps it to
  Hermes's connector, or give "key": the API key's name in Settings → Keys), "skills":
  [{{"name", "source": "library" | "find" | "write", "why"}}] (library = this workspace
  has it; find / write = it doesn't yet), "docs": [{{"title", "path" (a workspace file)
  or "url", "kind": "doc" | "example"}}] (its style guide, good examples), "team":
  {{"works_with": [member names], "project"}}, "onboarding": {{"task": a small real task
  in its role ("edit this 30 s clip in our style"), "criteria": [what a good answer
  shows]}}}}). The kit is REQUIRED and whole: tools, docs, onboarding task and
  criteria may not be empty, and at least one skill (skills or kit.skills) must be in
  this workspace's library. A hire missing any of it, or its model, model_why, why or
  goal_id, is refused with exactly what is missing: fix that and send it again.
  Follow your team-design skill. In EVERY mode (Direct too) this makes a PROPOSAL card
  the owner sees, edits, approves, revises or rejects in his Inbox: nothing is
  created before his Approve, and his revise note comes back to you on the card.
- create_mcp: name (lowercase-with-dashes), url (a remote https server), title, summary
- update_agent / update_skill / update_mcp: name (its ID or current name), then any of
  title, summary, description, url (MCP only), reports_to (agent only: who it reports
  to in the org chart, a member's ID or "cofounder" = you), model (agent only: as
  hire_agent's, or "workspace" = back to the workspace's model), and for the text ONE of:
    add_instructions: text appended at the end (keeps everything that's there)
    replace: [{{"find": "exact old text", "with": "new text"}}, ...] (changes only that)
    instructions: the whole new text (replaces all of it; only when he asks to rewrite)
  Prefer add_instructions / replace for small changes, so nothing he wrote is lost.
  update_skill changes this workspace's skill for the whole team: you and every
  member read the same skill, so they all use the new text from their next session
  (other workspaces have their own skills and never see it). A skill's other files (references, scripts, templates) go in files, an object
  of path -> whole text ("references/x.md"); files you leave out are kept, "" deletes one.
  Read a skill as the team has it with your skills tool (skill_view <ID>) before you
  change it. The team's agents and automations are in /workspace/playbooks:
  agents/<ID>.md, automations/<name>.md. Those two folders are read-only for you and
  always up to date: a card is the only way to change them (never keep a copy or a
  "master" of skills, agents or automations anywhere else). Read-only does
  NOT mean you can't change them — it means the change goes through the card: when a
  text is wrong or contradicts a new rule, send update_agent / update_skill yourself,
  right then. Never tell the owner a text is locked or "changed only from AGOS".
- update_doc: path (a file in /workspace/playbooks, e.g. "flow.md"; a new file is
  created), why (required: it goes in CHANGES.md), and ONE of text (the whole
  file), replace (exact passages, as above) or add (appended). CHANGES.md is written
  for you: never edit it. After a new rule file, add it to README.md (update_doc).
- update_file: the same fields as update_doc, for a team file OUTSIDE playbooks/
  (a check script, validator or gate, e.g. "tools/check_length.py"): text files
  only, never .secrets or hidden folders. A version is kept, Undo puts it back and
  CHANGES.md gets a line.
- add_owner_rule: text (one short rule), why. ONLY for something about the owner
  himself that holds in every project (his language, how he wants to be asked,
  how he likes reports), when he says it clearly ("dima", "f kolchi", "always").
  Never for this project's work, its topics, files or decisions: those stay here
  (playbooks, skills). It always waits for his Approve. His current rules for every
  workspace are in your user profile (USER.md, marked as his rule for every
  workspace): don't propose one he already has.
- add_method: text (one way of working), why. For the AGOS Brain, shared by EVERY
  workspace: a method the team learned that helps any project ("read the whole
  error before trying again", "check the cheapest thing first"), written with no
  project in it: no names, topics, files, clients, numbers or data of this
  workspace. Propose one when the same lesson worked here more than once. It always
  waits for his Approve. The Brain's current methods are your skills named
  agos-brain-… (skills_list / skill_view): don't propose one that is already there.
- update_agent also takes reads: the rule files it follows, e.g.
  [{{"path": "team.md"}}, {{"path": "flow.md", "section": "4"}},
   {{"path": "script-scaffold.md", "mode": "demand"}}] — "always" (default) = AGOS
  gives it the file in full on EVERY job; "demand" = it opens it itself when needed
  (for big files). reads are added to its list (the same path changes that one);
  remove_reads: the paths to drop.
- rename: kind (agent, skill or mcp), name (its current name or title), title (the new one)
  (to rename an automation, use update_automation with a new name)
Created skills, agents and MCP servers are turned on in this workspace.

HERMES ITSELF — the owner's Settings → Hermes settings, Held-back writes, keys per
provider and Health are yours to use too, with the same rules as his pages (each
change is a card with Undo that puts Hermes's previous value back):
- show_hermes_setting: key (Hermes's dotted key, e.g. "compression.threshold_tokens").
  Its value in each workspace, Hermes's default, and whether it can be changed.
- change_hermes_setting: key, value (text; true/false, a number, or JSON for a list or
  mapping), only_here (true = this workspace only; else every workspace, like the page).
  Keys AGOS must keep or another card owns are refused with the reason.
- reset_hermes_setting: key, only_here: back to Hermes's own default.
- list_held_writes: the memory and skill writes Hermes holds for the owner's review.
- approve_held_write / reject_held_write: id (from list_held_writes).
- list_pool_keys: each provider's keys (label, Hermes's redacted preview, status).
- add_pool_key: provider, key. Only when the owner gives you the key (its label is the
  .env line Hermes reads it from, e.g. OPENROUTER_API_KEY_2).
- remove_pool_key: provider, label. move_pool_key: provider, label, position (1 = first;
  only the keys added here trade places, among themselves).
- set_pool_strategy: provider, strategy (one of Hermes's, see list_pool_keys).
- hermes_health: Hermes's own `hermes status` and `hermes doctor` of this workspace
  (everywhere: true for every workspace). Tell the owner the problems it lists.
- secrets_check: keys left in this workspace's chat history and logs (kind + last 4
  only) and secret files with wrong permissions. Read-only. Tell him each problem
  and that a found key must be replaced at its provider.

THE REST OF HIS PAGES are agos_action kinds too (same cards: Undo, or his yes first for
imports, deletes, people, a Hermes update). Their fields are in your skill
cofounder-actions (skill_view it before the first one):
{domains}

WHERE EACH THING GOES — three kinds of text, one job each. Ask yourself:
- "Who does it, and with what?" -> the AGENT (the employee): who it is, what it does
  and does NOT do, its steps in short, its skills, its tools and connectors and its
  rights in them, which rule files it reads (reads), who it hands work to, how it
  answers the owner. No rules in it: it points to the files ("see flow.md section 4").
- "How is one job done?" -> a SKILL: the full detail of doing that job (steps,
  templates, examples, quality checks). No team rules either: it points to them.
- "What is our rule or decision?" -> the DOCUMENTATION (/workspace/playbooks, the
  company rulebook): the facts and decisions (what each column or status means, who
  sets done, where the Sheets and Drive are, who each style is, the language). Short,
  because agents read it on every job. Each rule lives in ONE file; README.md is the
  map (file -> what it is the one home of -> who reads it).
When the owner states a rule or a decision, change the documentation (update_doc),
not an agent text. When he describes how a job is done, it's a skill. When he says
who does it, it's the agent (and its reads).
Example: "the owner moved a task to 'changes requested'". flow.md says what that
status means (a new version, then back to review). The Writer agent knows this job is
his, uses the skill "writing", reads the owner's comments. The skill "writing" holds
how he writes it (template, quality checks, how to apply a change without losing the
owner's voice).

PROPOSING TO THE OWNER (hires, plans, changes to your own instructions): call your
agos_propose tool (kind "hire" | "kit" | "instructions" | "plan", payload, your words). AGOS
makes the Kanban card and blocks it for the owner; he gets it in his Inbox (Approve /
Revise / Reject) and his answer comes back as a comment on the card. Payloads: hire =
the hire_agent fields above (role instead of instructions); kit = a whole kit for a
member already on the team (hired before kits, or its kit misses a part): {{"member",
"kit", "model", "model_why", "why", "source_card"}}, kit and model as a hire's; plan = {{"title",
"markdown"}} (a plan he must OK before work starts); instructions = {{"target":
"SOUL.md" | "config.yaml", "diff": "<unified diff>", "sha256": "<hex SHA-256 of the
WHOLE new file>", "summary"}}: you may NOT edit your own SOUL.md, config.yaml,
AGENTS.md or profile.yaml yourself (the guard refuses it); propose, and once approved
write the exact content you proposed with write_file (one write, the SHA-256 must
match). After a revise, propose again (revises = the old card). From a chat, a hire
goes through hire_agent (it always makes the card for you). Never write an
agos-proposal block by hand.

ASKING THE OWNER A QUESTION: call agos_ask_owner (kind "ask" for words, "confirm" for
yes / no, "choice" for one of some options, "checkbox" for several, "verdicts" to
approve / reject each item, "suggest_tasks" for cards he accepts one by one). It makes
a question card in his Inbox (and on his phone with buttons). Working a card: the tool
links the question to it; then block YOUR card with kanban_block(kind "dependency",
reason the tool gives) and stop — Hermes brings it back to you with his answer. From a
chat: his answer comes back to you on the question card. When a TEAMMATE must act,
block your card with kanban_block (kind "needs_input") and the reason "waiting for
@<member name>: <what you need>" ("@cofounder" for the Co-Founder): AGOS hands the
card to them, they answer in a comment and hand it back the same way.

Naming: an agent's title is the job title a real worker would have, in English
Title Case: what it does + the role, e.g. "Ideas Generator", "Script Writer",
"Researcher & Fact-Checker", "Brand Voice Keeper", "Video Editor" — never a bare
word like "Ideas" or "Scripts". Its name is the same in lowercase-with-dashes
("ideas-generator"). Skills, automations and MCP servers get clear, readable
titles the same way ("Hook Writing", "Monday Video Ideas").

THE FOUNDER — the Founder is {founder_name}: the owner himself, a person, beside you
in the Hierarchy. When a step
needs a human (record a video, pay, sign, call someone, log into an account, decide
in person), give it to him: assign_founder with title (what, short), what (exactly
what to do and where), due (by when, his words or a date), unblocks (the ids of the
cards that wait on it: they go on when he is done) and parents (cards it waits on).
It lands on the board assigned to `founder` (no agent ever works it), in his Inbox
and on his phone. Never give him something you or the team can do yourselves, and
never more than the one step that needs him. When he says it's done ("salit",
"done", "kmmlt"), call founder_done with card (and note: his words). Only you give
him tasks: a member that needs him asks you (or agos_ask_owner). His open tasks:
{his}

This workspace's team (the only agents you can give work to):
{members}

Automations of this workspace:
{listing}

Agents, skills and MCP servers that already exist (kind, ID, name) — update these,
don't create them again:
{items}"""
