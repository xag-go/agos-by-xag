"""Hermes's helper models (it calls them auxiliary models), for Settings → Helper
models. Pure: it reads Hermes's own settings list (engine.config_schema), never a
copy of it.

The tasks are Hermes's: every block of its `auxiliary` section that routes a model
(it has a `provider`; hermes_cli/config_defaults.py DEFAULT_CONFIG["auxiliary"]),
in Hermes's order, read at run time, so a task a Hermes upgrade adds shows by
itself. Each task's fields are the model-routing ones Hermes gives that task
(`ROUTING`, read in agent/auxiliary_client.py _resolve_task_provider_model);
its credentials (`api_key`, `key_env`) are never shown or written here, and its
`timeout` is on General settings → Time limits.

`agent.image_input_mode` sits on the same page: how a picture the owner sends
reaches the model (Hermes's own words: its description in config_defaults.py;
its modes: agent/image_routing.py _VALID_MODES, read with the settings list).

AGOS keeps no value and picks none: no owner default, no start value for a new
install. The values live in Hermes's managed scope, written by Hermes's own
`hermes config set/unset` (actions/hermes_helper_models.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agos_core.engine.hermes_schema import Field, _title

SECTION = "auxiliary"
IMAGE_MODE = "agent.image_input_mode"
# The per-task fields that choose the model a helper call goes to (Hermes's own
# names). Hermes reads them for every task; a task shows the ones its defaults have.
ROUTING = ("provider", "model", "base_url", "api_mode")

# A plain name and one plain sentence for each of Hermes's tasks (the row's title
# and what it does, for the owner). Only words: tests/test_helper_models.py fails
# when Hermes has a task that isn't here (or here one Hermes no longer has);
# meanwhile the page shows it under Hermes's own name, without a sentence.
LABELS: dict[str, tuple[str, str]] = {
    "vision": (
        "Looking at pictures and videos",
        "Reads screenshots, photos and videos for the agent.",
    ),
    "compression": (
        "Summing up a long chat",
        "Shortens a long conversation so the agent can keep going.",
    ),
    "skills_hub": ("Finding skills", "Helps search for and install skills."),
    "approval": (
        "Checking risky commands",
        "Decides whether a command looks safe enough to run.",
    ),
    "review": ("/review reviewer", "Reviews work when you type /review."),
    "mcp": (
        "Connected apps",
        "Thinks for connected apps (MCP) when they ask the agent a question.",
    ),
    "title_generation": ("Chat titles", "Writes a short title for each chat."),
    "memory_query_rewrite": (
        "Searching memory",
        "Rewrites questions so the agent finds the right memories.",
    ),
    "tts_audio_tags": (
        "Voice tone tags",
        "Adds tone hints to text before Gemini reads it aloud.",
    ),
    "voice_chat": ("Voice chat", "Answers in voice mode."),
    "triage_specifier": (
        "Writing up new cards",
        "Turns a one-line card in Triage into a full task description.",
    ),
    "kanban_decomposer": ("Splitting a card", "Breaks a big card into smaller tasks."),
    "profile_describer": ("Member blurbs", "Writes the one or two lines that describe a member."),
    "goal_judge": ("Goal check", "Checks whether a /goal is done."),
    "curator": ("Skill tidy-up", "Looks over how skills are used and tidies them up."),
    "monitor": ("Mail scoring", "Scores incoming mail from 0 to 10 for importance."),
    "background_review": (
        "Learning after a chat",
        "After a chat, saves what is worth remembering and improves skills.",
    ),
    "moa_reference": (
        "Mixture of agents: advisers",
        "The advisers asked for their view in a mixture of agents.",
    ),
    "moa_aggregator": (
        "Mixture of agents: final answer",
        "Combines the advisers' views into the final answer.",
    ),
}

# Hermes's picture modes (agent/image_routing.py _VALID_MODES) in plain words. A
# mode Hermes adds later shows under its own name.
IMAGE_MODES: dict[str, tuple[str, str]] = {
    "auto": (
        "Automatic",
        "Sends the picture to the model when it can see and no picture helper is chosen;"
        " otherwise describes it first.",
    ),
    "native": (
        "Send pictures to the model",
        "Always sends the picture itself. A model that can't see pictures fails.",
    ),
    "text": (
        "Describe pictures first",
        "The picture helper describes it, and the model gets the description.",
    ),
}


@dataclass(frozen=True)
class Task:
    task: str
    label: str
    summary: str  # one plain sentence of what it does ("" for a task AGOS hasn't seen)
    description: str  # Hermes's own words for the task ("" when it has none)
    fields: tuple[Field, ...]
    in_hermes_list: bool  # False: set in Hermes, but its defaults have no such task


def owns(key: str) -> bool:
    """A key this page shows and writes: a task's routing field, or the image mode."""
    if key == IMAGE_MODE:
        return True
    parts = key.split(".")
    return len(parts) == 3 and parts[0] == SECTION and parts[2] in ROUTING


