"""A fake Telegram Bot API for real-Hermes end-to-end runs (no network, no bot).

Run: python fake_bot_api.py <port> <log file>

Hermes's Telegram adapter talks to it through `platforms.telegram.extra.base_url`
(http://127.0.0.1:<port>/bot). Every method call is logged as one JSON line; the
test injects what the owner writes with POST /control/message {chat, text, topic?,
from?} and presses with POST /control/press {chat, data, topic?, from?, message?}
(`from`: someone else than the owner); GET /control/sent lists what the bot sent,
GET /control/answered the notes shown on button taps.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

LOG = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/dev/null")
OWNER = 4242
BOT = {"id": 777000, "is_bot": True, "first_name": "AGOS e2e", "username": "agos_e2e_bot"}
_updates: list[dict[str, Any]] = []
_sent: list[dict[str, Any]] = []
_answered: list[dict[str, Any]] = []
_lock = threading.Condition()
_ids = {"msg": 5000, "topic": 60}  # topics AGOS makes: 61, 62… (41 is linked by hand)


def _person(params: dict[str, Any]) -> dict[str, Any]:
    """The owner, or someone else (`from`): a stranger to the bot."""
    who = int(params.get("from") or OWNER)
    name = "owner" if who == OWNER else f"stranger{who}"
    return {"id": who, "is_bot": False, "first_name": name.title(), "username": name}


def _chat(chat: str) -> dict[str, Any]:
    cid = int(chat)
    if cid < 0:
        return {"id": cid, "type": "supergroup", "title": "Team", "is_forum": True}
    return {"id": cid, "type": "private", "first_name": "Owner", "username": "owner"}


def _message(params: dict[str, Any], text: str) -> dict[str, Any]:
    _ids["msg"] += 1
    msg: dict[str, Any] = {
        "message_id": _ids["msg"],
        "date": int(time.time()),
        "chat": _chat(str(params.get("chat_id") or OWNER)),
        "from": BOT,
        "text": text,
    }
    if params.get("message_thread_id"):
        msg |= {"message_thread_id": int(params["message_thread_id"]), "is_topic_message": True}
    return msg


def handle(method: str, params: dict[str, Any]) -> Any:
    if method == "getMe":
        return BOT
    if method == "getUpdates":
        offset = int(params.get("offset") or 0)
        timeout = min(float(params.get("timeout") or 0), 2.0)
        with _lock:
            if not [u for u in _updates if u["update_id"] >= offset]:
                _lock.wait(timeout)
            return [u for u in _updates if u["update_id"] >= offset][:100]
    if method in ("sendMessage", "editMessageText", "sendPhoto", "sendDocument", "sendVoice"):
        text = str(params.get("text") or params.get("caption") or "")
        _sent.append(
            {
                "method": method,
                **{
                    k: params.get(k)
                    for k in ("chat_id", "message_thread_id", "text", "reply_markup", "message_id")
                },
            }
        )
        return _message(params, text)
    if method == "createForumTopic":
        _ids["topic"] += 1
        return {"message_thread_id": _ids["topic"], "name": params.get("name"), "icon_color": 0}
    if method == "getChat":
        return _chat(str(params.get("chat_id")))
    if method == "getChatMember":
        return {"status": "administrator", "user": BOT}
    if method == "getMyCommands":
        return []
    if method == "answerCallbackQuery":
        _answered.append({"id": params.get("callback_query_id"), "text": params.get("text")})
        return True
    if method == "getFile":
        return {"file_id": params.get("file_id"), "file_unique_id": "u", "file_size": 1}
    return True  # deleteWebhook, setMyCommands, sendChatAction, answerCallbackQuery, …


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        return

    def _reply(self, body: Any, code: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _params(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        kind = self.headers.get("content-type") or ""
        if "json" in kind:
            return dict(json.loads(raw or b"{}"))
        if "form-urlencoded" in kind:
            return {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        if "multipart" in kind:
            out: dict[str, Any] = {}
            for part in raw.split(b"--")[1:]:
                head, _, body = part.partition(b"\r\n\r\n")
                if b'name="' in head and b"filename=" not in head:
                    name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
                    out[name] = body.rstrip(b"\r\n").decode(errors="replace")
            return out
        return {}

    def do_GET(self) -> None:
        if self.path.startswith("/control/sent"):
            self._reply(_sent)
        elif self.path.startswith("/control/answered"):
            self._reply(_answered)
        else:
            self._reply({"ok": False}, 404)

    def do_POST(self) -> None:
        params = self._params()
        if self.path == "/control/message":
            with _lock:
                update_id = len(_updates) + 1
                msg = {
                    "message_id": 100 + update_id,
                    "date": int(time.time()),
                    "chat": _chat(str(params["chat"])),
                    "from": _person(params),
                    "text": params["text"],
                }
                if params.get("topic"):
                    msg |= {"message_thread_id": int(params["topic"]), "is_topic_message": True}
                _updates.append({"update_id": update_id, "message": msg})
                _lock.notify_all()
            self._reply({"ok": True})
            return
        if self.path == "/control/press":
            with _lock:
                update_id = len(_updates) + 1
                message = {
                    "message_id": int(params.get("message") or 7),
                    "date": int(time.time()),
                    "chat": _chat(str(params["chat"])),
                    "from": BOT,
                    "text": str(params.get("text") or "card"),
                }
                if params.get("topic"):
                    message |= {"message_thread_id": int(params["topic"]), "is_topic_message": True}
                _updates.append(
                    {
                        "update_id": update_id,
                        "callback_query": {
                            "id": f"cb{update_id}",
                            "chat_instance": "ci",
                            "from": _person(params),
                            "data": params["data"],
                            "message": message,
                        },
                    }
                )
                _lock.notify_all()
            self._reply({"ok": True})
            return
        method = self.path.rsplit("/", 1)[-1]
        result = handle(method, params)
        with LOG.open("a") as out:
            out.write(
                json.dumps({"at": time.time(), "method": method, "params": params})[:4000] + "\n"
            )
        self._reply({"ok": True, "result": result})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
