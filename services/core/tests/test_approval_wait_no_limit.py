"""An approval the owner answers while Full access is on used to wait inside
Hermes's pre_tool_call hook, which Hermes cuts after `plugins.hook_callback_timeout`
(30 s by default): his tap a minute later found "Approval expired". 925047d set the
key to 0, which switched Hermes's hang guard off for EVERY plugin hook. Now
agos-guard asks him in its tool_execution middleware (no timeout in Hermes), so his
wait keeps no limit while the hook guard is back at Hermes's own cap."""

from agos_core.engine import time_limits


def test_his_wait_has_no_limit_and_the_hook_guard_is_hermess_cap() -> None:
    limits = {t.key: t for t in time_limits.TIME_LIMITS}
    assert limits["approvals.timeout"].default == time_limits.HERMES_MAX_SECONDS
    hook = limits["plugins.hook_callback_timeout"]
    assert hook.zero_is_no_limit  # Hermes: <= 0 = no timeout (the owner may still pick it)
    assert hook.default == time_limits.HOOK_GUARD_SECONDS == 600
    assert time_limits.owner_defaults()["plugins.hook_callback_timeout"] == "600"
