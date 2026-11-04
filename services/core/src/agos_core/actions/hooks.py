"""Automations that start the moment something happens outside (webhooks).

Any app that can send a webhook (a project board, a Google Sheet's Apps Script, Zapier,
GitHub, a form...) posts to the automation's address. The workspace's Hermes
receives it (its webhook platform, on this machine only, behind the public
relay) and does all of it: checks the signature, the events the automation
starts on (its route's filters), the rate, and refuses everything while the
automation is off (the route is disabled). For a delivery it takes, it runs the
route's script (no agent, no tokens): the automation's run script
(engine/automation_run.py), which puts the run on the Kanban with the delivery as
data, or adds it to the run that waits.

The webhook is Hermes's route and nothing else: its address (the route's name),
signing secret, events and on/off are read from Hermes's routes and written
into them with Hermes's own store update, under its lock (engine/hermes.py
webhook_routes). AGOS keeps no copy; it writes the scripts and shows what
Hermes's script noted of each delivery.

Rules:
- The address carries a long random token; with a signing secret, every
  delivery must also be signed (HMAC-SHA256 of the raw body). Without a valid
  address or signature Hermes refuses it.
- Deliveries that arrive while a run is going wait on Hermes's board: the next
  run's cards wait on the running one's (Hermes parents), and deliveries that come
  before that next run begins are added to it (nothing is lost, bursts cost one run).
  Hermes's own `coalesce` can't do this: it only debounces agent-mode routes.
- The payload is data from outside: the agents are told never to follow
  instructions found inside it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import automations as automations_repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.activity import add_activity
from agos_core.db.records import AutomationEvent, AutomationHook, HookCondition
from agos_core.domain.hooks import ROUTE_PREFIX, route_name
from agos_core.engine.cron import hook_script_name
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hooks")


def _row(core: Core, workspace_id: str, automation_id: int) -> Any:
    row = automations_repo.row(core.db, workspace_id, automation_id)
    if row is None:
        raise NotFoundError("This automation")
    return row


# ---- Hermes's routes: the one place of a webhook ----------------------------------

# The first webhook port tried. AGOS_WEBHOOK_FIRST_PORT moves it (end-to-end runs on one
# machine each take their own range, so two test cores never pick the same port).
FIRST_PORT = int(os.environ.get("AGOS_WEBHOOK_FIRST_PORT") or 8650)
ROUTES_FILE = "hook-routes.json"  # in AGOS's system folder: route → port, for the relay
SUBSCRIPTIONS = "webhook_subscriptions.json"  # Hermes's own routes file (hot-reloaded)
DESCRIBED = "AGOS automation: "  # + its name: the route's description
INSECURE = "INSECURE_NO_AUTH"  # Hermes allows it on loopback only: the address is the check
# An automation's route: "agos-<automation>-<digest of its token>" (domain/hooks.py).
_ROUTE = re.compile(rf"^{re.escape(ROUTE_PREFIX)}(\d+)-[0-9a-f]{{24}}$")


@dataclass(frozen=True)
class Route:
    """An automation's webhook as Hermes holds it."""

    name: str
    route: dict[str, Any]

    @property
    def on(self) -> bool:
        # Hermes: only an explicit `enabled: false` turns a route off.
        return self.route.get("enabled", True) is not False

    @property
    def title(self) -> str:
        """The automation's name as the route holds it (its description, written by
        AGOS as DESCRIBED + name; H: hermes_cli/webhook.py:213 description)."""
        text = str(self.route.get("description") or "")
        return text[len(DESCRIBED) :].strip() if text.startswith(DESCRIBED) else ""

    @property
    def secret(self) -> str:
        return str(self.route.get("secret") or INSECURE)

    @property
    def events(self) -> list[str]:
        for spec in self.route.get("filters") or []:
            if _is_events_filter(spec):
                return sorted(str(e) for e in spec["any"][0].get("in") or [])
        return []

    @property
    def conditions(self) -> list[Any]:
        """Hermes's own route filters beyond the events AGOS writes (e.g. which moves
        need work): set in Hermes, kept as they are whenever AGOS rewrites the route."""
        filters = self.route.get("filters") or []
        if isinstance(filters, dict):
            filters = [filters]
        return [spec for spec in filters if not _is_events_filter(spec)]


