"""Password-protected backups of everything AGOS owns, and a safe restore.

One file (`agos-backup-<utc>.agosb`): a tar of
  - agos-data/ (workspaces and their files, database, encrypted secrets, master key,
    global library), minus each workspace's Hermes root;
  - Hermes's own backups, never a copy AGOS makes of Hermes's files: `hermes backup`
    of the shared home (`hermes/hermes-backup.zip`: its profiles) and of every
    workspace's root (`hermes/roots/<name>.zip`, ADR 0020); `hermes import`
    restores each,
encrypted with AES-256-GCM under a key derived from the owner's password (scrypt).

No key is in a backup, encrypted or not (owner's rule, ADR 0023: a restore needs
the keys re-entered by hand). Taken out of everything above:
  - every file that holds keys: each `.env` (the shared home's, every root's and
    member's: the API keys and the Telegram bot tokens), the provider logins
    (auth.json), `.credentials.json`, `*.token` (the core's internal token: a new one
    is made at start), and, inside a Hermes home, every credential store Hermes
    itself never ships in a profile export (H: hermes_cli/profiles.py
    profile_path_is_private: vault, mcp-tokens, Google / Slack tokens, pairing,
    browser logins, …; asked from Hermes when it answers, `private`);
  - AGOS's own sealed values in its agos.db copy (security/secrets.py "v1." values:
    the backup password, a workspace's Composio key or MCP token, the web push key):
    a settings row holding one is left out, any other cell holding one is emptied.
    With nothing sealed left, the master key that opens them (system/master.key)
    is left out too; the restored AGOS makes a new one and simply has none of
    these set (each page asks again, push makes a new key).
  `manifest.json` lists what was taken out: the files' paths and the key NAMES of
  each `.env` and each sealed value, never a value. The restore rehearsal shows them
  as "Re-enter these keys in Settings → Keys: …". Backups made before this have no
  such list and restore as they are.
The engine's backup has no encryption, no schedule and none of AGOS's data: that much
(this wrapper, agos.db, actions/backups.py's schedule and rehearsal) stays AGOS's.

The database is copied with SQLite's online backup API (consistent while running).
Restore only ever writes into an EMPTY target; it never overwrites live data.
Older backups that held AGOS's own copy of the profiles (`hermes/profiles/`) still
restore as they are.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"AGOSB2\n"
# Backups made before the app was named AGOS start with this one.
LEGACY_MAGIC = b"XAGB2\n"
CHUNK = 4 * 1024 * 1024
SKIP_NAMES = {
    "auth.json",
    "auth.lock",
    "gateway.sock",
    "gateway.pid",
    "gateway.lock",
    "processes.json",
    ".DS_Store",
}
SKIP_DIRS = {
    "cache",
    "audio_cache",
    "image_cache",
    "sandboxes",
    "__pycache__",
    "node_modules",
    "logs",
    "runtime",
    "backups",
    ".trash",
    # deploy/agos's update snapshots and rolled-from copies (system/update-snapshots):
    # they hold the Hermes roots' .env files, and a backup holds no key (ADR 0023).
    "update-snapshots",
}
SKIP_SUFFIXES = (".sock", ".lock", "-shm", "-wal", ".pyc")


log = logging.getLogger("agos.engine.backup")
# AGOS's own database, inside the data folder: every backup must hold it.
DATABASE = Path("system") / "agos.db"


class BackupError(RuntimeError):
    """Shown to the owner as-is."""


@dataclass(frozen=True)
class Manifest:
    created_at: str
    files: dict[str, str]  # archive path -> sha256
    agos_version: str = "1"
    # What was taken out because it holds keys: {"files": [{"where", "path"}],
    # "keys": [{"where", "name"}]} (names only). None: a backup made before.
    keys_out: dict[str, list[dict[str, str]]] | None = None

    def as_json(self) -> bytes:
        body: dict[str, object] = {
            "created_at": self.created_at,
            "files": self.files,
            "agos_version": self.agos_version,
        }
        if self.keys_out is not None:
            body["keys_out"] = self.keys_out
        return json.dumps(body, indent=1, sort_keys=True).encode()

    def reenter(self) -> list[str]:
        """The keys to re-enter by hand after a restore: "NAME (where)", once each."""
        out: list[str] = []
        for key in (self.keys_out or {}).get("keys", []):
            line = f"{key['name']} ({key['where']})"
            if line not in out:
                out.append(line)
        return out


# Files that hold keys, wherever they are (ADR 0023).
KEY_FILES = {
    ".env",
    "auth.json",
    "auth.lock",
    ".credentials.json",
    "master.key",
    "vault.key",
    "vault.json.enc",
}
KEY_SUFFIXES = (".token",)
KEY_DIRS = {"mcp-tokens"}
# Hermes's own answer for paths inside a Hermes home (relative to that home):
# whether each is a credential store (H: hermes_cli/profiles.py profile_path_is_private).
Private = Callable[[list[tuple[str, ...]]], list[bool]]
# AGOS's sealed values (security/secrets.py encrypt_secret: "v1.iv.tag.data").
_SEALED = re.compile(r"v1\.[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]*")
_ENV_NAME = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def holds_keys(parts: tuple[str, ...]) -> bool:
    """A file that holds keys by its name (any folder)."""
    name = parts[-1] if parts else ""
    return (
        name in KEY_FILES
        or name.startswith((".env.", "auth.json."))
        or name.endswith(KEY_SUFFIXES)
        or any(p in KEY_DIRS for p in parts[:-1])
    )


def env_names(data: bytes) -> list[str]:
    """The key names of a .env file (never a value)."""
    names: list[str] = []
    for line in data.decode("utf-8", "replace").splitlines():
        m = _ENV_NAME.match(line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


class _KeysOut:
    """What a backup takes out (paths and names only)."""

    def __init__(self) -> None:
        self.files: list[dict[str, str]] = []
        self.keys: list[dict[str, str]] = []

    def drop(self, where: str, path: str, data: bytes | None) -> None:
        self.files.append({"where": where, "path": path})
        name = path.rsplit("/", 1)[-1]
        if data is not None and (name == ".env" or name.startswith(".env.")):
            self.keys += [{"where": where, "name": n} for n in env_names(data)]

    def as_dict(self) -> dict[str, list[dict[str, str]]]:
        return {"files": self.files, "keys": self.keys}


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 10:
        raise BackupError("Use a backup password of at least 10 characters.")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def _skip(path: Path) -> bool:
    if path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES):
        return True
    return any(part in SKIP_DIRS for part in path.parts)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_copy(source: Path, target: Path) -> None:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _homes(files: list[Path]) -> set[Path]:
    """Folders that are a Hermes home (its config.yaml beside its SOUL.md or sessions)."""
    names: dict[Path, set[str]] = {p.parent: set() for p in files}
    for p in files:
        names[p.parent].add(p.name)
    return {d for d, n in names.items() if "config.yaml" in n and n & {"SOUL.md", "state.db"}}


def _home_parts(path: Path, homes: set[Path]) -> tuple[str, ...] | None:
    for parent in path.parents:
        if parent in homes:
            return path.relative_to(parent).parts
    return None


def _ask_private(private: Private | None, parts: list[tuple[str, ...]]) -> list[bool]:
    if private is None or not parts:
        return [False] * len(parts)
    answer = private(parts)
    if len(answer) != len(parts):
        raise BackupError("The engine didn't say which files hold keys.")
    return [bool(a) for a in answer]


def _walk(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not (here / d).is_symlink() and here / d not in exclude
        ]
        for name in filenames:
            path = here / name
            if path.is_symlink() or not path.is_file() or _skip(path.relative_to(root)):
                continue
            yield path


HERMES_ZIP = "hermes/hermes-backup.zip"  # Hermes's own backup (`hermes import` restores it)
ROOTS_PREFIX = "hermes/roots/"  # one Hermes backup per workspace root (ADR 0020)


def collect(
    data_dir: Path,
    staging: Path,
    hermes_backup: Callable[[Path], None] | None = None,
    roots: dict[str, Callable[[Path], None]] | None = None,
    exclude: tuple[Path, ...] = (),
    private: Private | None = None,
) -> Manifest:
    """Copies everything into `staging` (consistent DB copies) and hashes it, every
    key taken out (module doc). `hermes_backup` writes Hermes's own backup of the
    shared home (its profiles); `roots`: each workspace's own Hermes root, as
    Hermes's own backup of that root (`hermes/roots/<name>.zip`); `exclude`: folders
    of `data_dir` left out (the roots themselves: Hermes backs them up, and their
    runtime and caches are no data); `private`: Hermes's own answer to which files
    in a Hermes home are credential stores (None: only the files named by AGOS)."""
    files: dict[str, str] = {}
    out = _KeysOut()
    _collect_hermes(staging, hermes_backup, roots or {}, out, private, files)
    if data_dir.is_dir():
        _collect_data(data_dir, staging, exclude, out, private, files)
    if str("agos-data" / DATABASE) not in files:
        # The database is the backup's whole point: never a "good" backup without it.
        raise BackupError(f"AGOS's database ({DATABASE}) is missing: nothing was backed up.")
    return Manifest(
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        files=files,
        keys_out=out.as_dict(),
    )


def _collect_hermes(
    staging: Path,
    hermes_backup: Callable[[Path], None] | None,
    roots: dict[str, Callable[[Path], None]],
    out: _KeysOut,
    private: Private | None,
    files: dict[str, str],
) -> None:
    """Hermes's own backups (the shared home, then each root) into `staging`, keys
    taken out, each hashed into `files`."""
    hermes = (
        [(HERMES_ZIP, hermes_backup, "The engine's backup", "shared home")] if hermes_backup else []
    )
    hermes += [
        (f"{ROOTS_PREFIX}{name}.zip", write, f"The engine's backup of {name}", name)
        for name, write in sorted(roots.items())
    ]
    for zip_name, write, label, where in hermes:
        target = staging / zip_name
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target)
        if not target.is_file():
            raise BackupError(f"{label} didn't write its file.")
        _without_keys(target, where, out, private)
        files[zip_name] = _sha256(target)


def _collect_data(
    data_dir: Path,
    staging: Path,
    exclude: tuple[Path, ...],
    out: _KeysOut,
    private: Private | None,
    files: dict[str, str],
) -> None:
    """AGOS's data folder into `staging/agos-data`: key files dropped (by name or
    by Hermes's answer), databases as consistent copies, each hashed into `files`."""
    found = list(_walk(data_dir, exclude))
    homes = _homes(found)
    inside = [(p, _home_parts(p, homes)) for p in found]
    asked = [(p, parts) for p, parts in inside if parts is not None]
    hermes_says = dict(
        zip(
            [p for p, _ in asked],
            _ask_private(private, [parts for _, parts in asked]),
            strict=True,
        )
    )
    for path in found:
        rel = path.relative_to(data_dir)
        if holds_keys(rel.parts) or hermes_says.get(path, False):
            out.drop("AGOS data", rel.as_posix(), _read_small(path))
            continue
        dest = staging / "agos-data" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            _copy_data_file(path, dest, out)
        except FileNotFoundError:
            # Gone since the walk (a runtime file such as system/deadman.state,
            # removed while the backup ran): it is not there to back up. Any
            # other read error still fails the backup.
            if path.exists():
                raise
            dest.unlink(missing_ok=True)
            log.info("backup: %s vanished during the copy (left out)", rel.as_posix())
            continue
        files[str(Path("agos-data") / rel)] = _sha256(dest)


