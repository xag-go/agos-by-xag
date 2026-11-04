"""The agent evals' scores (tests/evals/run.py): pure, no rig.

    from scoring import Scenario
    s = Scenario("tainted turn asks before power")
    s.check("an Allow / Deny card waits", asked, detail)
    report = Report([s], tokens=1200, budget=200000)
    report.json() / report.markdown()

A scenario's score is its passed checks over its checks; the run's score is every
passed check over every check (so a scenario with more checks weighs more), and the
run passes when that score reaches `min_score` and the tokens stay in the budget.

Owns: checks, scores, the report (JSON for the trend, Markdown for the job summary).
Must not: talk to the rig or Hermes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Check", "Report", "Scenario"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Scenario:
    name: str
    checks: list[Check] = field(default_factory=list)
    seconds: float = 0.0
    error: str = ""

    def check(self, name: str, ok: object, detail: str = "") -> bool:
        passed = bool(ok)
        self.checks.append(Check(name, passed, detail[:500]))
        print(("PASS" if passed else "FAIL"), f"[{self.name}]", name, detail[:200], flush=True)
        return passed

    def fail(self, error: str) -> None:
        """The scenario stopped early (a timeout, the rig broke): it scores 0."""
        self.error = error[:500]
        if not self.checks:
            self.checks.append(Check("ran to the end", False, self.error))

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.checks)

    @property
    def score(self) -> float:
        if self.error:
            return 0.0
        return self.passed / len(self.checks) if self.checks else 0.0


@dataclass
class Report:
    scenarios: list[Scenario]
    tokens: int = 0
    budget: int = 0
    min_score: float = 1.0
    at: float = field(default_factory=time.time)
    commit: str = ""

    @property
    def score(self) -> float:
        total = sum(len(s.checks) for s in self.scenarios)
        if not total:
            return 0.0
        return sum(s.passed for s in self.scenarios if not s.error) / total

    @property
    def over_budget(self) -> bool:
        return bool(self.budget) and self.tokens > self.budget

    @property
    def ok(self) -> bool:
        return bool(self.scenarios) and self.score >= self.min_score and not self.over_budget

    def json(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "commit": self.commit,
            "score": round(self.score, 4),
            "ok": self.ok,
            "tokens": self.tokens,
            "budget": self.budget,
            "minScore": self.min_score,
            "scenarios": [
                {
                    "name": s.name,
                    "score": round(s.score, 4),
                    "passed": s.passed,
                    "checks": len(s.checks),
                    "seconds": round(s.seconds, 1),
                    "error": s.error,
                    "results": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in s.checks],
                }
                for s in self.scenarios
            ],
        }

    def dumps(self) -> str:
        return json.dumps(self.json(), indent=1, ensure_ascii=False) + "\n"

    def markdown(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        lines = [
            f"### Agent evals: {head}, score {self.score:.0%}"
            + (f" (min {self.min_score:.0%})" if self.min_score < 1 else ""),
            "",
            f"Tokens: {self.tokens}"
            + (f" of {self.budget}" if self.budget else "")
            + (" — OVER BUDGET" if self.over_budget else ""),
            "",
            "| Scenario | Score | Checks | Seconds |",
            "| --- | --- | --- | --- |",
        ]
        for s in self.scenarios:
            lines.append(
                f"| {s.name} | {s.score:.0%} | {s.passed}/{len(s.checks)} | {s.seconds:.0f} |"
            )
        failed = [(s, c) for s in self.scenarios for c in s.checks if not c.ok]
        if failed:
            lines += ["", "Failed checks:", ""]
            lines += [
                f"- {s.name}: {c.name}" + (f" ({c.detail[:160]})" if c.detail else "")
                for s, c in failed
            ]
        return "\n".join(lines) + "\n"
