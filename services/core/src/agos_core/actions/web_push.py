"""Web Push: AGOS installed on his phone (or any browser) gets a notification.

A second phone place next to Telegram, for the installed AGOS app itself: an
agent waiting for his approval, one of AGOS's own cards (Allow once / Deny, a
token warning), and an answer that finished in a chat he started from AGOS.
Tapping opens that chat in AGOS. The owner's Telegram card stays as it is.

Standard Web Push (RFC 8030 / 8291 / 8292) with the `cryptography` and `httpx`
AGOS already has: a VAPID key pair made once (sealed in app_settings with the
master key), each browser's subscription in `push_subscriptions`, and the
message encrypted for that browser (aes128gcm). Every push is an outbox row
(`queue`, on the caller's connection: inside its Unit of Work it commits or rolls
back with the change); the outbox loop sends it (actions/outbox_push.py `send`),
retries it while the push service can't be reached, and never sends it twice. A
subscription the push service reports gone (404 / 410) is dropped there.

Owns: the push keys, subscriptions, crypto and payload, and what AGOS tells the
phone. Must not: send outside the outbox loop.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import struct
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand

from agos_core.actions import staging
from agos_core.context import Core
from agos_core.db import push_subscriptions as push_rows
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.rows import now
from agos_core.outbox import delivery
from agos_core.security.secrets import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

SETTING = "push.vapid"
SEAL_CONTEXT = "push.vapid.private"
SUBJECT = "mailto:owner@agos.local"
RECORD_SIZE = 4096
TTL = 24 * 3600
TIMEOUT = 10.0
CHANNEL = "push"  # the outbox channel (actions/outbox_push.py sends it)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---- keys ------------------------------------------------------------------


def _private_key(core: Core) -> ec.EllipticCurvePrivateKey:
    saved = get_setting(core.db, SETTING, None)
    if isinstance(saved, dict) and saved.get("private"):
        raw = unb64url(decrypt_secret(core.master_key, str(saved["private"]), SEAL_CONTEXT))
        return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    set_setting(
        core.db,
        SETTING,
        {
            "private": encrypt_secret(core.master_key, b64url(raw), SEAL_CONTEXT),
            "public": b64url(_uncompressed(key.public_key())),
        },
    )
    return key


def _uncompressed(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def public_key(core: Core) -> str:
    """The VAPID public key the browser subscribes with (base64url, 65 bytes)."""
    return b64url(_uncompressed(_private_key(core).public_key()))


# ---- subscriptions ---------------------------------------------------------


def subscribe(core: Core, endpoint: str, p256dh: str, auth: str, label: str) -> None:
    if not endpoint.startswith("https://") or len(endpoint) > 2000:
        raise ValueError("not a push endpoint")
    if len(unb64url(p256dh)) != 65 or len(unb64url(auth)) != 16:
        raise ValueError("bad subscription keys")
    push_rows.save(core.db, endpoint, p256dh, auth, label[:120], now())


def unsubscribe(core: Core, endpoint: str) -> bool:
    return push_rows.drop(core.db, endpoint)


def subscriptions(core: Core) -> list[dict[str, Any]]:
    return push_rows.listed(core.db)


# ---- sending ---------------------------------------------------------------


def queue(
    core: Core,
    title: str,
    body: str,
    *,
    url: str = "/",
    tag: str = "",
    where: str = "",
    dedupe_key: str | None = None,
    workspace_id: str | None = None,
) -> int | None:
    """One push as an outbox row on the caller's connection; None when this dedupe
    key is queued already. The outbox loop sends it after the commit."""
    payload = {
        "title": title[:120],
        "body": body[:400],
        "url": url,
        "tag": tag[:80],
        "where": where,
    }
    row_id = delivery.enqueue(
        core.db, CHANNEL, payload, workspace_id=workspace_id, dedupe_key=dedupe_key
    )
    delivery.wake()
    return row_id


def notify(
    core: Core,
    title: str,
    body: str,
    *,
    url: str = "/",
    tag: str = "",
    where: str = "",
    dedupe_key: str | None = None,
    workspace_id: str | None = None,
) -> int:
    """Queues a notification to every subscribed browser; returns how many.
    `tag` folds repeats of the same thing into one; `where` tells the app which
    chat it is about (it stays quiet when he is looking at that chat already).
    A staging copy (actions/staging.py) sends none."""
    if staging.on():
        return 0
    subs = subscriptions(core)
    if not subs:
        return 0
    queue(
        core,
        title,
        body,
        url=url,
        tag=tag,
        where=where,
        dedupe_key=dedupe_key,
        workspace_id=workspace_id,
    )
    return len(subs)


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


def send_one(
    http: httpx.Client,
    key: ec.EllipticCurvePrivateKey,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: bytes,
) -> int:
    body = encrypt(payload, unb64url(p256dh), unb64url(auth))
    parts = urlsplit(endpoint)
    token = vapid_token(key, f"{parts.scheme}://{parts.netloc}")
    response = http.post(
        endpoint,
        content=body,
        headers={
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL),
            "Urgency": "high",
            "Authorization": f"vapid t={token}, k={b64url(_uncompressed(key.public_key()))}",
        },
    )
    return response.status_code


def vapid_token(
    key: ec.EllipticCurvePrivateKey, audience: str, *, lifetime: int = 12 * 3600
) -> str:
    """RFC 8292: a short-lived ES256 JWT for one push service."""
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64url(
        json.dumps(
            {"aud": audience, "exp": int(time.time()) + lifetime, "sub": SUBJECT},
            separators=(",", ":"),
        ).encode()
    )
    signing = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(key.sign(signing, ec.ECDSA(hashes.SHA256())))
    return f"{header}.{claims}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def encrypt(
    plaintext: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    *,
    as_private: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 (aes128gcm, one record): the message only that browser can read.
    `as_private` / `salt` are fixed only by the test (the RFC's own example)."""
    if len(plaintext) > RECORD_SIZE - 17:
        raise ValueError("push message too long")
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _uncompressed(as_private.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_private.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(shared)
    # One PRK (HKDF-Extract), expanded twice: the content key and the nonce.
    prk = _hkdf_extract(salt, ikm)
    cek = HKDFExpand(
        algorithm=hashes.SHA256(), length=16, info=b"Content-Encoding: aes128gcm\x00"
    ).derive(prk)
    nonce = HKDFExpand(
        algorithm=hashes.SHA256(), length=12, info=b"Content-Encoding: nonce\x00"
    ).derive(prk)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!I", RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + record


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, "sha256").digest()


