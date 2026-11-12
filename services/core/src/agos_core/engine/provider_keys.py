"""API keys added from the app (Settings → Models → API key).

The key is tested first with Hermes's own probe, then handed to Hermes on stdin
(never argv, never logged) and saved by Hermes's own credential save under Hermes's
own variable for the provider (its registry, read with the model catalog). AGOS
keeps nothing: the last four characters are read from Hermes's `.env`, and how the
key did when Hermes last used it from Hermes's credential pool (engine/key_status.py).

- Test: Hermes's dashboard probe, the one its "Save" runs before a key is kept
  (H: hermes_cli/web_routers/config_env.py `validate_provider_credential` over
  `_CREDENTIAL_PROBES`: OpenRouter, OpenAI, xAI, Gemini). That table has no
  Anthropic row, so a Claude key goes through `hermes doctor`'s own Anthropic
  probe (H: hermes_cli/doctor_connectivity.py `_probe_anthropic`). Both run in
  Hermes's runtime in an empty throwaway home, so the saved key never answers for
  the new one.
- Save / remove: Hermes's credential lifecycle (H: hermes_cli/credential_lifecycle.py
  `save_provider_env_credential` / `remove_provider_env_credential`), the path
  `hermes config set` and the dashboard take. It writes `.env`, rotates any
  config.yaml copy of the old value, and puts the key into the credential pool in
  `auth.json`, which the runtime reads. A write to `.env` alone left env-backed
  providers 401'ing.
"""

import json
import subprocess
from dataclasses import dataclass

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python
from agos_core.engine.waits import hermes_wait

_SAVE = """
import sys
from hermes_cli.credential_lifecycle import save_provider_env_credential
key = sys.stdin.read().strip()
if not key:
    sys.exit(2)
save_provider_env_credential(sys.argv[1], key)
print("ok")
"""

_REMOVE = """
import sys
from hermes_cli.credential_lifecycle import remove_provider_env_credential
remove_provider_env_credential(sys.argv[1])
print("ok")
"""

_READ = """
import sys
from hermes_cli.config import get_env_value
sys.stdout.write(get_env_value(sys.argv[1]) or "")
"""

# Hermes's own pre-save probe of a key (see the module doc), in a throwaway home.
_PROBE = r"""
import asyncio, json, os, shutil, sys, tempfile
name = sys.argv[1]
value = sys.stdin.read().strip()
home = tempfile.mkdtemp(prefix="agos-key-probe-")
os.environ["HERMES_HOME"] = home
try:
    if name == "ANTHROPIC_API_KEY":
        os.environ[name] = value
        from hermes_cli.doctor_connectivity import _probe_anthropic
        found = _probe_anthropic()
        mark = " ".join(str(x) for x in (found.lines[0] if found.lines else ()))
        status = "ok" if "✓" in mark else "fail" if "✗" in mark else "unknown"
        out = {"ok": status == "ok", "reachable": status != "unknown", "message": "", "probed": True}
    else:
        from types import SimpleNamespace as NS
        from hermes_cli.web_models import EnvVarUpdate
        from hermes_cli.web_routers.config_env import _CREDENTIAL_PROBES, validate_provider_credential
        if name not in _CREDENTIAL_PROBES:
            out = {"ok": True, "reachable": False, "message": "", "probed": False}
        else:
            # The dashboard's own route, called in-process (its token check
            # passes for a signed-in session).
            request = NS(app=NS(state=NS(auth_required=True)), state=NS(session=object()))
            out = dict(asyncio.run(
                validate_provider_credential(EnvVarUpdate(key=name, value=value), request)))
            out["probed"] = True
finally:
    shutil.rmtree(home, ignore_errors=True)
print("AGOS-PROBE " + json.dumps(out))
"""


# What a ProviderKeys call raises when Hermes did not do it (no answer, a crash, too
# slow): callers say "Hermes did not ..." for these.
CALL_FAILED: tuple[type[Exception], ...] = (OSError, RuntimeError, subprocess.TimeoutExpired)


class KeyProblem(ValueError):
    """Something the owner can fix (wrong key, unknown provider)."""


@dataclass(frozen=True)
class KeyCheck:
    ok: bool
    message: str


def verdict(answer: dict[str, object]) -> "KeyCheck | None":
    """What Hermes's probe said, in the owner's words. None: Hermes has no probe for
    this key (it can't be tested before it is saved)."""
    if not answer.get("probed", True):
        return None
    if answer.get("ok"):
        return KeyCheck(True, "Key works.")
    if not answer.get("reachable"):
        return KeyCheck(False, "Couldn't reach the provider to test the key. Try again.")
    said = str(answer.get("message") or "").strip()
    return KeyCheck(False, said or "The provider refused this key. Check it and paste it again.")


def clean_key(key: str) -> str:
    key = key.strip()
    if not key or len(key) > 500 or any(c.isspace() for c in key):
        raise KeyProblem("Paste the key exactly as the provider shows it, with no spaces.")
    return key


class ProviderKeys:
    def __init__(self, engine: EngineConfig) -> None:
        self.engine = engine

    def _env(self) -> dict[str, str]:
        return {
            "HOME": str(self.engine.host_home),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            **self.engine.runtime_env(),
        }

    def _hermes(self, script: str, name: str, stdin: str = "") -> str:
        off_loop("hermes provider keys")
        result = subprocess.run(  # noqa: S603 - fixed argv; the key goes on stdin
            [hermes_python(self.engine), "-c", script, name],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=self._env(),
            check=False,
        )
        hermes_contract.ran(result)
        if result.returncode != 0:
            raise RuntimeError("The engine did not save the change.")
        return result.stdout

    def probe(self, name: str, key: str) -> KeyCheck | None:
        """Hermes's own test of a key for its variable `name` (None: Hermes has no
        probe for it)."""
        out = self._hermes(_PROBE, _checked_env(name), stdin=key)
        line = next((ln for ln in out.splitlines() if ln.startswith("AGOS-PROBE ")), "")
        try:
            answer = json.loads(line[len("AGOS-PROBE ") :])
        except ValueError as error:
            raise RuntimeError("The engine did not test the key.") from error
        return verdict(answer if isinstance(answer, dict) else {})

    def check(self, name: str, key: str) -> KeyCheck:
        """A key for Hermes's variable `name` (its registry's), tested by Hermes."""
        found = self.probe(name, key)
        return found or KeyCheck(True, "Key saved (there is no test for it).")

    def save_env(self, name: str, key: str) -> None:
        """A provider's key, under Hermes's own variable for it."""
        self._hermes(_SAVE, _checked_env(name), stdin=key)

    def remove_env(self, name: str) -> None:
        self._hermes(_REMOVE, _checked_env(name))

    def stored(self, name: str) -> str:
        return self._hermes(_READ, _checked_env(name)).strip()


def _checked_env(name: str) -> str:
    import re

    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", name):
        raise KeyProblem("This provider takes no API key here.")
    return name