def _copy_data_file(path: Path, dest: Path, out: _KeysOut) -> None:
    """One data file to `dest`: a database as a consistent copy (agos.db then loses
    its sealed values), anything else byte for byte."""
    if path.suffix != ".db":
        dest.write_bytes(path.read_bytes())
        return
    try:
        _sqlite_copy(path, dest)
    except sqlite3.DatabaseError:
        dest.write_bytes(path.read_bytes())
        return
    if path.name == "agos.db":
        out.keys += [{"where": "AGOS", "name": n} for n in _without_sealed(dest)]


def _read_small(path: Path) -> bytes | None:
    """A dropped file's bytes, only to read its key names (a .env is small)."""
    name = path.name
    if not (name == ".env" or name.startswith(".env.")):
        return None
    try:
        return path.read_bytes()[: 1024 * 1024]
    except OSError:
        return None


def _without_sealed(db_path: Path) -> list[str]:
    """AGOS's sealed values out of its database copy: a settings row holding one goes
    (the restored AGOS then has it unset and asks again), any other cell holding one
    is emptied. Returns the settings names that went."""
    gone: list[str] = []
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        for row in db.execute("SELECT key, value FROM app_settings").fetchall():
            if _SEALED.search(str(row["value"])):
                db.execute("DELETE FROM app_settings WHERE key = ?", (row["key"],))
                gone.append(str(row["key"]))
        tables = [
            str(r["name"])
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND sql NOT LIKE "
                "'CREATE VIRTUAL%' AND name NOT LIKE 'sqlite_%' AND name != 'app_settings'"
            )
        ]
        for raw_table in tables:
            # Names from the copied file itself: quoted as SQL identifiers ("" inside).
            table = raw_table.replace('"', '""')
            for col in db.execute(f'PRAGMA table_info("{table}")').fetchall():
                raw_name, required = str(col["name"]), bool(col["notnull"])
                name = raw_name.replace('"', '""')
                rows = db.execute(
                    f'SELECT rowid, "{name}" FROM "{table}" WHERE instr("{name}", \'v1.\') > 0'
                ).fetchall()
                for found in rows:
                    rowid, text = found[0], str(found[1])
                    if not _SEALED.search(text):
                        continue
                    try:
                        clean: object = json.dumps(_unsealed(json.loads(text)))
                    except ValueError:
                        clean = "" if required else None
                    db.execute(
                        f'UPDATE "{table}" SET "{name}" = ? WHERE rowid = ?',
                        (clean, rowid),
                    )
        db.commit()
        db.execute("VACUUM")  # no freed page keeps an old copy
    finally:
        db.close()
    return gone