# ---- what AGOS tells the phone --------------------------------------------


def chat_url(workspace_id: str, chat_id: int | None) -> str:
    base = f"/w/{workspace_id}/sessions"
    return f"{base}?chat={chat_id}" if chat_id else base


def card(core: Core, workspace_id: str, body: str, chat_id: int | None, source: str) -> int:
    """One of AGOS's own cards (an Allow once / Deny, a token warning): the phone
    shows the first line; the app opens the chat where the buttons are."""
    from agos_core.db.workspaces import name_of

    text = " ".join(body.replace("**", "").split())
    return notify(
        core,
        name_of(core.db, workspace_id) or workspace_id,
        text,
        url=chat_url(workspace_id, chat_id),
        tag=f"card:{source}",
        where=chat_url(workspace_id, chat_id),
        dedupe_key=f"card:{workspace_id}:{source}",  # one push per card, like its Telegram row
        workspace_id=workspace_id,
    )


def waiting(core: Core, workspace_id: str, chat_id: int, what: str) -> int:
    """Hermes asks his approval in an AGOS chat."""
    from agos_core.db.chats import title_of
    from agos_core.db.workspaces import name_of

    title = title_of(core.db, chat_id) or "a chat"
    return notify(
        core,
        f"{name_of(core.db, workspace_id) or workspace_id} · {title}",
        "Waiting for your approval" + (f": {what[:200]}" if what else ""),
        url=chat_url(workspace_id, chat_id),
        tag=f"waiting:{chat_id}",
        where=chat_url(workspace_id, chat_id),
        workspace_id=workspace_id,
    )


def answered(core: Core, workspace_id: str, chat_id: int, text: str) -> int:
    """An answer finished in a chat he started from AGOS (not a Telegram one:
    Telegram tells him itself). Quiet when nothing was said."""
    from agos_core.db.chats import title_of
    from agos_core.db.workspaces import name_of

    row = core.db.execute(
        "SELECT kind, channel FROM chats WHERE id = ? AND workspace_id = ?", (chat_id, workspace_id)
    ).fetchone()
    if row is None or (row["channel"] or "") == "telegram":
        return 0
    line = " ".join(text.replace("**", "").split())
    if not line:
        return 0
    return notify(
        core,
        f"{name_of(core.db, workspace_id) or workspace_id} · {title_of(core.db, chat_id) or 'Chat'}",
        line[:280] + ("…" if len(line) > 280 else ""),
        url=chat_url(workspace_id, chat_id),
        tag=f"answer:{chat_id}",
        where=chat_url(workspace_id, chat_id),
        workspace_id=workspace_id,
    )