# ---- "Only if" lines <-> Hermes's route filters ---------------------------------------
# Each line is one Hermes filter (Hermes needs every filter to match), written so it can
# be read back as the same line. A filter set in Hermes in another shape is kept as it
# is and only counted (AutomationHook.other_filters).

_EVENT_FIELD = "payload.event"


def _field(field: str) -> str:
    """Where Hermes reads the value: the delivery's own fields sit under payload."""
    clean = field.strip().removeprefix("payload.")
    return f"payload.{clean}"


def condition_filter(c: HookCondition) -> dict[str, Any]:
    """The Hermes route filter of one line."""
    field, values = _field(c.field), [v for v in (str(x).strip() for x in c.values) if v]
    if c.op in ("is", "is_not"):
        test: dict[str, Any] = {"field": field, "in": values}
    else:
        test = {"any": [{"field": field, "contains": v} for v in values]}
    if c.op in ("is_not", "not_contains"):
        test = {"not": test}
    if c.when:
        # Only for that event: any other event passes this line.
        return {"any": [{"field": _EVENT_FIELD, "not_equals": c.when}, test]}
    return test


def _read_test(spec: Any) -> tuple[str, str, list[str]] | None:
    """(field, op, values) of a filter condition_filter wrote without `when`."""
    if not isinstance(spec, dict):
        return None
    negated = set(spec) == {"not"}
    inner = spec["not"] if negated else spec
    if not isinstance(inner, dict):
        return None
    if set(inner) == {"field", "in"} and isinstance(inner["in"], list):
        field, values, op = inner["field"], inner["in"], "is_not" if negated else "is"
    elif set(inner) == {"any"} and isinstance(inner["any"], list) and inner["any"]:
        items = inner["any"]
        if not all(isinstance(i, dict) and set(i) == {"field", "contains"} for i in items):
            return None
        fields = {i["field"] for i in items}
        if len(fields) != 1:
            return None
        field, values = fields.pop(), [i["contains"] for i in items]
        op = "not_contains" if negated else "contains"
    else:
        return None
    if not isinstance(field, str) or not field.startswith("payload.") or field == _EVENT_FIELD:
        return None
    return field.removeprefix("payload."), op, [str(v) for v in values]


def read_condition(spec: Any) -> HookCondition | None:
    """The line a Hermes filter shows as, or None for a filter of another shape."""
    when: str | None = None
    items = spec.get("any") if isinstance(spec, dict) and set(spec) == {"any"} else None
    if (
        isinstance(items, list)
        and len(items) == 2
        and isinstance(items[0], dict)
        and set(items[0]) == {"field", "not_equals"}
        and items[0]["field"] == _EVENT_FIELD
    ):
        when, spec = str(items[0]["not_equals"]), items[1]
    found = _read_test(spec)
    if found is None:
        return None
    field, op, values = found
    return HookCondition(when=when, field=field, op=op, values=values)  # type: ignore[arg-type]


def clean_conditions(conditions: list[HookCondition]) -> list[HookCondition]:
    """The owner's lines as Hermes will hold them: no empty line, no empty value."""
    out: list[HookCondition] = []
    for c in conditions:
        values = [v.strip() for v in c.values if v.strip()]
        field = c.field.strip().removeprefix("payload.")
        if not field or not values:
            raise ActionError("Each “Only if” line needs a field and at least one value.")
        if field == "event":
            raise ActionError("Pick the events in “Only these events”, not as a line.")
        out.append(
            HookCondition(when=(c.when or "").strip() or None, field=field, op=c.op, values=values)
        )
    return out


def _is_events_filter(spec: Any) -> bool:
    """The filter AGOS writes for the events the owner picked (see _route)."""
    items = spec.get("any") if isinstance(spec, dict) else None
    return (
        isinstance(items, list)
        and len(spec) == 1
        and bool(items)
        and isinstance(items[0], dict)
        and items[0].get("field") == "event"
    )


def routes(core: Core, workspace_id: str) -> dict[int, Route]:
    """The workspace's automation routes in its Hermes, by automation. Read like
    Hermes reads them (lock-free: Hermes publishes the file by atomic rename)."""
    if core.engine is None:
        return {}
    path = core.engine.profile_home(workspace_id) / SUBSCRIPTIONS
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError):
        return {}
    found: dict[int, Route] = {}
    for name, route in data.items() if isinstance(data, dict) else ():
        match = _ROUTE.match(str(name))
        if match and isinstance(route, dict):
            found[int(match[1])] = Route(str(name), route)
    return found


