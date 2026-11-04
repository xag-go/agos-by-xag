"""Workspace identifiers: fixed at creation, used as folder names."""

import re
import unicodedata

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def is_workspace_id(value: str) -> bool:
    """Safe alphabet only: no dots, slashes or leading dashes, so no traversal."""
    return bool(_ID.fullmatch(value))


def require_workspace_id(value: str) -> str:
    if not is_workspace_id(value):
        raise ValueError("use lowercase letters, digits and dashes (max 63 chars)")
    return value


def workspace_id_from_name(name: str) -> str:
    """'Argan Store 2' -> 'argan-store-2'."""
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug[:63].rstrip("-")