def _unsealed(value: object) -> object:
    if isinstance(value, str):
        return None if _SEALED.search(value) else value
    if isinstance(value, list):
        return [_unsealed(v) for v in value]
    if isinstance(value, dict):
        return {k: _unsealed(v) for k, v in value.items()}
    return value


def _seal_stream(source: Path, output: Path, key: bytes, salt: bytes) -> None:
    """File = MAGIC | salt | per chunk: 4-byte length | 12-byte nonce | ciphertext.
    Each chunk's associated data binds its index and whether it is the last one,
    so chunks can't be reordered, dropped or truncated."""
    aes = AESGCM(key)
    size = source.stat().st_size
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with source.open("rb") as src, os.fdopen(fd, "wb") as out:
        out.write(MAGIC + salt)
        index, done = 0, 0
        while True:
            chunk = src.read(CHUNK)
            done += len(chunk)
            last = done >= size
            nonce = secrets.token_bytes(12)
            sealed = aes.encrypt(nonce, chunk, MAGIC + index.to_bytes(8, "big") + bytes([last]))
            out.write(len(sealed).to_bytes(4, "big") + nonce + sealed)
            index += 1
            if last:
                break


def _open_stream(path: Path, key_for: Callable[[bytes], bytes], output: Path) -> None:
    with path.open("rb") as src, output.open("wb") as out:
        head = src.read(len(MAGIC))
        magic = MAGIC
        if head != MAGIC:
            if head[: len(LEGACY_MAGIC)] != LEGACY_MAGIC:
                raise BackupError("That isn't an AGOS backup file (or it's from another version).")
            magic = LEGACY_MAGIC
            src.seek(len(LEGACY_MAGIC))
        salt = src.read(16)
        aes = AESGCM(key_for(salt))
        index = 0
        while True:
            head = src.read(4)
            if len(head) < 4:
                raise BackupError("The backup file is cut short.")
            length = int.from_bytes(head, "big")
            nonce, sealed = src.read(12), src.read(length)
            for last in (False, True):
                try:
                    plain = aes.decrypt(
                        nonce, sealed, magic + index.to_bytes(8, "big") + bytes([last])
                    )
                    break
                except Exception:  # noqa: BLE001 - InvalidTag: try the other flag, then give up
                    plain = None
            if plain is None:
                raise BackupError("Wrong password, or the file is damaged.")
            out.write(plain)
            index += 1
            if last:
                if src.read(1):
                    raise BackupError("The backup file has extra data at the end.")
                return