def hooks_of(core: Core, workspace_id: str) -> dict[int, AutomationHook]:
    """The workspace's webhooks, read from Hermes's routes (with the last delivery)."""
    return {
        aid: hook_from(core, workspace_id, aid, route)
        for aid, route in routes(core, workspace_id).items()
    }


def hook_from(core: Core, workspace_id: str, automation_id: int, route: Route) -> AutomationHook:
    """The webhook as the owner sees it: Hermes's route, with its last delivery."""
    last = last_delivery(core, workspace_id, automation_id)
    lines = [read_condition(spec) for spec in route.conditions]
    from agos_core.actions import hook_secrets

    return AutomationHook(
        path=f"/webhooks/{route.name}",
        signed=route.secret != INSECURE,
        secret_waiting=hook_secrets.waiting(core, workspace_id, automation_id),
        events=route.events,
        conditions=[c for c in lines if c is not None],
        other_filters=sum(1 for c in lines if c is None),
        last_received_at=last or None,
    )


def _route(
    name: str,
    secret: str,
    events: list[str],
    on: bool,
    automation: Any,
    conditions: list[Any] | None = None,
) -> dict[str, Any]:
    route: dict[str, Any] = {
        "description": f"{DESCRIBED}{automation.name}",
        "events": [],
        "secret": secret,
        "prompt": "",
        "deliver": "log",
        # Hermes runs it for each delivery it takes: the run goes on the Kanban.
        "script": hook_script_name(int(automation.id)),
        # Off: Hermes refuses the deliveries (the address stays).
        "enabled": on,
    }
    if events:
        # The event's name: Hermes's own (a header, event_type, type) or the
        # payload's "event" (what older XAG apps send).
        route["filters"] = [
            {
                "any": [
                    {"field": "event", "in": events},
                    {"field": "payload.event", "in": events},
                ]
            }
        ]
    if conditions:
        # Hermes's filters all have to match: the deliveries no step has work for
        # are dropped by Hermes before any card exists (no run, no tokens).
        route["filters"] = [*route.get("filters", []), *conditions]
    return route


def _publish(
    core: Core, workspace_id: str, put: dict[str, dict[str, Any]], drop: list[int]
) -> None:
    """Into Hermes's routes with Hermes's own update (its lock): the routes of the
    automations in `drop` go, the ones in `put` are written. Then the relay's map."""
    engine = core.engine
    if engine is None:
        raise ActionError("The engine is off, so the webhook can't change now.", 409)
    if not (engine.profile_home(workspace_id) / "config.yaml").is_file():
        raise ActionError("This workspace's agent isn't set up yet (is Docker running?).", 409)
    try:
        engine.webhook_routes(workspace_id, put, [f"{ROUTE_PREFIX}{a}-" for a in drop])
    except (EngineError, OSError) as error:
        raise ActionError(f"The webhook didn't change: {error}", 503) from error
    relay_map(core)


# ---- the owner's settings ------------------------------------------------------


