"""Every clock Hermes puts on the team's work, in plain words (General settings →
Time limits). Pure data: no Hermes, no Docker.

Each entry is one Hermes setting: a config.yaml key, or (UPPER_SNAKE) a .env
setting that Hermes's own `hermes config set` writes into the profile's .env.
- `zero_is_no_limit`: Hermes reads 0 as "no limit" (checked in its source, see
  `source`); "No limit" then writes 0.
- otherwise 0 is NOT "no limit" in Hermes (an instant timeout, a floor, or its
  default), so "No limit" writes `NO_LIMIT_SECONDS` (24 hours: no command, page or
  helper call of the team's runs that long), or Hermes's own ceiling where it has one.
- `default`: the owner's choice: what Hermes's managed scope starts with (one
  value for every workspace, actions/hermes_managed.py).
- Hermes's default (what it uses while the key isn't set) is NOT kept here: it is
  read from Hermes's own settings list (engine.config_schema, its DEFAULT_CONFIG),
  actions/hermes_time_limits.py `defaults`. Only a key DEFAULT_CONFIG lacks, whose
  default is a literal in Hermes's code (`resolve_timeout("key", 420)`, an .env
  setting read with a fallback), has it in `code_default`, with `source`.
- `read`: Hermes v0.22.2 reads the key (False: kept for when it does).

tests/test_time_limits_guard.py parses the installed Hermes and fails when it has
a timeout that is neither here nor in its reviewed list, so an upgrade can't add a
clock unseen.
"""

from __future__ import annotations

from dataclasses import dataclass

NO_LIMIT_SECONDS = 86_400  # 24 h: Hermes's practical "no limit" where 0 isn't one
# Hermes's own cap on approvals.timeout (agent/deadline.py MAX_SAFE_TIMEOUT_S, one
# year; tools/approval_context.py _get_approval_timeout clamps to it).
HERMES_MAX_SECONDS = 31_536_000
# Hermes's own cap on plugins.hook_callback_timeout (hermes_cli/plugins_dispatch.py
# _MAX_HOOK_CALLBACK_TIMEOUT_SECS): the hang guard of every plugin hook. The owner's
# yes under Full access no longer waits inside a hook (agos-guard asks him in its
# tool_execution middleware, which Hermes runs with no timeout).
HOOK_GUARD_SECONDS = 600

# The helper models themselves (provider, model) are Hermes's own settings on
# Settings → Helper models (engine/helper_models.py); only their clocks are here.
HELPERS = "Background helpers"
GROUPS = (
    "Tools & commands",
    "Browser",
    "Waiting for you",
    HELPERS,
)


@dataclass(frozen=True)
class TimeLimit:
    key: str
    group: str
    label: str
    hint: str
    zero_is_no_limit: bool
    default: int
    source: str  # where Hermes reads it (v0.22.2), for whoever checks
    no_limit: int = NO_LIMIT_SECONDS  # what "No limit" writes when 0 isn't one
    restart: bool = False  # Hermes reads it when the workspace's Hermes starts
    code_default: int | None = None  # only where DEFAULT_CONFIG has no default
    read: bool = True  # Hermes v0.22.2 reads this key

    @property
    def no_limit_value(self) -> int:
        return 0 if self.zero_is_no_limit else self.no_limit

    @property
    def read_by_hermes(self) -> bool:
        return self.read

    def is_no_limit(self, value: int) -> bool:
        return value <= 0 if self.zero_is_no_limit else value >= self.no_limit


def _aux(task: str, label: str, hint: str, read: bool = True) -> TimeLimit:
    return TimeLimit(
        key=f"auxiliary.{task}.timeout",
        group=HELPERS,
        label=label,
        hint=hint + " Hermes's helper call; 0 would end it at once, so No limit is 24 hours.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        read=read,
        source="agent/auxiliary_client.py:6357 _get_task_timeout (float, no 0 = off)",
    )


TOOLS = "Tools & commands"
WAIT = "Waiting for you"