def create(
    data_dir: Path,
    output: Path,
    password: str,
    hermes_backup: Callable[[Path], None] | None = None,
    roots: dict[str, Callable[[Path], None]] | None = None,
    exclude: tuple[Path, ...] = (),
    private: Private | None = None,
) -> Manifest:
    salt = secrets.token_bytes(16)
    key = _key(password, salt)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agos-backup-", dir=output.parent) as tmp:
        staging = Path(tmp) / "stage"
        staging.mkdir()
        manifest = collect(data_dir, staging, hermes_backup, roots, exclude, private)
        (staging / "manifest.json").write_bytes(manifest.as_json())
        archive = Path(tmp) / "backup.tar.gz"
        with tarfile.open(archive, mode="w:gz") as tar:
            tar.add(staging, arcname=".", recursive=True)
        partial = output.with_suffix(output.suffix + ".partial")
        _seal_stream(archive, partial, key, salt)
        partial.replace(output)
    return manifest


def restore(path: Path, password: str, target: Path) -> Manifest:
    """Unpacks into `target`, which must be empty (never over live data), and
    checks every file against the manifest."""
    if target.exists() and any(target.iterdir()):
        raise BackupError("Restore only goes into an empty folder.")
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agos-restore-", dir=target.parent) as tmp:
        archive = Path(tmp) / "backup.tar.gz"
        _open_stream(path, lambda salt: _key(password, salt), archive)
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name)
                if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                    raise BackupError("The backup contains an unsafe path.")
            tar.extractall(target, filter="data")
    manifest_data = json.loads((target / "manifest.json").read_text())
    manifest = Manifest(
        created_at=manifest_data["created_at"],
        files=manifest_data["files"],
        keys_out=manifest_data.get("keys_out"),
    )
    bad = [
        p
        for p, digest in manifest.files.items()
        if not (target / p).is_file() or _sha256(target / p) != digest
    ]
    if bad:
        raise BackupError(f"{len(bad)} file(s) don't match the backup (first: {bad[0]}).")
    return manifest


