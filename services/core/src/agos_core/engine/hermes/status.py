"""A root's gateway as Hermes reports it: its status (control socket first, then
Hermes's own reader), the lamps' verdicts, pairing, and Hermes's own usage
analytics.

Owns: Read-only gateway verdicts and their caches.

Must not: Start, stop or restart a gateway (gateway_run.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import copy
import json
import logging
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import read_cache
from agos_core.engine.hermes.stamps import _gateway_files
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "GATEWAY_SOCKET",
    "GATEWAY_SOCKET_POINTER",
    "GATEWAY_SOCKET_PROTOCOL",
    "GATEWAY_SOCKET_WAIT_S",
    "_GATEWAY_SOCKET_MAX",
    "_GATEWAY_STATUS",
    "_PAIRED",
    "_SOCKET_ONLY",
    "_USAGE",
    "_gateway_up",
    "_gw_ask",
    "_gw_behind",
    "_gw_mark",
    "_gw_socket",
    "_wait_gone",
    "gateway_shown",
    "gateway_socket_status",
    "gateway_status",
    "hermes_usage",
    "pairing_approved",
]


# Run in Hermes's runtime by hermes_usage, with HERMES_HOME = the workspace's root:
# Hermes's own counts of the root (profile None) and each member (by name), summed,
# each over Hermes's read-only SessionDB of that profile. The headline and the
# per-model lines are Hermes's /insights count (agent/insights.py
# InsightsEngine.generate: per model, auxiliary usage included, every token the
# provider was sent or gave: input, prompt-cache reads and writes, output; on Claude
# the cached part is most of every prompt), so the lines add up to the headline. The
# bars are the dashboard's daily series (hermes_cli/web_routers/analytics.py
# _get_usage_analytics, GET /api/analytics/usage): input + cache reads + output per
# local day (Hermes keeps no daily count of cache writes). A profile whose state.db
# isn't there yet is skipped (a read-only open would create one).
_USAGE = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from agent.insights import InsightsEngine
from hermes_cli.web_routers.analytics import _get_usage_analytics
from hermes_cli.web_server_sessions import _open_session_db_for_profile
job = json.loads(@JOB@)
models, days = {}, {}
for profile, home in job["profiles"]:
    if not (Path(home) / "state.db").is_file():
        continue
    db = _open_session_db_for_profile(profile, read_only=True)
    try:
        report = InsightsEngine(db).generate(days=job["month_days"])
    finally:
        db.close()
    for m in report.get("models") or []:
        acc = models.setdefault(str(m.get("model") or "unknown"),
                                {"tokens": 0, "calls": 0, "input": 0, "output": 0, "cached": 0})
        acc["input"] += int(m.get("input_tokens") or 0)
        acc["output"] += int(m.get("output_tokens") or 0)
        acc["cached"] += int(m.get("cache_read_tokens") or 0) + int(m.get("cache_write_tokens") or 0)
        acc["tokens"] += int(m.get("total_tokens") or 0)
        acc["calls"] += int(m.get("api_calls") or 0)
    for d in _get_usage_analytics(job["chart_days"], profile)["daily"]:
        acc = days.setdefault(str(d.get("day")), {"tokens": 0, "calls": 0})
        acc["tokens"] += sum(int(d.get(k) or 0) for k in ("input_tokens", "cache_read_tokens", "output_tokens"))
        acc["calls"] += int(d.get("api_calls") or 0)
print("AGOS-USAGE " + json.dumps({"models": models, "days": days}))
"""

# Run in Hermes's runtime by pairing_approved: Hermes's own public pairing check in
# a root (gateway/pairing.py PairingStore.is_approved, its id matching included).
_PAIRED = r"""
import json, logging, sys
logging.disable(logging.CRITICAL)
from gateway.pairing import PairingStore
job = json.loads(@JOB@)
print("AGOS-PAIRED " + json.dumps(bool(PairingStore().is_approved(job["platform"], job["user"]))))
"""

