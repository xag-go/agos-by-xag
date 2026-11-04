"""A webhook automation's Hermes route name: its public address, unguessable."""

import hashlib

ROUTE_PREFIX = "agos-"


def route_name(automation_id: int, token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()[:24]
    return f"{ROUTE_PREFIX}{automation_id}-{digest}"
