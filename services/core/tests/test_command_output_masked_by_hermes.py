"""P9 (925047d area 1): a failed Hermes command's output is masked by Hermes's own
redaction (agent/redact.py redact_sensitive_text through engine/hermes_redact.py),
not by AGOS's regex list, and its stderr too."""

import logging
import sys
from pathlib import Path

import pytest

from agos_core.engine import hermes_redact
from agos_core.engine.hermes import EngineError, SubprocessRunner


class _Hermes:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def mask_many(self, texts: list[str]) -> list[str]:
        self.asked += texts
        return [t.replace("opaque-credential-77", "***") for t in texts]


def test_a_failed_commands_output_is_masked_by_hermes(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    hermes = _Hermes()
    hermes_redact.use(hermes)
    script = tmp_path / "fails.py"
    script.write_text(
        "import sys\nprint('out opaque-credential-77')\n"
        "print('err opaque-credential-77', file=sys.stderr)\nsys.exit(3)\n"
    )
    try:
        with caplog.at_level(logging.INFO, logger="agos.engine"), pytest.raises(EngineError):
            SubprocessRunner().run([sys.executable, str(script)], timeout=30)
    finally:
        hermes_redact.use(None)
    text = caplog.text
    assert "opaque-credential-77" not in text
    assert "out ***" in text and "err ***" in text
    assert any("out opaque" in a for a in hermes.asked)
    assert any("err opaque" in a for a in hermes.asked)


def test_without_hermes_nothing_of_the_output_is_logged(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    hermes_redact.use(None)
    script = tmp_path / "fails.py"
    script.write_text("print('opaque-credential-77')\nraise SystemExit(1)\n")
    with caplog.at_level(logging.INFO, logger="agos.engine"), pytest.raises(EngineError):
        SubprocessRunner().run([sys.executable, str(script)], timeout=30)
    assert "opaque-credential-77" not in caplog.text and hermes_redact.HIDDEN in caplog.text
