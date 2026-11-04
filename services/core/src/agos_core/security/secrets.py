"""Stored secrets (API keys, tokens): AES-256-GCM with a master key.

Format "v1.iv.tag.data" (base64url), same as the earlier TypeScript version.
`context` is bound as associated data, so a value copied to another row fails
to decrypt.
"""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_or_create_master_key(file: Path) -> bytes:
    """Created once on this machine (0600), next to — never inside — the database."""
    try:
        text = file.read_text().strip()
    except FileNotFoundError:
        pass
    else:
        try:
            key = _unb64(text)
        except ValueError:
            key = b""
        if len(key) != _KEY_BYTES:
            raise ValueError("the master key file is damaged")
        return key
    file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = os.urandom(_KEY_BYTES)
    try:
        # O_EXCL: never overwrite; if another process wrote it first, use theirs.
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_or_create_master_key(file)
    with os.fdopen(fd, "w") as handle:
        handle.write(_b64(key))
    return key


def encrypt_secret(key: bytes, plaintext: str, context: str) -> str:
    iv = os.urandom(12)
    sealed = AESGCM(key).encrypt(iv, plaintext.encode(), context.encode())
    data, tag = sealed[:-16], sealed[-16:]
    return ".".join(["v1", _b64(iv), _b64(tag), _b64(data)])


def decrypt_secret(key: bytes, sealed: str, context: str) -> str:
    parts = sealed.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        raise ValueError("not an encrypted value")
    _, iv, tag, data = parts
    return AESGCM(key).decrypt(_unb64(iv), _unb64(data) + _unb64(tag), context.encode()).decode()
