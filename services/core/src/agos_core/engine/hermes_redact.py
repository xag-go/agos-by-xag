"""Hermes's own secret masking (agent.redact.redact_sensitive_text), for what AGOS
shows from Hermes's sessions (an answer's steps: commands and their results).

Hermes masks what it shows live (its tool previews); its session keeps the raw
call. AGOS shows the session's steps through the same function, run in Hermes's
own runtime: one small helper process, asked line by line. When it can't answer,
nothing is shown rather than the raw text.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import Any

from agos_core.engine.hermes import with_runtime
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

log = logging.getLogger("agos.hermes_redact")

HIDDEN = "(hidden: the engine couldn't check it for secrets)"

_LOOP = (
    "import sys, json\n"
    "from agent.redact import redact_sensitive_text\n"
    "def one(t):\n"
    "    return redact_sensitive_text(t, force=True, redact_url_credentials=True)\n"
    "for line in sys.stdin:\n"
    "    texts = json.loads(line)\n"
    "    sys.stdout.write(json.dumps([one(t) for t in texts]) + '\\n')\n"
    "    sys.stdout.flush()\n"
)


class Redactor:
    # What runs in Hermes's runtime in place of its module (one answer per line).
    LOOP = _LOOP

    def __init__(self, hermes_bin: str, home: str) -> None:
        self.hermes_bin = hermes_bin
        self.home = home
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def _argv(self) -> list[str]:
        out = subprocess.run(  # noqa: S603 - Hermes's documented launcher
            [self.hermes_bin, "--print-runtime-command", "--module", "agos_goal_judge"],
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=with_runtime({"HOME": self.home, "PATH": "/usr/bin:/bin"}),
            check=True,
        ).stdout
        argv: list[str] = json.loads(out)
        run = "runpy.run_module('agos_goal_judge', run_name='__main__', alter_sys=True)"
        if not argv or run not in argv[-1]:
            raise RuntimeError("this install can't run code for AGOS")
        argv[-1] = argv[-1].replace(run, f"exec({self.LOOP!r})")
        return argv

    def _start(self) -> subprocess.Popen[str]:
        if self._proc is None or self._proc.poll() is not None:
            off_loop("hermes redact")
            self._proc = subprocess.Popen(  # noqa: S603 - Hermes's own runtime
                self._argv(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env=with_runtime({"HOME": self.home, "PATH": "/usr/bin:/bin"}),
                start_new_session=True,
            )
        return self._proc

    def running(self) -> bool:
        """Its process is up (asking it then starts nothing)."""
        return self._proc is not None and self._proc.poll() is None

    def warm(self) -> None:
        """Starts Hermes's runtime ahead of the first chat opened (it takes seconds)."""
        self.mask_many(["warm"])

    def mask(self, text: str) -> str:
        return self.mask_many([text])[0]

    def mask_many(self, texts: list[str]) -> list[str]:
        if not any(texts):
            return list(texts)
        out = self.ask(list(texts))
        if out is not None:
            return [str(t) for t in out]
        return [HIDDEN if t else t for t in texts]

    def ask(self, texts: list[str]) -> list[Any] | None:
        """The helper's answer for these texts (one per text), None when it can't."""
        with self._lock:
            for _ in range(2):
                try:
                    proc = self._start()
                    assert proc.stdin is not None and proc.stdout is not None
                    proc.stdin.write(json.dumps(texts) + "\n")
                    proc.stdin.flush()
                    line = proc.stdout.readline()
                    if line:
                        out = json.loads(line)
                        if isinstance(out, list) and len(out) == len(texts):
                            return out
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    log.info("Hermes's masking didn't answer: %s", error)
                if self._proc is not None:
                    self._proc.kill()
                    self._proc = None
        return None


_current: dict[str, Any] = {"redactor": None}


def use(redactor: Any) -> None:
    _current["redactor"] = redactor


def mask(text: str) -> str:
    """Hermes's masking of this text (HIDDEN when Hermes isn't there)."""
    return mask_many([text])[0]


def mask_many(texts: list[str]) -> list[str]:
    redactor = _current["redactor"]
    if redactor is None:
        return [HIDDEN if t else t for t in texts]
    many = getattr(redactor, "mask_many", None)
    if many is None:
        return [str(redactor.mask(t)) for t in texts]
    return [str(t) for t in many(texts)]
