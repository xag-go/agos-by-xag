"""Typed questions an agent asks the owner, as Hermes Kanban cards: pure rules.

A question is a card (made by AGOS for the agent's `agos_ask_owner` tool) whose
body carries ONE fenced block, blocked for the owner (kanban block, kind
needs_input, reason "waiting for the owner: question"):

    ```agos-question
    {"kind": "confirm", "payload": {...}, "continuation": "wake_assignee", "from": "t_1"}
    ```

- the info string is exactly `agos-question`; the JSON is read the way proposals
  are (engine/proposals.py parse: from the fence on, never up to a closing fence);
- `kind`: ask (free text) | confirm (yes / no) | checkbox (several of the
  options) | choice (one of the options) | verdicts (approve / reject each item)
  | suggest_tasks (cards the owner accepts one by one);
- `payload`: question (the words), then per kind: options [{id, label}] (checkbox,
  choice), items [{id, label}] (verdicts), tasks [{title, body, member}]
  (suggest_tasks), placeholder (ask);
- `continuation`: what happens to the question card once answered —
  wake_assignee (default: the card goes on to its assignee with the answer; when
  it was asked from another card, the question card is completed with the answer
  as its result and Hermes wakes the asking card, which waits on it as a parent)
  | none (completed with the answer, nobody woken);
- `from`: the card the agent was working when it asked (its own run), if any.

The answer is written on the card as a comment that starts with a stable marker,
`[agos-answer <card> r<round>]`, then its JSON, then the words the agent reads.
"""

from __future__ import annotations

import json
import re
from typing import Any

FENCE = "agos-question"
KINDS = ("ask", "confirm", "checkbox", "choice", "verdicts", "suggest_tasks")
CONTINUATIONS = ("wake_assignee", "none")
OWNER_OK = "waiting for the owner:"
BLOCK_REASON = f"{OWNER_OK} question"
MAX_OPTIONS = 30
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")

_OPEN = re.compile(r"^[ \t]*```[ \t]*" + re.escape(FENCE) + r"[ \t]*$", re.M)
_MARK = re.compile(r"^\[agos-answer (?P<card>[A-Za-z0-9_-]+) r(?P<round>\d+)\]")


