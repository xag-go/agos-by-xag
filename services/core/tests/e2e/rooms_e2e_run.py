# ruff: noqa: S105, S108, S310, S603, S607 - a test harness on throwaway local services
"""The `run` phase of rooms_e2e.py: every check, against the live throwaway setup."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from rooms_e2e import GROUP_CHAT, RUNTIME, E, api, gone, root_of, say, state, tg, wait

RESULTS: list[tuple[str, bool, str]] = []
FROM = int(os.environ.get("E2E_FROM") or "1")  # re-run from a later step
# The shared install's launchers: no throwaway root may rewrite them (compared with
# what they were when this run started).
LAUNCHER_PATHS = (
    str(Path.home() / ".hermes/hermes-agent/.hermes/bin/hermes"),
    str(Path.home() / ".hermes/hermes-agent/.hermes/bin/hermes-acp"),
)


def routing_yolo(ws: str, chat: int) -> list[Any]:
    """Hermes's own /yolo for an AGOS conversation: its gateway's routing entries
    (state.db gateway_routing) of the root and its profiles."""
    found: list[Any] = []
    root = root_of(ws)
    for home in [root, *sorted((root / "profiles").glob("*"))]:
        if not (home / "state.db").is_file():
            continue
        con = sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True, timeout=10)
        try:
            rows = con.execute("SELECT session_key, entry_json FROM gateway_routing").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            con.close()
        found += [
            json.loads(raw).get("yolo") for key, raw in rows if key.endswith(f":agos:dm:{chat}")
        ]
    return found


def soft_wait(what: str, found: Any, timeout: float) -> Any:
    """Like `wait`, but a timeout is a failed check, not the end of the run."""
    try:
        return wait(what, found, timeout, 2)
    except SystemExit as error:
        say("WAIT", str(error)[:300])
        return None


def pairing_by_hermes(ws: str, group: int) -> None:
    """Who may write to the bot is Hermes's DM pairing: a stranger gets Hermes's code,
    AGOS lists his request, the owner's Approve / Remove are Hermes's own."""
    conn = int(state()["conn"])
    approved = root_of(ws) / "platforms" / "pairing" / "telegram-approved.json"

    def request() -> Any:
        bots = [b for b in api("GET", "/channels") if b["id"] == conn]
        return next((p for b in bots for p in b["pending"] if p["id"] == "5151"), None)

    asked = soft_wait("Hermes's pairing request for the stranger", request, 120)
    coded = [
        s
        for s in tg("/control/sent")
        if s.get("method") == "sendMessage" and str(s.get("chat_id")) == "5151"
    ]
    check(
        "telegram: a stranger gets Hermes's pairing code; AGOS lists his request",
        bool(asked) and bool(coded),
        json.dumps(coded)[:300],
    )
    if not asked:
        return
    api("POST", f"/channels/{conn}/pairing/{asked['requestId']}")
    bot = next(b for b in api("GET", "/channels") if b["id"] == conn)
    check(
        "telegram: Approve in AGOS is Hermes's own pairing approval",
        "5151" in bot["allowed"]
        and approved.is_file()
        and "5151" in json.loads(approved.read_text()),
        json.dumps(bot["people"]),
    )
    tg("/control/message", {"chat": "5151", "text": "approved says hi", "from": 5151})

    def reached() -> Any:
        chats = {int(c["id"]) for c in api("GET", f"/workspaces/{ws}/chats")}
        chats |= {int(c["id"]) for c in api("GET", f"/workspaces/{ws}/workers")["dms"]}
        return [
            c for c in chats | {group} if any("approved says" in m["body"] for m in messages(ws, c))
        ] or None

    check(
        "telegram: once approved, his message reaches AGOS",
        bool(soft_wait("his message in AGOS", reached, 120)),
    )
    time.sleep(15)  # the Co-Founder's answer to him ends
    api("DELETE", f"/channels/{conn}/people/5151")
    bot = next(b for b in api("GET", "/channels") if b["id"] == conn)
    check(
        "telegram: Remove in AGOS is Hermes's own revoke",
        "5151" not in bot["allowed"] and "5151" not in json.loads(approved.read_text()),
        json.dumps(bot["people"]),
    )


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    say("PASS" if ok else "FAIL", name, detail[:300])
    return bool(ok)


def db() -> sqlite3.Connection:
    con = sqlite3.connect(E / "data" / "system" / "agos.db", timeout=30)
    con.row_factory = sqlite3.Row
    return con


def messages(ws: str, chat: int) -> list[dict[str, Any]]:
    return list(api("GET", f"/workspaces/{ws}/chats/{chat}")["messages"])


def agent_msgs(ws: str, chat: int) -> list[tuple[str, str]]:
    return [
        (m.get("speaker") or "cofounder", m["body"])
        for m in messages(ws, chat)
        if m["from"] == "agent"
    ]


def chat_asks(ws: str, chat: int) -> bool:
    """The chat's own Allow once / Deny card is waiting (its live answer)."""
    live = api("GET", f"/workspaces/{ws}/chats/{chat}/live").get("live") or {}
    return any(
        a.get("kind") == "approval" and a.get("status") == "waiting"
        for a in live.get("activity") or []
    )


def working(ws: str, chat: int) -> bool:
    return bool(api("GET", f"/workspaces/{ws}/chats/{chat}").get("working"))


def post(ws: str, chat: int, text: str, attachments: list[dict[str, Any]] | None = None) -> int:
    return int(
        api(
            "POST",
            f"/workspaces/{ws}/chats/{chat}/messages",
            {"body": text, "attachments": attachments or []},
        )["id"]
    )


def settle(
    ws: str, chat: int, n_before: int, final: str, timeout: float = 480
) -> list[tuple[str, str]]:
    def done() -> Any:
        got = agent_msgs(ws, chat)[n_before:]
        return got if any(final in b for _, b in got) and not working(ws, chat) else None

    return list(wait(f"room answer containing {final!r}", done, timeout, 2))


def md5(path: str) -> str:
    return subprocess.run(["md5sum", path], capture_output=True, text=True).stdout[:12]


LAUNCHER = {path: md5(path) for path in LAUNCHER_PATHS}


def local_terminal(ws: str) -> None:
    """No docker on the test machine: the agents' terminal runs locally in these
    throwaway roots (AGOS itself always sets the docker sandbox)."""
    import rooms_e2e as rig

    root = root_of(ws)
    for home in (root, *(p for p in (root / "profiles").iterdir() if p.is_dir())):
        rig.hset(home, "terminal.backend", "local")
    rig.restart_gateway(root)


def llm_log() -> list[dict[str, Any]]:
    return [json.loads(x) for x in (E / "logs" / "llm.jsonl").read_text().splitlines() if x]


def inbox_rows(ws: str, chat: int, text: str) -> list[sqlite3.Row]:
    return list(
        db().execute(
            """SELECT id, taken_at, done_at FROM hermes_inbox WHERE workspace_id = ?
                 AND chat_ref = ? AND kind = 'message' AND text = ?""",
            (ws, f"agos:{chat}", text),
        )
    )


def dm_turns_on_hermes(ws: str) -> None:
    """14. A DM runs on Hermes's session alone: AGOS hands each message over once and
    keeps no queue; Hermes batches, steers, and resumes after a crash."""
    chat = next(
        (c["id"] for c in api("GET", f"/workspaces/{ws}/workers")["dms"] if not c["agent"]),
        None,
    )
    if chat is None:
        check("DM chats: the Co-Founder's DM exists", False)
        return
    chat = int(chat)
    # a) Messages one after another: one turn (Hermes's inbound text batching).
    n = len(agent_msgs(ws, chat))
    burst = [f"burst {w} {int(time.time())}" for w in ("one", "two", "three")]
    for text in burst:
        post(ws, chat, text)
    got = settle(ws, chat, n, "DM answer", 180)
    asked = [r for r in llm_log() if burst[0] in str(r.get("prompt")) and r.get("topic")]
    check(
        "DM: messages one after another are one Hermes turn (its text batching)",
        len(got) == 1 and bool(asked) and all(b in str(asked[0].get("prompt")) for b in burst),
        json.dumps({"got": got, "prompt": [r.get("prompt") for r in asked][:2]})[:500],
    )
    rows = [inbox_rows(ws, chat, b) for b in burst]
    check(
        "DM: each message handed to Hermes once, confirmed after the batch went in",
        all(len(r) == 1 and r[0]["done_at"] for r in rows),
        str([[dict(x) for x in r] for r in rows])[:400],
    )
    # a2) A reply: Hermes's own reply context, his words as he wrote them.
    answer = [m for m in messages(ws, chat) if m["from"] == "agent"][-1]
    n = len(agent_msgs(ws, chat))
    mine = f"reply probe {int(time.time())}"
    api(
        "POST",
        f"/workspaces/{ws}/chats/{chat}/messages",
        {"body": mine, "attachments": [], "replyTo": answer["id"]},
    )
    settle(ws, chat, n, "reply probe", 180)
    asked = [r for r in llm_log() if mine in str(r.get("prompt")) and r.get("topic")]
    check(
        "reply: Hermes's own reply context, no AGOS text",
        bool(asked)
        and "[Replying to your previous message:" in str(asked[0].get("prompt"))
        and "The owner is replying" not in str(asked[0].get("prompt")),
        str([r.get("prompt") for r in asked][:1])[:400],
    )
    # b) A message while it works: straight to Hermes (its steer), AGOS holds nothing.
    n = len(agent_msgs(ws, chat))
    slow, more = f"slow job {int(time.time())}", f"and steer this {int(time.time())}"
    post(ws, chat, slow)
    wait("the Co-Founder working", lambda: working(ws, chat) or None, 60, 1)
    wait(
        "Hermes asked the model",
        lambda: any(slow in str(r.get("prompt")) for r in llm_log()) or None,
        60,
        1,
    )
    post(ws, chat, more)
    handed = wait(
        "the second message handed over while it works",
        lambda: (inbox_rows(ws, chat, more) or None) if working(ws, chat) else None,
        30,
        0.5,
    )
    settle(ws, chat, n, "steer this", 240)
    check(
        "busy: his message went to Hermes while it worked (no AGOS queue)",
        bool(handed) and any(more in str(r.get("prompt")) for r in llm_log()),
        str([dict(x) for x in handed or []]),
    )
    # c) The gateway dies mid-answer: Hermes resumes the turn itself (v0.21.5 and
    # v0.22.2 alike); AGOS hands nothing over again.
    n = len(agent_msgs(ws, chat))
    crash = f"slow crash probe {int(time.time())}"
    post(ws, chat, crash)
    wait(
        "the crash probe at the model",
        lambda: any(crash in str(r.get("prompt")) for r in llm_log()) or None,
        60,
        1,
    )
    pid = json.loads((root_of(ws) / "gateway_state.json").read_text())["pid"]
    killed = time.time()
    subprocess.run(["kill", "-KILL", str(pid)], check=False)
    import rooms_e2e as rig

    wait("gateway gone", lambda: rig.gone(pid), 60)

    rig.service_restart(root_of(ws))  # Hermes's service (Restart=always), not AGOS
    got = list(
        wait(
            "the answer after the crash",
            lambda: (
                agent_msgs(ws, chat)[n:]
                if len(agent_msgs(ws, chat)) > n and not working(ws, chat)
                else None
            ),
            420,
            3,
        )
    )
    crashed = inbox_rows(ws, chat, crash)
    resumed = [
        r
        for r in llm_log()
        if float(r.get("at") or 0) > killed
        and "previous turn was interrupted" in str(r.get("prompt"))
    ]
    check(
        "crash: Hermes resumed the answer itself; AGOS handed it over once",
        bool(got) and bool(resumed) and len(crashed) == 1,
        json.dumps(got)[:300] + str([dict(x) for x in crashed]) + str(len(resumed)),
    )
    turns = (
        db()
        .execute(
            "SELECT status FROM chat_turns WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat,)
        )
        .fetchone()
    )
    check(
        "crash: the AGOS turn ended",
        turns is not None and turns["status"] != "running",
        str(dict(turns or {})),
    )


