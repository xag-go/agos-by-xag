"""The nightly scan drivers' pure parts: ZAP's plan and report reading (the scans
themselves run in the nightly only: tests/security/zap_baseline.py, test_api_fuzz.py)."""

from pathlib import Path

from security import zap_baseline


def test_the_zap_plan_is_a_baseline_scan_of_the_web_only(tmp_path: Path) -> None:
    plan = zap_baseline.plan("http://127.0.0.1:9734", tmp_path)
    kinds = [job["type"] for job in plan["jobs"]]
    assert kinds == ["passiveScan-config", "spider", "passiveScan-wait", "report", "report"]
    assert not any("activeScan" in kind for kind in kinds)  # passive rules only, no attack
    (context,) = plan["env"]["contexts"]
    assert context["urls"] == ["http://127.0.0.1:9734"]
    assert context["includePaths"] == ["http://127.0.0.1:9734.*"]
    reports = {job["parameters"]["reportFile"] for job in plan["jobs"] if job["type"] == "report"}
    assert reports == {"zap.json", "zap.html"}


def test_alerts_are_read_worst_first() -> None:
    report = {
        "site": [
            {
                "alerts": [
                    {"riskcode": "1", "name": "Cookie without SameSite", "instances": [{}]},
                    {"riskcode": "3", "name": "SQL Injection", "instances": [{}, {}]},
                    {"riskcode": "2", "name": "CSP not set", "instances": []},
                ]
            }
        ]
    }
    assert zap_baseline.alerts(report) == [
        (3, "SQL Injection", 2),
        (2, "CSP not set", 0),
        (1, "Cookie without SameSite", 1),
    ]
    assert zap_baseline.alerts({}) == []


def test_downloads_are_pinned_by_sha256() -> None:
    for url, sha in (zap_baseline.ZAP, zap_baseline.JRE):
        assert url.startswith("https://github.com/")
        assert len(sha) == 64 and int(sha, 16) >= 0
