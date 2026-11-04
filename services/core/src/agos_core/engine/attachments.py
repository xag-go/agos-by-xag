"""What the owner attaches to a chat message: screenshots, voice notes, files.

Files are kept in the workspace's own folder (`/workspace/.agos/uploads/…` inside
the sandbox), so the agent can open them with its tools and nothing leaves the
workspace. Images also go to the model directly; voice notes are transcribed by
Hermes and the transcript goes with the message.
"""

import base64
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import agos_core.engine.hermes as _hermes_engine
from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

Kind = Literal["image", "audio", "file"]

MAX_FILES = 8
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_VOICE_SECONDS = 30 * 60  # a voice note's length (the web stops recording here)
# Sent to the model as pixels; SVG is excluded (it is a document, not an image).
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
}
UPLOADS = Path(".agos") / "uploads"
SANDBOX_ROOT = "/workspace"


class AttachmentError(ValueError):
    """Safe to show to the owner."""


@dataclass(frozen=True)
class Incoming:
    kind: Kind
    name: str
    mime: str
    data: bytes
    duration: float | None = None


def _base_mime(mime: str) -> str:
    return mime.split(";", 1)[0].strip().lower()


def safe_name(name: str) -> str:
    """A file name that can't climb out of its folder or surprise a shell."""
    base = Path(name.replace("\\", "/")).name
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .")
    return (clean or "file")[:80]


def check(kind: str, name: str, mime: str, data_b64: str, duration: float | None) -> Incoming:
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (ValueError, TypeError) as error:
        raise AttachmentError("An attachment could not be read.") from error
    if not data:
        raise AttachmentError("An attachment is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentError("Each attachment can be up to 20 MB.")
    base = _base_mime(mime)
    if kind == "image" and base not in IMAGE_TYPES:
        raise AttachmentError("Images can be PNG, JPEG, WebP or GIF.")
    if kind == "audio" and base not in AUDIO_TYPES:
        raise AttachmentError("This voice note format isn't supported.")
    if kind not in ("image", "audio", "file"):
        raise AttachmentError("Unknown attachment.")
    if duration is not None and not 0 <= duration <= MAX_VOICE_SECONDS:
        raise AttachmentError(f"Voice notes can be up to {MAX_VOICE_SECONDS // 60} minutes.")
    return Incoming(kind=kind, name=safe_name(name), mime=base, data=data, duration=duration)  # type: ignore[arg-type]


def check_all(items: list[Incoming]) -> None:
    if len(items) > MAX_FILES:
        raise AttachmentError(f"Up to {MAX_FILES} attachments per message.")
    if sum(len(i.data) for i in items) > MAX_TOTAL_BYTES:
        raise AttachmentError("Attachments can be up to 30 MB per message.")


def relative_path(chat_id: int, message_id: int, index: int, name: str) -> str:
    return str(UPLOADS / f"chat-{chat_id}" / f"{message_id}-{index}-{safe_name(name)}")


def write(files_dir: Path, relative: str, data: bytes) -> Path:
    target = (files_dir / relative).resolve()
    root = files_dir.resolve()
    if root not in target.parents:
        raise AttachmentError("An attachment path was refused.")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o600)
    return target


def resolve(files_dir: Path, relative: str) -> Path | None:
    target = (files_dir / relative).resolve()
    if files_dir.resolve() not in target.parents or not target.is_file():
        return None
    return target


def sandbox_path(relative: str) -> str:
    return f"{SANDBOX_ROOT}/{relative}"


# ---- what the agent receives ------------------------------------------------------


@dataclass(frozen=True)
class Stored:
    kind: str
    name: str
    mime: str
    relative: str
    transcript: str | None
    data: bytes | None = None  # images only: sent to the model as pixels


def turn_content(texts: list[str], stored: list[Stored]) -> str | list[dict[str, Any]]:
    """The owner's turn for Hermes: plain text, or text + images (vision parts)."""
    lines = [t.strip() for t in texts if t.strip()]
    for item in stored:
        where = sandbox_path(item.relative)
        if item.kind == "audio":
            heard = (item.transcript or "").strip()
            lines.append(
                f"[Voice note, transcribed] {heard}"
                if heard
                else f"[Voice note at {where}: it could not be transcribed]"
            )
        elif item.kind == "image":
            lines.append(f"[Screenshot attached: {item.name}, also saved at {where}]")
        else:
            lines.append(f"[File attached: {item.name}, saved at {where}]")
    text = "\n\n".join(lines) or "(no text)"
    images = [i for i in stored if i.kind == "image" and i.data]
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
    for image in images:
        encoded = base64.b64encode(image.data or b"").decode()
        parts.append({"type": "input_image", "image_url": f"data:{image.mime};base64,{encoded}"})
    return parts


# ---- voice notes: Hermes transcribes them -------------------------------------------

_TRANSCRIBE = """
import json, sys
from tools.transcription_tools import transcribe_audio
result = transcribe_audio(sys.argv[1], source="agos")
print(json.dumps({"ok": bool(result.get("success")), "text": result.get("transcript") or "",
                  "error": str(result.get("error") or "")[:300]}))
"""


def transcribe(engine: EngineConfig, python: str, path: Path, timeout: float = 300) -> str:
    """The words of a voice note, with the speech-to-text Hermes is set up with."""
    env = {"HOME": str(engine.host_home), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    off_loop("hermes transcribe")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [python, "-c", _TRANSCRIBE, str(path)],
        capture_output=True,
        text=True,
        timeout=hermes_wait(timeout),
        env=_hermes_engine.with_runtime(env),
        check=False,
        # venv/bin/python -> the Hermes checkout (not resolved: venvs symlink python).
        cwd=str(Path(python).parent.parent.parent),
    )
    hermes_contract.ran(result)
    lines = [line for line in (result.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        tail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"transcription failed: {tail[0][:200]}")
    payload = json.loads(lines[-1])
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "transcription failed")
    return str(payload.get("text") or "").strip()