def member_topic_on_hermes(ws: str) -> None:
    """17. A member's DM linked to its own topic is Hermes's routed conversation:
    the root's gateway.profile_routes (written by AGOS, read by Hermes at its
    restart), the member's conversation from before goes on there, the member
    answers once in the topic (with Hermes's message timestamps), the web chat is
    that same session both ways, Hermes's commands there are the member's, and the
    approval card of the topic's session survives a gateway restart."""
    import re

    import rooms_e2e as rig

    root = root_of(ws)
    member_home = root / "profiles" / "a-writer"
    stamp = int(time.time())
    dm = int(api("POST", f"/workspaces/{ws}/workers/dm", {"agent": "writer"})["id"])
    # His talk with the writer before its topic existed (the agos platform).
    n = len(agent_msgs(ws, dm))
    before = f"before topic {stamp}"
    post(ws, dm, before)
    settle(ws, dm, n, before, 240)

    def member_db(sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
        with contextlib.closing(
            sqlite3.connect(f"file:{member_home / 'state.db'}?mode=ro", uri=True, timeout=10)
        ) as h:
            return list(h.execute(sql, args))

    old = member_db(
        "SELECT id FROM sessions WHERE source = 'agos' AND chat_id = ? ORDER BY started_at DESC",
        (str(dm),),
    )
    check("topic: the member's talk from before is its agos session", bool(old), str(old))
    old_session = str(old[0][0]) if old else ""
    pid = json.loads((root / "gateway_state.json").read_text()).get("pid")
    api("PUT", f"/workspaces/{ws}/telegram-group", {"group": GROUP_CHAT})
    api("POST", f"/workspaces/{ws}/chats/{dm}/telegram-topic")
    address = str(
        db().execute("SELECT address FROM chat_addresses WHERE chat_id = ?", (dm,)).fetchone()[0]
    )
    thread = address.partition(":")[2]

    def routed() -> Any:
        routes = hermes_value(root, "gateway.profile_routes") or []
        return [r for r in routes if isinstance(r, dict) and r.get("profile") == "a-writer"] or None

    got = soft_wait("the root's route for the writer's topic", routed, 180) or []
    check(
        "topic: AGOS wrote Hermes's own gateway.profile_routes in the root",
        got
        == [
            {
                "name": f"agos-topic-{GROUP_CHAT}-{thread}",
                "platform": "telegram",
                "chat_id": GROUP_CHAT,
                "profile": "a-writer",
                "thread_id": thread,
            }
        ],
        json.dumps(got),
    )
    check(
        "topic: the member's own profile carries no routes",
        not hermes_value(member_home, "gateway.profile_routes"),
    )

    def restarted() -> Any:
        state_now = json.loads((root / "gateway_state.json").read_text())
        return (
            state_now.get("pid") not in (None, pid)
            and state_now.get("gateway_state") == "running"
            and not gone(state_now.get("pid") or 0)
        ) or None

    check(
        "topic: the root's gateway restarted to read its routes",
        bool(soft_wait("gateway restarted", restarted, 300)),
    )
    check(
        "duplicates: Telegram is quiet (no interim messages, no working bubble), restarts drain",
        hermes_value(root, "display.platforms.telegram.interim_assistant_messages") is False
        and hermes_value(root, "display.platforms.telegram.long_running_notifications") is False
        and hermes_value(root, "agent.restart_drain_timeout") == 60,
    )

    def bound() -> Any:
        rows = (
            db()
            .execute(
                "SELECT done_at FROM hermes_inbox WHERE chat_ref = ? AND kind = 'bind'", (address,)
            )
            .fetchall()
        )
        return (bool(rows) and all(r[0] for r in rows)) or None

    check("topic: the bind item was taken by the plugin", bool(soft_wait("bind", bound, 240)))

    def routing() -> Any:
        with contextlib.closing(
            sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True, timeout=10)
        ) as h:
            rows = h.execute(
                "SELECT session_key, entry_json FROM gateway_routing WHERE session_key LIKE ?",
                (f"agent:a-writer:telegram:group:{GROUP_CHAT}:{thread}%",),
            ).fetchall()
        return [(k, json.loads(v).get("session_id")) for k, v in rows] or None

    keys = soft_wait("the topic's routing entry", routing, 120) or []
    check(
        "topic: Hermes's key of the topic goes on in the member's session from before",
        bool(keys) and all(sid == old_session for _, sid in keys),
        json.dumps(keys),
    )

    def thread_sent(text: str, since: int) -> list[dict[str, Any]]:
        return [
            s
            for s in tg("/control/sent")[since:]
            if s.get("method") == "sendMessage"
            and str(s.get("chat_id")) == GROUP_CHAT
            and str(s.get("message_thread_id")) == thread
            and text in str(s.get("text"))
        ]

    # He writes in the topic: the writer (its own profile) answers once, there.
    sent_before = len(tg("/control/sent"))
    n = len(agent_msgs(ws, dm))
    hello = f"topic hello {stamp}"
    tg("/control/message", {"chat": GROUP_CHAT, "topic": int(thread), "text": hello})
    answer = soft_wait(
        "the writer's answer in the topic",
        lambda: thread_sent("DM answer: ", sent_before) and thread_sent(hello, sent_before),
        240,
    )
    time.sleep(10)  # anything sent twice would be out by now
    again = thread_sent(hello, sent_before)
    check(
        "topic: answered once, in the same topic, by the shared bot",
        bool(answer) and len(again) == 1,
        json.dumps(again)[:400],
    )
    check(
        "topic: his message carries Hermes's message timestamp (gateway.message_timestamps)",
        any(
            re.search(r"\[[A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2}", str(r.get("prompt")))
            for r in llm_log()
            if hello in str(r.get("prompt"))
        ),
        str([r.get("prompt") for r in llm_log() if hello in str(r.get("prompt"))][:1])[-300:],
    )
    in_member = member_db(
        "SELECT session_id FROM messages WHERE role = 'user' AND content LIKE ?", (f"%{hello}%",)
    )
    with contextlib.closing(
        sqlite3.connect(f"file:{root / 'state.db'}?mode=ro", uri=True, timeout=10)
    ) as h:
        in_root = h.execute(
            "SELECT count(*) FROM messages WHERE content LIKE ?", (f"%{hello}%",)
        ).fetchone()[0]
    check(
        "topic: answered by the member's profile, in its conversation from before",
        [r[0] for r in in_member] == [old_session] and in_root == 0,
        f"{in_member} root={in_root}",
    )
    shown = messages(ws, dm)
    replies = [m for m in shown if m["from"] == "agent" and hello in m["body"]]
    check(
        "topic: the AGOS web chat shows it, once, after the talk from before",
        any(before in m["body"] for m in shown)
        and any(m["from"] == "owner" and hello in m["body"] for m in shown)
        and len(replies) == 1,
        json.dumps([m["body"][:80] for m in shown][-6:]),
    )
    relayed = (
        db()
        .execute(
            """SELECT count(*) FROM channel_outbox WHERE address = ? AND source NOT LIKE 'mirror:%'
                 AND (sent_id IS NULL OR sent_id != 'skipped')""",
            (address,),
        )
        .fetchone()[0]
    )
    check("topic: AGOS queued no outbox row of the answer", relayed == 0, str(relayed))

    # He writes in AGOS: the same session, answered in the topic too.
    sent_before = len(tg("/control/sent"))
    n = len(agent_msgs(ws, dm))
    web = f"web to topic {stamp}"
    post(ws, dm, web)
    settle(ws, dm, n, web, 240)
    in_member = member_db(
        "SELECT session_id FROM messages WHERE role = 'user' AND content LIKE ?", (f"%{web}%",)
    )
    check(
        "topic: a web message to the member goes on in the same session",
        [r[0] for r in in_member] == [old_session],
        str(in_member),
    )
    check(
        "topic: its answer goes to the topic (Hermes's own send)",
        bool(
            soft_wait(
                "the web message's answer in the topic", lambda: thread_sent(web, sent_before), 120
            )
        ),
    )

    # The approval card of the topic's session, after a gateway restart (the plugin
    # has seen no message there since).
    rig.restart_gateway(root)
    n = len(agent_msgs(ws, dm))
    post(ws, dm, f"danger: topic probe {stamp}")
    asked = soft_wait(
        "the AGOS card of the topic's approval", lambda: chat_asks(ws, dm) or None, 240
    )
    check("approval: the card of a topic's session shows in AGOS after a restart", bool(asked))
    if asked:
        api("POST", f"/workspaces/{ws}/chats/{dm}/approval", {"choice": "once"})
        got = settle(ws, dm, n, "Tool said", 240)
        check(
            "approval: answered in AGOS, Hermes ran it in the topic's session",
            any("Tool said" in b for _, b in got) and not chat_asks(ws, dm),
            json.dumps(got)[:300],
        )

    # Hermes's own command typed in the topic: the member's session (a new one). Hermes
    # asks to confirm /new (its destructive-command card); Approve Once starts it.
    sent_before = len(tg("/control/sent"))
    tg("/control/message", {"chat": GROUP_CHAT, "topic": int(thread), "text": "/new"})

    def confirm() -> Any:
        for s in tg("/control/sent")[sent_before:]:
            markup = json.dumps(s.get("reply_markup") or "")
            if str(s.get("message_thread_id")) == thread and "sc:once:" in markup:
                return s
        return None

    card = soft_wait("Hermes's confirm of /new in the topic", confirm, 120)
    if card:
        markup = card.get("reply_markup") or {}
        if isinstance(markup, str):
            markup = json.loads(markup)
        once = next(
            b["callback_data"]
            for row in markup["inline_keyboard"]
            for b in row
            if str(b["callback_data"]).startswith("sc:once:")
        )
        tg("/control/press", {"chat": GROUP_CHAT, "topic": int(thread), "data": once})

    def fresh() -> Any:
        return (
            member_db(
                """SELECT id FROM sessions WHERE source = 'telegram' AND chat_id = ?
                     AND thread_id = ? AND id != ? AND ended_at IS NULL""",
                (GROUP_CHAT, thread, old_session),
            )
            or None
        )

    check(
        "topic: Hermes's /new there is the member's own (a new session in its profile)",
        bool(card) and bool(soft_wait("the member's new topic session", fresh, 120)),
    )


