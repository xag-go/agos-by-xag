"""Every typed error code AGOS's API answers with, in plain words.

Owns: the `ErrorCode` names (the `code` field of an error body), which code an HTTP
status gets when the error named none, and each code's plain text for someone who
is not a developer: what happened and what to do (`help` in the error body,
docs/errors.md). Must not: decide an HTTP status, log, or import anything of AGOS
(it is the lowest layer).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["TEXTS", "ErrorCode", "ErrorText", "code_for_status", "help_for"]


class ErrorCode(StrEnum):
    """The `code` of an API error body. The HERMES_* and ENGINE_ERROR values are the
    Hermes Gateway's own (hermes_gateway/errors.py, ADR 0024)."""

    INVALID_REQUEST = "invalid_request"
    INVALID_VALUE = "invalid_value"
    NOT_ALLOWED = "not_allowed"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    TOO_LARGE = "too_large"
    UNSUPPORTED_FILE = "unsupported_file"
    SERVICE_FAILED = "service_failed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"
    CAGE_REFUSED = "cage_refused"
    ENGINE_ERROR = "ENGINE_ERROR"
    HERMES_FAILED = "HERMES_FAILED"
    HERMES_TIMEOUT = "HERMES_TIMEOUT"
    HERMES_UNAVAILABLE = "HERMES_UNAVAILABLE"


@dataclass(frozen=True)
class ErrorText:
    """`means`: what happened, in a sentence; `what_to_do`: the next step."""

    means: str
    what_to_do: str


TEXTS: dict[ErrorCode, ErrorText] = {
    ErrorCode.INVALID_REQUEST: ErrorText(
        "Something in what was asked is missing or not filled in the way AGOS expects.",
        "Read the message, correct the field it names and try again.",
    ),
    ErrorCode.INVALID_VALUE: ErrorText(
        "A value AGOS received is not one it can use (a wrong date, number or name).",
        "Check what you typed or picked and try again. If it keeps happening, "
        "reload the page: it may show an old version of the item.",
    ),
    ErrorCode.NOT_ALLOWED: ErrorText(
        "This is not allowed here: it needs the owner, or a setting turns it off.",
        "Do it yourself from the page it belongs to, or turn on the setting the message names.",
    ),
    ErrorCode.NOT_FOUND: ErrorText(
        "The item is gone: it was deleted, archived or moved, maybe from another window "
        "or by an agent.",
        "Reload the page to see what is there now.",
    ),
    ErrorCode.CONFLICT: ErrorText(
        "AGOS can't do this right now, in the state the item is in (it is busy, "
        "already done, or something else must happen first).",
        "Read the message: it says what is in the way. Wait for it to finish, or do "
        "the step it names first, then try again.",
    ),
    ErrorCode.TOO_LARGE: ErrorText(
        "The file or text is bigger than AGOS accepts here.",
        "Use a smaller file (or split it), then try again.",
    ),
    ErrorCode.UNSUPPORTED_FILE: ErrorText(
        "AGOS can't read this kind of file here.",
        "Save it in one of the formats the message names, then try again.",
    ),
    ErrorCode.SERVICE_FAILED: ErrorText(
        "Another program AGOS asked (the agents' engine, an app you connected, or the "
        "model provider) answered with an error.",
        "Try again in a minute. If it keeps failing, check the connection or key in "
        "Settings, and look at Settings → Errors for the details.",
    ),
    ErrorCode.SERVICE_UNAVAILABLE: ErrorText(
        "A part AGOS needs is not running or not reachable right now.",
        "Wait a minute and try again. If it lasts, run `agos status` on the server "
        "(or open Settings → Errors) to see which part is down.",
    ),
    ErrorCode.INTERNAL_ERROR: ErrorText(
        "AGOS hit a bug. Nothing you did caused it.",
        "Try again. If it happens again, open Settings → Errors, copy the diagnostics "
        "and report it with the reference shown in the message.",
    ),
    ErrorCode.CAGE_REFUSED: ErrorText(
        "Workspace isolation (the cage around each workspace's agents) can't be built "
        "on this machine, so AGOS won't start the workspace's agents without it.",
        "Run `agos doctor` on the server: it says why and the exact fix (usually: run the "
        "installer again, it installs bubblewrap and its AppArmor profile). See "
        'docs/troubleshooting.md, "The cage refused to start".',
    ),
    ErrorCode.ENGINE_ERROR: ErrorText(
        "The engine behind the agents could not do what AGOS asked.",
        "Try again. If it keeps failing, open Settings → Errors for what the engine said.",
    ),
    ErrorCode.HERMES_FAILED: ErrorText(
        "The engine ran but refused or failed this request.",
        "Read the message for the engine's reason, fix what it names (a setting, a key, a "
        "name already in use) and try again.",
    ),
    ErrorCode.HERMES_TIMEOUT: ErrorText(
        "The engine did not answer in time: the server is busy, or the request was long.",
        "Wait a minute and try again. If it happens often, the server may need more "
        'memory: see docs/INSTALL.md, "Minimum hardware".',
    ),
    ErrorCode.HERMES_UNAVAILABLE: ErrorText(
        "The engine is not answering right now, so AGOS paused calls to it for a short "
        "time.",
        "Wait a minute: AGOS tries again by itself. If it lasts, restart AGOS "
        "(`agos restart`) and look at Settings → Errors.",
    ),
}

_BY_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    403: ErrorCode.NOT_ALLOWED,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_FILE,
    422: ErrorCode.INVALID_REQUEST,
    502: ErrorCode.SERVICE_FAILED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def code_for_status(status: int) -> ErrorCode:
    """The code of an error that named none: by its HTTP status (500 for any other)."""
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    return ErrorCode.INVALID_REQUEST if 400 <= status < 500 else ErrorCode.INTERNAL_ERROR


def help_for(code: str) -> str:
    """What to do about an error with this code ("" for a code AGOS doesn't know)."""
    try:
        return TEXTS[ErrorCode(code)].what_to_do
    except ValueError:
        return ""