TIME_LIMITS: tuple[TimeLimit, ...] = (
    # ---- Tools & commands ---------------------------------------------------------
    TimeLimit(
        "timeouts.tools.sequential_call",
        TOOLS,
        "One tool call",
        "The longest one tool call can run before Hermes gives up on it.",
        zero_is_no_limit=True,
        default=0,
        code_default=420,
        source="agent/tool_executor.py:841 → agent/deadline.py:159 resolve_timeout (≤0 = unbounded)",
    ),
    TimeLimit(
        "timeouts.tools.concurrent_batch",
        TOOLS,
        "Tool calls run together",
        "The longest a batch of tool calls running side by side can take.",
        zero_is_no_limit=True,
        default=0,
        code_default=420,
        source="agent/tool_executor.py:186 → agent/deadline.py:159 resolve_timeout (≤0 = unbounded)",
    ),
    TimeLimit(
        "timeouts.mcp.tool_call",
        TOOLS,
        "One call to a connected app (MCP)",
        "The longest a connected app's tool can take to answer. Here 0 is not "
        "'no limit': Hermes falls back to its 5-minute default, so No limit is 24 hours.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        code_default=300,
        source="tools/mcp_tool_common.py:44-58 _resolve_tool_timeout (0 → None → 300 s default)",
    ),
    TimeLimit(
        "terminal.timeout",
        TOOLS,
        "A command, when the agent doesn't say how long",
        "How long a terminal command may run when the agent sets no time of its own. "
        "0 would end every command at once.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="tools/terminal_tool.py:753, :1152 (timeout or config['timeout'], 0 = instant)",
    ),
    TimeLimit(
        "TERMINAL_MAX_FOREGROUND_TIMEOUT",
        TOOLS,
        "A command the agent waits on",
        "Above this a command moves to the background and the agent is told when it "
        "ends. Kept in each profile's .env (Hermes's own setting); 0 would send every "
        "command to the background.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        code_default=600,
        source="tools/terminal_tool.py:76 (read from the environment at start), :1147",
        restart=True,
    ),
    TimeLimit(
        "agent.gateway_timeout",
        TOOLS,
        "A quiet answer",
        "Ends an answer that has done nothing at all for this long (not while it runs "
        "tools or waits for the model).",
        zero_is_no_limit=True,
        default=0,
        source="gateway/run_turn.py:3424 (v > 0 else None: 0 = unlimited)",
        restart=True,
    ),
    TimeLimit(
        "agent.turn_liveness.timeout_s",
        TOOLS,
        "An answer that shows no progress",
        "Interrupts an answer with no visible progress for this long.",
        zero_is_no_limit=True,
        default=0,
        source="agent/turn_liveness.py:85 (timeout_s <= 0 opts out)",
    ),
    TimeLimit(
        "delegation.child_timeout_seconds",
        TOOLS,
        "A helper agent (subagent) with no progress",
        "Stops a subagent that makes no progress for this long.",
        zero_is_no_limit=True,
        default=0,
        source="tools/delegate_tool_config.py:134 _parse_timeout (<= 0 disables)",
    ),
    TimeLimit(
        "agent.restart_after_turn_timeout",
        TOOLS,
        "A restart waits for running work",
        "When Hermes restarts (an update, /restart) it first waits this long for "
        "running answers to finish. Here 0 is not 'no limit': Hermes restarts at once "
        "and cuts them, so No limit is 24 hours.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="gateway/run_shutdown.py:1644 (timeout <= 0 → stop at once), gateway/restart.py:305",
        restart=True,
    ),
    # ---- Browser -------------------------------------------------------------------
    TimeLimit(
        "browser.command_timeout",
        "Browser",
        "One browser step",
        "The longest one browser step (open a page, click, screenshot) can take. "
        "Hermes never goes under 5 seconds.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="tools/browser_tool.py:218 (max(int(v), 5))",
        restart=True,
    ),
    TimeLimit(
        "browser.inactivity_timeout",
        "Browser",
        "An idle browser",
        "Closes a browser nobody used for this long. Hermes never goes under 30 seconds.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="tools/browser_tool.py:397 (max(int(v), 30))",
        restart=True,
    ),
    # ---- Waiting for you -----------------------------------------------------------
    TimeLimit(
        "approvals.timeout",
        WAIT,
        "A command waiting for your yes",
        "How long a risky command waits for your answer before it's refused. 0 would "
        "refuse it at once, so No limit is Hermes's own maximum (one year).",
        zero_is_no_limit=False,
        default=HERMES_MAX_SECONDS,
        source="tools/approval_gateway_wait.py:58, tools/approval_context.py:256 (cap 1 year)",
        no_limit=HERMES_MAX_SECONDS,
    ),
    TimeLimit(
        "plugins.hook_callback_timeout",
        WAIT,
        "A stuck plugin step",
        "Hermes's guard for every plugin step before or after a tool or an answer: a "
        "step stuck this long is skipped (a tool's check refuses the tool), so one "
        "stuck plugin can't freeze a chat. Your yes while Full access is on is asked "
        "outside it and waits with no limit. Hermes's own maximum is 10 minutes.",
        zero_is_no_limit=True,
        default=HOOK_GUARD_SECONDS,
        source="hermes_cli/plugins.py:1125 _resolve_hook_callback_timeout (<= 0: no timeout; "
        "cap 600 s, hermes_cli/plugins_dispatch.py:157)",
    ),
    TimeLimit(
        "agent.clarify_timeout",
        WAIT,
        "A question waiting for your answer",
        "How long the agent waits when it asks you something.",
        zero_is_no_limit=True,
        default=0,
        source="tools/clarify_gateway.py:263 resolve_clarify_timeout (<= 0 unlimited)",
    ),
    TimeLimit(
        "agent.gateway_timeout_warning",
        WAIT,
        "'Still quiet' warning",
        "Sends one warning when an answer has been quiet for this long.",
        zero_is_no_limit=True,
        default=0,
        source="gateway/run_turn.py:3424 (v > 0 else None: 0 = off)",
        restart=True,
    ),
    TimeLimit(
        "agent.session_stall_timeout",
        WAIT,
        "'Try /new' note on a stuck chat",
        "Tells you to start a new chat when one looks stuck for this long.",
        zero_is_no_limit=True,
        default=0,
        source="gateway/run_watchers.py:244 (only when > 0)",
        restart=True,
    ),
    TimeLimit(
        "discord.voice_channel_inactivity_timeout_seconds",
        WAIT,
        "Leaving a quiet Discord voice channel",
        "Leaves a Discord voice channel after this long without anyone talking.",
        zero_is_no_limit=True,
        default=0,
        source="plugins/platforms/discord/adapter.py:1280, :3677 (0 = stay)",
        restart=True,
    ),
    # ---- Background helpers (auxiliary models) ------------------------------------
    _aux("compression", "Summing up a long chat", "Compacting older turns."),
    _aux("skills_hub", "Skills hub", "Searching and reading skills."),
    _aux("approval", "Risk check of a command", "The model that rates a command."),
    _aux("mcp", "Connected apps helper", "Hermes's helper for connected apps."),
    _aux("title_generation", "Chat titles", "Naming a chat."),
    _aux("memory_query_rewrite", "Memory search", "Rewriting a memory search."),
    _aux("tts_audio_tags", "Voice tags", "Tagging text before it's spoken."),
    _aux("voice_chat", "Voice chat", "Answering in a voice chat."),
    _aux("background_review", "Background review", "Looking back over a session."),
    _aux("curator", "Skill curator", "Reviewing how skills are used."),
    _aux("goal_judge", "Goal check", "Checking whether a goal is met."),
    _aux("kanban_decomposer", "Splitting a card", "Breaking a card into steps."),
    _aux("moa_aggregator", "Mixture of agents: final answer", "Joining advisers."),
    _aux("moa_reference", "Mixture of agents: advisers", "Each adviser's answer."),
    _aux("monitor", "Mail scoring", "Rating how important a mail is."),
    _aux("profile_describer", "Member blurb", "Writing a member's short description."),
    _aux("review", "/review reviewer", "The reviewer subagent.", read=False),
    _aux("triage_specifier", "Triage card", "Turning a one-liner into a spec."),
    # ---- Background helpers: pictures and videos ----------------------------------
    TimeLimit(
        "auxiliary.vision.timeout",
        HELPERS,
        "Looking at a picture or a video",
        "The model call that reads a picture or a video (Hermes gives video at least "
        "3 minutes). 0 would end it at once.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="tools/vision_tools.py:755 _aux_call_kwargs (video uses this one too)",
    ),
    TimeLimit(
        "auxiliary.vision.download_timeout",
        HELPERS,
        "Downloading a picture",
        "Fetching a picture from a link before reading it. 0 would end it at once.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        source="tools/vision_tools.py:84 (read at start)",
        restart=True,
    ),
    TimeLimit(
        "auxiliary.video.timeout",
        HELPERS,
        "Video helper",
        "Kept for video's own helper; Hermes v0.22.2 times video with the picture setting above.",
        zero_is_no_limit=False,
        default=NO_LIMIT_SECONDS,
        read=False,
        source="not read by Hermes v0.22.2 (`hermes config set` warns it's unrecognized)",
    ),
)

BY_KEY = {limit.key: limit for limit in TIME_LIMITS}


def owner_defaults() -> dict[str, str]:
    """The owner's choice for every limit: what Hermes's managed scope starts with
    (actions/hermes_managed.py move_once), one value for every workspace (an
    UPPER_SNAKE one goes to the scope's .env). Only timeouts: AGOS picks no helper
    model and no image mode (those are Hermes's, Settings → Helper models)."""
    return {limit.key: str(limit.default) for limit in TIME_LIMITS}
