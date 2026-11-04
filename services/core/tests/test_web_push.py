"""The installed app's notifications: RFC 8291's own example decrypts, the key
pair is one and sealed, subscriptions come and go, a send reaches each browser
once and a gone subscription is dropped."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from agos_core.actions import outbox_push, web_push
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.outbox import delivery

# RFC 8291 Appendix A: the example message and keys.
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def key_of(b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(web_push.unb64url(b64), "big"), ec.SECP256R1())


def test_rfc8291_example_encrypts_byte_for_byte() -> None:
    body = web_push.encrypt(
        RFC["plaintext"],  # type: ignore[arg-type]
        web_push.unb64url(RFC["ua_public"]),  # type: ignore[arg-type]
        web_push.unb64url(RFC["auth"]),  # type: ignore[arg-type]
        as_private=key_of(RFC["as_private"]),  # type: ignore[arg-type]
        salt=web_push.unb64url(RFC["salt"]),  # type: ignore[arg-type]
    )
    assert web_push.b64url(body) == RFC["body"]


def test_vapid_token_is_a_signed_es256_jwt() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    token = web_push.vapid_token(key, "https://push.example")
    header, claims, signature = token.split(".")
    assert json.loads(web_push.unb64url(header)) == {"typ": "JWT", "alg": "ES256"}
    body = json.loads(web_push.unb64url(claims))
    assert body["aud"] == "https://push.example" and body["sub"] == web_push.SUBJECT
    raw = web_push.unb64url(signature)
    assert len(raw) == 64
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as test_client:
        test_client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield test_client


def subscription(n: int) -> dict[str, str]:
    ua = ec.generate_private_key(ec.SECP256R1())
    return {
        "endpoint": f"https://push.example/send/{n}",
        "p256dh": web_push.b64url(web_push._uncompressed(ua.public_key())),
        "auth": web_push.b64url(b"\x01" * 16),
        "label": f"Phone {n}",
    }


def test_key_is_made_once_and_subscriptions_come_and_go(client: TestClient) -> None:
    key = client.get("/push/key").json()["key"]
    assert len(web_push.unb64url(key)) == 65
    assert client.get("/push/key").json()["key"] == key  # one pair, kept
    assert client.put("/push/subscriptions", json=subscription(1)).status_code == 204
    assert client.put("/push/subscriptions", json=subscription(1)).status_code == 204  # same again
    assert client.put("/push/subscriptions", json=subscription(2)).status_code == 204
    listed = client.get("/push/subscriptions").json()
    assert [s["label"] for s in listed] == ["Phone 1", "Phone 2"]
    assert "p256dh" not in listed[0]  # keys stay inside
    bad = dict(subscription(3), endpoint="http://plain.example/x")
    assert client.put("/push/subscriptions", json=bad).status_code == 422
    assert (
        client.post("/push/unsubscribe", json={"endpoint": subscription(1)["endpoint"]}).status_code
        == 204
    )
    assert [s["label"] for s in client.get("/push/subscriptions").json()] == ["Phone 2"]


def test_a_send_reaches_each_browser_once_and_drops_a_gone_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts: list[tuple[str, dict[str, str], int]] = []
    done = threading.Event()

    def service(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        posts.append((url, dict(request.headers), len(request.content)))
        if len(posts) == 2:
            done.set()
        return httpx.Response(410 if url.endswith("/2") else 201)

    monkeypatch.setattr(
        web_push, "_client", lambda: httpx.Client(transport=httpx.MockTransport(service))
    )
    client.put("/push/subscriptions", json=subscription(1))
    client.put("/push/subscriptions", json=subscription(2))
    monkeypatch.setitem(delivery.SENDERS, outbox_push.CHANNEL, outbox_push.send)
    assert client.post("/push/test").json() == {"sent": 2}
    assert posts == []  # queued, not sent inline (the outbox loop sends it)
    delivery.deliver_due(client.app.state.core)  # type: ignore[attr-defined]
    assert done.wait(5)
    urls = sorted(u for u, _, _ in posts)
    assert urls == ["https://push.example/send/1", "https://push.example/send/2"]
    _, headers, size = posts[0]
    assert headers["content-encoding"] == "aes128gcm" and headers["ttl"] == str(web_push.TTL)
    assert headers["authorization"].startswith("vapid t=") and ", k=" in headers["authorization"]
    assert size > 16 + 4 + 1 + 65 + 16  # header + a sealed record
    # The push service said /2 is gone: dropped.
    assert [s["label"] for s in client.get("/push/subscriptions").json()] == ["Phone 1"]
