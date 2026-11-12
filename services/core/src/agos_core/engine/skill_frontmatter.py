"""SKILL.md frontmatter, read by Hermes's own reader.

Hermes reads a skill's `---` block with agent/skill_utils.py `parse_frontmatter`
(YAML, so a folded `description: >-` is one text; malformed YAML falls back to
`key: value` lines). AGOS shows what Hermes reads, so it asks that same function,
run with Hermes's Python, instead of reading the block itself. Many texts go in
one call; answers are kept by the text's hash (a SKILL.md is read often).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import threading
from typing import Any

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python
from agos_core.engine.waits import hermes_wait

log = logging.getLogger("agos.skill_frontmatter")

_READ = """
import json, sys
from agent.skill_utils import parse_frontmatter
out = []
for text in json.load(sys.stdin):
    head, body = parse_frontmatter(text)
    flat = {str(k): str(v) for k, v in (head or {}).items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    out.append([flat, body])
sys.stdout.write(json.dumps(out))
"""

_KEEP = 2000


class HermesFrontmatter:
    """Callable: texts -> [(frontmatter, body)] as Hermes reads them."""

    def __init__(self, engine: EngineConfig) -> None:
        self.engine = engine
        self._seen: dict[str, tuple[dict[str, str], str]] = {}
        self._lock = threading.Lock()

    def __call__(self, texts: list[str]) -> list[tuple[dict[str, str], str]]:
        keys = [hashlib.sha256(t.encode("utf-8", "replace")).hexdigest() for t in texts]
        with self._lock:
            missing = [(k, t) for k, t in zip(keys, texts, strict=True) if k not in self._seen]
        if missing:
            answers = self._ask([t for _k, t in missing])
            with self._lock:
                if len(self._seen) > _KEEP:
                    self._seen.clear()
                for (key, _t), answer in zip(missing, answers, strict=True):
                    self._seen[key] = answer
        with self._lock:
            return [self._seen[k] for k in keys]

    def _ask(self, texts: list[str]) -> list[tuple[dict[str, str], str]]:
        off_loop("hermes skill frontmatter")
        done = subprocess.run(  # noqa: S603 - Hermes's Python, fixed script; texts on stdin
            [hermes_python(self.engine), "-c", _READ],
            input=json.dumps(texts),
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env={
                "HOME": str(self.engine.host_home),
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "HERMES_HOME": str(self.engine.hermes_home),
                **self.engine.runtime_env(),
            },
            check=False,
        )
        hermes_contract.ran(done)
        if done.returncode != 0:
            raise RuntimeError(f"The engine did not read the skill: {done.stderr.strip()[-300:]}")
        rows: Any = json.loads(done.stdout)
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise RuntimeError("The engine answered something else.")
        return [(dict(row[0]), str(row[1])) for row in rows]