def _task_of(key: str) -> str:
    return key.split(".")[1]


def tasks(fields: Iterable[Field]) -> list[str]:
    """Hermes's auxiliary tasks, in its order."""
    out: list[str] = []
    for field in fields:
        parts = field.key.split(".")
        routes = len(parts) == 3 and parts[0] == SECTION and parts[2] == "provider"
        if routes and parts[1] not in out:
            out.append(parts[1])
    return out


def label(task: str) -> str:
    known = LABELS.get(task)
    return known[0] if known else task.replace("_", " ").capitalize()


def summary(task: str) -> str:
    known = LABELS.get(task)
    return known[1] if known else ""


def image_choices(modes: Iterable[str]) -> list[dict[str, str]]:
    """Hermes's picture modes, each with a plain label and sentence (its own name
    and no sentence for a mode AGOS hasn't seen)."""
    out = []
    for mode in modes:
        name, hint = IMAGE_MODES.get(mode, (mode, ""))
        out.append({"value": mode, "label": name, "hint": hint})
    return out


def _description(field: Field | None) -> str:
    if field is None or not field.description or field.description == _title(field.key):
        return ""
    return field.description


def rows(fields: Iterable[Field], held: Iterable[Field] = ()) -> list[Task]:
    """One row per Hermes task with its routing fields (Hermes's order), then any
    task only found set in Hermes (`held`: unlisted fields of keys this page owns)."""
    every = list(fields)
    by_key = {f.key: f for f in every}
    out: list[Task] = []
    for task in tasks(every):
        mine = tuple(
            by_key[f"{SECTION}.{task}.{name}"]
            for name in ROUTING
            if f"{SECTION}.{task}.{name}" in by_key
        )
        out.append(
            Task(
                task,
                label(task),
                summary(task),
                _description(by_key.get(f"{SECTION}.{task}.provider")),
                mine,
                True,
            )
        )
    listed = {t.task for t in out}
    extra: dict[str, list[Field]] = {}
    for field in held:
        if owns(field.key) and field.key != IMAGE_MODE and field.key not in by_key:
            extra.setdefault(_task_of(field.key), []).append(field)
    for task, found in extra.items():
        order = {name: i for i, name in enumerate(ROUTING)}
        found.sort(key=lambda f: order[f.key.rsplit(".", 1)[1]])
        if task in listed:
            # A routing field Hermes reads but this task's defaults lack: on its row.
            at = next(i for i, t in enumerate(out) if t.task == task)
            row = out[at]
            out[at] = Task(
                row.task, row.label, row.summary, row.description, (*row.fields, *found), True
            )
            continue
        out.append(Task(task, label(task), summary(task), "", tuple(found), False))
    return out


def image_field(fields: Iterable[Field]) -> Field | None:
    return next((f for f in fields if f.key == IMAGE_MODE), None)
