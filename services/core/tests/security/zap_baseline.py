"""The nightly's OWASP ZAP baseline scan of the web (spider + passive rules, no attack).

The web build's standalone server runs in front of the browser tests' light core
(tests/browser/rig.py light_rig: seeded data, no Hermes, nothing real behind it) on
127.0.0.1:9733/9734, and ZAP's automation framework spiders it and runs its passive
rules, like zap-baseline.py. ZAP and a Java runtime are downloaded once into
~/.cache/agos-zap (pinned versions, SHA-256 checked): the nightly runner's account
has no Docker and no sudo. Reports (HTML, JSON) go to --out; a High alert fails the
run, Medium and below are listed in the job summary.

`PYTHONPATH=tests uv run python tests/security/zap_baseline.py --out DIR` from
services/core, after
`pnpm --filter @agos/web build`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from browser.rig import light_rig  # tests/ on sys.path: pytest's rootdir, or PYTHONPATH

__all__ = ["alerts", "main", "plan"]

CACHE = Path.home() / ".cache" / "agos-zap"
ZAP = (
    "https://github.com/zaproxy/zaproxy/releases/download/v2.17.0/ZAP_2.17.0_Crossplatform.zip",
    "94c8f767b1c2e94f0db66b3ae56514d5e3f5a728ee1b6c798e0c8fe2d61fbff0",
)
JRE = (
    "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/"
    "OpenJDK21U-jre_x64_linux_hotspot_21.0.13_9.tar.gz",
    "a535a1df9c6284d9618872984e026ae0352d1f7e9e0605425c0e6114f47351dd",
)
PORTS = "9733,9734"
HIGH = 3  # ZAP's riskcode: 0 info, 1 low, 2 medium, 3 high


def _fetch(url: str, sha256: str, to: Path) -> Path:
    if to.is_file() and hashlib.sha256(to.read_bytes()).hexdigest() == sha256:
        return to
    to.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as answer:  # noqa: S310 - pinned https URL
        to.write_bytes(answer.read())
    got = hashlib.sha256(to.read_bytes()).hexdigest()
    if got != sha256:
        to.unlink()
        raise RuntimeError(f"{url}: SHA-256 {got}, expected {sha256}")
    return to


def install(cache: Path = CACHE) -> tuple[Path, Path]:
    """(zap.sh, the Java home), downloaded and unpacked once."""
    zap_dir, jre_dir = cache / "zap", cache / "jre"
    if not (zap_dir / "zap.sh").is_file():
        archive = _fetch(*ZAP, cache / "zap.zip")
        shutil.rmtree(zap_dir, ignore_errors=True)
        with zipfile.ZipFile(archive) as z:
            if any(n.startswith("/") or ".." in Path(n).parts for n in z.namelist()):
                raise RuntimeError(f"{archive}: a member outside the folder")
            z.extractall(cache / "zap-unpack")  # noqa: S202 - pinned archive, members checked
        (inner,) = (cache / "zap-unpack").iterdir()
        inner.rename(zap_dir)
        (cache / "zap-unpack").rmdir()
        (zap_dir / "zap.sh").chmod(0o755)
    if not (jre_dir / "bin" / "java").is_file():
        archive = _fetch(*JRE, cache / "jre.tar.gz")
        shutil.rmtree(jre_dir, ignore_errors=True)
        with tarfile.open(archive) as t:
            t.extractall(cache / "jre-unpack", filter="data")
        (inner,) = (cache / "jre-unpack").iterdir()
        inner.rename(jre_dir)
        (cache / "jre-unpack").rmdir()
    return zap_dir / "zap.sh", jre_dir


def plan(target: str, out: Path) -> dict[str, Any]:
    """ZAP's automation plan: the baseline scan (spider, passive rules, reports)."""
    return {
        "env": {
            "contexts": [{"name": "agos-web", "urls": [target], "includePaths": [f"{target}.*"]}],
            "parameters": {"failOnError": True, "progressToStdout": True},
        },
        "jobs": [
            {"type": "passiveScan-config", "parameters": {"maxAlertsPerRule": 10}},
            {"type": "spider", "parameters": {"context": "agos-web", "maxDuration": 5}},
            {"type": "passiveScan-wait", "parameters": {"maxDuration": 5}},
            {
                "type": "report",
                "parameters": {
                    "template": "traditional-json",
                    "reportDir": str(out),
                    "reportFile": "zap.json",
                },
            },
            {
                "type": "report",
                "parameters": {
                    "template": "traditional-html",
                    "reportDir": str(out),
                    "reportFile": "zap.html",
                },
            },
        ],
    }


def alerts(report: dict[str, Any]) -> list[tuple[int, str, int]]:
    """(riskcode, alert name, number of URLs) of a traditional-json report, worst first."""
    found = [
        (int(a.get("riskcode", 0)), str(a.get("name", "")), len(a.get("instances", [])))
        for site in report.get("site", [])
        for a in site.get("alerts", [])
    ]
    return sorted(found, key=lambda a: (-a[0], a[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    zap, java_home = install()
    os.environ.setdefault("AGOS_BROWSER_PORTS", PORTS)
    os.environ.setdefault("AGOS_BROWSER_OUT", str(out / "rig"))
    with light_rig() as rig:
        plan_file = out / "zap-plan.json"
        plan_file.write_text(json.dumps(plan(rig.web, out), indent=2))
        env = dict(os.environ, JAVA_HOME=str(java_home))
        env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        done = subprocess.run(  # noqa: S603 - the pinned ZAP install
            [str(zap), "-cmd", "-dir", str(out / "zap-home"), "-Xmx1g", "-autorun", str(plan_file)],
            env=env,
            check=False,
        )
    found = alerts(json.loads((out / "zap.json").read_text()))
    for risk, name, count in found:
        print(f"{['info', 'low', 'medium', 'high'][min(risk, 3)]:6} {name} ({count} URLs)")
    high = [a for a in found if a[0] >= HIGH]
    return 1 if high or done.returncode not in (0, 2) else 0  # 2: ZAP's "warnings"


if __name__ == "__main__":
    raise SystemExit(main())