def set_hook(
    core: Core,
    workspace_id: str,
    automation_id: int,
    *,
    on: bool,
    secret: str | None = None,
    events: list[str] | None = None,
    new_address: bool = False,
    schedule: str | None = None,
    enabled: bool | None = None,
    conditions: list[HookCondition] | None = None,
    new_secret: bool = False,
    shown: bool = False,
) -> AutomationHook | None:
    """Turns the webhook on/off. `secret` "" removes the signing secret, None keeps it.
    A new webhook gets a random signing secret (signed by default), and `new_secret`
    gives one to an existing webhook: that secret is in the answer once
    (`AutomationHook.new_secret`), never shown again. Unsigned stays only as the
    owner's explicit choice (`secret=""`).
    `conditions`: its "Only if" lines (Hermes route filters), None keeps them; the
    filters set in Hermes in another shape always stay.
    `schedule`: the one being saved with it (None: its schedule now, from Hermes).
    `enabled`: the automation's on/off being saved with it (None: its own now).
    `shown`: the caller shows a made secret to the owner now (the webhook's dialog);
    otherwise it waits for him, sealed, until he shows it once (actions/hook_secrets).
    """
    from agos_core.actions import automation_cards, hook_secrets
    from agos_core.actions import automations as automation_actions  # late: it imports us

    row = _row(core, workspace_id, automation_id)
    automation = automation_actions.get(core, workspace_id, automation_id)
    assert automation is not None
    current = routes(core, workspace_id).get(automation_id)
    if not on:
        if not (automation.schedule if schedule is None else schedule):
            raise ActionError(
                "This automation has no schedule, so the webhook is the only way it starts. "
                "Give it a schedule first, or delete it."
            )
        _publish(core, workspace_id, {}, [automation_id])
        hook_secrets.drop(core, workspace_id, automation_id)
        automation_cards.write_scripts(core, automation.model_copy(update={"hook": None}))
        add_activity(
            core.db, workspace_id, kind="automation.hook", text=f"Webhook off: {row['name']}"
        )
        return None
    name = current.name if current and not new_address else ""
    if not name:
        name = route_name(automation_id, secrets.token_urlsafe(32))
    sealed = current.secret if current else INSECURE
    made = secrets.token_urlsafe(32) if current is None or new_secret else ""
    sealed = made or sealed
    if secret is not None:
        made = ""  # his own secret (or his "unsigned") wins over a made one
        clean = secret.strip()
        if clean and len(clean) < 16:
            raise ActionError("The signing secret is too short (16 characters at least).")
        sealed = clean or INSECURE
    clean_events = sorted({e.strip() for e in (events or []) if e.strip()})
    kept = current.conditions if current else []
    if conditions is not None:
        others = [spec for spec in kept if read_condition(spec) is None]
        kept = [*(condition_filter(c) for c in clean_conditions(conditions)), *others]
    route = _route(
        name,
        sealed,
        clean_events,
        automation.on if enabled is None else enabled,
        automation,
        kept,
    )
    hook = AutomationHook(path=f"/webhooks/{name}", signed=sealed != INSECURE, events=clean_events)
    # Its script first: Hermes runs it from the moment the route is there.
    automation_cards.write_scripts(core, automation.model_copy(update={"hook": hook}))
    _publish(core, workspace_id, {name: route}, [automation_id])
    held_by_route(core, workspace_id, automation_id, automation.name)
    if current is None or new_address:
        add_activity(
            core.db,
            workspace_id,
            kind="automation.hook",
            text=f"Webhook {'address changed' if current else 'on'}: {row['name']}",
        )
    if made:
        add_activity(
            core.db, workspace_id, kind="automation.hook", text=f"Webhook signed: {row['name']}"
        )
    if made and not shown:
        hook_secrets.keep(core, workspace_id, automation_id, made)  # he shows it once
    elif made or secret is not None:
        hook_secrets.drop(core, workspace_id, automation_id)  # shown now, or his own
    found = hooks_of(core, workspace_id).get(automation_id)
    return found.model_copy(update={"new_secret": made}) if found is not None and made else found


def follow(core: Core, workspace_id: str, automation_id: int, *, on: bool) -> None:
    """The automation changed (saved, turned on or off): its route follows (its
    on/off, its name in Hermes) and so does its script."""
    from agos_core.actions import automation_cards
    from agos_core.actions import automations as automation_actions  # late: it imports us

    current = routes(core, workspace_id).get(automation_id)
    automation = automation_actions.get(core, workspace_id, automation_id)
    if current is None or automation is None:
        return
    automation_cards.write_scripts(core, automation)
    route = _route(current.name, current.secret, current.events, on, automation, current.conditions)
    if route != current.route:
        _publish(core, workspace_id, {current.name: route}, [automation_id])
    held_by_route(core, workspace_id, automation_id, automation.name)


def held_by_route(core: Core, workspace_id: str, automation_id: int, name: str) -> bool:
    """An automation started by an event only (no Hermes job): once its Hermes route
    holds the owner's name, AGOS's copy goes (the name lives once). True when the
    route holds it."""
    route = routes(core, workspace_id).get(automation_id)
    if route is None or not name or route.title != name:
        return False
    automations_repo.drop_webhook_name(core.db, workspace_id, automation_id, name)
    return True


def move_names(core: Core) -> int:
    """Once: the names AGOS still kept for automations whose Hermes route holds them
    go (safe to repeat)."""
    rows = automations_repo.webhook_names(core.db)
    return sum(
        held_by_route(core, str(r["workspace_id"]), int(r["id"]), str(r["name"])) for r in rows
    )


