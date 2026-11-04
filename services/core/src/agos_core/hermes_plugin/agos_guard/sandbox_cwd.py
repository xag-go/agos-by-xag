"""Hermes's "TERMINAL_CWD does not exist: /workspace" warning, quieted (moved out of
agos_guard/__init__.py, which re-exports both names)."""

from __future__ import annotations

import logging


class SandboxCwdNote(logging.Filter):
    """Drops Hermes's "TERMINAL_CWD does not exist: /workspace" warning. AGOS's
    profiles run the terminal in a docker sandbox whose working folder is
    /workspace INSIDE the container; Hermes checks that path on the host
    (agent/runtime_cwd.py `_existing_dir`), where it never exists. Hermes's own
    docstring says container paths may not exist on the host, and with a docker
    backend the path only feeds context-file discovery (the prompt's host cwd line
    is for a local terminal only: agent/prompt_builder.py). Any other missing
    folder is still logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if record.msg != "%s does not exist: %s" or len(args) != 2:
            return True
        label, path = str(args[0]), str(args[1])
        in_sandbox = path == "/workspace" or path.startswith("/workspace/")
        return not (label == "TERMINAL_CWD" and in_sandbox)


def quiet() -> None:
    target = logging.getLogger("agent.runtime_cwd")
    if not any(isinstance(f, SandboxCwdNote) for f in target.filters):
        target.addFilter(SandboxCwdNote())