def _in_home(parts: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """(member profile or "", the path inside that Hermes home) of a zip entry."""
    if len(parts) > 2 and parts[0] == "profiles":
        return parts[1], parts[2:]
    return "", parts


def _without_keys(path: Path, where: str, out: _KeysOut, private: Private | None) -> None:
    """The engine's backup keeps every key of the home (its .env, logins, token stores);
    none may be in AGOS's backup. The zip is rewritten without them (AGOS's names
    and Hermes's own credential stores), nothing else changes."""
    import zipfile

    kept = path.with_suffix(".nokeys")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(kept, "w", zipfile.ZIP_DEFLATED) as dst:
        infos = [i for i in src.infolist() if not i.is_dir()]
        homes = [_in_home(tuple(Path(i.filename).parts)) for i in infos]
        hermes_says = _ask_private(private, [inner for _, inner in homes])
        for info, (member, inner), says in zip(infos, homes, hermes_says, strict=True):
            if holds_keys(inner) or says:
                name = inner[-1] if inner else ""
                data = src.read(info) if name == ".env" or name.startswith(".env.") else None
                place = f"{where}, member {member}" if member else where
                out.drop(place, info.filename, data)
                continue
            with src.open(info) as data_in, dst.open(info, "w") as written:
                while chunk := data_in.read(CHUNK):
                    written.write(chunk)
    kept.replace(path)


def root_zip_problems(path: Path, name: str) -> list[str]:
    """A workspace root's Hermes backup opens, is intact and holds its home."""
    import zipfile

    rel = f"{ROOTS_PREFIX}{name}.zip"
    try:
        with zipfile.ZipFile(path) as zf:
            broken = zf.testzip()
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile) as error:
        return [f"{rel}: {error}"]
    problems = [f"{rel}: {broken} is damaged"] if broken else []
    if not any(n.endswith("config.yaml") for n in names):
        problems.append(f"{rel}: config.yaml missing")
    return problems


def hermes_zip_problems(path: Path, profiles: list[str]) -> list[str]:
    """The engine's backup zip opens, every file in it is intact, and each workspace's
    profile is in it (its config and sessions)."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            broken = zf.testzip()
            names = set(zf.namelist())
    except (OSError, zipfile.BadZipFile) as error:
        return [f"{HERMES_ZIP}: {error}"]
    problems = [f"{HERMES_ZIP}: {broken} is damaged"] if broken else []
    for profile in profiles:
        for needed in ("config.yaml", "state.db"):
            if f"profiles/{profile}/{needed}" not in names:
                problems.append(f"{HERMES_ZIP}: profiles/{profile}/{needed} missing")
    return problems


def verify_against_source(
    manifest: Manifest, data_dir: Path, exclude: tuple[Path, ...] = ()
) -> list[str]:
    """AGOS data present in the source now but missing from the backup (for the
    'everything identical' check right after a backup). Hermes's part is checked
    by opening its zips (hermes_zip_problems, root_zip_problems)."""
    have = set(manifest.files)
    have |= {
        str(Path("agos-data") / f["path"])
        for f in (manifest.keys_out or {}).get("files", [])
        if f.get("where") == "AGOS data"
    }
    if not data_dir.is_dir():
        return []
    return [
        key
        for path in _walk(data_dir, exclude)
        if (key := str(Path("agos-data") / path.relative_to(data_dir))) not in have
    ]