# Run in Hermes's runtime by gateway_status: Hermes's own verdict on a home's
# gateway (gateway/status.py): the running pid (lock held and pid file checked
# against the live process, nothing cleaned up), the runtime snapshot, whether its
# pid is live (with Hermes's start-time guard against a reused pid) and whether
# the snapshot is stale (no heartbeat for 120 s).
_GATEWAY_STATUS = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from gateway.status import (
    get_running_pid, read_runtime_status, runtime_status_is_stale, runtime_status_pid_is_live,
)
home = Path(@HOME@)
record = read_runtime_status(home / "gateway_state.json")
record = record if isinstance(record, dict) else None
print("AGOS-GW " + json.dumps({
    "pid": get_running_pid(home / "gateway.pid", cleanup_stale=False),
    "record": record,
    "live": bool(runtime_status_pid_is_live(record)) if record else False,
    "stale": bool(runtime_status_is_stale(record)),
}, default=str))
"""

# Hermes's gateway control socket (gateway/control_socket.py, protocol 1): a running
# gateway answers `status` itself (its live runtime status and the pid answering),
# one JSON line in, one out, then it closes. Hermes's contract: a gateway that
# answers IS live; consumers prefer the socket and fall back to the state files.
# A lamp asks it first, so no Hermes runtime start (~0.7 s per root) while it answers.
GATEWAY_SOCKET = "gateway.sock"
GATEWAY_SOCKET_POINTER = "gateway.sock.path"  # a home too deep for sun_path
GATEWAY_SOCKET_PROTOCOL = 1
GATEWAY_SOCKET_WAIT_S = 0.3
_GATEWAY_SOCKET_MAX = 512 * 1024  # Hermes's own answer cap (_MAX_RESPONSE_BYTES)
_SOCKET_ONLY = ("protocol", "answered_at", "answering_pid")  # what it adds to the record


def gateway_socket_status(home: Path) -> dict[str, Any] | None:
    """The `status` answer of the gateway serving `home` (Hermes's own client:
    query_gateway_control), or None: no socket, no answer in time, `ok` false or
    another protocol. Never raises."""
    path = home / GATEWAY_SOCKET
    if not path.exists():
        try:
            pointer = (home / GATEWAY_SOCKET_POINTER).read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        if not pointer or not Path(pointer).exists():
            return None
        path = Path(pointer)
    ask = {"verb": "status", "id": 1, "protocol": GATEWAY_SOCKET_PROTOCOL}
    chunks: list[bytes] = []
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(GATEWAY_SOCKET_WAIT_S)
            sock.connect(str(path))
            sock.sendall(json.dumps(ask).encode() + b"\n")
            deadline = time.monotonic() + GATEWAY_SOCKET_WAIT_S
            while time.monotonic() < deadline:
                chunk = sock.recv(65536)
                chunks.append(chunk)
                if not chunk or b"\n" in chunk:
                    break
                if sum(len(c) for c in chunks) > _GATEWAY_SOCKET_MAX:
                    return None
        answer = json.loads(b"".join(chunks).partition(b"\n")[0])
    except (OSError, ValueError):
        return None
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        return None
    if answer.get("protocol") != GATEWAY_SOCKET_PROTOCOL:
        return None
    result = answer.get("result")
    return result if isinstance(result, dict) else None


def pairing_approved(self: "HermesEngine", home: Path, platform: str, user_id: str) -> bool:
    """Hermes's own answer whether this user is approved by pairing in that home
    (PairingStore.is_approved, public)."""
    script = _PAIRED.replace("@JOB@", repr(json.dumps({"platform": platform, "user": user_id})))
    return bool(json.loads(self._in_runtime(home, script, "AGOS-PAIRED", timeout=30)))


def gateway_status(
    self: "HermesEngine", home: Path, *, fresh: bool = False, kept: bool = False
) -> dict[str, Any]:
    """Hermes's own verdict on this home's gateway, kept 2 s: the gateway's answer
    on its control socket (gateway/control_socket.py: no Hermes start), else
    gateway/status.py run in its runtime: {"pid": the running gateway's pid or None, "record":
    its gateway_state.json, "live": the record's pid is alive (start-time
    guard), "stale": no heartbeat for 120 s}. Hermes not answering = nothing
    known: not running.

    `kept` (a page's lamp; every decision asks without it): older verdicts come
    at once and are asked again behind the page, while the gateway processes the
    verdict named are still the same live ones and no gateway started or
    stopped (its pid file); one that died, restarted or started is asked about
    before the lamp shows (a dead gateway never keeps a green lamp). Each start
    of Hermes's runtime is ~1 s, one per bot on every Channels or dashboard
    view without it."""
    key = str(home)
    seen = self._gw_seen.get(key)
    if seen is not None and not fresh:
        if time.monotonic() - seen[0] < 2:
            return seen[1]
        if kept and seen[2] == self._gw_mark(home, seen[1]):
            self._gw_behind(home)
            return seen[1]
    return self._gw_ask(home)


def _gw_ask(self: "HermesEngine", home: Path) -> dict[str, Any]:
    found: dict[str, Any] = {"pid": None, "record": None, "live": False, "stale": True}
    answered = self._gw_socket(home)
    if answered is not None:
        self._gw_seen[str(home)] = (time.monotonic(), answered, self._gw_mark(home, answered))
        return answered
    try:
        got = json.loads(
            self._in_runtime(
                home, _GATEWAY_STATUS.replace("@HOME@", repr(str(home))), "AGOS-GW", timeout=30
            )
        )
        if isinstance(got, dict):
            found = {**found, **got}
    except (EngineError, ValueError) as error:
        log.debug("Hermes's gateway status of %s unknown: %s", home, error)
    self._gw_seen[str(home)] = (time.monotonic(), found, self._gw_mark(home, found))
    return found


def _gw_socket(home: Path) -> dict[str, Any] | None:
    """The verdict from the gateway's own answer on its control socket: it answers,
    so it is live and its snapshot is not stale (Hermes's socket contract); None
    when it doesn't answer or the record it holds is not its own (another pid):
    then Hermes's state files decide, in its runtime."""
    status = gateway_socket_status(home)
    if status is None:
        return None
    pid = status.get("answering_pid")
    record = {k: v for k, v in status.items() if k not in _SOCKET_ONLY}
    if not isinstance(pid, int) or isinstance(pid, bool) or record.get("pid") != pid:
        return None
    return {"pid": pid, "record": record, "live": True, "stale": False}


def _gw_mark(home: Path, verdict: dict[str, Any]) -> tuple[Any, ...]:
    """What makes a kept lamp wrong: the gateway's pid file (a gateway started,
    stopped or was replaced) and, for each process the verdict named, whether it
    is still the same one (its start time in /proc, what Hermes's own pid guard
    compares). Not gateway_state.json: its heartbeat rewrites it every 30 s."""
    record = verdict.get("record")
    pids = {verdict.get("pid"), record.get("pid") if isinstance(record, dict) else None}
    procs: list[tuple[int, str | None]] = []
    for pid in sorted(p for p in pids if isinstance(p, int) and p > 0):
        try:
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            start = None
        procs.append((pid, start))
    return (read_cache.file_stamp(home / "gateway.pid"), tuple(procs))


def _gw_behind(self: "HermesEngine", home: Path) -> None:
    """Hermes's verdict asked again in the background (one ask per home at a time)."""
    key = str(home)
    with self._gw_lock:
        if key in self._gw_asking:
            return
        self._gw_asking.add(key)

    def run() -> None:
        try:
            self._gw_ask(home)
        finally:
            with self._gw_lock:
                self._gw_asking.discard(key)

    read_cache.submit(run)


def gateway_shown(self: "HermesEngine", home: Path) -> dict[str, Any]:
    """gateway_status for what the pages show (a bot's lamp): Hermes's verdict,
    asked again at once when the gateway's own files say something new (what
    its snapshot says about the gateway and its platforms, whether the process
    it names is still the same one, its pid file), so a gateway that died or a
    bot Hermes marks failing shows on the very next page. Otherwise the kept
    verdict comes at once and is asked again in the background at most every
    30 s, so Hermes's verdict on a silent gateway (stale after 120 s) still
    comes and no page waits for it. Start, stop and their waits keep asking
    gateway_status itself."""
    key = str(home)
    files = _gateway_files(home)
    same = self._lamp_files.get(key) == files
    self._lamp_files[key] = files
    return copy.deepcopy(
        self._lamps.get(
            key,
            (files, int(time.time() // 30)),
            lambda: self.gateway_status(home, fresh=True),
            stale_ok=same,
        )
    )


def _gateway_up(self: "HermesEngine", home: Path) -> bool:
    """A gateway of this home is running, as Hermes says (its lock is held and
    its pid file names a live gateway) and it says "running"/"starting". A busy
    gateway can miss a health check; this never takes a busy one for dead."""
    status = self.gateway_status(home)
    record = status.get("record") or {}
    return status.get("pid") is not None and str(record.get("gateway_state") or "") in (
        "running",
        "starting",
    )


def _wait_gone(self: "HermesEngine", home: Path, wait_s: float = 30) -> None:
    """The home's last gateway process (Hermes's snapshot names it, its pid still
    live by Hermes's start-time guard) has exited when it says it is not
    running any more. A running one is left alone."""
    status = self.gateway_status(home, fresh=True)
    if not status.get("live") or self._gateway_up(home):
        return
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and self.gateway_status(home, fresh=True).get("live"):
        time.sleep(0.5)


def hermes_usage(
    self: "HermesEngine", root: Path, members: list[str], month_days: float, chart_days: int
) -> dict[str, dict[str, dict[str, int]]]:
    """The workspace's usage as Hermes's own analytics counts it (the _USAGE
    script, in its root): {"models": {model: {"tokens", "calls", "input",
    "output"}} over the last `month_days`, "days": {local day: {"tokens",
    "calls"}} over the last `chart_days`}, root and members summed.

    Hermes counts again only when a profile's sessions changed (its state.db or
    their WAL), a day or a month began; until its new count is in, the last one
    is given (usage moves all the time: the page never waits for Hermes's
    start, the count it shows is at most one change old)."""
    homes = [root, *(root / "profiles" / m for m in members)]
    sessions_stamp = (
        tuple(read_cache.sqlite_stamp(h / "state.db") for h in homes),
        time.strftime("%Y-%m-%d"),  # Hermes's daily series: local days
        int(time.time() - month_days * 86400) // 3600,  # the month it counts from
    )

    def ask() -> dict[str, dict[str, dict[str, int]]]:
        profiles = [[None, str(root)], *([m, str(root / "profiles" / m)] for m in members)]
        job = {"profiles": profiles, "month_days": month_days, "chart_days": chart_days}
        found: dict[str, dict[str, dict[str, int]]] = json.loads(
            self._in_runtime(root, _USAGE.replace("@JOB@", repr(json.dumps(job))), "AGOS-USAGE")
        )
        return found

    key = (str(root), tuple(members), chart_days)
    return copy.deepcopy(self._usage.get(key, sessions_stamp, ask, stale_ok=True))
