"""Webhook routes in Hermes's own subscription store: filters and enabled, written
with Hermes's own helper in its runtime (no CLI has them).

Owns: Reading and replacing a home's webhook routes.

Must not: Deliver a webhook or decide its signing secret (actions/).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import inspect
import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any

from agos_core.engine import hermes_contract
from agos_core.engine.hermes.runtime_env import JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_WEBHOOK_ROUTES",
    "apply_webhook_routes",
    "webhook_routes",
]


def apply_webhook_routes(subscriptions: dict[str, Any], job: dict[str, Any]) -> None:
    """AGOS's change to Hermes's webhook routes: the routes whose name starts with
    one of `drop` go (unless put again), the routes in `put` are written whole.
    Runs inside Hermes's own store update (under its lock); stdlib only."""
    put = job.get("put") or {}
    for name in list(subscriptions):
        if name not in put and any(name.startswith(p) for p in job.get("drop") or []):
            del subscriptions[name]
    subscriptions.update(put)


# Hermes's webhook routes are its subscription store (webhook_subscriptions.json).
# Hermes's own update locks it (.webhook_subscriptions.lock), re-reads it, changes
# it and publishes it atomically (hermes_cli/webhook.py _mutate_subscriptions).
_WEBHOOK_ROUTES = r"""
import json
from typing import Any
from hermes_cli.webhook import _mutate_subscriptions
@APPLY@
job = json.loads(@JOB@)
_mutate_subscriptions(lambda subscriptions: apply_webhook_routes(subscriptions, job))
print("AGOS-WEBHOOKS ok")
"""


def webhook_routes(
    self: "HermesEngine", workspace_id: str, put: dict[str, dict[str, Any]], drop: list[str]
) -> None:
    """Writes AGOS's routes into the workspace's Hermes webhook routes with
    Hermes's own store update, in Hermes's runtime (see apply_webhook_routes)."""
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    script = _WEBHOOK_ROUTES.replace("@APPLY@", inspect.getsource(apply_webhook_routes)).replace(
        "@JOB@", repr(json.dumps({"put": put, "drop": drop}))
    )
    env = child_env({**self._env(), "HERMES_HOME": str(self.profile_home(workspace_id))})
    off_loop("hermes webhook routes")
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=env,
            check=False,
            start_new_session=True,
        )
        hermes_contract.ran(done)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineError("Hermes did not take the webhook change") from error
    if done.returncode != 0 or "AGOS-WEBHOOKS ok" not in done.stdout:
        log.info("webhook routes not written (%s): %s", done.returncode, done.stderr[-500:])
        raise EngineError("Hermes did not take the webhook change")