def team_in_hermes(ws: str) -> None:
    """16. The team is its Hermes profiles: title, description, on/off and membership
    are the members' own profile data, read and changed there; an agent row AGOS
    kept whole before moves into its profile by itself (live migration)."""
    import rooms_e2e as rig
    import yaml

    root = root_of(ws)

    def meta(name: str) -> dict[str, Any]:
        path = root / "profiles" / f"a-{name}" / "profile.yaml"
        return (yaml.safe_load(path.read_text()) if path.is_file() else None) or {}

    def hermes(home: Path, *args: str) -> str:
        return subprocess.run(
            [rig.HERMES, *args],
            env=rig.hermes_env(home),
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout

    agents = {a["name"]: a for a in api("GET", f"/workspaces/{ws}/agents")}
    check(
        "team: each member's title is its Hermes profile's display name",
        {n: meta(n).get("display_name") for n in ("writer", "editor")}
        == {"writer": "Writer", "editor": "Editor"}
        and {n: a["title"] for n, a in agents.items()} == {"writer": "Writer", "editor": "Editor"},
        json.dumps({n: meta(n) for n in ("writer", "editor")})[:300],
    )
    rows = (
        db()
        .execute(
            "SELECT name, title, summary, definition FROM library_items"
            " WHERE kind = 'agent' AND workspace_id = ?",
            (ws,),
        )
        .fetchall()
    )
    check(
        "team: AGOS keeps only an id per member (no title, text or switch)",
        sorted(r["name"] for r in rows) == ["editor", "writer"]
        and all((r["title"], r["summary"], r["definition"]) == ("", "", "{}") for r in rows),
        json.dumps([dict(r) for r in rows])[:300],
    )
    editor = agents["editor"]
    body = {
        "name": "editor",
        "title": "Chief Editor",
        "summary": "Checks every text.",
        "definition": editor["definition"],
    }
    api("PUT", f"/workspaces/{ws}/agents/{editor['id']}", body)
    shown = hermes(root, "profile", "show", "a-editor")
    titles = [m["title"] for m in api("GET", f"/workspaces/{ws}/workers")["members"]]
    check(
        "team: a renamed job title is Hermes's own (profile show, description)",
        "Chief Editor (a-editor)" in shown
        and meta("editor").get("description") == "Checks every text."
        and "Chief Editor" in titles,
        shown[:200] + json.dumps(titles),
    )
    api("PUT", f"/workspaces/{ws}/connectors/{editor['id']}", {"on": False, "local": ""})
    member = root / "profiles" / "a-editor"

    def served(want: bool) -> list[str]:
        """The root gateway's own served set (gateway_state.json, Hermes's
        publish_runtime_status); a slow serve finishes on Hermes's rescan (<30 s)."""
        names: list[str] = []
        for _ in range(45):
            with contextlib.suppress(OSError, ValueError):
                state = json.loads((root / "gateway_state.json").read_text())
                names = list(state.get("served_profiles") or [])
            if ("a-editor" in names) == want and "a-writer" in names:
                break
            time.sleep(1)
        return names

    def said(verb: str) -> list[str]:
        return [
            ln
            for ln in (E / "logs" / "core.log").read_text(errors="replace").splitlines()
            if f"editor of {ws}: Profile 'a-editor' {verb}" in ln
        ]

    now = served(False)
    check(
        "team: off is Hermes's `gateway stop`: the root's gateway unserved it",
        "a-editor" not in now and "a-writer" in now and bool(said("parked")),
        f"{now} {said('parked')[-1:]}"[:300],
    )
    dispatch = hermes_value(root, "kanban.dispatch_profiles") or []
    status = hermes(member, "gateway", "status")
    check(
        "team: off = Hermes's parked marker; the board stops dispatching to it",
        (member / "gateway.parked").exists()
        and "a-editor" not in dispatch
        and "parked" in status
        and [m["name"] for m in api("GET", f"/workspaces/{ws}/workers")["members"]] == ["writer"],
        f"{dispatch} {status[:160]}",
    )
    api("PUT", f"/workspaces/{ws}/connectors/{editor['id']}", {"on": True, "local": ""})
    now = served(True)
    check(
        "team: back on is Hermes's `gateway start`: the root's gateway serves it again",
        "a-editor" in now and bool(said("served") or said("unparked")),
        f"{now} {(said('served') + said('unparked'))[-1:]}"[:300],
    )
    check(
        "team: back on = the marker gone, dispatched again",
        not (member / "gateway.parked").exists()
        and "a-editor" in (hermes_value(root, "kanban.dispatch_profiles") or []),
    )
    api("PUT", f"/workspaces/{ws}/agents/{editor['id']}", {**body, "title": "Editor"})


def proposal_round_trip(ws: str) -> None:
    """43. A proposal is a Hermes Kanban card blocked for the owner (an agos-proposal
    block in its body, kind needs_input), decided from AGOS: the decision lands on
    the card as a marker comment, the card goes on, and a second decision is refused."""
    import rooms_e2e as rig

    root = root_of(ws)

    def hermes(*args: str) -> str:
        return subprocess.run(
            [rig.HERMES, *args],
            env=rig.hermes_env(root),
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout

    body = (
        "Here is the plan.\n\n```agos-proposal\n"
        + json.dumps({"kind": "plan", "payload": {"title": "E2E plan", "markdown": "# Plan\n1. a"}})
        + "\n```"
    )
    made = json.loads(
        hermes("kanban", "create", "Plan: E2E plan", "--json", "--body", body) or "{}"
    )
    card = str((made.get("task") or made).get("id") or "")
    check("proposal: the card is Hermes's (unassigned, ready)", bool(card), json.dumps(made)[:200])
    hermes("kanban", "block", card, "--kind", "needs_input", "waiting for the owner: proposal")

    def listed() -> Any:
        found = [p for p in api("GET", f"/workspaces/{ws}/proposals") if p["card"] == card]
        return found[0] if found else None

    shown = None
    with contextlib.suppress(SystemExit):  # wait() exits on its timeout
        shown = wait("proposal told by Hermes's block hook", listed, timeout=20, every=2)
    if shown is None:
        # The CLI's hook may not reach the plugin here: post what the plugin posts.
        bridge = json.loads((root / "agos-bridge.json").read_text())
        request = urllib.request.Request(
            f"{bridge['core'].rstrip('/')}/hermes-bridge/{bridge['workspace']}/kanban-blocked",
            data=json.dumps({"card": card}).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {bridge['key']}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as r:
            r.read()
        shown = listed()
    check(
        "proposal: AGOS reads the kind and payload from the card body",
        bool(shown) and shown["kind"] == "plan" and shown["payload"]["title"] == "E2E plan",
        json.dumps(shown)[:300],
    )
    if not shown:
        return
    decided = api("POST", f"/workspaces/{ws}/proposals/{shown['id']}", {"choice": "approve"})
    detail = json.loads(hermes("kanban", "show", card, "--json") or "{}")
    comments = [c.get("body") or "" for c in detail.get("comments") or []]
    check(
        "proposal: approve = a marker comment on the card (Hermes) and the card goes on",
        decided["status"] == "approved"
        and any(c.startswith(f"[agos-decision {card} r1: approve]") for c in comments)
        and (detail.get("task") or {}).get("status") in ("ready", "todo"),
        json.dumps({"status": (detail.get("task") or {}).get("status"), "comments": comments})[
            :300
        ],
    )
    again = api("POST", f"/workspaces/{ws}/proposals/{shown['id']}", {"choice": "approve"})
    refused = ""
    try:
        api("POST", f"/workspaces/{ws}/proposals/{shown['id']}", {"choice": "reject"})
    except RuntimeError as error:
        refused = str(error)
    check(
        "proposal: the same decision again is a no-op, another one is a 409",
        again["status"] == "approved" and " 409 " in refused,
        refused[:200],
    )
    hermes("kanban", "archive", card)


def question_round_trip(ws: str) -> None:
    """45. An agent's typed question (what its agos_ask_owner tool posts) is a Hermes
    Kanban card AGOS makes and blocks for the owner (an agos-question block in its
    body); the answer from AGOS lands on the card as a marker comment, the card goes
    on (unblocked for the asker), and a second, different answer is refused."""
    import rooms_e2e as rig

    root = root_of(ws)

    def hermes(*args: str) -> str:
        return subprocess.run(
            [rig.HERMES, *args],
            env=rig.hermes_env(root),
            capture_output=True,
            text=True,
            timeout=180,
        ).stdout

    bridge = json.loads((root / "agos-bridge.json").read_text())

    def plugin_posts(path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{bridge['core'].rstrip('/')}/hermes-bridge/{bridge['workspace']}/{path}",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {bridge['key']}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as r:
            found: dict[str, Any] = json.loads(r.read() or b"{}")
            return found

    made = plugin_posts(
        "ask-owner",
        {
            "member": "",
            "kind": "confirm",
            "payload": {"question": "E2E: publish the draft today?"},
            "continuation": "wake_assignee",
            "card": "",
        },
    )
    card = str(made.get("card") or "")
    detail = json.loads(hermes("kanban", "show", card, "--json") or "{}") if card else {}
    task = detail.get("task") or {}
    # `kanban show --json` has no block_kind field: the typed block is the card's
    # last `blocked` event (Hermes's classify-in-place writes kind there).
    kinds = [
        (e.get("payload") or {}).get("kind")
        for e in detail.get("events") or []
        if e.get("kind") == "blocked"
    ]
    check(
        "question: AGOS made the card through Hermes's CLI and blocked it needs_input",
        bool(card)
        and task.get("status") == "blocked"
        and bool(kinds)
        and kinds[-1] == "needs_input"
        and "```agos-question" in str(task.get("body") or ""),
        json.dumps({"made": made, "status": task.get("status"), "kinds": kinds})[:300],
    )
    if not card:
        return
    found = [q for q in api("GET", f"/workspaces/{ws}/questions") if q["card"] == card]
    check(
        "question: listed with its kind and payload (the Inbox's row)",
        bool(found) and found[0]["kind"] == "confirm" and found[0]["id"] == made.get("ask_id"),
        json.dumps(found)[:300],
    )
    if not found:
        return
    items = api("GET", f"/workspaces/{ws}/inbox")["items"]
    check(
        "question: the Inbox shows it once, as a question",
        [i["type"] for i in items if i["card"] == card] == ["question"],
        json.dumps([(i["type"], i["card"]) for i in items])[:300],
    )
    answered = api(
        "POST", f"/workspaces/{ws}/questions/{found[0]['id']}", {"answer": {"yes": True}}
    )
    detail = json.loads(hermes("kanban", "show", card, "--json") or "{}")
    comments = [c.get("body") or "" for c in detail.get("comments") or []]
    check(
        "question: the answer is a marker comment on the card (Hermes) and the card goes on",
        answered["status"] == "answered"
        and answered["answer"] == {"yes": True}
        and any(c.startswith(f"[agos-answer {card} r1]") for c in comments)
        and (detail.get("task") or {}).get("status") in ("ready", "todo"),
        json.dumps({"status": (detail.get("task") or {}).get("status"), "comments": comments})[
            :300
        ],
    )
    refused = ""
    try:
        api("POST", f"/workspaces/{ws}/questions/{found[0]['id']}", {"answer": {"yes": False}})
    except RuntimeError as error:
        refused = str(error)
    again = api("POST", f"/workspaces/{ws}/questions/{found[0]['id']}", {"answer": {"yes": True}})
    check(
        "question: the same answer again is a no-op, another one is a 409",
        again["status"] == "answered" and " 409 " in refused,
        refused[:200],
    )
    hermes("kanban", "archive", card)


def members_menu(ws: str, group_chat: int) -> None:
    """The group's members are commands in Hermes's own Telegram menu (the agos-guard
    policy, Hermes's command_menu.priority, its setMyCommands); a renamed job title
    reaches it without anything else changing."""
    from agos_core.actions.hermes_channel import command_name
    from agos_core.hermes_plugin.agos_guard import POLICY_FILE

    root = root_of(ws)
    names = json.loads(
        db().execute("SELECT members FROM chats WHERE id = ?", (group_chat,)).fetchone()[0]
    )
    wanted = sorted(command_name(n) for n in names)

    def menu() -> Any:
        try:
            got = json.loads((root / POLICY_FILE).read_text()).get("members") or []
        except (OSError, ValueError):
            return None
        return got if sorted(m["command"] for m in got) == wanted else None

    got = wait("the members' menu", menu, 120, 2)
    first = hermes_value(root, "platforms.telegram.extra.command_menu.priority")
    check(
        "telegram: the group's members are Hermes's menu commands (first in its menu)",
        bool(got) and sorted(first or []) == wanted,
        json.dumps([got, first])[:300],
    )
    agents = {a["name"]: a for a in api("GET", f"/workspaces/{ws}/agents")}
    who = agents[names[0]]
    title = f"E2E {who['title']}"[:60]
    api(
        "PUT",
        f"/workspaces/{ws}/agents/{who['id']}",
        {
            "name": who["name"],
            "title": title,
            "summary": who.get("summary") or "",
            "definition": who["definition"],
        },
    )

    def renamed() -> Any:
        found = menu() or []
        return any(m["title"] == title for m in found) or None

    check(
        "telegram: a renamed job title reaches the menu (change seen, no polling of files)",
        bool(wait("the renamed title in the menu", renamed, 60, 2)),
        (root / POLICY_FILE).read_text()[:300],
    )
    api(
        "PUT",
        f"/workspaces/{ws}/agents/{who['id']}",
        {
            "name": who["name"],
            "title": who["title"],
            "summary": who.get("summary") or "",
            "definition": who["definition"],
        },
    )


def hermes_value(home: Path, key: str) -> Any:
    """A value as Hermes itself resolves it (`hermes config get --json`)."""
    import rooms_e2e as rig

    out = subprocess.run(
        [rig.HERMES, "config", "get", key, "--json"],
        capture_output=True,
        text=True,
        env=rig.hermes_env(home),
        timeout=60,
    ).stdout
    try:
        return json.loads(out)
    except ValueError:
        return None


def screen_in_hermes(home: Path) -> bool:
    off = hermes_value(home, "agent.disabled_toolsets") or []
    return any(name not in off for name in ("browser", "computer_use"))


def hook_post(port: int, name: str, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
    """A delivery straight to the workspace's Hermes webhook platform."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/webhooks/{name}",
        data=body,
        method="POST",
        headers={"content-type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read()[:300]


def webhooks_on_hermes(ws: str) -> None:
    """A webhook is Hermes's route alone: AGOS writes it with Hermes's own store
    update (its lock), Hermes checks and runs it, AGOS reads it back from there."""
    import hashlib
    import hmac

    from rooms_e2e import MODEL

    root = root_of(ws)
    subs = root / "webhook_subscriptions.json"
    secret = "e2e-webhook-secret-0123456789"
    aid = api(
        "POST",
        f"/workspaces/{ws}/automations",
        {
            "name": "e2e hook",
            "instructions": "Note what arrived.",
            "schedule": "",
            "model": MODEL,
            "on": True,
            "hook": True,
            "checkFirst": True,  # the owner's OK card first: no agent works on it
        },
    )["id"]
    hook = api(
        "POST",
        f"/workspaces/{ws}/automations/{aid}/hook",
        {"on": True, "secret": secret, "events": ["e2e.ping"]},
    )
    name = hook["path"].removeprefix("/webhooks/")
    route = (json.loads(subs.read_text()) if subs.is_file() else {}).get(name) or {}
    check(
        "webhooks: the route is in the root's Hermes store, written under Hermes's lock",
        route.get("secret") == secret
        and route.get("script") == f"agos-hook-{aid}.py"
        and (root / ".webhook_subscriptions.lock").is_file(),
        json.dumps(route)[:300],
    )
    columns = [str(r[1]) for r in db().execute("PRAGMA table_info(automations)")]
    check(
        "webhooks: AGOS keeps no copy (token, secret, events)",
        not [c for c in columns if c.startswith("hook")],
        str(columns),
    )
    # The webhook port is Hermes's own setting (WEBHOOK_PORT in the root's .env).
    port = int(
        next(
            line.split("=", 1)[1]
            for line in (root_of(ws) / ".env").read_text().splitlines()
            if line.startswith("WEBHOOK_PORT=")
        )
    )
    check(
        "webhooks: the port is read from Hermes's .env (AGOS keeps no copy)",
        db()
        .execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'hooks.port.%'")
        .fetchone()[0]
        == 0,
        str(port),
    )

    def signed(body: bytes, delivery: str, event: str = "e2e.ping") -> dict[str, str]:
        mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return {
            "X-Hub-Signature-256": f"sha256={mac}",
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
        }

    def runs_on_board() -> set[str]:
        board = root / "kanban.db"  # Hermes's default board of the root
        if not board.is_file():
            return set()
        con = sqlite3.connect(f"file:{board}?mode=ro", uri=True, timeout=10)
        keys = [
            str(r[0])
            for r in con.execute(
                "SELECT idempotency_key FROM tasks WHERE idempotency_key LIKE ?",
                (f"agos-automation:{aid}:%",),
            )
        ]
        con.close()
        return {k.split(":")[2] for k in keys}

    body = json.dumps({"event": "e2e.ping", "data": {"title": "first ping"}}).encode()
    _code, said = wait(
        "webhook route live",
        lambda: (r := hook_post(port, name, body, signed(body, "e2e-d1")))[0] == 200 and r,
        120,
        2,
    ) or (0, None)
    check(
        "webhooks: Hermes took a signed delivery and ran the route's script",
        said == {"status": "ignored", "reason": "script", "route": name},
        str(said),
    )
    check("webhooks: the run is on Hermes's Kanban", len(runs_on_board()) == 1)
    again = hook_post(port, name, body, signed(body, "e2e-d1"))
    events = api("GET", f"/workspaces/{ws}/automations/{aid}/events")
    check(
        "webhooks: the same delivery again runs nothing twice",
        len(runs_on_board()) == 1 and [e["status"] for e in events][:2] == ["duplicate", "started"],
        json.dumps([again[0], [e["status"] for e in events]]),
    )
    logged = [
        e
        for e in api("GET", f"/workspaces/{ws}/log")["entries"]
        if e["area"] == "webhook" and f"?runs={aid}" in e["href"]
    ]
    check(
        "webhooks: the Log shows the deliveries (read through Hermes's routes)",
        len(logged) >= 2,
        json.dumps([e["text"] for e in logged])[:300],
    )
    check(
        "webhooks: Hermes refuses an unsigned delivery",
        hook_post(port, name, body, {"X-GitHub-Event": "e2e.ping"})[0] == 401,
    )
    other = json.dumps({"event": "e2e.other"}).encode()
    check(
        "webhooks: Hermes's route filter drops another event",
        hook_post(port, name, other, signed(other, "e2e-d2", "e2e.other"))[1]
        == {"status": "ignored", "reason": "filter", "route": name},
    )
    api("POST", f"/workspaces/{ws}/automations/{aid}/toggle", {"on": False})
    got = api("GET", f"/workspaces/{ws}/automations/{aid}")
    late = json.dumps({"event": "e2e.ping", "data": {"title": "late"}}).encode()
    check(
        "webhooks: off is the route's own enabled: false, Hermes refuses, AGOS reads it there",
        (json.loads(subs.read_text()).get(name) or {}).get("enabled") is False
        and got["on"] is False
        and hook_post(port, name, late, signed(late, "e2e-d3"))[0] == 403,
        json.dumps(got.get("hook")),
    )
    # The Log lists the deliveries of every automation Hermes has a route for.
    logged = [
        e
        for e in api("GET", f"/workspaces/{ws}/log")["entries"]
        if str(e.get("id", "")).startswith(f"webhook:{aid}:")
    ]
    check("webhooks: the Log shows the route's deliveries", bool(logged), str(len(logged)))
    api("DELETE", f"/workspaces/{ws}/automations/{aid}")
    left = [n for n in json.loads(subs.read_text()) if n.startswith(f"agos-{aid}-")]
    check("webhooks: deleting an automation removes its Hermes route", left == [], str(left))


def jobs_in(home: Path) -> dict[str, dict[str, Any]]:
    """A profile's Hermes cron jobs by name (its own jobs.json)."""
    try:
        data = json.loads((home / "cron" / "jobs.json").read_text())
    except (OSError, ValueError):
        return {}
    jobs = data.get("jobs") if isinstance(data, dict) else data
    return {str(j.get("name")): j for j in jobs or [] if isinstance(j, dict)}


def member_automations(ws: str) -> None:
    """16. A member's automation is a job in the member's own Hermes cron: the
    root's gateway ticks it and Hermes runs it as that member (its SOUL.md); AGOS
    pastes no role. A job left in the Co-Founder's cron for a member moves (the live
    migration)."""
    root = root_of(ws)
    writer, editor = root / "profiles" / "a-writer", root / "profiles" / "a-editor"
    model = {"provider": "fakellm", "mode": "api", "model": "fake-model", "effort": "medium"}
    body = {
        "name": "E2E member brief",
        "instructions": "automation hello from cron",
        "schedule": "0 9 * * *",
        "model": model,
        "on": True,
        "agent": "writer",
    }
    # The writer pins a skill (its own local one here): Hermes's cron leaves
    # skills.auto_load out, so it rides on the writer's jobs as their `skills`.
    pinned = writer / "skills" / "e2e-pinned"
    pinned.mkdir(parents=True, exist_ok=True)
    (pinned / "SKILL.md").write_text(
        "---\nname: e2e-pinned\ndescription: The e2e pinned skill.\n---\n\n"
        "E2E-PINNED-SKILL-TEXT: follow it.\n"
    )
    me = next(a for a in api("GET", f"/workspaces/{ws}/agents") if a["name"] == "writer")
    api(
        "PUT",
        f"/workspaces/{ws}/agents/{me['id']}",
        {
            "name": "writer",
            "title": me["title"],
            "summary": me.get("summary") or "",
            "definition": {**me["definition"], "skills": ["e2e-pinned"]},
        },
    )
    aid = int(api("POST", f"/workspaces/{ws}/automations", body)["id"])
    name = "E2E member brief"  # the owner's name is the Hermes job's own
    job = jobs_in(writer).get(name)
    kept = db().execute("SELECT name FROM automations WHERE id = ?", (aid,)).fetchone()
    check("automation: AGOS keeps no copy of its name", kept["name"] == "", str(dict(kept)))
    check("automation: the job is in the member's own cron", job is not None, str(job)[:200])
    check(
        "automation: the member's pinned skill is the job's own skills",
        (job or {}).get("skills") == ["e2e-pinned"],
        str((job or {}).get("skills")),
    )
    six = int(
        api(
            "POST",
            f"/workspaces/{ws}/automations",
            body | {"name": "E2E six fields", "schedule": "0 9 * * 1 30"},
        )["id"]
    )
    held6 = jobs_in(writer).get("E2E six fields") or {}
    check(
        "automation: a 6-field cron Hermes takes is saved",
        (held6.get("schedule") or {}).get("kind") == "cron",
        str(held6.get("schedule")),
    )
    api("DELETE", f"/workspaces/{ws}/automations/{six}")
    check("automation: not in the Co-Founder's cron", name not in jobs_in(root))
    prompt = str((job or {}).get("prompt") or "")
    check(
        "automation: no role text pasted in the prompt",
        "automation hello from cron" in prompt and "work in that role" not in prompt,
        prompt[:300],
    )
    got = api("GET", f"/workspaces/{ws}/automations/{aid}")
    check("automation: AGOS shows who does it from Hermes", got.get("agent") == "writer", str(got))
    md = E / "data" / "workspaces" / ws / str(got.get("file") or "x")
    check(
        "automation: the job's prompt is the one copy of the instructions (no AGOS file)",
        got.get("instructions") == "automation hello from cron" and not md.exists(),
        str(got.get("instructions"))[:200],
    )
    try:
        api("POST", f"/workspaces/{ws}/automations", body | {"schedule": "61 9 * * *"})
        refused = ""
    except RuntimeError as error:
        refused = str(error)
    check(
        "automation: Hermes's own parser refuses a bad schedule",
        ": 400 " in refused and "Schedule:" in refused,
        refused[:300],
    )
    natural = int(
        api(
            "POST",
            f"/workspaces/{ws}/automations",
            body | {"name": "E2E natural", "schedule": "every monday 9am"},
        )["id"]
    )
    held = jobs_in(writer).get("E2E natural") or {}
    check(
        "automation: a schedule in Hermes's own words is taken",
        (held.get("schedule") or {}).get("kind") == "cron",
        str(held.get("schedule")),
    )
    api("DELETE", f"/workspaces/{ws}/automations/{natural}")
    row = db().execute("SELECT agent FROM automations WHERE id = ?", (aid,)).fetchone()
    check("automation: AGOS keeps no copy of the agent", row["agent"] is None, str(dict(row)))
    api("POST", f"/workspaces/{ws}/automations/{aid}/run")
    seen = wait(
        "the member's cron run reaching the model",
        lambda: [x for x in llm_log() if "automation hello from cron" in x.get("prompt", "")],
        300,
        3,
    )
    check(
        "automation: Hermes ran it as the member (its SOUL.md)",
        bool(seen) and all(x.get("member") == "Writer" for x in seen),
        json.dumps([x.get("member") for x in seen]),
    )
    check(
        "automation: the member's cron run loaded its pinned skill",
        bool(seen) and all("E2E-PINNED-SKILL-TEXT" in x.get("prompt", "") for x in seen),
        str([x.get("prompt", "")[:200] for x in seen])[:400],
    )
    runs = wait(
        "the run in AGOS's list",
        lambda: [
            r for r in api("GET", f"/workspaces/{ws}/automations/{aid}/runs") if r["result"] == "ok"
        ],
        180,
        3,
    )
    check("automation: its run is read from the member's cron", bool(runs), str(runs)[:300])

    # The live migration: a job AGOS left in the Co-Founder's cron for a member.
    old = int(
        api("POST", f"/workspaces/{ws}/automations", body | {"name": "E2E old", "agent": None})[
            "id"
        ]
    )
    oname = "E2E old"
    check("automation: a Co-Founder's one is in the root's cron", oname in jobs_in(root))
    db().execute("UPDATE automations SET agent = 'editor' WHERE id = ?", (old,)).connection.commit()
    moved = wait(
        "the old job moving to the member's cron",
        lambda: oname in jobs_in(editor) and oname not in jobs_in(root),
        120,
        3,
    )
    check("migration: the member's job left the Co-Founder's cron for its own", bool(moved))
    # Its instructions kept in AGOS's file, as before Hermes's prompt was their copy:
    # the next round puts them into the job's prompt once, and the file goes.
    old_file = api("GET", f"/workspaces/{ws}/automations/{old}")["file"]
    old_md = E / "data" / "workspaces" / ws / str(old_file)
    old_md.write_text('---\nname: "E2E old"\n---\n\nautomation text from the old file\n')
    new_prompt = wait(
        "the old file's text moving into Hermes's prompt",
        lambda: (
            not old_md.exists()
            and "automation text from the old file"
            in (p := str(jobs_in(editor).get(oname, {}).get("prompt")))
            and p
        ),
        120,
        3,
    )
    check(
        "migration: the old file's text is in Hermes's prompt, the file is gone",
        bool(new_prompt),
        str(jobs_in(editor).get(oname, {}).get("prompt"))[:300],
    )
    row = (
        db().execute("SELECT agent, hermes_job_id FROM automations WHERE id = ?", (old,)).fetchone()
    )
    check(
        "migration: linked to the new job, no AGOS copy of the agent",
        row["agent"] is None and row["hermes_job_id"] == jobs_in(editor)[oname]["id"],
        str(dict(row)),
    )
    for a in (aid, old):
        api("DELETE", f"/workspaces/{ws}/automations/{a}")
    left = [n for h in (root, writer, editor) for n in jobs_in(h) if n in (name, oname)]
    check("automation: delete removes the job from the member's cron", not left, str(left))
    api(
        "PUT",
        f"/workspaces/{ws}/agents/{me['id']}",
        {
            "name": "writer",
            "title": me["title"],
            "summary": me.get("summary") or "",
            "definition": me["definition"],
        },
    )

    # Run now of a scheduled team automation: Hermes runs its job (`hermes cron run`).
    team = int(
        api(
            "POST",
            f"/workspaces/{ws}/automations",
            {
                "name": "E2E team run now",
                "instructions": "Check with me first.",
                "schedule": "0 9 * * *",
                "model": model,
                "on": True,
                "checkFirst": True,
            },
        )["id"]
    )
    tname = "E2E team run now"
    api("POST", f"/workspaces/{ws}/automations/{team}/run")
    tjob = jobs_in(root).get(tname) or {}
    con = sqlite3.connect(f"file:{root / 'kanban.db'}?mode=ro", uri=True, timeout=10)
    cards = [
        str(r[0])
        for r in con.execute(
            "SELECT idempotency_key FROM tasks WHERE idempotency_key LIKE ?",
            (f"agos-automation:{team}:%",),
        )
    ]
    con.close()
    check(
        "run now: a scheduled team automation is Hermes's own run of its job",
        bool(tjob.get("last_run_at"))
        and tjob.get("last_status") == "ok"
        and len({c.split(":")[2] for c in cards}) == 1,
        json.dumps([tjob.get("last_run_at"), tjob.get("last_status"), cards])[:300],
    )
    try:
        api("POST", f"/workspaces/{ws}/automations/{team}/run")
        again = ""
    except RuntimeError as error:
        again = str(error)
    check("run now: again while its run is on the board is refused", "still going" in again, again)
    api("DELETE", f"/workspaces/{ws}/automations/{team}")


def memory_plugin_everywhere(*workspaces: str) -> None:
    """17. Holographic memory (a Hermes catalog plugin since v0.22) is in every root
    and member profile, installed by AGOS with Hermes's `plugins install`."""
    homes = [
        h
        for ws in workspaces
        for h in (root_of(ws), *sorted((root_of(ws) / "profiles").glob("a-*")))
        # A member off the team (Hermes's parked marker) is not synced: it gets
        # its config, then Holographic, when it is back on.
        if (h / "config.yaml").is_file() and not (h / "gateway.parked").exists()
    ]
    done = wait(
        "holographic in every profile",
        lambda: all((h / "plugins" / "holographic" / "plugin.yaml").is_file() for h in homes),
        1500,
        10,
    )
    missing = [str(h) for h in homes if not (h / "plugins" / "holographic").is_dir()]
    check(
        "memory: every root and member has Holographic (Hermes's catalog)", bool(done), str(missing)
    )
    core_log = (E / "logs" / "core.log").read_text(errors="replace")
    check(
        "memory: AGOS installed it with Hermes's plugins install",
        "Holographic memory installed in" in core_log,
    )
    status = subprocess.run(
        [rig_hermes(), "memory", "status"],
        env=hermes_env_of(homes[0]),
        capture_output=True,
        text=True,
        timeout=180,
    ).stdout
    check(
        "memory: Hermes says holographic is the provider, installed",
        "Provider:  holographic" in status and "installed ✓" in status,
        status[:300],
    )


def fallback_in_hermes() -> None:
    """18. General settings → Fallback models: the saved chain is Hermes's own
    fallback_providers, ONE chain in Hermes's managed scope that every root and
    member reads (Hermes's `config get` resolves it in each), no profile keeps a
    copy, Hermes refuses a profile's own, AGOS's database holds none of it, and a
    cleared list is Hermes's empty one."""
    import rooms_e2e as rig
    import yaml

    every = [
        str(r[0])
        for r in db().execute("SELECT id FROM workspaces WHERE deleted_at IS NULL").fetchall()
    ]
    homes = [
        h
        for ws in every
        for h in (root_of(ws), *sorted((root_of(ws) / "profiles").glob("*")))
        if (h / "config.yaml").is_file() and not h.name.startswith(".")
    ]
    managed = rig.E / "hermes-managed" / "config.yaml"
    marker = "e2e-fallback/model-s22"
    chain = [
        {"provider": "openrouter", "mode": "api", "model": marker},
        {"provider": "nous", "model": "e2e-second"},
    ]
    want = [
        {"provider": "openrouter", "model": marker},
        {"provider": "nous", "model": "e2e-second"},
    ]
    view = api("PUT", "/preferences/hermes-fallback", {"chain": chain})
    check(
        "fallback: the card counts every root and member",
        view["profiles"] == len(homes) and view["spread"] == [],
        f"{view['profiles']} vs {len(homes)}",
    )
    held = (yaml.safe_load(managed.read_text()) or {}).get("fallback_providers")
    check("fallback: the saved chain is in Hermes's managed scope", held == want, str(held))
    copies = {
        str(h): (yaml.safe_load((h / "config.yaml").read_text()) or {}).get("fallback_providers")
        for h in homes
    }
    check(
        "fallback: no profile keeps a copy",
        all(v is None for v in copies.values()),
        json.dumps(copies)[:600],
    )
    check(
        "fallback: Hermes resolves it in every root and member (config get)",
        all(hermes_value(h, "fallback_providers") == want for h in (homes[0], homes[-1])),
        str(hermes_value(homes[-1], "fallback_providers")),
    )
    con = db()
    tables = [
        t
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        if any(
            marker in json.dumps([str(v) for v in tuple(row)])
            for row in con.execute(f'SELECT * FROM "{t}"').fetchall()
        )
    ]
    check("fallback: no AGOS table holds the chain", tables == [], str(tables))
    # A profile can't take its own: Hermes refuses a key its managed scope pins.
    refused = subprocess.run(
        [rig_hermes(), "config", "set", "fallback_providers", "[]"],
        env=hermes_env_of(homes[-1]),
        capture_output=True,
        timeout=120,
        check=False,
    )
    check(
        "fallback: Hermes refuses a profile's own chain (managed)",
        refused.returncode != 0
        and (yaml.safe_load((homes[-1] / "config.yaml").read_text()) or {}).get(
            "fallback_providers"
        )
        is None,
        refused.stderr.decode()[-300:],
    )
    api("PUT", "/preferences/hermes-fallback", {"chain": []})
    check(
        "fallback: a cleared list is Hermes's empty one for everyone",
        (yaml.safe_load(managed.read_text()) or {}).get("fallback_providers") == []
        and hermes_value(homes[-1], "fallback_providers") == [],
    )


def rig_hermes() -> str:
    import rooms_e2e as rig

    return str(rig.HERMES)


def tool_keys_in_hermes(alpha: str, bravo: str) -> None:
    """19. Workspace → Keys: a key for the workspace's tools is a line of its root's
    .env (Hermes's writer) and a name in its terminal.env_passthrough; a command
    Hermes runs gets it as $NAME; Hermes's own provider key gets a TOOLS_ copy; the
    other workspace sees none of it; the key is in no answer, log or AGOS table."""
    import sys

    import yaml

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hrun
    import rooms_e2e as rig

    secret = "e2e-tool-key-" + base64.b32encode(os.urandom(10)).decode().lower()
    root = root_of(alpha)
    shown = api("POST", f"/workspaces/{alpha}/tool-keys/name", {"app": "E2E Tool"})
    check(
        "keys: the name comes from the app's name", shown["name"] == "E2E_TOOL_API_KEY", str(shown)
    )
    answers = [json.dumps(shown)]
    saved = api("POST", f"/workspaces/{alpha}/tool-keys", {"app": "E2E Tool", "key": secret})
    answers.append(json.dumps(saved))
    env_lines = (root / ".env").read_text()
    listed = ((yaml.safe_load((root / "config.yaml").read_text()) or {}).get("terminal") or {}).get(
        "env_passthrough"
    )
    check("keys: the key is a line of the root's .env", f"E2E_TOOL_API_KEY={secret}" in env_lines)
    check(
        "keys: the name is in Hermes's passthrough list",
        listed == ["E2E_TOOL_API_KEY"],
        str(listed),
    )
    row = (saved.get("keys") or [{}])[0]
    check(
        "keys: the list shows app, name and last four only",
        row.get("app") == "E2E Tool" and row.get("endsWith") == secret[-4:],
        json.dumps(row),
    )
    tested = api("POST", f"/workspaces/{alpha}/tool-keys/E2E_TOOL_API_KEY/test")
    answers.append(json.dumps(tested))
    check("keys: Test says Hermes hands it to the tools", tested.get("ok") is True, str(tested))
    # As the root's gateway does at its start (gateway/run.py load_hermes_dotenv; AGOS
    # restarts it after a key change): the root's .env, then the command.
    code = (
        "import json\n"
        "from hermes_constants import get_hermes_home\n"
        "from hermes_cli.env_loader import load_hermes_dotenv\n"
        "load_hermes_dotenv(hermes_home=get_hermes_home())\n"
        "from tools.terminal_tool import terminal_tool\n"
        "print('AGOS-T ' + json.dumps(terminal_tool("
        '\'test -n "$E2E_TOOL_API_KEY" && echo HAS-KEY-$(printf %s "$E2E_TOOL_API_KEY" | wc -c)\', '
        "task_id='agos-e2e-keys')))\n"
    )
    ran = subprocess.run(
        hrun.runtime_argv(rig.HERMES),
        input=code,
        capture_output=True,
        text=True,
        env=rig.hermes_env(root),
        timeout=180,
        check=False,
    )
    out = (ran.stdout + ran.stderr).replace(secret, "<key>")
    check(
        "keys: a command Hermes runs reads it as $NAME",
        f"HAS-KEY-{len(secret)}" in ran.stdout and secret not in ran.stdout + ran.stderr,
        out[-300:],
    )
    before = [
        ln
        for ln in (root / ".env").read_text().splitlines()
        if ln.startswith("OPENROUTER_API_KEY=")
    ]
    gpt = api("POST", f"/workspaces/{alpha}/tool-keys", {"app": "OpenRouter", "key": secret + "x"})
    answers.append(json.dumps(gpt))
    check(
        "keys: OpenRouter's tools key is TOOLS_OPENROUTER_API_KEY",
        gpt.get("savedName") == "TOOLS_OPENROUTER_API_KEY"
        and [
            ln
            for ln in (root / ".env").read_text().splitlines()
            if ln.startswith("OPENROUTER_API_KEY=")
        ]
        == before,
        str(gpt.get("savedName")),
    )
    other = api("GET", f"/workspaces/{bravo}/tool-keys")
    check("keys: the other workspace lists none", other.get("keys") == [], str(other))
    check(
        "keys: the other workspace's root has none",
        "E2E_TOOL_API_KEY" not in (root_of(bravo) / ".env").read_text(),
    )
    soul = (root / "SOUL.md").read_text()
    check(
        "keys: the Co-Founder knows the name, not the key",
        "$E2E_TOOL_API_KEY" in soul and secret not in soul,
    )
    for name in ("E2E_TOOL_API_KEY", "TOOLS_OPENROUTER_API_KEY"):
        answers.append(json.dumps(api("DELETE", f"/workspaces/{alpha}/tool-keys/{name}")))
    listed = ((yaml.safe_load((root / "config.yaml").read_text()) or {}).get("terminal") or {}).get(
        "env_passthrough"
    )
    check(
        "keys: Delete takes it out of the .env and the list",
        "E2E_TOOL_API_KEY" not in (root / ".env").read_text() and listed == [],
        str(listed),
    )
    leaks = [a[:80] for a in answers if secret in a]
    for path in E.rglob("*"):
        if path.is_file() and path.name != ".env" and path.stat().st_size < 50_000_000:
            with contextlib.suppress(OSError):
                if secret.encode() in path.read_bytes():
                    leaks.append(str(path))
    check("keys: the key is in no answer, log or database", leaks == [], str(leaks[:5]))


def hermes_env_of(home: Path) -> dict[str, str]:
    import rooms_e2e as rig

    return rig.hermes_env(home)


# ---- step 17: the time on every path, and the chat moves to Hermes --------------------

STAMP_RE = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"


def _stamps(text: str) -> int:
    import re

    return len(re.findall(STAMP_RE, text))


def time_and_chats(ws: str, group: int) -> None:
    """Agents always know the real time (once), and the chat features are Hermes's:
    /yolo, titles, the Daily digest, turn ends, Telegram media."""
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo

    zone = "Africa/Casablanca"
    api("PUT", "/preferences/timezone", {"timezone": zone})
    root = root_of(ws)
    for home in (root, root / "profiles" / "a-writer"):
        env = hermes_value(home, "terminal.docker_env") or {}
        check(
            f"time: {home.name}'s sandbox has the owner's TZ (terminal.docker_env)",
            isinstance(env, dict) and env.get("TZ") == zone,
            json.dumps(env),
        )
    # A room (group chat) turn: Hermes's TUI path, no gateway stamp; the hook adds it.
    since = time.time()
    n = len(agent_msgs(ws, group))
    post(ws, group, "write a short poem about the time")
    settle(ws, group, n, "FINAL")
    room = [r for r in llm_log() if float(r.get("at") or 0) > since and r.get("who")]
    check(
        "time: every room turn sees the current time exactly once (pre_llm_call)",
        bool(room)
        and all(
            _stamps(str(r["prompt"])) == 1 and "[Current time: " in str(r["prompt"]) for r in room
        ),
        json.dumps([str(r["prompt"])[-160:] for r in room[:3]]),
    )
    # The Co-Founder's DM and a member's DM: Hermes's gateway stamps them; never twice.
    cofounder_dm = next(
        c["id"] for c in api("GET", f"/workspaces/{ws}/workers")["dms"] if not c["agent"]
    )
    writer_dm = api("POST", f"/workspaces/{ws}/workers/dm", {"agent": "writer"})["id"]
    for label, chat in (("Co-Founder DM", cofounder_dm), ("writer DM", writer_dm)):
        words = f"what time is it {label} {int(time.time())}"
        n = len(agent_msgs(ws, chat))
        post(ws, chat, words)
        settle(ws, chat, n, "DM answer", 180)
        asked = [r for r in llm_log() if words in str(r.get("prompt")) and r.get("topic")]
        prompt = str(asked[0].get("prompt")) if asked else ""
        check(
            f"time: {label} sees the current time exactly once (Hermes's gateway stamp)",
            bool(asked) and _stamps(prompt) == 1 and "[Current time: " not in prompt,
            prompt[:200],
        )
        # The stamp is when he sent it (the queue item's time), in his zone.
        sent = (
            db()
            .execute(
                "SELECT created_at FROM hermes_inbox WHERE text = ? ORDER BY id DESC LIMIT 1",
                (words,),
            )
            .fetchone()
        )
        shown = re.search(STAMP_RE, prompt)
        if sent is not None and shown is not None:
            when = datetime.fromisoformat(str(sent[0]).replace("Z", "+00:00"))
            local = when.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S")
            check(
                f"time: {label}'s stamp is the time he sent it, in his zone",
                shown.group(0) == local,
                f"{shown.group(0)} vs {local}",
            )
    workers = [r for r in llm_log() if str(r.get("prompt") or "").startswith("work kanban task")]
    check(
        "time: a Kanban worker (hermes chat -q) sees the current time exactly once",
        bool(workers)
        and all(
            _stamps(str(r["prompt"])) == 1 and "[Current time: " in str(r["prompt"])
            for r in workers
        ),
        json.dumps([str(r["prompt"])[:160] for r in workers[:2]]),
    )
    crons = [r for r in llm_log() if "automation hello from cron" in str(r.get("prompt") or "")]
    check(
        "time: a cron run sees the current time exactly once",
        bool(crons)
        and all(
            _stamps(str(r["prompt"])) == 1 and "[Current time: " in str(r["prompt"]) for r in crons
        ),
        json.dumps([str(r["prompt"])[-160:] for r in crons[:2]]),
    )
    # Hermes's on_session_end reaches AGOS (the turn's end, never agent.log).
    core_log = (E / "logs" / "core.log").read_text(errors="replace")
    check(
        "turns: Hermes's on_session_end reports each turn's end (turn-end)",
        f"/hermes-bridge/{ws}/turn-end" in core_log,
        str(core_log.count("/turn-end")),
    )

    # A chat's Full access: Hermes's own /yolo command (only when it differs).
    # Only what this switch sends (an earlier step toggled this chat too).
    before = db().execute("SELECT COALESCE(MAX(id), 0) FROM hermes_inbox").fetchone()[0]
    api("PUT", f"/workspaces/{ws}/chats/{cofounder_dm}", {"access": "full"})
    sent_yolo = (
        db()
        .execute(
            "SELECT kind, text FROM hermes_inbox WHERE chat_ref = ? AND text = '/yolo' AND id > ?",
            (f"agos:{cofounder_dm}", before),
        )
        .fetchall()
    )
    check(
        "access: Full access is Hermes's own /yolo command, on its routing entry",
        True in routing_yolo(ws, cofounder_dm)
        and [tuple(r) for r in sent_yolo] == [("command", "/yolo")],
        json.dumps([tuple(r) for r in sent_yolo]),
    )
    api("PUT", f"/workspaces/{ws}/chats/{cofounder_dm}", {"access": "full"})  # no change: no toggle
    check(
        "access: the same switch again sends no /yolo (it would toggle it off)",
        True in routing_yolo(ws, cofounder_dm),
        json.dumps(routing_yolo(ws, cofounder_dm)),
    )
    api("PUT", f"/workspaces/{ws}/chats/{cofounder_dm}", {"access": "ask"})
    check("access: Ask me = /yolo off", True not in routing_yolo(ws, cofounder_dm))
    time.sleep(3)
    noise = [b for _, b in agent_msgs(ws, cofounder_dm) if "YOLO mode" in b]
    check("access: Hermes's /yolo confirmations are not shown in the chat", not noise, str(noise))

    # Titles: Hermes decides; its refusal reaches the owner.
    first = api("POST", f"/workspaces/{ws}/chats", {"title": "Plan e2e"})["id"]
    other = api("POST", f"/workspaces/{ws}/chats", {"title": "Other e2e"})["id"]
    for chat in (first, other):
        n = len(agent_msgs(ws, chat))
        post(ws, chat, f"hello titles {chat}")
        settle(ws, chat, n, "DM answer", 180)
    api("PUT", f"/workspaces/{ws}/chats/{other}", {"title": "Plan e2e"})
    refused = soft_wait(
        "Hermes's title refusal in the chat",
        lambda: next(
            (
                m["body"]
                for m in messages(ws, other)
                if m["from"] == "agent" and "already in use" in m["body"]
            ),
            None,
        ),
        90,
    )
    title = api("GET", f"/workspaces/{ws}/chats/{other}").get("title")
    check(
        "titles: Hermes's refusal shows in the chat; the name stays Hermes's",
        bool(refused) and title == "Other e2e",
        f"{refused!r} {title!r}",
    )
    api("PUT", f"/workspaces/{ws}/chats/{other}", {"title": "Other e2e renamed"})
    renamed = soft_wait(
        "the rename in Hermes",
        lambda: (
            api("GET", f"/workspaces/{ws}/chats/{other}").get("title") == "Other e2e renamed"
            or None
        ),
        90,
    )
    check("titles: a free name is Hermes's /title", bool(renamed))

    # Daily digest: no Telegram card now, a line for the next digest. Its clock and
    # delivery are Hermes's: a no-agent cron job in the root, to the Co-Founder's place.
    api("PUT", "/preferences/notifications", {"rules": {"task.waiting": "batched"}})

    def digest_job_now() -> dict[str, Any] | None:
        try:
            data = json.loads((root_of(ws) / "cron" / "jobs.json").read_text())
        except (OSError, ValueError):
            return None
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        return next((j for j in jobs if j.get("name") == "agos-digest"), None)

    digest_job = None
    for _ in range(30):
        digest_job = digest_job_now()
        if digest_job:
            break
        time.sleep(2)
    found_job: dict[str, Any] = digest_job or {}
    check(
        "digest: a no-agent Hermes cron job at 9:00 delivers to his Telegram",
        found_job.get("no_agent") is True
        and found_job.get("schedule_display") == "0 9 * * *"
        and str(found_job.get("deliver") or "").startswith("telegram:")
        and (root_of(ws) / "scripts" / "agos-digest.py").is_file(),
        str(digest_job)[:300],
    )
    probe = Path("/tmp/agos-approval-probe")
    probe.mkdir(exist_ok=True)
    before = len(tg("/control/sent"))
    n = len(agent_msgs(ws, cofounder_dm))
    post(ws, cofounder_dm, "danger: clean the probe folder")
    wait("the approval in the chat", lambda: chat_asks(ws, cofounder_dm) or None, 180, 2)
    time.sleep(8)
    cards = [s for s in tg("/control/sent")[before:] if "ea:once:" in json.dumps(s)]
    held = (
        db()
        .execute("SELECT value FROM app_settings WHERE key = ?", (f"digest.held.{ws}",))
        .fetchone()
    )
    check(
        "digest: on Daily digest no card on the phone now, one line kept for the digest",
        not cards and held is not None and "rm -rf" in str(held[0]),
        f"{len(cards)} cards, held={str(held[0] if held else None)[:200]}",
    )
    api("POST", f"/workspaces/{ws}/chats/{cofounder_dm}/approval", {"choice": "once"})
    settle(ws, cofounder_dm, n, "", 180)
    api("PUT", "/preferences/notifications", {"rules": {"task.waiting": "instant"}})

    # A Telegram-linked chat: his file goes to Hermes as a file (Hermes's own handling).
    conn = int(state()["conn"])
    linked = api("POST", f"/workspaces/{ws}/chats", {"title": "Telegram files e2e"})["id"]
    address = api(
        "POST",
        f"/workspaces/{ws}/chats/{linked}/addresses",
        {"connectionId": conn, "address": "4242:0"},
    )
    secret = f"e2e-tg-file-{int(time.time())}"
    data = base64.b64encode(f"The note says {secret}.\n".encode()).decode()
    sent_before = len(tg("/control/sent"))
    post(
        ws,
        linked,
        "read the note",
        [{"kind": "file", "name": "note.txt", "mime": "text/plain", "data": data}],
    )
    asked = soft_wait(
        "the file at the model through Hermes's Telegram",
        lambda: next(
            (
                r
                for r in llm_log()
                if "read the note" in str(r.get("prompt")) and "note.txt" in str(r.get("prompt"))
            ),
            None,
        ),
        180,
    )
    prompt = str((asked or {}).get("prompt") or "")
    check(
        "telegram: his file reaches Hermes as a file (Hermes's own note), not AGOS text",
        # Hermes's own note (gateway/run.py "The user sent a text document"; AGOS
        # inlines nothing, so it says to read the file), never AGOS's "[File attached".
        bool(asked)
        and "The user sent a text document: " in prompt
        and "Its content is not inlined here" in prompt
        and "[File attached" not in prompt,
        prompt[:300],
    )
    answered = soft_wait(
        "the answer in Telegram",
        lambda: next(
            (
                s
                for s in tg("/control/sent")[sent_before:]
                if str(s.get("chat_id")) == "4242" and "DM answer" in str(s.get("text"))
            ),
            None,
        ),
        180,
    )
    check("telegram: Hermes answered it in Telegram", bool(answered))
    shown = soft_wait(
        "his message with its file in AGOS",
        lambda: next(
            (
                m
                for m in messages(ws, linked)
                if m["from"] == "owner" and m.get("attachments") and m["id"] < 1 << 49
            ),
            None,
        ),
        60,
    )
    check(
        "telegram: AGOS shows his file on Hermes's message",
        bool(shown),
        json.dumps(
            [
                (m["id"], m["body"][:60], len(m.get("attachments") or []))
                for m in messages(ws, linked)
            ]
        )[:400],
    )
    if isinstance(address, dict) and address.get("id"):
        api("DELETE", f"/workspaces/{ws}/chats/{linked}/addresses/{address['id']}")


def group_name_in_hermes(alpha: str, ga: int) -> None:
    """The group's name is its Hermes room's (AGOS keeps no copy); a rename is
    Hermes's own rename_room. Run last: a rename is a room event, and it changes
    what Hermes shows the members next (the fake model reads that)."""

    def room_names() -> dict[str, str]:
        path = root_of(alpha) / "shared-state.db"
        with contextlib.closing(
            sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        ) as con:
            return {
                str(a): str(b) for a, b in con.execute("SELECT room_id, name FROM hosted_rooms")
            }

    def own_title() -> str:
        with contextlib.closing(db()) as con:
            return str(con.execute("SELECT title FROM chats WHERE id = ?", (ga,)).fetchone()[0])

    room_id = str(
        db().execute("SELECT room_id FROM group_rooms WHERE chat_id = ?", (ga,)).fetchone()[0]
    )
    held = soft_wait("room name", lambda: own_title() == "" and room_names().get(room_id), 60)
    check(
        "room: the group's name is the Hermes room's, AGOS keeps no copy",
        held == f"Launch · #{ga}"
        and api("GET", f"/workspaces/{alpha}/chats/{ga}")["title"] == "Launch",
        f"{held!r} own={own_title()!r}",
    )
    api("PUT", f"/workspaces/{alpha}/chats/{ga}", {"title": "Launch room"})
    renamed = soft_wait(
        "room rename",
        lambda: own_title() == "" and room_names().get(room_id) == f"Launch room · #{ga}",
        90,
    )
    check(
        "room: a rename is Hermes's rename_room, shown from Hermes",
        bool(renamed) and api("GET", f"/workspaces/{alpha}/chats/{ga}")["title"] == "Launch room",
        f"{room_names().get(room_id)!r} own={own_title()!r}",
    )


def run() -> None:
    st = state()
    alpha, bravo = st["ws"]["Alpha"], st["ws"]["Bravo"]
    import rooms_e2e as rig

    wrong = rig.bridges_point_here()
    if wrong:
        raise SystemExit(f"bridge files name another core: {wrong[:3]}")
    ga, gb = int(st[f"group_{alpha}"]), int(st[f"group_{bravo}"])

    if FROM <= 1:
        # 1. Layout: one root per workspace, Co-Founder = root, members under it.
        for ws in (alpha, bravo):
            root = root_of(ws)
            check(f"{ws}: root is AGOS's", (root / ".agos-root").is_file(), str(root))
            check(
                f"{ws}: members under the root",
                all(
                    (root / "profiles" / m / "config.yaml").is_file()
                    for m in ("a-writer", "a-editor")
                ),
            )
            check(
                f"{ws}: nothing in the shared home",
                not (E / "home" / ".hermes" / "profiles" / f"agos-{ws}").exists(),
            )
            cfg = (root / "config.yaml").read_text()
            check(f"{ws}: no gateway.standalone shim", "standalone: true" not in cfg)
            # The screen is Hermes's Bot Desktop: the desktop image, in the sandbox.
            check(
                f"{ws}: screen is Hermes's (desktop image, placement terminal)",
                ":desktop" in cfg and "placement: terminal" in cfg and "headed: true" in cfg,
            )
            shown = api("GET", f"/workspaces/{ws}/screen")
            check(
                f"{ws}: Screen tab reads Hermes's config",
                shown["enabled"] == screen_in_hermes(root),
                str(shown),
            )
            # Its idle stop is Hermes's own bot_desktop.idle_stop_minutes (its default
            # from Hermes's settings list while the workspace sets none).
            check(
                f"{ws}: Screen tab says Hermes's idle stop",
                isinstance(shown.get("idleStopMinutes"), (int, float)),
                str(shown),
            )
            check(
                f"{ws}: no screen running in Hermes, no picture",
                api("GET", f"/workspaces/{ws}/screen.jpg") is None,
            )
            for home in (root, root / "profiles" / "a-writer"):
                env = (home / ".env").read_text()
                check(
                    f"{ws}/{home.name}: General Settings key synced",
                    "GEMINI_API_KEY=e2e-general-gemini-1" in env,
                )
        check(
            "no home got a runtime of its own (HERMES_RUNTIME_DIR)",
            not (E / "home" / ".hermes" / "tools").exists()
            and not any((E / "roots").glob("*/tools")),
        )

    if FROM <= 2:
        # 2. A room conversation from the AGOS web: Co-Founder directs writer and editor.
        n0 = len(agent_msgs(alpha, ga))
        post(alpha, ga, "write a short poem about the sea")
        got = settle(alpha, ga, n0, "FINAL")
        speakers = [s for s, _ in got]
        check(
            "room: Co-Founder delegates, writer + editor work, Co-Founder sums up",
            speakers[:1] == ["cofounder"]
            and "writer" in speakers
            and "editor" in speakers
            and speakers[-1] == "cofounder",
            json.dumps(got)[:600],
        )
        first_owner = [m for m in messages(alpha, ga) if m["from"] == "owner"][-1]["body"]
        check("room: the owner's words are shown as he wrote them", first_owner.startswith("write"))
        first_send = (
            db()
            .execute("SELECT text FROM hermes_inbox WHERE kind = 'room-send' ORDER BY id LIMIT 1")
            .fetchone()[0]
        )
        check(
            "room: his words go in as he wrote them (AGOS adds nothing to the room)",
            json.loads(first_send)["text"].startswith("write a short poem"),
            first_send[:200],
        )

    if FROM <= 3:
        # 3. Exactly once: the same messages after the gateway restarts.
        import rooms_e2e as rig

        before = agent_msgs(alpha, ga)
        rig.restart_gateway(root_of(alpha))  # what Hermes's service does after a crash
        time.sleep(10)
        check("restart: no message twice", agent_msgs(alpha, ga) == before)

    if FROM <= 4:
        # 4. Telegram: the group's topic mirrors the room, each reply with its author's name.
        conn = int(st["conn"])
        api(
            "POST",
            f"/workspaces/{alpha}/chats/{ga}/addresses",
            {"connectionId": conn, "address": f"{GROUP_CHAT}:41"},
        )
        n1 = len(agent_msgs(alpha, ga))
        tg("/control/message", {"chat": GROUP_CHAT, "topic": 41, "text": "one more line please"})
        got = settle(alpha, ga, n1, "FINAL")
        owner = [m for m in messages(alpha, ga) if m["from"] == "owner"][-1]["body"]
        check("telegram: his topic message reached the room", "one more line" in owner, owner)
        # Hermes's own send paces a group's messages (about one a second): wait for
        # the round's last reply.
        sent = wait(
            "telegram copies",
            lambda: (
                [
                    s
                    for s in tg("/control/sent")
                    if str(s.get("chat_id")) == GROUP_CHAT
                    and str(s.get("message_thread_id")) == "41"
                    and s.get("method") == "sendMessage"
                ]
                if any(
                    "FINAL" in str(s.get("text"))
                    for s in tg("/control/sent")
                    if str(s.get("message_thread_id")) == "41"
                )
                else None
            ),
            120,
            2,
        )
        # Telegram MarkdownV2 escapes the hyphen: "*Co\\-Founder:*".
        texts = [str(s.get("text") or "").replace("\\-", "-") for s in sent]
        check(
            "telegram: replies carry each agent's name",
            any("Co-Founder" in t for t in texts) and any("Writer" in t for t in texts),
            json.dumps(texts)[:600],
        )
        time.sleep(8)
        again = [
            s
            for s in tg("/control/sent")
            if str(s.get("message_thread_id")) == "41" and s.get("method") == "sendMessage"
        ]
        check(
            "telegram: each reply once",
            len(again) == len(sent) and len({t for t in texts}) == len(texts),
            f"{len(again)} vs {len(sent)}",
        )

    if FROM <= 4:
        # 4b. The members' "/" menu on Telegram follows the team: rebuilt when a group
        # or a member's job title changes (the core looks at marks, not profiles).
        members_menu(alpha, ga)

    if FROM <= 5:
        local_terminal(alpha)
        # 5. Files: saved in the workspace files, the room gets the path, a member opens it.
        secret = f"e2e-file-{int(time.time())}"
        data = base64.b64encode(f"The note says {secret}.\n".encode()).decode()
        n2 = len(agent_msgs(alpha, ga))
        post(
            alpha,
            ga,
            "@writer read file and tell me",
            [{"kind": "file", "name": "note.txt", "mime": "text/plain", "data": data}],
        )
        sent_text = wait(
            "room-send with the path",
            lambda: next(
                (
                    json.loads(r["text"])["text"]
                    for r in db().execute(
                        "SELECT text FROM hermes_inbox WHERE kind = 'room-send' ORDER BY id DESC LIMIT 1"
                    )
                    if "[File attached: note.txt" in r["text"]
                ),
                None,
            ),
            60,
        )
        check(
            "files: the room message names where it is saved",
            "saved at" in sent_text,
            sent_text[-200:],
        )
        stored = sorted(
            (E / "data" / "workspaces" / alpha).rglob("*note.txt"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        check("files: saved in the workspace files", bool(stored), str(stored[:1]))
        # Docker is not available here: the member's terminal is local, so the harness
        # asks it to read the host copy (the sandbox path is checked above).
        n2 = len(agent_msgs(alpha, ga))
        post(alpha, ga, f"@writer read file {stored[0]}")
        got = settle(alpha, ga, n2, "I read the file", 180)
        check(
            "files: a member opened it with its terminal tool",
            any(secret in b for _, b in got),
            json.dumps(got)[:400],
        )

    if FROM <= 6:
        # 6. An approval: writer runs a dangerous command; the chat's card + Allow once.
        probe = Path("/tmp/agos-approval-probe")
        probe.mkdir(exist_ok=True)
        n3 = len(agent_msgs(alpha, ga))
        post(alpha, ga, "@writer danger: clean the probe folder")
        # Hermes's own pending set (the room's status), shown in the chat's live answer.
        ask = wait("an approval in AGOS", lambda: chat_asks(alpha, ga) or None, 120, 2)
        check("approval: shown in the chat", chat_asks(alpha, ga))
        # The Telegram copy is sent beside the chat's card: wait for it (it can come
        # a moment after the chat shows the card).
        wait(
            "the approval in Telegram",
            lambda: [s for s in tg("/control/sent") if "rm -rf" in str(s.get("text"))] or None,
            60,
            1,
        )
        tg_ask = [s for s in tg("/control/sent") if "rm -rf" in str(s.get("text"))]
        check(
            "approval: shown in Telegram with buttons",
            bool(tg_ask) and bool(tg_ask[-1].get("reply_markup")),
            json.dumps(tg_ask[-1:])[:400],
        )
        api("POST", f"/workspaces/{alpha}/chats/{ga}/approval", {"choice": "once"})
        wait("the command ran", lambda: not probe.exists(), 120, 2)
        check(
            "approval: answered via approve_room_task, the command ran",
            not probe.exists(),
            str(ask),
        )
        settle(alpha, ga, n3, "", 120)

    if FROM <= 7:
        # 7. Stop: Hermes's stop_room.
        post(alpha, ga, "pingpong")
        wait("room working", lambda: working(alpha, ga), 60, 1)
        time.sleep(3)
        api("POST", f"/workspaces/{alpha}/chats/{ga}/stop")
        wait("room stopped", lambda: not working(alpha, ga), 60, 1)
        stop = wait(
            "stop_room in the log",
            lambda: (
                db()
                .execute("SELECT 1 FROM room_events WHERE kind = 'room.stop_requested'")
                .fetchone()
            ),
            60,
            2,
        )
        check("stop: AGOS's Stop is Hermes's stop_room", bool(stop))

    if FROM <= 8:
        # 8. max_rounds: the room ping-pongs until Hermes's own limit stops it; AGOS
        # adds nothing to the room (no continuation of its own).
        n4 = len(agent_msgs(alpha, ga))
        post(alpha, ga, "@cofounder pingpong again")
        got = list(
            wait(
                "the room stops at its limit",
                lambda: (
                    agent_msgs(alpha, ga)[n4:]
                    if len(agent_msgs(alpha, ga)) > n4 + 1 and not working(alpha, ga)
                    else None
                ),
                400,
                3,
            )
        )
        check(
            "max_rounds: Hermes stopped the room, AGOS added nothing",
            bool(got) and not any(s == "AGOS" and "carry on" in b for s, b in got),
            json.dumps(got)[-600:],
        )

    if FROM <= 9:
        # 9. Isolation: a room in Bravo naming a profile only Alpha has is refused by Hermes.
        with contextlib.suppress(RuntimeError):  # made by an earlier run of this step
            api(
                "POST",
                f"/workspaces/{alpha}/agents",
                {"name": "researcher", "title": "Researcher", "definition": {"instructions": "x"}},
            )
        wait(
            "alpha researcher",
            lambda: (root_of(alpha) / "profiles" / "a-researcher" / "agos-bridge.json").is_file(),
            300,
            3,
        )
        con = db()
        job = {
            "room_id": f"agos-c{gb}-g9",
            "name": "cross",
            "disband": None,
            "members": [
                {"member_id": "cofounder", "profile": "default", "handle": "cofounder"},
                {"member_id": "researcher", "profile": "a-researcher", "handle": "researcher"},
            ],
        }
        con.execute(
            """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)
                       VALUES (?, ?, ?, 'room-sync', strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
            (bravo, f"room:{gb}", json.dumps(job)),
        )
        con.commit()
        if not working(bravo, gb):  # Bravo's gateway runs (its room) — make sure
            post(bravo, gb, "hello team")
        refused = wait(
            "Bravo refuses the foreign member",
            lambda: (
                db()
                .execute(
                    "SELECT text FROM activity WHERE workspace_id = ? AND kind = 'room.refused'",
                    (bravo,),
                )
                .fetchone()
            ),
            240,
            3,
        )
        check(
            "isolation: a member of workspace A can't be seated in B's room",
            bool(refused),
            str(refused[0] if refused else ""),
        )
        rooms_b = subprocess.run(
            [
                "sqlite3",
                str(root_of(bravo) / "shared-state.db"),
                "SELECT room_id FROM hosted_rooms",
            ],
            capture_output=True,
            text=True,
        ).stdout
        check(
            "isolation: no such room exists in B", f"agos-c{gb}-g9" not in rooms_b, rooms_b.strip()
        )

    if FROM <= 10:
        # 10. Membership change: disband + recreate, history kept.
        hist = len(messages(alpha, ga))
        api("PUT", f"/workspaces/{alpha}/workers/groups/{ga}/members", {"members": ["writer"]})
        n5 = len(agent_msgs(alpha, ga))
        post(alpha, ga, "write one more")
        settle(alpha, ga, n5, "FINAL", 240)
        row = (
            db()
            .execute("SELECT room_id, generation FROM group_rooms WHERE chat_id = ?", (ga,))
            .fetchone()
        )
        check(
            "members changed: a new room generation",
            int(row["generation"]) >= 2,
            dict(row).__repr__(),
        )
        check("members changed: AGOS history kept", len(messages(alpha, ga)) > hist)

    if FROM <= 11:
        # 11. DMs keep working on the new roots (the Co-Founder's and a member's).
        dms = api("GET", f"/workspaces/{alpha}/workers")["dms"]
        cofounder_dm = next(
            (
                c["id"]
                for c in api("GET", f"/workspaces/{alpha}/chats")
                if c.get("kind") in ("chat", "dm") and not c.get("agent")
            ),
            None,
        )
        writer_dm = api("POST", f"/workspaces/{alpha}/workers/dm", {"agent": "writer"})["id"]
        for label, chat in (("Co-Founder DM", cofounder_dm), ("writer DM", writer_dm)):
            if chat is None:
                check(f"{label}: exists", False, json.dumps(dms)[:200])
                continue
            n = len(agent_msgs(alpha, chat))
            post(alpha, chat, f"hello from the {label}")
            got = settle(alpha, chat, n, "DM answer", 180)
            check(f"{label}: answered on the root", any("DM answer" in b for _, b in got))
            # Its model is Hermes's (its session), how it ended Hermes's on_session_end; its
            # tokens are Hermes's count (session_model_usage). AGOS keeps no copy.
            turns = api("GET", f"/workspaces/{alpha}/chats/{chat}").get("turns") or []
            record = (
                db()
                .execute("SELECT * FROM chat_turns WHERE chat_id = ? ORDER BY id DESC", (chat,))
                .fetchone()
            )
            check(
                f"{label}: the answer's model is Hermes's, AGOS's record has no copy",
                bool(turns)
                and bool(turns[-1].get("model"))
                and record is not None
                and not {"usage", "provider", "model"} & set(record.keys()),
                json.dumps(turns[-1:])[:300],
            )
            used = api("GET", f"/workspaces/{alpha}/overview")["usage"]
            check(
                f"{label}: tokens are Hermes's own count", int(used["tokens"]) > 0, str(used)[:200]
            )
            # What the agent is told comes from Hermes (SOUL.md, the chat's name as
            # the conversation's topic), never as AGOS text in his message.
            asked = [
                r
                for r in map(json.loads, (E / "logs" / "llm.jsonl").read_text().splitlines())
                if f"hello from the {label}" in str(r.get("prompt") or "")
                and r.get("topic")  # the conversation's turn (not Hermes's title call)
            ]
            check(
                f"{label}: rules from SOUL.md, nothing added to his message",
                bool(asked)
                and all(r.get("soulRules") for r in asked)
                and not any("[AGOS" in str(r.get("prompt")) for r in asked),
                json.dumps(asked[-1:])[:300],
            )
            check(
                f"{label}: the chat's name is Hermes's topic",
                bool(asked),
                str([r.get("topic") for r in asked]),
            )
            if label == "Co-Founder DM":
                check(
                    "Co-Founder DM: its view of the workspace is in SOUL.md",
                    bool(asked) and all(r.get("cofounderView") for r in asked),
                )
            else:
                check(
                    f"{label}: no Co-Founder's view in a member's SOUL.md",
                    bool(asked) and not any(r.get("cofounderView") for r in asked),
                )

    if FROM <= 13:
        # 13. Full access is Hermes's own approvals (Phase 5): the switch writes
        # approvals.mode off on the root and every member; a member's risky command
        # then runs without asking. Back to Ask me first: manual again.
        def approvals(home: Path) -> tuple[str, str]:
            got = [
                subprocess.run(
                    [rig.HERMES, "config", "get", key],
                    env=rig.hermes_env(home),
                    capture_output=True,
                    text=True,
                    timeout=120,
                ).stdout.strip()
                for key in ("approvals.mode", "approvals.cron_mode")
            ]
            return got[0], got[1]

        # A later profile sync (a new member, a membership change) puts the members'
        # terminal back on docker, which this machine lacks.
        local_terminal(alpha)
        root = root_of(alpha)
        homes = (root, root / "profiles" / "a-writer", root / "profiles" / "a-editor")
        rig.access(alpha, "Alpha", "full")
        seen = {h.name: approvals(h) for h in homes}
        check(
            "access: Full access = approvals.mode off on the root and every member",
            all(v == ("off", "approve") for v in seen.values()),
            json.dumps(seen),
        )
        # The root's gateway serves the members (Hermes multiplexing) and reads a
        # member's changed config at its next profile re-scan (every 30 s).
        time.sleep(35)
        probe = Path("/tmp/agos-approval-probe")
        probe.mkdir(exist_ok=True)
        asked_before = (
            db()
            .execute("SELECT count(*) FROM channel_outbox WHERE source LIKE 'roomask:%'")
            .fetchone()[0]
        )
        n6 = len(agent_msgs(alpha, ga))
        post(alpha, ga, "@writer danger: clean the probe folder")
        ran = wait("the command ran by itself", lambda: not probe.exists() or None, 180, 2)
        settle(alpha, ga, n6, "", 120)
        asked_after = (
            db()
            .execute("SELECT count(*) FROM channel_outbox WHERE source LIKE 'roomask:%'")
            .fetchone()[0]
        )
        check(
            "access: on Full access the command ran with no approval asked",
            bool(ran) and asked_after == asked_before,
            f"approval cards {asked_before} -> {asked_after}",
        )
        rig.access(alpha, "Alpha", "ask")
        seen = {h.name: approvals(h) for h in homes}
        check(
            "access: Ask me first = approvals.mode manual everywhere",
            all(v == ("manual", "approve") for v in seen.values()),
            json.dumps(seen),
        )

    if FROM <= 14:
        # 14. Telegram is Hermes's (Phase 9): an approval asked in an AGOS chat is
        # Hermes's own Telegram Allow / Deny card (its `ea:` buttons, resolved by
        # Hermes for that AGOS conversation), in the Co-Founder's place on the phone (the
        # bot's private chat with him); a member's DM (another profile of the root's
        # gateway) too. AGOS queues no card of its own; the chat shows it while it
        # waits. A stranger never reaches AGOS (Hermes's own allowlist).
        time.sleep(35)  # step 13's switch back to Ask me: the gateway re-reads profiles
        cofounder_dm = next(
            c["id"] for c in api("GET", f"/workspaces/{alpha}/workers")["dms"] if not c["agent"]
        )
        writer_dm = api("POST", f"/workspaces/{alpha}/workers/dm", {"agent": "writer"})["id"]
        probe = Path("/tmp/agos-approval-probe")
        for label, chat in (("Co-Founder DM", cofounder_dm), ("writer DM", writer_dm)):
            # A chat's Full access is Hermes's own /yolo of its conversation, kept on
            # its gateway routing entry (AGOS keeps no copy); Ask me turns it off.
            api("PUT", f"/workspaces/{alpha}/chats/{chat}", {"access": "full"})
            check(
                f"{label}: Full access = Hermes's /yolo on its conversation's routing entry",
                True in routing_yolo(alpha, chat)
                and api("GET", f"/workspaces/{alpha}/chats/{chat}")["access"] == "full",
                json.dumps(routing_yolo(alpha, chat)),
            )
            api("PUT", f"/workspaces/{alpha}/chats/{chat}", {"access": "ask"})
            check(
                f"{label}: Ask me = Hermes's /yolo off",
                True not in routing_yolo(alpha, chat)
                and api("GET", f"/workspaces/{alpha}/chats/{chat}")["access"] == "ask",
                json.dumps(routing_yolo(alpha, chat)),
            )
            probe.mkdir(exist_ok=True)
            sent_before = len(tg("/control/sent"))
            n = len(agent_msgs(alpha, chat))
            post(alpha, chat, "danger: clean the probe folder")

            def hermes_card(seen: int = sent_before) -> Any:
                for s in tg("/control/sent")[seen:]:
                    markup = json.dumps(s.get("reply_markup") or "")
                    if s.get("method") == "sendMessage" and "ea:once:" in markup:
                        return s
                return None

            sent = wait(f"{label}: Hermes's own approval card in Telegram", hermes_card, 180, 2)
            markup = sent.get("reply_markup") or {}
            if isinstance(markup, str):
                markup = json.loads(markup)
            choices = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
            check(
                f"{label}: Hermes's own Allow / Deny card, in the owner's chat with the bot",
                str(sent.get("chat_id")) == "4242"
                and any(d.startswith("ea:once:") for d in choices),
                json.dumps(sent)[:400],
            )
            check(
                f"{label}: AGOS queued no card of its own",
                db()
                .execute(
                    "SELECT count(*) FROM channel_outbox WHERE buttons LIKE ?",
                    (f'%"chatcmd:once:{chat}"%',),
                )
                .fetchone()[0]
                == 0,
            )
            check(f"{label}: the chat shows the waiting approval", chat_asks(alpha, chat))
            once = next(d for d in choices if d.startswith("ea:once:"))

            def asking(c: int = chat) -> bool:
                return chat_asks(alpha, c)

            # Someone Hermes doesn't let in presses it: it still waits.
            tg("/control/press", {"chat": "4242", "data": once, "from": 5151, "message": 9})
            time.sleep(6)
            check(
                f"{label}: a stranger's press answers nothing (Hermes's check)",
                asking() and working(alpha, chat),
            )
            tg("/control/press", {"chat": "4242", "data": once, "message": 9})
            got = settle(alpha, chat, n, "Tool said", 180)
            check(
                f"{label}: Hermes's button answered it, the command ran",
                any("Tool said" in b for _, b in got)
                and not any("denied" in b.lower() or "blocked" in b.lower() for _, b in got),
                json.dumps(got)[:300],
            )
            edited = [
                s
                for s in tg("/control/sent")[sent_before:]
                if s.get("method") == "editMessageText" and str(s.get("message_id")) == "9"
            ]
            check(f"{label}: Hermes closed its own card", bool(edited), json.dumps(edited)[:300])
            check(f"{label}: the AGOS card closed too", not chat_asks(alpha, chat))
            # The Log reads the chat's turns from Hermes (agent.log + its sessions):
            # this answer went through, so no failed answer shows for the chat.
            page = api("GET", f"/workspaces/{alpha}/log?area=chat")
            check(
                f"{label}: the Log (from Hermes's logs) shows no failed answer here",
                not any(
                    f"chat={chat}" in str(e.get("href")) or f"c={chat}" in str(e.get("href"))
                    for e in page["entries"]
                ),
                json.dumps(page["entries"])[:300],
            )
        # A stranger writing to the bot: Hermes's to turn away, AGOS never hears it.
        tg("/control/message", {"chat": "5151", "text": "stranger says hi", "from": 5151})
        time.sleep(10)
        chats = {int(c["id"]) for c in api("GET", f"/workspaces/{alpha}/chats")}
        chats |= {int(c["id"]) for c in api("GET", f"/workspaces/{alpha}/workers")["dms"]}
        stored = [
            c for c in chats | {ga} if any("stranger says" in m["body"] for m in messages(alpha, c))
        ]
        check(
            "telegram: a stranger never reaches AGOS (Hermes's allowlist)", not stored, str(stored)
        )
        pairing_by_hermes(alpha, ga)
        # The bot's lamp is Hermes's own state of it (gateway_state.json), read live.
        hermes_tg = (
            json.loads((root_of(alpha) / "gateway_state.json").read_text()).get("platforms") or {}
        ).get("telegram") or {}
        bot = next(b for b in api("GET", "/channels") if b["id"] == int(state()["conn"]))
        cols = {r[1] for r in db().execute("PRAGMA table_info(channel_connections)")}
        check(
            "telegram: the lamp is Hermes's gateway_state.json, no AGOS cache",
            hermes_tg.get("state") == "connected"
            and bot["status"] == "connected"
            and not {"status", "status_reason", "last_ok_at"} & cols,
            f"{hermes_tg} / {bot['status']}",
        )

    if FROM <= 15:
        # 15. Browser / Computer use on and off is only Hermes's config (Bravo).
        tool_ids = {t["name"]: t["id"] for t in api("GET", "/library?kind=tool")}
        broot = root_of(bravo)
        image = hermes_value(broot, "terminal.docker_image")
        for screen in (False, True):
            for name in ("browser", "computer_use"):
                api("PUT", f"/workspaces/{bravo}/connectors/{tool_ids[name]}", {"on": screen})
            check(
                f"screen {'on' if screen else 'off'}: Hermes's disabled_toolsets says so",
                screen_in_hermes(broot) is screen,
                json.dumps(hermes_value(broot, "agent.disabled_toolsets")),
            )
            check(
                f"screen {'on' if screen else 'off'}: the Screen tab follows Hermes",
                api("GET", f"/workspaces/{bravo}/screen")["enabled"] == screen,
            )
            check(
                f"screen {'on' if screen else 'off'}: same sandbox image (no switch)",
                hermes_value(broot, "terminal.docker_image") == image,
                image,
            )

    if FROM <= 12:
        # 12a. Kanban news are Hermes's notifier: a card AGOS made starts, the plugin's
        # claim hook subscribes the Co-Founder's conversation with `wake` only (the
        # owner's rule since c477b87: every card speaks once), and when the card ends
        # Hermes wakes the Co-Founder, whose own answer is the one message about it.
        cofounder_chat = next(
            (c["id"] for c in api("GET", f"/workspaces/{alpha}/workers")["dms"] if not c["agent"]),
            None,
        )
        card = api(
            "POST",
            f"/workspaces/{alpha}/kanban",
            {"title": "e2e notify card", "member": "cofounder"},
        )["id"]
        boards = list(root_of(alpha).rglob("kanban.db"))

        def subscribed() -> Any:
            for board in boards or list(root_of(alpha).rglob("kanban.db")):
                found = subprocess.run(
                    [
                        "sqlite3",
                        str(board),
                        "SELECT platform, chat_id, delivery_mode FROM kanban_notify_subs"
                        f" WHERE task_id = '{card}'",
                    ],
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if found:
                    return found
            return None

        sub = wait("the card's Hermes subscription", subscribed, 240, 3)
        # /task is Hermes's skill command (AGOS's shared `task` skill): the Co-Founder's
        # Hermes makes the card with its own kanban_create; AGOS catches nothing.
        post(alpha, int(cofounder_chat or 0), "/task e2e skill card")

        def task_card() -> Any:
            for board in list(root_of(alpha).rglob("kanban.db")):
                found = subprocess.run(
                    [
                        "sqlite3",
                        str(board),
                        "SELECT id FROM tasks WHERE title = 'e2e skill card'",
                    ],
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if found:
                    return found
            return None

        made = wait("the /task card on Hermes's board", task_card, 240, 3)
        check("/task: Hermes's skill command made the card", bool(made), str(made))
        check(
            "kanban: the Co-Founder's conversation follows the card (Hermes's wake only)",
            sub in (f"agos|{cofounder_chat}|wake",)
            or (str(sub).startswith("telegram|") and str(sub).endswith("|wake")),
            str(sub),
        )

        def told() -> Any:
            got = [b for _, b in agent_msgs(alpha, int(cofounder_chat or 0)) if card in b]
            return got or None

        said = wait("the Co-Founder's own message about the card", told, 300, 3)
        check(
            "kanban: Hermes woke the Co-Founder, its answer tells the card is done",
            bool(said) and any(b.startswith("Co-Founder here:") for b in said),
            str(said)[:300],
        )
        check(
            "kanban: no Hermes notice line beside it (one message per card)",
            not [b for b in said if b.lstrip().startswith("✔")],
            str(said)[:300],
        )

    if FROM <= 14:
        # 14. What a workspace has on lives in its Hermes config (no AGOS copy):
        # MCP servers, tools, apps in the root's config.yaml (members get a copy),
        # the owner's rules as the agos-guard prompt section (master: the shared
        # home's USER.md, no copy in any root or member). Old AGOS rows move in once.

        def hermes_get(home: Path, key: str) -> Any:
            done = subprocess.run(
                [rig.HERMES, "config", "get", key, "--json"],
                env=rig.hermes_env(home),
                capture_output=True,
                text=True,
                timeout=120,
            )
            try:
                return json.loads(done.stdout)
            except ValueError:
                return None

        mark = "[The owner's rule for every workspace, set in AGOS] "
        # a) Every web screen reads Hermes's own state, and the finished moves and the
        # copies of Hermes's state are gone (step 17).
        root = root_of(alpha)
        from agos_core.actions.kanban_board import EVENTS

        def board_feed(ws: str) -> list[int]:
            """The board's latest events, read from Hermes's own kanban.db."""
            path = root_of(ws) / "kanban.db"
            if not path.is_file():
                return []
            with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as k:
                marks = ",".join("?" * len(EVENTS))
                return [
                    int(r[0])
                    for r in k.execute(
                        f"SELECT id FROM task_events WHERE kind IN ({marks})"
                        " ORDER BY id DESC LIMIT 20",
                        tuple(EVENTS),
                    )
                ]

        feed = api("GET", f"/workspaces/{alpha}/activity")
        other_feed = api("GET", f"/workspaces/{bravo}/activity")
        check(
            "dashboard: Board activity is Hermes's Kanban events of this workspace's board",
            bool(feed)
            and [i["id"] for i in feed] == board_feed(alpha)
            and [i["id"] for i in other_feed] == board_feed(bravo)
            and all(i["taskId"] and "“" in i["text"] for i in feed),
            json.dumps(feed[:3])[:300],
        )
        bots = api("GET", f"/workspaces/{alpha}/bots")
        env_token = next(
            (
                line.split("=", 1)[1].strip()
                for line in (root / ".env").read_text().splitlines()
                if line.startswith("TELEGRAM_BOT_TOKEN=")
            ),
            "",
        )
        check(
            "channels: a workspace page gets only its own bots; the token's end is Hermes's .env",
            [b["id"] for b in bots] == [int(st["conn"])]
            and all(b["workspaceId"] == alpha for b in bots)
            and int(st["conn"]) not in [b["id"] for b in api("GET", f"/workspaces/{bravo}/bots")]
            and bool(env_token)
            and bots[0]["secret"] == "••••" + env_token[-4:],
            json.dumps(bots)[:300],
        )
        skill = "---\nname: e2e-notes\ndescription: Keeps e2e notes.\n---\nWrite notes.\n"
        made_skill = api(
            "POST",
            f"/workspaces/{alpha}/skills",
            {"name": "e2e-notes", "definition": {"text": skill}},
        )
        listed = {i["id"]: i for i in api("GET", f"/workspaces/{alpha}/skills")}
        stored = (
            db()
            .execute("SELECT summary FROM library_items WHERE id = ?", (made_skill["id"],))
            .fetchone()[0]
        )
        check(
            "skills: a skill's summary is its SKILL.md description (no AGOS copy)",
            listed[made_skill["id"]]["summary"] == "Keeps e2e notes." and stored == "",
            f"{listed[made_skill['id']]['summary']!r} {stored!r}",
        )
        own_skill = root / "skills" / "agos-library" / "e2e-notes" / "SKILL.md"
        check(
            "skills: a workspace's skill is one file in its own root (the Co-Founder's), "
            "none in another workspace",
            own_skill.is_file()
            and not (root_of(bravo) / "skills" / "agos-library" / "e2e-notes").exists()
            and api("GET", f"/workspaces/{bravo}/skills") == [],
            str(own_skill),
        )
        con = db()
        tables = {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master")}
        shapes = {
            t: {str(r[1]) for r in con.execute(f"PRAGMA table_info({t})")}
            for t in ("channel_connections", "message_rows", "chat_turns", "automations")
        }
        keys = [
            str(r[0])
            for r in con.execute(
                "SELECT key FROM app_settings WHERE key LIKE 'hooks.port.%'"
                " OR key LIKE 'chats.title_told.%' OR key = 'owner.timezone'"
            )
        ]
        con.close()
        check(
            "db: the finished moves' tables, columns and keys are gone",
            "workspace_connectors" not in tables
            and not {"secret", "secret_last4"} & shapes["channel_connections"]
            and not {"legacy", "hermes_uid"} & shapes["message_rows"]
            and "model" not in shapes["chat_turns"]
            and "job_digest" not in shapes["automations"]
            and keys == [],
            json.dumps({k: sorted(v) for k, v in shapes.items()})[:300] + str(keys),
        )
        # b) Changes from the AGOS UI are written into Hermes and read back from it.
        broot = root_of(bravo)
        gw_before = json.loads((broot / "gateway_state.json").read_text()).get("pid")
        made = api(
            "POST",
            f"/workspaces/{bravo}/mcp",
            {"name": "e2e-wiki", "definition": {"url": "https://example.com/mcp"}},
        )
        wiki = (hermes_get(broot, "mcp_servers") or {}).get("e2e-wiki") or {}
        check("ui: a new MCP server is an entry of the root's Hermes", wiki.get("enabled") is True)
        api(
            "PUT",
            f"/workspaces/{bravo}/connectors/{made['id']}",
            {"on": False, "allowedTools": [], "local": ""},
        )
        wiki = (hermes_get(broot, "mcp_servers") or {}).get("e2e-wiki") or {}
        listed = {c["name"]: c for c in api("GET", f"/workspaces/{bravo}/connectors")}
        check(
            "ui: off = Hermes's own enabled: false, and AGOS shows it from there",
            wiki.get("enabled") is False and listed["e2e-wiki"]["on"] is False,
            json.dumps(wiki),
        )
        check(
            "ui: Hermes's own MCP list knows it",
            "e2e-wiki"
            in subprocess.run(
                [rig.HERMES, "mcp", "list"],
                env=rig.hermes_env(broot),
                capture_output=True,
                text=True,
                timeout=120,
            ).stdout,
        )

        # c) MCP: an added, removed or switched server is Hermes's own reconcile (no
        # command from AGOS); an edited one is Hermes's /reload-mcp, with no confirm
        # (approvals.mcp_reload_confirm: false) and no /approve from AGOS.
        def commands(text: str) -> list[Any]:
            return (
                db()
                .execute(
                    """SELECT done_at FROM hermes_inbox WHERE workspace_id = ?
                         AND chat_ref LIKE 'agos:0%' AND text = ?""",
                    (bravo, text),
                )
                .fetchall()
            )

        def hermes_conf(home: Path, key: str) -> str:
            return subprocess.run(
                [rig.HERMES, "config", "get", key],
                env=rig.hermes_env(home),
                capture_output=True,
                text=True,
                timeout=120,
            ).stdout.strip()

        member_homes = (
            sorted((broot / "profiles").glob("*")) if (broot / "profiles").is_dir() else []
        )
        confirms = {
            h.name: hermes_conf(h, "approvals.mcp_reload_confirm") for h in [broot, *member_homes]
        }
        check(
            "mcp: every profile skips Hermes's /reload-mcp confirm",
            all(v.lower() == "false" for v in confirms.values()),
            json.dumps(confirms),
        )
        check(
            "mcp: add / off is Hermes's reconcile (no /reload-mcp)", commands("/reload-mcp") == []
        )
        api(
            "PUT",
            f"/workspaces/{bravo}/connectors/{made['id']}",
            {"on": True, "allowedTools": [], "local": ""},
        )

        def reconciled() -> Any:
            logs = broot / "logs"
            text = (
                "".join(p.read_text(errors="replace") for p in logs.glob("*.log") if p.is_file())
                if logs.is_dir()
                else ""
            )
            return ("e2e-wiki" in text and "MCP servers reconciled with config" in text) or None

        check(
            "mcp: Hermes's own reconcile took the switched-on server",
            bool(soft_wait("MCP reconcile", reconciled, 240)),
        )
        api(
            "PUT",
            f"/workspaces/{bravo}/connectors/{made['id']}",
            {"on": True, "allowedTools": ["search"], "local": ""},
        )

        def reloaded() -> Any:
            rows = commands("/reload-mcp")
            if not rows or not all(r["done_at"] for r in rows):
                return None
            with contextlib.closing(
                sqlite3.connect(f"file:{broot / 'state.db'}?mode=ro", uri=True)
            ) as h:
                said = h.execute(
                    "SELECT count(*) FROM messages WHERE content LIKE '%MCP servers have been reloaded%'"
                ).fetchone()[0]
            return said or None

        check(
            "mcp: an edited server is Hermes's own /reload-mcp, run with no confirm",
            bool(wait("reload-mcp", reloaded, 240, 3)),
        )
        check("mcp: AGOS sent no /approve", commands("/approve") == [])
        gw_after = json.loads((broot / "gateway_state.json").read_text()).get("pid")
        check(
            "mcp: the gateway was never stopped for an MCP change",
            gw_before == gw_after and not gone(gw_after or 0),
            f"{gw_before} -> {gw_after}",
        )
        api("POST", "/owner-rules", {"text": "e2e rule: say hi first."})
        homes = (
            E / "home" / ".hermes",
            root,
            root_of(bravo) / "profiles" / "a-editor",
        )
        rule = "e2e rule: say hi first."
        # The master: the shared Hermes home's USER.md (General Settings' home).
        shared_md = homes[0] / "memories" / "USER.md"
        check(
            "ui: an owner rule lives in the shared Hermes home's USER.md",
            mark + rule in (shared_md.read_text() if shared_md.is_file() else ""),
        )

        def no_copy(h: Path) -> bool:
            md = h / "memories" / "USER.md"
            return not md.is_file() or mark not in md.read_text()

        copies = {str(h): not no_copy(h) for h in homes[1:]}
        check(
            "ui: no root or member USER.md holds an AGOS copy of his rules",
            not any(copies.values()),
            json.dumps(copies),
        )

        # What each profile's agos-guard section gets (its own bridge key).
        def section_of(h: Path) -> str:
            bridge = json.loads((h / "agos-bridge.json").read_text())
            body = "{}"  # as the plugin posts it
            request = urllib.request.Request(
                f"{bridge['core'].rstrip('/')}/hermes-bridge/{bridge['workspace']}/owner-rules",
                data=body.encode(),
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {bridge['key']}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as reply:
                return str(json.loads(reply.read()).get("text") or "")

        sections = {str(h): rule in section_of(h) for h in homes[1:]}
        check(
            "ui: an owner rule reaches every root and member's agos-guard prompt section",
            all(sections.values()),
            json.dumps(sections),
        )
        # And the agent really has it: a new session's system prompt carries the
        # plugin section Hermes rendered (register_system_prompt_section).
        ask = f"e2e rules probe {int(time.time())}"
        fresh = api("POST", f"/workspaces/{bravo}/chats", {"title": "Rules e2e"})["id"]
        post(bravo, fresh, ask)
        rules_seen: dict[str, Any] | None = None
        for _ in range(120):
            rules_seen = next((r for r in llm_log() if ask in str(r.get("prompt"))), None)
            if rules_seen:
                break
            time.sleep(2)
        check(
            "ui: a new session's system prompt has his rule in the agos-guard section",
            bool(rules_seen) and rule in str((rules_seen or {}).get("ownerRules")),
            str((rules_seen or {}).get("ownerRules"))[:300],
        )

    if FROM <= 16:
        team_in_hermes(bravo)
        proposal_round_trip(bravo)
        question_round_trip(bravo)

    if FROM <= 12:
        # 12. The owner's launcher is untouched (as it was when this run started).
        launcher: dict[str, str] = st.get("launcher") or LAUNCHER
        for path, want in launcher.items():
            check(f"launcher unchanged: {Path(path).name}", md5(path) == want, md5(path))
        check("runtime used", Path(RUNTIME).is_dir())

    if FROM <= 13:
        # 13. Webhooks: Hermes's routes only.
        webhooks_on_hermes(bravo)

    if FROM <= 16:
        member_automations(alpha)

    if FROM <= 17:
        memory_plugin_everywhere(alpha, bravo)
        # 17. The time on every path; /yolo, titles, digest, turn ends, Telegram files.
        time_and_chats(alpha, ga)
        member_topic_on_hermes(alpha)

    if FROM <= 18:
        fallback_in_hermes()

    if FROM <= 19:
        tool_keys_in_hermes(alpha, bravo)

    if FROM <= 14:
        # Last: it kills the gateway on purpose.
        dm_turns_on_hermes(alpha)

    group_name_in_hermes(alpha, ga)
    ok = sum(1 for _, good, _ in RESULTS if good)
    say(f"RESULT {ok}/{len(RESULTS)} passed")
    (E / "logs" / "results.json").write_text(json.dumps(RESULTS, indent=1))
