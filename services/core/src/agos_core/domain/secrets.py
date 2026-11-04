"""Comparing a secret the caller sent with the one AGOS holds.

Owns: the constant-time compare of tokens, keys and nonces. A value with a character
outside ASCII is compared as UTF-8 bytes, so it is simply not a match (a refusal),
never the `TypeError` `hmac.compare_digest` raises for such a str (a 500).
Must not: import anything else from agos_core, log, or say which side was wrong.
"""

from __future__ import annotations

import hmac

__all__ = ["same_secret"]


def same_secret(given: str | None, held: str | None) -> bool:
    """True when both are non-empty and equal (constant time)."""
    if not given or not held:
        return False
    return hmac.compare_digest(
        given.encode("utf-8", "surrogateescape"), held.encode("utf-8", "surrogateescape")
    )
