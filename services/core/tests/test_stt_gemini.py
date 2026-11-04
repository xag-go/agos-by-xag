"""His voice notes are heard by Gemini (a Hermes STT provider in agos-guard)."""

import json
from pathlib import Path
from typing import Any

from agos_core.hermes_plugin.agos_guard import stt_gemini


class Answer:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def test_a_voice_note_goes_to_gemini_and_comes_back_as_text(tmp_path: Path) -> None:
    note = tmp_path / "audio_1.ogg"
    note.write_bytes(b"OggS-fake-audio")
    sent: list[Any] = []

    def opener(request: Any, timeout: float) -> Answer:
        sent.append(request)
        return Answer(
            {"candidates": [{"content": {"parts": [{"text": "salam, chno kayn lyoum?"}]}}]}
        )

    out = stt_gemini.transcribe_file(str(note), key="k-123", opener=opener)
    assert out == {"success": True, "transcript": "salam, chno kayn lyoum?", "provider": "gemini"}
    request = sent[0]
    assert "gemini-3-flash-preview:generateContent" in request.full_url
    assert request.get_header("X-goog-api-key") == "k-123"
    part = json.loads(request.data)["contents"][0]["parts"][1]["inline_data"]
    assert part["mime_type"] == "audio/ogg"
    # No key: a clear error, never a crash.
    none = stt_gemini.transcribe_file(str(note), key="", opener=opener)
    assert none["success"] is False and "Settings" in none["error"]


def test_voice_notes_start_off_and_gemini_is_one_choice() -> None:
    import inspect

    from agos_core.engine import rules, stt

    # One choice for every workspace in Hermes's managed scope (General settings →
    # Voice notes), starting off (Hermes's stt.enabled false); Gemini is offered
    # with its model; never a per-profile copy.
    assert stt.DEFAULT_SETTINGS == (("stt.enabled", "false"),)
    assert stt.GEMINI.name == "gemini" and stt.GEMINI.models == (stt_gemini.DEFAULT_MODEL,)
    assert "stt.provider" not in rules.profile_config(image="i:1", mounts=[])
    assert '"stt.echo_transcripts": "false"' in inspect.getsource(rules.profile_config)


def test_the_key_set_once_for_every_workspace_is_found(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# keys\nOTHER=1\nGEMINI_API_KEY='g-key-1'\n")
    assert stt_gemini._from_env_file(env) == "g-key-1"
    assert stt_gemini._from_env_file(tmp_path / "none") == ""


def test_a_busy_or_closed_model_falls_back_to_googles_current_cheap_flash(tmp_path: Path) -> None:
    import io
    import urllib.error

    note = tmp_path / "a.ogg"
    note.write_bytes(b"x")
    asked: list[str] = []

    def opener(request: Any, timeout: float) -> Answer:
        asked.append(request.full_url)
        if len(asked) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        return Answer({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    out = stt_gemini.transcribe_file(str(note), key="k", opener=opener)
    assert out == {"success": True, "transcript": "ok", "provider": "gemini"}
    assert "gemini-flash-lite-latest" in asked[1]


def test_gemini_3_is_asked_the_way_google_says_and_a_silent_model_is_not_waited_on(
    tmp_path: Path,
) -> None:
    """At temperature 0 Gemini 3 looped on his Darija notes and never answered: the
    request keeps Google's default temperature with little thinking, and a model that
    doesn't answer in time hands the note to the fallback."""
    note = tmp_path / "audio_1.ogg"
    note.write_bytes(b"OggS-fake-audio")
    asked: list[tuple[str, float, dict[str, Any]]] = []

    def opener(request: Any, timeout: float) -> Answer:
        asked.append((request.full_url, timeout, json.loads(request.data)["generationConfig"]))
        if "gemini-3-flash-preview" in request.full_url:
            raise TimeoutError
        return Answer({"candidates": [{"content": {"parts": [{"text": "salam"}]}}]})

    out = stt_gemini.transcribe_file(str(note), key="k", opener=opener)
    assert out == {"success": True, "transcript": "salam", "provider": "gemini"}
    assert [u.rsplit("/", 1)[1] for u, _, _ in asked] == [
        "gemini-3-flash-preview:generateContent",
        f"{stt_gemini.FALLBACK_MODEL}:generateContent",
    ]
    config = asked[0][2]
    assert "temperature" not in config and config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert asked[0][1] <= 60
