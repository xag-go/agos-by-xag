"""The workspace sandbox image (docker/sandbox/Dockerfile) keeps an agent's basics."""

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[3] / "docker" / "sandbox" / "Dockerfile"


def test_pip_install_user_works_for_the_unprivileged_agent() -> None:
    """Ops VM: `pip install --user requests` in the sandbox was refused by Debian's
    PEP 668 marker (externally-managed-environment), though the egress proxy let it
    through. The terminal is the unprivileged `agent`: pip can only write its own
    ~/.local, so allowing it breaks no system package."""
    text = DOCKERFILE.read_text()
    assert "PIP_BREAK_SYSTEM_PACKAGES=1" in text
    users = [ln.split()[1] for ln in text.splitlines() if ln.startswith("USER ")]
    assert users and users[-1] == "agent"
