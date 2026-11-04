"""Hermes's host-side check of the sandbox's /workspace is not logged as a warning."""

import logging

from agos_core.hermes_plugin import agos_guard


def _record(label: str, path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "agent.runtime_cwd",
        logging.WARNING,
        __file__,
        1,
        "%s does not exist: %s",
        (label, path),
        None,
    )


def test_only_the_sandbox_folder_is_quiet() -> None:
    note = agos_guard.SandboxCwdNote()
    assert note.filter(_record("TERMINAL_CWD", "/workspace")) is False
    assert note.filter(_record("TERMINAL_CWD", "/workspace/project")) is False
    assert note.filter(_record("TERMINAL_CWD", "/home/x/gone")) is True
    assert note.filter(_record("configured working directory", "/workspace")) is True
    agos_guard._quiet_sandbox_cwd()
    agos_guard._quiet_sandbox_cwd()
    filters = logging.getLogger("agent.runtime_cwd").filters
    assert sum(isinstance(f, agos_guard.SandboxCwdNote) for f in filters) == 1
