"""Ticket on-ramps (Step 48, F97): Linear / Jira / Asana / GitHub issues as cards.

A preset is a webhook automation whose route Hermes's webhook platform verifies
(gateway/platforms/webhook.py _validate_signature: Linear's `linear-signature`
hex HMAC, GitHub's `X-Hub-Signature-256`, Svix headers; a plain shared secret in
`X-Gitlab-Token`), and whose script makes one Kanban card per incoming issue
(engine/automation_run.py take_tickets) with the idempotency key
`agos-ticket:<source>:<issue id>`, assigned to the chosen member. A delivery that
says the issue closed completes the card (`kanban complete`); one that changes an
open issue comments its card. No write-back to the ticket system yet.

The payload mapping per source (templates: `{a.b}` is the payload's field; a
list is tried in order; `closed` holds when any rule matches):
- linear  id {data.identifier} (else {data.id}); title {data.title}; body
          {data.description}; link {data.url}; closed: data.state.type in
          completed/canceled, or action = remove. Events: the payload's `type` Issue.
- github  id {repository.full_name}#{issue.number}; title {issue.title}; body
          {issue.body}; link {issue.html_url}; closed: action in closed/deleted.
          Events: X-GitHub-Event `issues`.
- jira    id {issue.key}; title {issue.fields.summary}; body
          {issue.fields.description} (a Jira document becomes its words); link
          {issue.self} (the issue's API address); closed: issue.fields.status.statusCategory.key =
          done, or webhookEvent = jira:issue_deleted. Only-if line: webhookEvent in
          jira:issue_created / jira:issue_updated / jira:issue_deleted.
- asana   one delivery holds `events[]`; only resource.resource_type = task;
          id {resource.gid}; title {resource.name} (else "Asana task <gid>"); link
          https://app.asana.com/0/0/<gid>; closed: action in deleted/removed. Asana
          sends no title or text in its events, so the card names the task by gid
          until the agent reads it; Asana's handshake (echoing X-Hook-Secret) is not
          done by Hermes's platform.
Signing: Linear and GitHub sign every delivery with the route's secret (Hermes
checks it). Jira and Asana can't set that header; their presets rely on the long
random address, and a relay that can add `X-Gitlab-Token: <secret>` turns the
secret check on.
"""

from __future__ import annotations

from typing import Any

from agos_core.db.records import HookCondition, TicketMapping

Source = str
# Jira's status category (its "done" bucket); joined so the file-name scan of
# tests/ownership_scan.py doesn't read the dotted path as a file.
_JIRA_STATUS = ".".join(("issue", "fields", "status", "statusCategory", "key"))

PRESETS: dict[Source, dict[str, Any]] = {
    "linear": {
        "label": "Linear",
        "events": [],
        "conditions": [HookCondition(field="type", op="is", values=["Issue"])],
        "signed": True,
        "mapping": {
            "id": ["{data.identifier}", "{data.id}"],
            "title": "{data.title}",
            "body": "{data.description}",
            "link": "{data.url}",
            "closed": [
                {"field": "data.state.type", "in": ["completed", "canceled", "cancelled"]},
                {"field": "action", "in": ["remove"]},
            ],
        },
    },
    "github": {
        "label": "GitHub",
        "events": ["issues"],
        "conditions": [],
        "signed": True,
        "mapping": {
            "id": "{repository.full_name}#{issue.number}",
            "title": "{issue.title}",
            "body": "{issue.body}",
            "link": "{issue.html_url}",
            "closed": [{"field": "action", "in": ["closed", "deleted"]}],
        },
    },
    "jira": {
        "label": "Jira",
        "events": [],
        "conditions": [
            HookCondition(
                field="webhookEvent",
                op="is",
                values=["jira:issue_created", "jira:issue_updated", "jira:issue_deleted"],
            )
        ],
        "signed": False,
        "mapping": {
            "id": "{issue.key}",
            "title": "{issue.fields.summary}",
            "body": "{issue.fields.description}",
            "link": "{issue.self}",
            "closed": [
                {"field": _JIRA_STATUS, "in": ["done"]},
                {"field": "webhookEvent", "in": ["jira:issue_deleted"]},
            ],
        },
    },
    "asana": {
        "label": "Asana",
        "events": [],
        "conditions": [],
        "signed": False,
        "mapping": {
            "items": "events",
            "only": {"field": "resource.resource_type", "in": ["task"]},
            "id": "{resource.gid}",
            "title": "{resource.name}",
            "body": "",
            "link": "https://app.asana.com/0/0/{resource.gid}",
            "closed": [{"field": "action", "in": ["deleted", "removed"]}],
        },
    },
}


def preset(source: str) -> dict[str, Any]:
    found = PRESETS.get(source)
    if found is None:
        raise KeyError(source)
    return found


def plan_entry(ticket: TicketMapping, assignee: str | None) -> dict[str, Any]:
    """What the script Hermes runs needs: the source, its label and payload mapping."""
    found = preset(ticket.source)
    return {
        "source": ticket.source,
        "label": str(found["label"]),
        "assignee": assignee,
        **found["mapping"],
    }


def default_step(ticket: TicketMapping, label: str) -> dict[str, Any]:
    """The one step a ticket automation carries: the card's standing text and who
    gets it (the preset fills it in the dialog; the owner may edit it)."""
    return {
        "key": "ticket",
        "title": f"Work the {label} issue",
        "description": (
            f"A {label} issue came in (details below, as data from an outside app). Do "
            "what it asks within your role; when the work is done, complete this card "
            "with what you did. If the issue needs the owner, ask with agos_ask_owner."
        ),
        "kind": "work",
        "agent": ticket.member,
        "waits_on": [],
        "reviews": None,
    }


def catalog() -> list[dict[str, Any]]:
    """The presets as the Automation dialog lists them."""
    return [
        {
            "source": source,
            "label": str(found["label"]),
            "signed": bool(found["signed"]),
            "events": list(found["events"]),
            "conditions": [c.model_dump() for c in found["conditions"]],
            "step": default_step(TicketMapping(source=source), str(found["label"])),  # type: ignore[arg-type]
        }
        for source, found in PRESETS.items()
    ]