def parse(body: str) -> dict[str, Any] | None:
    """The question in a card body, or None (no block, or one AGOS can't read)."""
    found = _OPEN.search(body or "")
    if found is None:
        return None
    rest = body[found.end() :].lstrip()
    try:
        raw, _ = json.JSONDecoder().raw_decode(rest)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    payload = raw.get("payload")
    if kind not in KINDS or not isinstance(payload, dict):
        return None
    out: dict[str, Any] = {"kind": kind, "payload": clean(kind, payload)}
    continuation = str(raw.get("continuation") or "wake_assignee").strip().lower()
    out["continuation"] = continuation if continuation in CONTINUATIONS else "wake_assignee"
    asked_from = str(raw.get("from") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", asked_from):
        out["from"] = asked_from
    return out


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "item"
    if not re.fullmatch(ID.pattern, base):
        base = "item"
    out, n = base, 2
    while out in used:
        out = f"{base[:28]}-{n}"
        n += 1
    return out


def _listed(raw: Any, key: str) -> list[dict[str, str]]:
    """Options or items as [{id, label}]: a bare string is its own label; ids are
    made from the labels when missing (Telegram's buttons carry them)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    used: set[str] = set()
    for entry in raw[:MAX_OPTIONS]:
        if isinstance(entry, str):
            label, given = entry.strip(), ""
        elif isinstance(entry, dict):
            label = str(entry.get("label") or entry.get("title") or entry.get(key) or "").strip()
            given = str(entry.get("id") or "").strip().lower()
        else:
            continue
        if not label:
            continue
        item_id = given if re.fullmatch(ID.pattern, given) and given not in used else ""
        item_id = item_id or _slug(label, used)
        used.add(item_id)
        out.append({"id": item_id, "label": label[:300]})
    return out


def clean(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload AGOS keeps: its known fields typed, the rest as given."""
    p: dict[str, Any] = {str(k)[:40]: v for k, v in payload.items() if isinstance(k, str)}
    p["question"] = str(p.get("question") or p.get("text") or "").strip()[:4000]
    p.pop("text", None)
    if kind == "ask":
        p["placeholder"] = str(p.get("placeholder") or "").strip()[:200]
    elif kind in ("checkbox", "choice"):
        p["options"] = _listed(p.get("options") or p.get("choices"), "label")
        p.pop("choices", None)
    elif kind == "verdicts":
        p["items"] = _listed(p.get("items"), "label")
    elif kind == "suggest_tasks":
        tasks: list[dict[str, str]] = []
        for raw in (p.get("tasks") or [])[:MAX_OPTIONS] if isinstance(p.get("tasks"), list) else []:
            if isinstance(raw, str):
                raw = {"title": raw}
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()[:200]
            if title:
                tasks.append(
                    {
                        "title": title,
                        "body": str(raw.get("body") or raw.get("description") or "")[:20_000],
                        "member": str(raw.get("member") or raw.get("assignee") or "")
                        .strip()
                        .lower()[:64],
                    }
                )
        p["tasks"] = tasks
    return p


def problems(kind: str, payload: dict[str, Any]) -> list[str]:
    """What keeps a question from being asked (told the agent)."""
    out = []
    if not payload.get("question") and kind != "suggest_tasks":
        out.append("question (the words) is missing")
    if kind in ("checkbox", "choice") and len(payload.get("options") or []) < 2:
        out.append("options needs at least two entries")
    if kind == "verdicts" and not payload.get("items"):
        out.append("items (what to approve or reject) is missing")
    if kind == "suggest_tasks" and not payload.get("tasks"):
        out.append("tasks (title, body, member) is missing")
    return out


def block(
    kind: str, payload: dict[str, Any], continuation: str = "wake_assignee", asked_from: str = ""
) -> str:
    """The fenced block AGOS writes into the question card's body."""
    raw: dict[str, Any] = {"kind": kind, "payload": payload, "continuation": continuation}
    if asked_from:
        raw["from"] = asked_from
    return f"```{FENCE}\n{json.dumps(raw, ensure_ascii=False, indent=1)}\n```"


def label(kind: str, payload: dict[str, Any]) -> str:
    """One line for the card, the push and the Inbox."""
    question = str(payload.get("question") or "").strip()
    first = question.splitlines()[0] if question else ""
    if kind == "suggest_tasks":
        n = len(payload.get("tasks") or [])
        return first or f"Suggests {n} task{'s' if n != 1 else ''}"
    if kind == "verdicts":
        return first or "Approve or reject each item"
    return first or "A question"


def marker(card: str, round_: int) -> str:
    return f"[agos-answer {card} r{round_}]"


def read_marker(comment: str) -> tuple[str, int] | None:
    """(card, round) when a comment is one of AGOS's answer comments."""
    found = _MARK.match(comment.strip())
    if found is None:
        return None
    return found["card"], int(found["round"])


def check_answer(kind: str, payload: dict[str, Any], answer: Any) -> dict[str, Any]:
    """The owner's answer, typed for the kind; ValueError says what is wrong.
    - ask: {text}; confirm: {yes: bool} (+ note); checkbox: {selected: [ids]};
    - choice: {selected: id}; verdicts: {verdicts: {id: approve | reject}};
    - suggest_tasks: {accepted: [indexes]}. Every kind takes an optional note."""
    raw = answer if isinstance(answer, dict) else {}
    note = str(raw.get("note") or "").strip()[:4000]
    out: dict[str, Any] = {}
    if kind == "ask":
        text = str(raw.get("text") or "").strip()
        if not text:
            raise ValueError("Write an answer first.")
        out["text"] = text[:20_000]
    elif kind == "confirm":
        yes = raw.get("yes")
        if yes in ("yes", "true", 1):
            yes = True
        elif yes in ("no", "false", 0):
            yes = False
        if not isinstance(yes, bool):
            raise ValueError("Answer yes or no.")
        out["yes"] = yes
    elif kind in ("checkbox", "choice"):
        ids = [o["id"] for o in payload.get("options") or []]
        selected = raw.get("selected")
        if kind == "choice":
            if not isinstance(selected, str) or selected not in ids:
                raise ValueError("Pick one of the options.")
            out["selected"] = selected
        else:
            if not isinstance(selected, list) or any(s not in ids for s in selected):
                raise ValueError("Pick from the options.")
            out["selected"] = list(dict.fromkeys(str(s) for s in selected))
    elif kind == "verdicts":
        ids = [i["id"] for i in payload.get("items") or []]
        verdicts = raw.get("verdicts")
        if not isinstance(verdicts, dict) or set(verdicts) != set(ids):
            raise ValueError("Give every item a verdict.")
        if any(v not in ("approve", "reject") for v in verdicts.values()):
            raise ValueError("Each verdict is approve or reject.")
        out["verdicts"] = {i: str(verdicts[i]) for i in ids}
    else:
        n = len(payload.get("tasks") or [])
        accepted = raw.get("accepted")
        if not isinstance(accepted, list) or any(
            not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < n for i in accepted
        ):
            raise ValueError("Say which suggested tasks you accept (their positions).")
        out["accepted"] = sorted(set(accepted))
    if note:
        out["note"] = note
    return out


def answer_text(kind: str, payload: dict[str, Any], answer: dict[str, Any]) -> str:
    """The words under the marker: what the agent reads when its card goes on."""
    note = f" Note: {answer['note']}" if answer.get("note") else ""
    if kind == "ask":
        return f"The owner answers: {answer.get('text', '')}"
    if kind == "confirm":
        return ("The owner says YES." if answer.get("yes") else "The owner says NO.") + note
    labels = {o["id"]: o["label"] for o in payload.get("options") or []}
    if kind == "choice":
        return f"The owner picked: {labels.get(str(answer.get('selected')), answer.get('selected'))}.{note}"
    if kind == "checkbox":
        picked = [labels.get(s, s) for s in answer.get("selected") or []]
        return ("The owner picked: " + ("; ".join(picked) if picked else "none") + ".") + note
    if kind == "verdicts":
        items = {i["id"]: i["label"] for i in payload.get("items") or []}
        lines = [f"- {items.get(i, i)}: {v}" for i, v in (answer.get("verdicts") or {}).items()]
        return "The owner's verdicts:\n" + "\n".join(lines) + note
    tasks = payload.get("tasks") or []
    accepted = [tasks[i]["title"] for i in answer.get("accepted") or [] if i < len(tasks)]
    made = answer.get("cards") or []
    return (
        "The owner accepted "
        + (f"{len(accepted)} of {len(tasks)} suggested tasks" if tasks else "no tasks")
        + (
            ": " + "; ".join(f"{t} ({c})" for t, c in zip(accepted, made, strict=False))
            if made
            else ""
        )
        + "."
        + note
    )


def result_text(kind: str, payload: dict[str, Any], answer: dict[str, Any]) -> str:
    """The question card's result when it is completed: the question, then the answer."""
    return f"{label(kind, payload)}\n{answer_text(kind, payload, answer)}"[:20_000]
