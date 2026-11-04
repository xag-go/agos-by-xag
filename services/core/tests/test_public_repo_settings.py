"""scripts/public-repo-settings.sh: the public repository's safety settings via gh api.

- the required checks are exactly the job names of .github/workflows/ci.yml and security.yml;
- a dry run (the default) calls nothing; --apply makes every call, refuses a private
  repository, and updates the tag ruleset in place when it already exists;
- shellcheck clean.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "public-repo-settings.sh"
GATES = [REPO / ".github" / "workflows" / name for name in ("ci.yml", "security.yml")]

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="no jq here")

FAKE_GH = """#!/usr/bin/env bash
# Records each call (args + body) and answers the two reads the script makes.
{ printf '%s\\n' "$*"; if [[ " $* " == *" --input - "* ]]; then cat; echo; fi; } >> "$GH_LOG"
case "$*" in
  *"--jq .visibility"*) echo "${FAKE_VISIBILITY:-public}" ;;
  *"/rulesets --jq"*) echo "${FAKE_RULESET_ID:-}" ;;
esac
"""


def _run(tmp_path: Path, *args: str, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    done = subprocess.run(  # noqa: S603
        ["/bin/bash", str(SCRIPT), "--repo", "someone/agos-public", *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "GH_LOG": str(log),
            **env,
        },
    )
    return done, log.read_text()


def _ci_job_names() -> list[str]:
    names = []
    for gate in GATES:
        flow = yaml.safe_load(gate.read_text())
        assert "pull_request" in flow.get("on", flow.get(True)), gate.name
        names += [job["name"] for job in flow["jobs"].values()]
    return names


def test_the_required_checks_are_the_ci_jobs_names(tmp_path: Path) -> None:
    done, _ = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    start = done.stdout.index("/branches/main/protection")
    body = done.stdout[done.stdout.index("{", start) : done.stdout.index("gh api", start + 1)]
    protection = json.loads(body)
    checks = protection["required_status_checks"]["checks"]
    assert sorted(c["context"] for c in checks) == sorted(_ci_job_names())
    assert {c["app_id"] for c in checks} == {15368}  # GitHub Actions only
    assert protection["allow_force_pushes"] is False
    assert protection["allow_deletions"] is False
    assert protection["required_pull_request_reviews"]["required_approving_review_count"] >= 1


def test_a_dry_run_calls_nothing(tmp_path: Path) -> None:
    done, log = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    assert log == ""
    assert "nothing changed" in done.stdout
    for path in ("/vulnerability-alerts", "/private-vulnerability-reporting"):
        assert f"PUT repos/someone/agos-public{path}" in done.stdout
    # Alerts only: the export gets no Dependabot PRs (they run in the development repo).
    assert "DELETE repos/someone/agos-public/automated-security-fixes" in done.stdout
    assert '"dependabot_security_updates": {\n' in done.stdout
    assert '"status": "disabled"' in done.stdout
    assert "POST repos/someone/agos-public/rulesets" in done.stdout
    assert '"has_wiki": false' in done.stdout and '"has_issues": true' in done.stdout
    assert '"has_discussions": false' in done.stdout


def test_apply_makes_every_call(tmp_path: Path) -> None:
    done, log = _run(tmp_path, "--apply", "--discussions")
    assert done.returncode == 0, done.stderr
    for call in (
        "-X PATCH repos/someone/agos-public",
        "-X PUT repos/someone/agos-public/vulnerability-alerts",
        "-X DELETE repos/someone/agos-public/automated-security-fixes",
        "-X PUT repos/someone/agos-public/private-vulnerability-reporting",
        "-X PUT repos/someone/agos-public/branches/main/protection",
        "-X POST repos/someone/agos-public/rulesets",
    ):
        assert call in log, call
    assert '"has_discussions": true' in log
    assert '"secret_scanning_push_protection"' in log
    assert '"refs/tags/v*"' in log


def test_apply_updates_the_tag_ruleset_in_place(tmp_path: Path) -> None:
    done, log = _run(tmp_path, "--apply", FAKE_RULESET_ID="42")
    assert done.returncode == 0, done.stderr
    assert "-X PUT repos/someone/agos-public/rulesets/42" in log
    assert "-X POST repos/someone/agos-public/rulesets" not in log


def test_apply_refuses_a_private_repository(tmp_path: Path) -> None:
    done, log = _run(tmp_path, "--apply", FAKE_VISIBILITY="private")
    assert done.returncode != 0
    assert "private" in done.stderr
    assert "-X " not in log


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck here")
def test_shellcheck_is_clean() -> None:
    done = subprocess.run(  # noqa: S603
        [str(shutil.which("shellcheck")), "-S", "style", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout
