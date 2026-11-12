"""Where library items come from: this machine's Hermes, or the web (through
Hermes's own hub, with its security scan). Definitions only — never secrets.

Skills from the web are installed by Hermes's own hub straight into the library:
the library's skill folder is the `skills/` of a Hermes home of its own (the
library home), so Hermes keeps its hub lock there and `hermes skills check /
update / uninstall` work on them. The owner's own Hermes setup is only read.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.config import EngineConfig
from agos_core.engine import library as lib
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

_SKIP_FILES = re.compile(r"(^\.env|\.pem$|\.key$|^id_rsa|secret|token)", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_BOX = re.compile(r"[│╭╮╰╯─┃━┏┓┗┛]")


# A line of Hermes's skills-guard report: "  HIGH     injection      listing.py:50  ..."
_FINDING = re.compile(r"^\s*(CRITICAL|HIGH|MEDIUM|LOW)\s+\S+\s+\S+")


class SourceError(RuntimeError):
    """Shown to the owner as-is."""


def _clean(text: str) -> str:
    text = _ANSI.sub("", text)
    return "\n".join(_BOX.sub("", line).rstrip() for line in text.splitlines()).strip()


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Found:
    kind: str
    name: str
    title: str
    summary: str
    origin: str  # path, catalog id or hub identifier
    importable: bool = True
    locked: str | None = None
    trust: str = ""


@dataclass(frozen=True)
class HubState:
    """A hub skill as Hermes's `hermes skills check` reports it."""

    name: str
    source: str
    status: str  # up_to_date, update_available, orphaned, …


class Sources:
    def __init__(
        self,
        engine: EngineConfig,
        python: str,
        repo: Path | None = None,
        library_home: Path | None = None,
        *,
        category: str = "",
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.engine = engine
        self.python = python
        # The Hermes checkout (catalogs). Managed installs: from the runtime command.
        self.repo = repo or Path(python).parent.parent.parent
        # The Hermes home the hub installs into (a workspace's root) and keeps its
        # lock in; `category`: the folder of its skills/ a hub skill lands in.
        self.library_home = library_home
        self.category = category
        # Given to Hermes's process only (never written into that home): the hub's
        # GitHub token, which stays in AGOS's library home's .env.
        self.extra_env = dict(extra_env or {})

    # ---- running hermes ----------------------------------------------------------

    def _hermes(self, args: list[str], *, home: Path | None = None, timeout: float = 180) -> str:
        env = {
            "HOME": str(self.engine.host_home),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            # Hermes's tables are read back: wide enough that no name is cut.
            "COLUMNS": "300",
            "NO_COLOR": "1",
        }
        if home is not None:
            env["HERMES_HOME"] = str(home)
        env.update(self.engine.runtime_env())
        env.update(self.extra_env)
        off_loop("hermes skills source")
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [self.engine.hermes_bin, *args],
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=env,
            check=False,
            cwd=str(self.engine.host_home),
        )
        if done.returncode != 0:
            said = _clean(done.stdout + "\n" + done.stderr).splitlines()
            # The scan's findings (Hermes's own lines), so the owner sees why.
            found = [" ".join(ln.split()) for ln in said if _FINDING.match(ln)][:5]
            tail = (said or ["no output"])[-3:]
            raise SourceError(" ".join([*tail, *(f"Finding: {f}" for f in found)])[:900])
        return done.stdout

    # ---- this machine ---------------------------------------------------------------

    def machine_skills(self) -> list[Found]:
        root = self.engine.hermes_home / "skills"
        files = [
            p
            for p in (sorted(root.glob("**/SKILL.md")) if root.is_dir() else [])
            if len(p.relative_to(root).parts) <= 4 and ".hub" not in p.parts
        ]
        texts: list[tuple[Path, str]] = []
        for skill_md in files:
            text = skill_md.read_text(errors="replace")[:60_000]
            if lib.has_frontmatter(text):
                texts.append((skill_md, text))
        heads = lib.parse_skills([t for _p, t in texts]) if texts else []
        found = []
        for (skill_md, _text), (head, _body) in zip(texts, heads, strict=True):
            name = head.get("name", skill_md.parent.name)
            found.append(
                Found(
                    kind="skill",
                    name=name,
                    title=name,
                    summary=head.get("description", "")[:300],
                    origin=str(skill_md.parent),
                    importable=bool(lib.NAME.fullmatch(name)),
                    locked=None if lib.NAME.fullmatch(name) else "Name isn't lowercase-dash.",
                )
            )
        return found

    def machine_mcp(self) -> list[Found]:
        """Hermes's approved MCP catalog (remote servers). OAuth servers are
        imported like the rest; each workspace then signs in on its own
        (Settings → Capabilities → Sign in), so its tokens stay in its profile."""
        found = []
        catalog = self.repo / "optional-mcps"
        for manifest in sorted(catalog.glob("*/manifest.yaml")) if catalog.is_dir() else []:
            text = manifest.read_text(errors="replace")
            name = _yaml_value(text, "name") or manifest.parent.name
            url = _yaml_block_value(text, "transport", "url")
            kind = _yaml_block_value(text, "transport", "type")
            auth = _yaml_block_value(text, "auth", "type") or "none"
            description = _yaml_folded(text, "description")
            locked = None
            if kind != "http" or not url:
                locked = "Runs as a local command; locked."
            elif auth not in ("none", "", "oauth"):
                locked = f"Needs a {auth} login AGOS doesn't support yet."
            if auth == "oauth" and locked is None:
                description = f"{description} (Sign in per workspace.)".strip()
            found.append(
                Found(
                    kind="mcp",
                    name=name,
                    title=name.replace("-", " ").title(),
                    summary=description[:300],
                    origin=f"catalog:{manifest.parent.name}|{url}",
                    importable=locked is None,
                    locked=locked,
                    trust="Nous-approved",
                )
            )
        return found

    def machine_plugins(self) -> list[Found]:
        try:
            data = json.loads(
                self._hermes(["plugins", "list", "--json", "--no-bundled"], timeout=60)
            )
        except (SourceError, ValueError, subprocess.TimeoutExpired):
            return []
        rows = data if isinstance(data, list) else data.get("plugins", [])
        return [
            Found(
                kind="plugin",
                name=str(p.get("name") or p.get("id") or ""),
                title=str(p.get("name") or ""),
                summary=str(p.get("description") or "")[:300],
                origin=f"plugin:{p.get('name')}",
            )
            for p in rows
            if isinstance(p, dict) and (p.get("name") or p.get("id"))
        ]

    def read_machine_skill(self, origin: str) -> tuple[str, Path]:
        folder = Path(origin).resolve()
        root = (self.engine.hermes_home / "skills").resolve()
        if root not in folder.parents or not (folder / "SKILL.md").is_file():
            raise SourceError("That skill isn't in this machine's Hermes skills.")
        return (folder / "SKILL.md").read_text(errors="replace"), folder

    # ---- the web ----------------------------------------------------------------------

    def search_skills(self, query: str, limit: int = 12) -> list[Found]:
        if not query.strip():
            return []
        raw = self._hermes(
            ["skills", "search", query.strip()[:100], "--json", "--limit", str(limit)]
        )
        start = raw.find("[")
        try:
            rows = json.loads(raw[start:]) if start >= 0 else []
        except ValueError as error:
            raise SourceError("The skills hub answered in an unexpected way.") from error
        return [
            Found(
                kind="skill",
                name=str(r.get("name") or ""),
                title=str(r.get("name") or ""),
                summary=str(r.get("description") or "")[:300],
                origin=str(r.get("identifier") or ""),
                trust=str(r.get("trust_level") or ""),
            )
            for r in rows
            if r.get("identifier")
        ]

    def inspect_skill(self, identifier: str) -> str:
        _check_identifier(identifier)
        return _clean(self._hermes(["skills", "inspect", identifier]))[:12_000]

    def _library(self) -> Path:
        if self.library_home is None:
            raise SourceError("The library has no home folder yet.")
        (self.library_home / "skills").mkdir(parents=True, exist_ok=True)
        return self.library_home

    def skill_name(self, identifier: str) -> str:
        """The name Hermes gives the skill (its own `hermes skills inspect`)."""
        text = self.inspect_skill(identifier)
        found = re.search(r"^\s*Name:\s*(\S+)", text, re.MULTILINE)
        if found is None:
            # Hermes found nothing: say what Hermes said, not a naming problem.
            said = [ln.strip() for ln in text.splitlines() if ln.strip()]
            errors = [ln for ln in said if ln.lower().startswith("error")]
            raise SourceError(
                (errors or said or ["The skills hub couldn't find this skill."])[-1][:300]
            )
        if not lib.NAME.fullmatch(found.group(1)):
            raise SourceError("The engine didn't name this skill in a way AGOS can use.")
        return found.group(1)

    def install_skill(
        self, identifier: str, name: str, *, force: bool = False
    ) -> tuple[str, Path, str]:
        """Hermes's hub installs it (`hermes skills install` in the home: scan,
        quarantine, hub lock), into skills/<category>/<name>. Returns (SKILL.md
        text, folder, Hermes's scan report). Hermes refuses a blocked scan verdict;
        `force` is Hermes's own --force, only when the owner read the findings and
        clicked Install anyway."""
        _check_identifier(identifier)
        home = self._library()
        args = ["skills", "install", identifier, "--yes", "--name", name]
        if self.category:
            args += ["--category", self.category]
        out = self._hermes([*args, "--force"] if force else args, home=home, timeout=300)
        folder = home / "skills" / self.category / name if self.category else home / "skills" / name
        if not (folder / "SKILL.md").is_file():
            raise SourceError("Nothing was installed (see the scan report).")
        report = _clean(out)
        keep = [
            ln
            for ln in report.splitlines()
            if ln.startswith(("Decision:", "Scan provenance", "Source:", "rules:", "Files:"))
            or "verdict" in ln.lower()
        ]
        return (folder / "SKILL.md").read_text(errors="replace"), folder, "\n".join(keep)[:2000]

    def hub_states(self) -> dict[str, HubState]:
        """Every hub skill of the library, with what `hermes skills check` says."""
        out = self._hermes(["skills", "check"], home=self._library(), timeout=300)
        found = {}
        for cells in _table_rows(out):
            if len(cells) == 3 and cells[0] != "Name":
                found[cells[0]] = HubState(name=cells[0], source=cells[1], status=cells[2])
        return found

    def update_skill(self, name: str) -> None:
        """`hermes skills update <name> --force`: the owner clicked Update, so a copy
        he edited in AGOS is replaced too (as Update always did)."""
        out = _clean(
            self._hermes(["skills", "update", name, "--force"], home=self._library(), timeout=300)
        )
        if "Not updated" in out:
            raise SourceError(out.splitlines()[-1][:400])

    def uninstall_skill(self, name: str) -> None:
        """`hermes skills uninstall`: Hermes removes the folder and its lock entry."""
        self._hermes(["skills", "uninstall", name, "--yes"], home=self._library(), timeout=120)


def _table_rows(text: str) -> list[list[str]]:
    """The rows of a table Hermes prints (`│ a │ b │`)."""
    rows = []
    for line in _ANSI.sub("", text).splitlines():
        line = line.strip()
        if line.startswith(("│", "┃")) and line.endswith(("│", "┃")):
            rows.append([c.strip() for c in re.split(r"[│┃]", line)[1:-1]])
    return rows


def _check_identifier(identifier: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._/:@-]{3,300}", identifier) or ".." in identifier:
        raise SourceError("That doesn't look like a skill identifier.")


def _yaml_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip().strip("\"'") if m else ""


def _yaml_block_value(text: str, block: str, key: str) -> str:
    m = re.search(rf"^{block}:\s*\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE)
    if not m:
        return ""
    inner = re.search(rf"^[ \t]+{key}:\s*(.+)$", m.group(1), re.MULTILINE)
    return inner.group(1).strip().strip("\"'") if inner else ""


def _yaml_folded(text: str, key: str) -> str:
    """A top-level `key: value` or folded (`>-` / `|`) scalar, joined on one line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        rest = line[len(key) + 1 :].strip()
        if rest and rest not in (">", ">-", "|", "|-"):
            return rest.strip("\"'")
        body = []
        for follow in lines[i + 1 :]:
            if not follow.startswith((" ", "\t")):
                break
            body.append(follow.strip())
        return " ".join(body)
    return ""


def as_dict(found: Found) -> dict[str, Any]:
    return {
        "kind": found.kind,
        "name": found.name,
        "title": found.title,
        "summary": found.summary,
        "origin": found.origin,
        "importable": found.importable,
        "locked": found.locked,
        "trust": found.trust,
    }
