"""Voice notes he sends, heard by Gemini: a speech-to-text provider for Hermes.

Registered with Hermes's own plugin API (`register_transcription_provider`); Hermes
uses it when `stt.provider` is "gemini" (its gateway transcribes a voice note before
the agent sees it). The key is Hermes's own GEMINI_API_KEY (or GOOGLE_API_KEY), set
once in AGOS → Settings → Models. Only his voice notes go through here: the reels a
workspace transcribes with its own tools keep their own service.
"""

from __future__ import annotations

import base64
import contextlib
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .guard_contract import STT_DEFAULT_MODEL, STT_NAME

NAME = STT_NAME  # the provider's name in Hermes's config (shared with the core)
DEFAULT_MODEL = STT_DEFAULT_MODEL

# Google's own alias for its current cheap Flash: tried when the chosen one is busy
# (503), closed (404) or rate-limited (429).
FALLBACK_MODEL = "gemini-flash-lite-latest"
MAX_BYTES = 19 * 1024 * 1024  # Gemini's inline audio limit is 20 MB per request
# A voice note comes back in seconds; past this the other model is asked.
TIMEOUT = 45
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = (
    "Transcribe this voice note word for word, in the language it is spoken. "
    "If it is Moroccan Darija, write it in Latin letters the way Moroccans type it "
    "(numbers for sounds like 3, 7, 9, 2), never in Arabic script. Keep French and "
    "English words as they are. Output only the transcript, nothing else. If there "
    "is no speech, output nothing."
)

_MIME = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mp3",
    ".m4a": "audio/aac",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


def _guard(name: str) -> Any:
    """contextlib.suppress(Exception), plus the report of a broken Hermes name."""
    try:
        from . import bridge

        return bridge._guard(name)
    except Exception:  # noqa: BLE001 — loaded alone (tests): as before
        return contextlib.suppress(Exception)


def api_key() -> str:
    """Hermes's own copy of the key (its .env, read the way Hermes reads it)."""
    with _guard("hermes_cli.config.get_env_value"):  # outside Hermes (tests): the environment
        from hermes_cli.config import get_env_value  # type: ignore[import-not-found]

        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            value = get_env_value(name)
            if value:
                return str(value).strip()
    # A workspace's profile: the key set once for every workspace (Settings → Models)
    # is in Hermes's root .env.
    with _guard("hermes_constants.get_default_hermes_root"):
        from hermes_constants import get_default_hermes_root  # type: ignore[import-not-found]

        found = _from_env_file(Path(get_default_hermes_root()) / ".env")
        if found:
            return found
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def _from_env_file(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    values: dict[str, str] = {}
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            values[name.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY") or ""


def transcribe_file(
    path: str, *, model: str | None = None, key: str | None = None, opener: Any = None
) -> dict[str, Any]:
    """Hermes's envelope: {"success", "transcript", "provider", "error"?}. Never raises."""
    chosen = model or DEFAULT_MODEL
    first = _transcribe_once(path, model=chosen, key=key, opener=opener)
    if first.get("success") or not first.get("retry") or chosen == FALLBACK_MODEL:
        first.pop("retry", None)
        return first
    second = _transcribe_once(path, model=FALLBACK_MODEL, key=key, opener=opener)
    second.pop("retry", None)
    return second


def _transcribe_once(path: str, *, model: str, key: str | None, opener: Any) -> dict[str, Any]:
    key = key if key is not None else api_key()
    if not key:
        return {
            "success": False,
            "transcript": "",
            "provider": NAME,
            "error": "No Gemini key: add it in AGOS → Settings → Models → Gemini.",
        }
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        return {"success": False, "transcript": "", "provider": NAME, "error": str(error)}
    if len(data) > MAX_BYTES:
        return {
            "success": False,
            "transcript": "",
            "provider": NAME,
            "error": "The voice note is too long for Gemini (over ~19 MB).",
        }
    ext = Path(path).suffix.lower()
    mime = _MIME.get(ext) or mimetypes.guess_type(path)[0] or "audio/ogg"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
                ],
            }
        ],
        # Google's own settings for Gemini 3: its default temperature (at 0 it can
        # loop and never answer: a 13 KB Darija note waited past 150 s, the same note
        # at the default came back in 3 s) and little thinking (a transcript needs none).
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}},
    }
    request = urllib.request.Request(  # noqa: S310 — fixed https endpoint
        ENDPOINT.format(model=model),
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT) as response:
            answer = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        detail = ""
        with contextlib.suppress(Exception):
            detail = json.loads(error.read() or b"{}").get("error", {}).get("message", "")
        return {
            "success": False,
            "transcript": "",
            "provider": NAME,
            "error": f"Gemini answered {error.code}: {detail[:200]}".strip(),
            "retry": error.code in (404, 429, 500, 503),
        }
    except Exception as error:  # noqa: BLE001 — network, timeout, bad JSON
        return {
            "success": False,
            "transcript": "",
            "provider": NAME,
            "error": f"Gemini didn't answer: {type(error).__name__}",
            "retry": True,  # the other model gets the note
        }
    parts = ((answer.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)).strip()
    return {"success": True, "transcript": text, "provider": NAME}


def provider() -> Any:
    """The provider object for Hermes (its TranscriptionProvider base)."""
    from agent.transcription_provider import TranscriptionProvider  # type: ignore[import-not-found]

    class GeminiTranscription(TranscriptionProvider):  # type: ignore[misc]
        @property
        def name(self) -> str:
            return NAME

        @property
        def display_name(self) -> str:
            return "Gemini (voice notes)"

        def is_available(self) -> bool:
            return bool(api_key())

        def default_model(self) -> str | None:
            return DEFAULT_MODEL

        def list_models(self) -> list[dict[str, Any]]:
            return [{"id": DEFAULT_MODEL, "name": "Gemini 3 Flash"}]

        def transcribe(
            self,
            file_path: str,
            *,
            model: str | None = None,
            language: str | None = None,
            **extra: Any,
        ) -> dict[str, Any]:
            del language, extra  # Gemini hears the language itself
            return transcribe_file(file_path, model=model)

    return GeminiTranscription()
