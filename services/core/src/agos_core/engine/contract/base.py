"""What a Hermes contract entry is (`Use`, `_u`, `_hooks`), the Hermes packages AGOS
imports from, and the feature lines the entries name (engine/hermes_contract.py).

Must not: hold contract entries (uses_*.py) or read a Hermes tree (tree.py).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "HERMES_ROOTS",
    "KINDS",
    "Use",
]

# The top-level modules / packages of a Hermes checkout AGOS imports from.
HERMES_ROOTS = (
    "agent",
    "cron",
    "gateway",
    "hermes_cli",
    "hermes_constants",
    "hermes_state",
    "hermes_state_common",
    "hermes_state_gateway",
    "hermes_state_sessions",
    "hermes_time",
    "model_tools",
    "plugins",
    "pm",  # Hermes's dependency manager: only a line its launcher prints (no import)
    "toolsets",
    "tools",
    "tui_gateway",
    "utils",
)

KINDS = ("function", "method", "class", "attr", "constant", "module", "override", "hook", "text")


@dataclass(frozen=True)
class Use:
    """One Hermes internal AGOS relies on."""

    module: str  # "tools.approval"
    name: str  # "_human_decision", "BasePlatformAdapter._pop_text_batch"; "" = the module
    kind: str  # one of KINDS
    area: str  # guard / bridge / kanban / rooms / voice / engine
    feature: str  # what of AGOS breaks when it changes
    pos: int = 0  # positional arguments AGOS passes (after self)
    kw: tuple[str, ...] = ()  # keyword arguments AGOS passes
    accepts: tuple[str, ...] = ()  # override: the parameters AGOS's own version takes
    more: bool = False  # override: AGOS's version also takes *args / **kwargs
    text: str = ""  # kind "text": a literal that must be in the module's source

    @property
    def key(self) -> str:
        return f"{self.module}.{self.name}" if self.name else self.module


def _u(
    module: str,
    name: str,
    kind: str,
    area: str,
    feature: str,
    *,
    pos: int = 0,
    kw: str = "",
    accepts: str = "",
    more: bool = False,
    text: str = "",
) -> Use:
    return Use(
        module,
        name,
        kind,
        area,
        feature,
        pos,
        tuple(kw.split()),
        tuple(accepts.split()),
        more,
        text,
    )


def _hooks(names: str, feature: str) -> list[Use]:
    return [_u("hermes_cli.plugins", n, "hook", "hooks", feature) for n in names.split()]


_RULES = "the owner's Autonomy rules (Never / Ask me) on every tool call"
_ASK = "Full access + 'Ask me': the owner's own Allow / Deny card (else the action is blocked)"
_TG = "the workspace's Telegram bot ↔ AGOS chat (messages, commands, cards)"
_CHATS = "AGOS chats as a Hermes platform (the 'agos' adapter)"
_ROUTE = "a member topic's routing / continuing its earlier conversation"
_EYES = "the 👀 / 👍 reaction on his Telegram message AGOS answers"
_CARDS = "the Allow / Deny card of an AGOS conversation on his phone"
_MENU = "the team members in the Telegram '/' menu"
_ALIVE = "whether a workspace's gateway lives (its lamp, start, stop)"
_UNANSWERED = "a chat Hermes answered without its agent (no AI login) stops showing it working"
_KAN = "Kanban cards: who hears a card's end (Hermes's notifier subscriptions)"
_PIPE = "pipeline rules (step 59): a card's move makes its follow-up, comment, assignment"
_SERVICES = "a card's dev servers and preview links (step 59, agos_service)"
_TOK = "the token watch on a Kanban card (far more than usual)"
_STOP = "how long AGOS's gateway stop waits (Hermes's stop budget from the owner's drain)"
_USAGE = "the Dashboard's usage: headline, per-model lines, daily bars (Hermes's analytics)"
_EST = "Board → Estimate effort"
_CARD = "a Kanban card's page (comments, events, links, summary, files) read from the board"
_SEARCH = (
    "Search (step 55): cards, comments and files read from the board, chats from Hermes's index"
)
_CATCH = "a run missed while the server was off runs once (or is skipped) per automation"
_STATUS = "status cards (step 55): the Co-Founder's summary job wakes only when its scope changed"
_DONE = "Mark done on a Kanban card: asking what was done first, and Hermes's reason on a refusal"
_ROOMS = "group chats (Hermes hosted rooms): sync, send, stop, approvals, log"
_PROPOSE = "an agent's proposal (hire, instructions, plan) as a blocked card the owner decides"
_QUESTION = "an agent's typed question / a card blocked for a teammate (step 45)"
_HOLD = "Pause / Resume / Cancel of a card's subtree (step 45)"
_REVIEW = "a card's review stages, round cap and plan-first (step 52)"
_FOUNDER = "the Founder's tasks: board cards assigned to the owner himself, never given a worker"
_THREADS = (
    "card threads (step 58): an agent's comment and its @mentions, the Board's bulk "
    "assign / labels in one Hermes process, who follows a card"
)
_VOICE = "voice notes heard by Gemini (stt.provider: gemini)"
_CLOCK = "the current time on a turn Hermes didn't stamp"
_MCP = "connecting an MCP app with its own sign-in (OAuth) from AGOS"
_TOOLS = "Settings → Tools: the toolsets, their services and which one is active"
_WSKEYS = "Workspace → Keys: a tool key's name, save, removal and test"
_SETTINGS = "Settings → Hermes settings: every Hermes setting, its description and default"
_TOOL_SEARCH = "the Co-Founder's tools kept eager or deferred (the token-cost switch)"
_MODELS = "Settings → Models: the providers, models and reasoning levels"
_KEYS = "API keys / tokens AGOS saves into Hermes's .env"
_ONE = (
    "General settings' fallback models, limits, time limits and timezone"
    " (one value for every workspace)"
)
_PROBE = "the test of an API key before it is saved (Hermes's own probe)"
_WRITES = "every Hermes setting AGOS saves (several keys of one home in one Hermes process)"
_POOLS = "Settings → Models: several keys per provider (Hermes's credential pool)"
_HELD = "Inbox → Memory / skill changes (Hermes's memory/skills write_approval queue)"
_RVA = "read vs act: memory and skill writes after an untrusted read wait for the owner"
_GIST = "content file_path old_string new_string"
_SKILLS_OWN = "the owner's and the Co-Founder's skill create / edit / delete and their Undo"
_LEARNED = "What I learned (each skill change's SKILL.md before / after)"
_VERSIONS = "Skill Studio → Versions (each skill's versions from Hermes's skill ledger)"
_GROW = "skills that grow: the weekly skill review's evidence and its curator pass (step 63)"
_FIND = "find-skills: an agent's skill request installed through Hermes's hub scan (step 63)"
_GRADE = "Skill Studio → Tests (a run graded by Hermes's auxiliary model, agos-grade)"
_ORGANIZE = (
    "Vision → Organize: the Co-Founder's one-shot Hermes run on the owner's notes"
    " (`hermes chat -Q -q`, quiet: only the final answer on stdout)"
)
_HOURS = (
    "work hours (Settings → Work hours, actions/work_hours.py): an off agent gets no "
    "worker, no cron run and no turn; a card past check-out + 2 h is parked; check-in "
    "goes on from the agent's note"
)
_NEW_SKILL = (
    "a new skill checked before anything is written (the Co-Founder's create_skill, the"
    " owner's New skill): Hermes's reason at once, no empty card left behind"
)