def forget(core: Core, workspace_id: str, automation_id: int) -> None:
    """The automation is deleted: its route goes from Hermes."""
    if automation_id not in routes(core, workspace_id):
        return
    try:
        _publish(core, workspace_id, {}, [automation_id])
    except ActionError as error:
        # Its script is gone, so Hermes runs nothing for it (it ignores the delivery).
        log.warning("webhook %s: its route stays in Hermes: %s", automation_id, error.message)


def _free(port: int) -> bool:
    """Nothing else on this machine listens there (8650 is also Hermes's own default
    webhook port, which another Hermes may hold)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _env_port(core: Core, workspace_id: str) -> int | None:
    """WEBHOOK_PORT in the workspace's Hermes .env (Hermes's own setting)."""
    from agos_core.engine import config_file

    if core.engine is None:
        return None
    found = config_file.read_env(core.engine.profile_home(workspace_id)).get("WEBHOOK_PORT", "")
    return int(found) if found.isdigit() else None


def port_of(core: Core, workspace_id: str) -> int:
    """The workspace's Hermes webhook port (127.0.0.1 only): WEBHOOK_PORT in its
    Hermes .env, read there like its API server's port (engine/hermes.py `api`). A
    workspace without one gets a free port no other workspace has, written there
    at once (the same from now on). AGOS keeps no copy."""
    found = _env_port(core, workspace_id)
    if found:
        return found
    taken = {
        p
        for other in workspaces_repo.ids(core.db)
        if other != workspace_id and (p := _env_port(core, other))
    }
    port = FIRST_PORT
    while port in taken or not _free(port):
        port += 1
    if core.engine is not None:
        from agos_core.engine import envfile

        home = core.engine.profile_home(workspace_id)
        home.mkdir(parents=True, exist_ok=True)
        envfile.rewrite(home / ".env", ("WEBHOOK_PORT=",), [f"WEBHOOK_PORT={port}"])
    return port


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def relay_map(core: Core) -> None:
    """The relay's map (AGOS's own file): each automation route in a workspace's
    Hermes → that Hermes's webhook port. Written when it changes."""
    found: dict[str, int] = {}
    for each in workspaces_repo.ids(core.db, trashed=False):
        for route in routes(core, each).values():
            found[route.name] = port_of(core, each)
    path = core.layout.system / ROUTES_FILE
    try:
        if json.loads(path.read_text()) == found:
            return
    except (OSError, ValueError):
        pass
    _write_json(path, found)


def hook_env(core: Core, workspace_id: str) -> dict[str, str]:
    """The profile's .env lines for Hermes's webhook platform (on this machine only)."""
    return {"WEBHOOK_ENABLED": "true", "WEBHOOK_PORT": str(port_of(core, workspace_id))}


def noted(core: Core, workspace_id: str, automation_id: int) -> list[dict[str, Any]]:
    """What Hermes's script noted of the deliveries it took, newest first."""
    from agos_core.actions import automation_cards

    if core.engine is None:
        return []
    try:
        lines = automation_cards.deliveries_log(core, workspace_id, automation_id).read_text()
    except OSError:
        return []
    out = []
    for n, line in enumerate(lines.splitlines(), start=1):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append({**item, "n": n})
    return list(reversed(out))


def last_delivery(core: Core, workspace_id: str, automation_id: int) -> str | None:
    found = noted(core, workspace_id, automation_id)
    if not found:
        return None
    return str(found[0].get("at") or "") or None


NOTED = 1_000_000_000  # ids of the deliveries Hermes noted (AGOS's own rows are below)


def events(core: Core, workspace_id: str, automation_id: int) -> list[AutomationEvent]:
    """The last deliveries: what Hermes's route script noted."""
    _row(core, workspace_id, automation_id)
    return [
        AutomationEvent(
            id=NOTED + int(item["n"]),
            event=str(item.get("event") or ""),
            status=(
                item["status"] if item.get("status") in ("rejected", "duplicate") else "started"
            ),
            detail=str(item.get("detail") or ""),
            plan_id=None,
            received_at=str(item.get("at") or ""),
            preview=str(item.get("preview") or "")[:200],
        )
        for item in noted(core, workspace_id, automation_id)[:30]
    ]
