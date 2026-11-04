"""Workspace actions drive the engine: create → profile + sandbox config, folder
change → config rewritten + sandbox rebuilt + verified, failure → agent stopped.
A fake runner stands in for `hermes` and `docker`."""

import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import root_unit
from agos_core.engine.hermes import EngineError, sandbox_label_of

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


def _agos_name(home: str) -> str:
    """The fake keys a Hermes home by AGOS's name of its profile: a root is
    "agos-<ws>", a member under it "agos-<ws>--a-<agent>" (ADR 0020)."""
    path = Path(home)
    if path.parent.name == "profiles" and path.parent.parent.name.startswith("agos-"):
        return f"{path.parent.parent.name}--{path.name}"
    return path.name if path.name.startswith("agos-") else home


def _pinned(folder: str, key: str) -> bool:
    """The key is a leaf of the managed config.yaml in `folder` (managed_scope.py
    is_key_managed)."""
    import yaml

    if folder and key.isupper() and (Path(folder) / ".env").is_file():
        # An UPPER_SNAKE name: its managed .env (config.py env_write_refusal).
        lines = (Path(folder) / ".env").read_text().splitlines()
        return any(line.startswith(f"{key}=") for line in lines)
    if not folder or not (Path(folder) / "config.yaml").is_file():
        return False
    node: Any = yaml.safe_load((Path(folder) / "config.yaml").read_text()) or {}
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return not (isinstance(node, dict) and node)


def profile_dir(hermes_home: Path, name: str) -> Path:
    """Where Hermes keeps AGOS's profile `name` ("agos-<ws>[--a-<agent>]") in the
    tests' layout: each workspace's own root (ADR 0020) beside the shared home
    (<tmp>/home/.hermes → <tmp>/data/hermes; <tmp>/.hermes → <tmp>/roots)."""
    base = Path(hermes_home)
    roots = (
        base.parent.parent / "data" / "hermes"
        if base.parent.name == "home"
        else base.parent / "roots"
    )
    ws, sep, sub = name.partition("--")
    return roots / ws / "profiles" / sub if sep else roots / ws


class FakeRunner:
    def __init__(self, hermes_home: Path) -> None:
        self.hermes_home = hermes_home
        self.calls: list[list[str]] = []
        self.config: dict[str, dict[str, str]] = {}
        self.containers: dict[str, list[dict[str, object]]] = {}
        self.docker_down = False
        self.networks: dict[str, list[str]] = {}
        self.proxy_running = False
        self.named: set[str] = set()  # named helper containers (local MCP servers)
        self.kanban: dict[str, dict[str, dict[str, Any]]] = {}  # profile → Hermes's cards
        self.envs: list[dict[str, str]] = []  # environments of the calls run IN a root
        self.homes: dict[str, Path] = {}  # AGOS's profile name → its home in a root
        self.gateway_verbs: list[tuple[str, str]] = []  # `hermes -p X gateway stop|start`
        self.plugin_installs: list[tuple[str, ...]] = []  # `hermes plugins install`
        self.plugins_down = False

    def _network(self, args: list[str]) -> str:
        if args[0] == "ls":
            wanted = args[args.index("--filter") + 1].split("=", 1)[1].strip("^$")
            return wanted if wanted in self.networks else ""
        if args[0] == "create":
            assert "--internal" in args
            self.networks[args[-1]] = []
        elif args[0] == "connect":
            self.networks[args[1]].append(args[2])
        elif args[0] == "disconnect":
            self.networks.get(args[-2], []).remove(args[-1]) if args[-1] in self.networks.get(
                args[-2], []
            ) else None
        elif args[0] == "rm":
            self.networks.pop(args[-1], None)
        return ""

    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        argv = list(args)
        self.calls.append(argv)
        tool = Path(argv[0]).name
        if tool == "hermes" and argv[1:3] in (["config", "set"], ["config", "unset"]):
            # Like Hermes (hermes_cli/config.py _exit_if_key_managed): a key its
            # managed scope pins can't be set or unset in a profile.
            key = next(a for a in argv[3:] if not a.startswith("--"))
            if _pinned((env or {}).get("HERMES_MANAGED_DIR", ""), key):
                raise EngineError("hermes failed")
        home_env = (env or {}).get("HERMES_HOME", "")
        if tool != "docker" and home_env and argv[1:2] != ["-p"] and tool == "hermes":
            # A workspace on its own root (ADR 0020): Hermes runs IN that home. The
            # fake keys it by its path, like a profile name.
            self.envs.append(dict(env or {}))
            if argv[1:2] == ["pause"]:
                # Like Hermes (agent/estop.py engage): the ESTOP sentinel, with the reason.
                reason = argv[argv.index("--reason") + 1] if "--reason" in argv else None
                (Path(home_env) / "ESTOP").write_text(
                    json.dumps({"reason": reason, "engaged_at": "2026-01-01T00:00:00+00:00"})
                )
                return ""
            if argv[1:2] == ["resume"]:
                (Path(home_env) / "ESTOP").unlink(missing_ok=True)
                return ""
            if argv[1:3] == ["profile", "create"]:
                home = Path(home_env) / "profiles" / argv[3]
                home.mkdir(parents=True)
                (home / "config.yaml").write_text("{}\n")
                return ""
            if argv[1:3] == ["profile", "delete"]:
                import shutil

                shutil.rmtree(Path(home_env) / "profiles" / argv[3])
                return ""
            if argv[1:3] == ["profile", "describe"] and "--text" in argv:
                # Like Hermes's write_profile_meta: only the description changes.
                import yaml

                meta_file = Path(home_env) / "profiles" / argv[3] / "profile.yaml"
                meta = (yaml.safe_load(meta_file.read_text()) if meta_file.is_file() else {}) or {}
                meta["description"] = argv[argv.index("--text") + 1].strip()
                meta_file.write_text(yaml.safe_dump(meta, sort_keys=False))
                return ""
            if argv[1] == "backup":
                import zipfile

                out = Path(argv[argv.index("--output") + 1])
                with zipfile.ZipFile(out, "w") as zf:
                    for path in sorted(Path(home_env).rglob("*")):
                        if path.is_file() and "installs" not in path.parts:
                            zf.write(path, str(path.relative_to(home_env)))
                return ""
            if argv[1:3] == ["config", "set"]:
                Path(home_env).mkdir(parents=True, exist_ok=True)
            name = _agos_name(home_env)
            self.homes[name] = Path(home_env)
            argv = [argv[0], "-p", name, *argv[1:]]
        if tool == "docker":
            if self.docker_down:
                raise EngineError("docker did not answer")
            if argv[1] == "network":
                return self._network(argv[2:])
            if argv[1] == "run":
                name = argv[argv.index("--name") + 1] if "--name" in argv else ""
                if name.startswith("agos-mcp-"):
                    self.named.add(name)
                    return name
                self.proxy_running = True
                return "proxy-id"
            if argv[1] == "port":
                return "127.0.0.1:41234\n"
            if argv[1] == "ps" and any(a.startswith("name=^agos-mcp-") for a in argv):
                wanted = next(a for a in argv if a.startswith("name=^"))[6:].rstrip("$")
                return wanted if wanted in self.named else ""
            if argv[1] == "ps" and "label=agos-mcp=1" in argv:
                profile = next(a for a in argv if a.startswith("label=agos-profile="))[18:]
                return "\n".join(n for n in self.named if n.startswith(f"agos-mcp-{profile}-"))
            if argv[1] == "rm" and any(a.startswith("agos-mcp-") for a in argv):
                for a in argv[2:]:
                    self.named.discard(a)
                return ""
            if argv[1] == "ps" and "name=^agos-egress$" in argv:
                return "proxy-id" if self.proxy_running else ""
            if argv[1] == "inspect" and argv[-1] == "agos-egress":
                return " ".join(
                    n for n, members in self.networks.items() if "agos-egress" in members
                )
            if argv[1] == "rm" and argv[-1] == "agos-egress":
                self.proxy_running = False
                return ""
            if argv[1] == "ps":
                profile = argv[-1].rsplit("=", 1)[1]
                return "\n".join(
                    c for c, m in self.containers.items() if m and m[0]["p"] == profile
                )
            if argv[1] == "rm":
                for cid in argv[3:]:
                    self.containers.pop(cid, None)
                return ""
            if argv[1] == "inspect":
                return json.dumps(self.containers[argv[-1]][1:])
            return ""
        if argv[1] == "backup":
            # Hermes's own backup: its home as one zip (sessions, memory, logins…).
            import zipfile

            out = Path(argv[argv.index("--output") + 1])
            with zipfile.ZipFile(out, "w") as zf:
                for path in sorted(self.hermes_home.rglob("*")):
                    rel = path.relative_to(self.hermes_home)
                    if path.is_file() and (not rel.parts or rel.parts[0] != "hermes-agent"):
                        zf.write(path, str(rel))
            return ""
        if argv[1] == "profile" and argv[2] == "create":
            home = self.hermes_home / "profiles" / argv[3]
            home.mkdir(parents=True)
            (home / "config.yaml").write_text("{}\n")
            return ""
        if argv[1] == "profile" and argv[2] == "delete":
            import shutil

            shutil.rmtree(self.hermes_home / "profiles" / argv[3])
            return ""
        if argv[1] == "-p" and argv[3:5] == ["config", "get"]:
            have = self.config.get(argv[2], {})
            if argv[5] in have:
                return have[argv[5]]
            # A section: printed like Hermes does (nested keys, indented).
            lines, seen = [], set()
            for key in sorted(k for k in have if k.startswith(argv[5] + ".")):
                parts = key[len(argv[5]) + 1 :].split(".")
                for depth, part in enumerate(parts[:-1]):
                    head = ".".join(parts[: depth + 1])
                    if head not in seen:
                        seen.add(head)
                        lines.append("  " * depth + f"{part}:")
                lines.append("  " * (len(parts) - 1) + f"{parts[-1]}: {have[key]}")
            return "\n".join(lines)
        if argv[1] == "-p" and argv[3] == "kanban":
            return self._kanban(argv[2], argv[4:])
        if argv[1] == "-p" and argv[3:5] == ["config", "unset"]:
            if argv[5].isupper():
                # Like Hermes: an UPPER_SNAKE name is removed from the .env.
                env_file = self.home_of(argv[2]) / ".env"
                lines = env_file.read_text().splitlines() if env_file.exists() else []
                kept = [line for line in lines if not line.startswith(f"{argv[5]}=")]
                env_file.write_text("".join(f"{line}\n" for line in kept))
                return ""
            held = self.config.setdefault(argv[2], {})
            for key in [k for k in held if k == argv[5] or k.startswith(f"{argv[5]}.")]:
                held.pop(key)  # like Hermes: a mapping goes with what it holds
            self._write_yaml(argv[2])
            return ""
        if argv[1] == "-p" and argv[3:5] == ["config", "set"]:
            rest = [a for a in argv[5:] if a != "--force"]
            if rest[0].isupper():
                # Like Hermes: an UPPER_SNAKE name is an environment setting (.env).
                self._set_env(argv[2], rest[0], rest[1])
                return ""
            self.config.setdefault(argv[2], {})[rest[0]] = rest[1]
            self._write_yaml(argv[2])
            return ""
        if argv[1] == "-p" and argv[3] == "pairing":
            return self._pairing(argv[2], argv[4:])
        if argv[1] == "-p" and argv[3:5] == ["plugins", "install"]:
            # Hermes's catalog install: the plugin's code in the profile's plugins/.
            if self.plugins_down:
                raise EngineError("could not reach the plugin catalog")
            self.plugin_installs.append((argv[2], argv[5], *argv[6:]))  # first: files => counted
            folder = self.home_of(argv[2]) / "plugins" / argv[5]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "plugin.yaml").write_text(f"name: {argv[5]}\n")
            return ""
        if argv[1] == "-p" and argv[3:5] == ["curator", "archive"]:
            # Hermes's curator moves a local skill to skills/.archive/ (skill_usage.archive_skill).
            skills = self.home_of(argv[2]) / "skills"
            found = [
                p.parent
                for p in skills.rglob("SKILL.md")
                if p.parent.name == argv[5] and ".archive" not in p.parts
            ]
            if not found:
                raise EngineError(f"curator: skill '{argv[5]}' not found")
            (skills / ".archive").mkdir(parents=True, exist_ok=True)
            found[0].rename(skills / ".archive" / argv[5])
            self.calls.append(["curator-archived", argv[2], argv[5]])
            return ""
        if argv[1] == "-p" and argv[3:4] == ["gateway"] and argv[4] in ("stop", "start"):
            # A member served by its root's running gateway (gateway_profile_lifecycle.py):
            # stop parks it, start unparks it; the host (un)serves it at once.
            self.gateway_verbs.append((argv[2], argv[4]))
            marker = self.home_of(argv[2]) / "gateway.parked"
            if argv[4] == "stop":
                marker.touch()
            else:
                marker.unlink(missing_ok=True)
            return ""
        return ""

    def home_of(self, profile: str) -> Path:
        return self.homes.get(profile) or (
            Path(profile) if profile.startswith("/") else self.hermes_home / "profiles" / profile
        )

    def _set_env(self, profile: str, name: str, value: str) -> None:
        env = self.home_of(profile) / ".env"
        lines = [
            line
            for line in (env.read_text().splitlines() if env.exists() else [])
            if not line.startswith(f"{name}=")
        ]
        env.write_text("\n".join([*lines, f"{name}={value}"]) + "\n")

    def _pairing(self, profile: str, args: list[str]) -> str:
        """Hermes's DM pairing CLI (gateway/pairing.py): approve a request, revoke."""
        folder = self.home_of(profile) / "platforms" / "pairing"
        folder.mkdir(parents=True, exist_ok=True)
        platform = args[1]
        pending_file = folder / f"{platform}-pending.json"
        approved_file = folder / f"{platform}-approved.json"
        pending = json.loads(pending_file.read_text()) if pending_file.exists() else {}
        approved = json.loads(approved_file.read_text()) if approved_file.exists() else {}
        env = self.home_of(profile) / ".env"
        allow = next(
            (
                line.split("=", 1)[1]
                for line in (env.read_text().splitlines() if env.exists() else [])
                if line.startswith("TELEGRAM_ALLOWED_USERS=")
            ),
            "",
        )
        ids = [x for x in allow.split(",") if x]
        if args[0] == "approve" and args[2] in pending:
            entry = pending.pop(args[2])
            approved[entry["user_id"]] = {"user_name": entry.get("user_name", "")}
            if ids and entry["user_id"] not in ids:  # mirrored into a configured allowlist
                self._set_env(profile, "TELEGRAM_ALLOWED_USERS", ",".join([*ids, entry["user_id"]]))
        elif args[0] == "revoke" and args[2] in approved:
            approved.pop(args[2])
            if args[2] in ids:
                rest = ",".join(x for x in ids if x != args[2])
                self._set_env(profile, "TELEGRAM_ALLOWED_USERS", rest)
        pending_file.write_text(json.dumps(pending))
        approved_file.write_text(json.dumps(approved))
        return ""

    def _write_yaml(self, profile: str) -> None:
        """Like Hermes: the profile's config.yaml holds what was set (nested keys)."""
        home = self.homes.get(profile) or (
            Path(profile) if profile.startswith("/") else self.hermes_home / "profiles" / profile
        )
        if not home.is_dir():
            return
        tree: dict[str, Any] = {}
        for key, value in self.config.get(profile, {}).items():
            *parents, leaf = key.split(".")
            node = tree
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = value

        def lines(node: dict[str, Any], depth: int) -> list[str]:
            out: list[str] = []
            for k, v in node.items():
                if isinstance(v, dict):
                    out += ["  " * depth + f"{k}:", *lines(v, depth + 1)]
                else:
                    # Like Hermes: a JSON value is stored as data, anything else as text.
                    try:
                        data = json.loads(v)
                    except (TypeError, ValueError):
                        data = v
                    out.append("  " * depth + f"{k}: {json.dumps(data)}")
            return out

        (home / "config.yaml").write_text("\n".join(lines(tree, 0)) + "\n")

    def _kanban(self, profile: str, args: list[str]) -> str:
        """Hermes's Kanban CLI, enough for AGOS's page (one board per profile)."""
        cards = self.kanban.setdefault(profile, {})

        def opt(name: str) -> str | None:
            return args[args.index(name) + 1] if name in args else None

        verb = args[0]
        if verb == "stats":  # hermes_cli/kanban_db.py board_stats (archived left out)
            by_status: dict[str, int] = {}
            for c in cards.values():
                if c["status"] != "archived":
                    by_status[str(c["status"])] = by_status.get(str(c["status"]), 0) + 1
            return json.dumps({"by_status": by_status, "by_assignee": {}})
        if verb == "list":
            return json.dumps([c for c in cards.values() if c["status"] != "archived"])
        if verb == "create":
            key = opt("--idempotency-key")
            for existing in cards.values():
                if key and existing.get("key") == key and existing["status"] != "archived":
                    return json.dumps(existing)
            card_id = f"t_{len(cards) + 1:08x}"
            parents = [args[i + 1] for i, a in enumerate(args) if a == "--parent"]
            waits = any(cards[p]["status"] not in ("done", "archived") for p in parents)
            cards[card_id] = {
                "id": card_id,
                "title": args[1],
                "body": opt("--body"),
                "assignee": opt("--assignee"),
                "status": "triage"
                if "--triage" in args
                else "blocked"
                if opt("--initial-status") == "blocked"
                else ("ready" if opt("--assignee") and not waits else "todo"),
                "model_override": opt("--model"),
                "goal": "--goal" in args,
                "parents": [args[i + 1] for i, a in enumerate(args) if a == "--parent"],
                "created_at": 1_800_000_000 + len(cards),
                "comments": [],
                "key": key,
            }
            return json.dumps(cards[card_id])
        if verb == "attach-rm":
            for c in cards.values():
                c["files"] = [x for x in c.get("files", []) if x["id"] != int(args[1])]
            return "ok"
        if verb == "link":  # hermes_cli/kanban_db.py link_tasks: parent -> child
            if args[1] not in cards or args[2] not in cards:
                raise EngineError(f"unknown task(s): {args[1]}, {args[2]}")
            cards[args[2]].setdefault("parents", []).append(args[1])
            return "ok"
        card = cards.get(args[1])
        if card is None:
            raise EngineError(f"no task {args[1]}")
        if verb == "attachments":
            return json.dumps(card.get("files", []))
        if verb == "attach":
            path = Path(args[2])
            files = card.setdefault("files", [])
            files.append(
                {
                    "id": sum(len(c.get("files", [])) for c in cards.values()) + 1,
                    "filename": opt("--name") or path.name,
                    "size": path.stat().st_size,
                    "uploaded_by": opt("--author") or "user",
                    "stored_path": str(self.hermes_home / "kept" / path.name),
                    "created_at": 1_800_000_200,
                }
            )
            kept = self.hermes_home / "kept"
            kept.mkdir(exist_ok=True)
            (kept / path.name).write_bytes(path.read_bytes())
            return "ok"
        if verb == "show":
            task = {k: v for k, v in card.items() if k != "comments"}
            return json.dumps(
                {
                    "task": task,
                    "latest_summary": card.get("summary"),
                    "comments": card["comments"],
                    "events": [],
                    "parents": [],
                    "children": [],
                }
            )
        if verb == "comment":
            card["comments"].append(
                {"author": opt("--author") or "user", "body": args[2], "created_at": 1_800_000_100}
            )
        elif verb == "assign":
            card["assignee"] = None if args[2] == "none" else args[2]
        elif verb == "edit":  # hermes_cli/kanban.py edit: --title / --body replaced
            card["body"] = opt("--body") if "--body" in args else card.get("body")
            card["title"] = opt("--title") or card["title"]
        elif verb == "complete":
            # Like Hermes (hermes_cli/kanban_db.py complete_task): --result/--summary
            # (its argparse takes `--flag=text` too) land on the card; its
            # empty-completion gate refuses a card out of anything but review with
            # no words and no stored result, and says why on stderr.
            given = dict(a.split("=", 1) for a in args[2:] if a.startswith("--") and "=" in a)
            result = given.get("--result", opt("--result"))
            summary = given.get("--summary", opt("--summary"))
            texts = (result, summary, card.get("result"))
            if card["status"] != "review" and not any(str(t or "").strip() for t in texts):
                raise EngineError(
                    "hermes failed",
                    reason=f"cannot complete {args[1]}: completion blocked: {args[1]} has no"
                    " result or summary evidence. Pass --result/--summary describing what was"
                    " done (an empty completion is not evidence).",
                )
            handoff = summary if summary is not None else result
            if handoff is None and card["status"] == "review":
                handoff = "Review approved without additional evidence."
            card.update(status="done", result=result, summary=handoff)
        elif verb == "schedule":
            # hermes_cli/kanban_db.py schedule_task: todo / ready / running / blocked
            if card["status"] not in ("todo", "ready", "running", "blocked"):
                raise EngineError("hermes failed", reason=f"cannot schedule {args[1]}")
            card["status"] = "scheduled"
        elif verb == "reopen-review":
            # hermes_cli/kanban_db.py reopen_review_task: review -> ready (todo while a
            # parent is open), the implementer of the review handoff back on it; the
            # CLI's --reason becomes a "CHANGES REQUESTED:" comment.
            if card["status"] != "review":
                raise EngineError(
                    "hermes failed", reason=f"cannot reopen {args[1]} (not in review?)"
                )
            reason = opt("--reason")
            if reason:
                card["comments"].append(
                    {
                        "author": "owner",
                        "body": f"CHANGES REQUESTED: {reason}",
                        "created_at": 1_800_000_100,
                    }
                )
            waits = any(
                cards[p]["status"] not in ("done", "archived")
                for p in card.get("parents") or []
                if p in cards
            )
            card["assignee"] = card.get("implementer") or card["assignee"]
            card["status"] = "todo" if waits else "ready"
        elif verb == "unblock":
            if card["status"] not in ("blocked", "scheduled"):
                raise EngineError(
                    "hermes failed", reason=f"cannot unblock {args[1]} (not blocked/scheduled?)"
                )
            card["status"] = "ready"
        else:
            card["status"] = {
                "archive": "archived",
                "block": "blocked",
            }[verb]
        return "ok"

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        self.calls.append(list(args))

    def fake_sandbox(self, cid: str, profile: str) -> None:
        """What Hermes would create from the profile's current config."""
        volumes = json.loads(self.config[profile]["terminal.docker_volumes"])
        # Hermes labels it with the profile's container key (AGOS's name, hashed).
        mounts: list[dict[str, object]] = [{"p": sandbox_label_of(profile)}]
        for spec in volumes:
            parts = spec.split(":")
            mounts.append(
                {"Type": "bind", "Source": parts[0], "Destination": parts[1], "RW": len(parts) == 2}
            )
        self.containers[cid] = mounts


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, FakeRunner, Path]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    runner = FakeRunner(hermes_home)
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        app.state.core.engine.runner = runner
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, runner, tmp_path


def test_create_sets_up_an_isolated_profile(env: tuple[TestClient, FakeRunner, Path]) -> None:
    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    config = runner.config["agos-argan"]
    assert config["terminal.backend"] == "docker"
    files = (tmp / "data" / "workspaces" / ws / "files").resolve()
    assert json.loads(config["terminal.docker_volumes"]) == [
        f"{files}:/workspace",
        *[
            f"{files}/playbooks/{k}:/workspace/playbooks/{k}:ro"
            for k in ("agents", "automations")  # skills: Hermes's own (external_dirs)
        ],
    ]
    env_file = profile_dir(tmp / "home" / ".hermes", "agos-argan") / ".env"
    text = env_file.read_text()
    assert "API_SERVER_HOST=127.0.0.1" in text and "API_SERVER_KEY=" in text
    assert env_file.stat().st_mode & 0o077 == 0


def test_folder_add_and_remove_rebuild_and_verify(env: tuple[TestClient, FakeRunner, Path]) -> None:
    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    reports = tmp / "Reports"
    reports.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert vols[1] == f"{reports.resolve()}:/shared/reports:ro"

    # A sandbox Hermes built while the folder was granted…
    runner.fake_sandbox("c1", "agos-argan")
    assert client.delete(f"/workspaces/{ws}/folders/reports").status_code == 200
    # …is gone, and the config no longer has the folder.
    assert "c1" not in runner.containers
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert not any("/shared/" in v for v in vols)
    assert ["/bin/docker", "rm", "-f", "c1"] in runner.calls


def test_added_folders_are_hermess_docker_volumes(env: tuple[TestClient, FakeRunner, Path]) -> None:
    """The folders shown are the `/shared/<name>` mounts in the root's Hermes
    `terminal.docker_volumes` (the one list): a change there shows, AGOS keeps no
    row, its old rows move into Hermes at the next sync, and a forbidden path put
    into Hermes by hand is still refused (fail closed)."""
    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    reports = tmp / "Reports"
    reports.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    core: Any = client.app.state.core  # type: ignore[attr-defined]
    shown = client.get(f"/workspaces/{ws}/folders").json()[1:]
    assert [(f["name"], f["access"]) for f in shown] == [
        ("reports", "read")
    ]  # read only by default
    # Changed in Hermes itself (read and write): shown as Hermes has it.
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    vols = [v.removesuffix(":ro") if "/shared/reports" in v else v for v in vols]
    runner.config["agos-argan"]["terminal.docker_volumes"] = json.dumps(vols)
    runner._write_yaml("agos-argan")
    shown = client.get(f"/workspaces/{ws}/folders").json()[1:]
    assert [(f["name"], f["access"]) for f in shown] == [("reports", "read-write")]
    assert (
        client.put(f"/workspaces/{ws}/folders/reports", json={"access": "read"}).status_code == 200
    )
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert f"{reports.resolve()}:/shared/reports:ro" in vols
    # AGOS's old rows (from before): into Hermes at the next sync, then gone.
    notes = tmp / "Notes"
    notes.mkdir()
    from agos_core.db.app_settings import get_setting, set_setting

    set_setting(
        core.db,
        f"folders.move.{ws}",
        [{"name": "notes", "host_path": str(notes.resolve()), "access": "read"}],
    )
    from agos_core.actions.engine import sync_workspace

    sync_workspace(core, ws)
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert f"{notes.resolve()}:/shared/notes:ro" in vols
    assert get_setting(core.db, f"folders.move.{ws}", None) is None
    # A secret folder written into Hermes by hand is never mounted.
    vols.append(f"{(tmp / 'home' / '.ssh')}:/shared/keys")
    runner.config["agos-argan"]["terminal.docker_volumes"] = json.dumps(vols)
    runner._write_yaml("agos-argan")
    import pytest

    from agos_core.actions.errors import ActionError

    with pytest.raises(ActionError):
        sync_workspace(core, ws)


def test_nothing_writes_workspace_folders() -> None:
    """Guard: the added folders live only in Hermes; AGOS's old table is gone, and
    what it held is only read (until moved) and deleted."""
    src = Path(__file__).resolve().parents[1] / "src" / "agos_core"
    for path in src.rglob("*.py"):
        if path.name == "migrations.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text()
        assert not re.search(r"\b(FROM|INTO|JOIN|UPDATE|TABLE)\s+workspace_folders\b", text), path
    for path in src.rglob("*.py"):
        if "__pycache__" in path.parts or path.name in ("migrations.py", "workspaces.py"):
            continue
        assert "MOVE_FOLDERS" not in path.read_text(), path


def test_private_folders_refused(env: tuple[TestClient, FakeRunner, Path]) -> None:
    client, _, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    for path in (tmp / "home", tmp / "home" / ".hermes"):
        r = client.post(f"/workspaces/{ws}/folders", json={"path": str(path)})
        assert r.status_code == 400, path
    assert client.get(f"/workspaces/{ws}/folders").json()[1:] == []


def test_fail_closed_when_docker_is_down(env: tuple[TestClient, FakeRunner, Path]) -> None:
    """Docker down before Hermes took the folder (its network can't be checked): the
    click says it wasn't saved and the agent is stopped, as before C2; no restart
    is waiting."""
    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    reports = tmp / "Reports"
    reports.mkdir()
    runner.docker_down = True
    r = client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)})
    assert r.status_code == 503 and "stopped" in r.json()["detail"]
    kinds = [a["text"] for a in client.get(f"/workspaces/{ws}/log").json()["entries"]]
    assert any("could not be updated" in k for k in kinds)
    assert client.get(f"/workspaces/{ws}/gateway-restart").json()["state"] != "restarting"


def _restart_ended(client: TestClient, ws: str) -> dict[str, Any]:
    """The workspace's gateway restart as the page reads it, once it has ended."""
    import time

    deadline = time.monotonic() + 15
    while True:
        said: dict[str, Any] = client.get(f"/workspaces/{ws}/gateway-restart").json()
        if said.get("state") != "restarting" or time.monotonic() > deadline:
            return said
        time.sleep(0.02)


def _running_root(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str]]:
    """The click's restart as live: in the background, its gateway running; the
    gateway's stop and start are recorded with the folders Hermes held then."""
    from agos_core.actions import engine as engine_actions

    monkeypatch.setattr(engine_actions, "RESTART_IN_BACKGROUND", True)
    monkeypatch.setattr(engine_actions, "RESTART_SETTLE_S", 0.0)
    core: Any = client.app.state.core  # type: ignore[attr-defined]
    seen: list[str] = []
    core.engine.is_running = lambda workspace_id: True
    core.engine.stop = lambda workspace_id, **_: seen.append("stop")
    core.engine.start = lambda workspace_id, **_: seen.append("start")
    return core, seen


def test_a_folder_click_answers_before_its_gateway_restarts(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2: the click answers once Hermes's terminal.docker_volumes holds the new
    folder; the gateway's stop, the sandbox drop and the start come after the
    answer, and the page reads 'restarting' until they are done."""
    import threading

    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core, seen = _running_root(client, monkeypatch)
    gate = threading.Event()

    def stop(workspace_id: str, **_: Any) -> None:
        assert gate.wait(10)
        seen.append("stop")

    core.engine.stop = stop
    runner.fake_sandbox("c1", "agos-argan")
    reports = tmp / "Reports"
    reports.mkdir()
    r = client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)})
    assert r.status_code == 201
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert f"{reports.resolve()}:/shared/reports:ro" in vols  # in Hermes at the answer
    assert seen == [] and "c1" in runner.containers  # nothing stopped or dropped yet
    assert client.get(f"/workspaces/{ws}/gateway-restart").json() == {
        "state": "restarting",
        "reason": "",
    }
    gate.set()
    assert _restart_ended(client, ws) == {"state": "done", "reason": ""}
    assert seen == ["stop", "start"] and "c1" not in runner.containers


def test_three_quick_folder_clicks_restart_the_gateway_once_with_the_last_setup(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2: folder clicks in a row are one restart, the newest setup wins."""
    import threading

    from agos_core.actions import engine as engine_actions

    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core, seen = _running_root(client, monkeypatch)
    held: list[list[str]] = []

    def stop(workspace_id: str, **_: Any) -> None:
        held.append(json.loads(runner.config["agos-argan"]["terminal.docker_volumes"]))
        seen.append("stop")

    core.engine.stop = stop
    clicks_in = threading.Event()
    settle = engine_actions._settle
    monkeypatch.setattr(engine_actions, "_settle", lambda job: (clicks_in.wait(10), settle(job)))
    reports, notes = tmp / "Reports", tmp / "Notes"
    reports.mkdir()
    notes.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    assert (
        client.put(f"/workspaces/{ws}/folders/reports", json={"access": "read-write"}).status_code
        == 200
    )
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(notes)}).status_code == 201
    clicks_in.set()
    assert _restart_ended(client, ws) == {"state": "done", "reason": ""}
    assert seen == ["stop", "start"]
    assert f"{reports.resolve()}:/shared/reports" in held[0]
    assert f"{notes.resolve()}:/shared/notes:ro" in held[0]


def test_a_folder_restart_that_fails_leaves_the_agent_stopped_and_says_why(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2, fail closed in the background: the gateway can't come back with the new
    folders -> the workspace is parked (stays stopped), the status says failed with
    the reason, the log says the agent was stopped."""
    client, _runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core, _seen = _running_root(client, monkeypatch)
    parked: list[str] = []

    def start(workspace_id: str, **_: Any) -> None:
        raise EngineError("the workspace's engine did not start")

    core.engine.start = start
    core.engine.park = parked.append
    reports = tmp / "Reports"
    reports.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    said = _restart_ended(client, ws)
    assert said["state"] == "failed"
    assert "the agent is stopped" in said["reason"]
    assert parked == [ws]
    texts = [a["text"] for a in client.get(f"/workspaces/{ws}/log").json()["entries"]]
    assert "The agent was stopped: its sandbox could not be updated" in texts
    # The next click starts over: restarting again, then its own verdict.
    core.engine.start = lambda workspace_id, **_: None
    notes = tmp / "Notes"
    notes.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(notes)}).status_code == 201
    assert _restart_ended(client, ws) == {"state": "done", "reason": ""}


def test_the_gateway_restart_status_is_owner_only(
    env: tuple[TestClient, FakeRunner, Path],
) -> None:
    client, _runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    assert client.get(f"/workspaces/{ws}/gateway-restart").json() == {
        "state": "done",
        "reason": "",
    }
    bad = client.get(f"/workspaces/{ws}/gateway-restart", headers={"x-agos-internal": "nope"})
    assert bad.status_code == 401
    assert client.get("/workspaces/nope/gateway-restart").status_code == 404


def test_trash_parks_and_purge_deletes_the_profile(
    env: tuple[TestClient, FakeRunner, Path],
) -> None:
    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    runner.fake_sandbox("c1", "agos-argan")
    assert client.post(f"/workspaces/{ws}/delete", json={"confirm": ws}).status_code == 200
    assert "c1" not in runner.containers
    profile = profile_dir(tmp / "home" / ".hermes", "agos-argan")
    assert profile.exists()  # restorable from the trash
    assert client.delete(f"/trash/{ws}").status_code == 200
    assert not profile.exists()


def test_leftover_profile_is_never_inherited(env: tuple[TestClient, FakeRunner, Path]) -> None:
    client, _, tmp = env
    (profile_dir(tmp / "home" / ".hermes", "agos-argan")).mkdir(parents=True)
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    assert ws == "argan-2"


def test_sandboxes_sit_on_an_internal_network_behind_the_egress_proxy(tmp_path: Path) -> None:
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine

    home = tmp_path / ".hermes"
    home.mkdir()
    runner = FakeRunner(home)
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
    )
    engine.is_running = lambda workspace_id: False  # type: ignore[method-assign]
    ws_files = tmp_path / "data" / "workspaces" / "a" / "files"
    ws_files.mkdir(parents=True)
    engine.apply(
        "a",
        files_dir=ws_files,
        workspaces_dir=tmp_path / "data" / "workspaces",
        agos_data=tmp_path / "data",
        grants=[],
    )
    assert runner.networks == {"agos-net-agos-a": ["agos-egress"]}
    assert runner.proxy_running
    config = runner.config["agos-a"]
    assert json.loads(config["terminal.docker_extra_args"]) == ["--network=agos-net-agos-a"]
    env = json.loads(config["terminal.docker_env"])
    assert (
        env["HTTPS_PROXY"] == "http://agos-egress:8888" and env["NO_PROXY"] == "localhost,127.0.0.1"
    )
    run = next(c for c in runner.calls if c[1] == "run")
    for flag in ("--read-only", "--cap-drop", "no-new-privileges"):
        assert flag in run
    assert not any("docker.sock" in part for part in run)
    # Purge removes the network.
    (profile_dir(home, "agos-a")).mkdir(parents=True, exist_ok=True)
    (profile_dir(home, "agos-a") / "config.yaml").write_text("{}")
    sandboxes = profile_dir(home, "agos-a") / "sandboxes"
    (sandboxes / "docker" / "default").mkdir(parents=True)
    runner.calls.clear()
    engine.delete_profile("a")
    assert runner.networks == {}
    # Root-owned sandbox folders are emptied by a one-shot container that sees
    # only that folder, as root, with no network.
    clear = next(c for c in runner.calls if c[1] == "run" and "--rm" in c)
    assert f"{sandboxes.resolve()}:/clear" in clear
    i = clear.index("--network")
    assert clear[i : i + 2] == ["--network", "none"]
    assert sum(1 for part in clear if part.endswith(":/clear")) == 1


def test_child_env_drops_hermes_session_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a parent Hermes session's markers, `hermes gateway stop` SIGTERMed
    agos-core itself (found live in step 10)."""
    from agos_core.engine.hermes import RUNTIME, child_env

    for name in (
        "_HERMES_GATEWAY",
        "HERMES_SESSION_KEY",
        "HERMES_PARENT_NONCE",
        "HERMES_HOME",
        "AGOS_DATA_DIR",
        "PYTEST_CURRENT_TEST",
        "TERMINAL_ENV",
    ):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = child_env({"HOME": "/home/x"})
    assert not [
        k
        for k in env
        if k.startswith(("HERMES", "_HERMES", "AGOS_", "PYTEST_", "TERMINAL_"))
        and k not in RUNTIME  # AGOS's own: the install's runtime, the managed scope
    ]
    assert all(env[k] == v for k, v in RUNTIME.items())
    assert env["HOME"] == "/home/x" and env["LANG"] == "C.UTF-8"


def test_foreign_process_records_are_removed_before_a_gateway_starts(tmp_path: Path) -> None:
    import os

    from agos_core.engine.hermes import scrub_foreign_processes

    records = [
        {
            "session_id": "a",
            "command": "npm run dev",
            "pid": 999_999,
            "pgid": 999_999,
            "cwd": "/workspace/app",
        },
        {
            "session_id": "b",
            "command": "uvicorn agos_core.api.app",
            "pid": 5,
            "pgid": 5,
            "cwd": "/workspace",
        },
        {
            "session_id": "c",
            "command": "sleep 1",
            "pid": os.getppid(),
            "pgid": 1,
            "cwd": "/workspace",
        },
        {
            "session_id": "d",
            "command": "pytest tests/",
            "pid": 999_998,
            "pgid": 999_998,
            "cwd": "/Users/someone/project",
        },
    ]
    (tmp_path / "processes.json").write_text(json.dumps(records))
    assert scrub_foreign_processes(tmp_path) == 3
    left = json.loads((tmp_path / "processes.json").read_text())
    assert [r["session_id"] for r in left] == ["a"]
    assert scrub_foreign_processes(tmp_path / "missing") == 0


def test_an_unchanged_workspace_is_not_restarted(env: tuple[TestClient, FakeRunner, Path]) -> None:
    """Each core start re-checks every workspace; a running answer is never cut
    when nothing changed. A real change still reloads (and is verified)."""
    client, _runner, tmp = env
    from agos_core.actions.engine import sync_workspace

    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core = client.app.state.core  # type: ignore[attr-defined]
    stops: list[str] = []
    core.engine.is_running = lambda workspace_id: True
    core.engine.stop = lambda workspace_id, **_: stops.append(workspace_id)
    core.engine.start = lambda workspace_id, **_: None
    sync_workspace(core, ws)  # first time with it running: applied once
    stops.clear()
    sync_workspace(core, ws)
    sync_workspace(core, ws)
    assert stops == []  # same setup: no restart
    reports = tmp / "Reports"
    reports.mkdir()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    assert stops == [ws]  # a real change still reloads


def test_a_gateway_gets_its_own_temp_folder_that_outlives_agos_core(tmp_path: Path) -> None:
    """agos-core runs with systemd PrivateTmp: a gateway it starts shared that /tmp,
    and when agos-core restarted (every update) the folder was deleted under the
    still-running gateway: the browser failed with "No such file or directory:
    /tmp/agent-browser-…". Each gateway gets a short temp folder of its own instead."""
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine

    spawned: list[dict[str, str]] = []

    class Runner:
        def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
            spawned.append(dict(env or {}))

    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
            gateway_supervisor="spawn",
        ),
        runner=Runner(),  # type: ignore[arg-type]
    )
    engine.is_running = lambda _ws: bool(spawned)  # type: ignore[method-assign,assignment]
    engine.start("a-very-long-workspace-name")
    engine.is_running = lambda _ws: len(spawned) > 1  # type: ignore[method-assign,assignment]
    engine.start("other--a-member")  # a member's key starts its root's one gateway
    one, two = (Path(e["TMPDIR"]) for e in spawned)
    assert one != two and one.is_dir() and two.is_dir()
    assert one.is_relative_to(tmp_path / ".agos-tmp")
    # Hermes needs it short for the browser's socket (/home/agos/ + 21 chars here).
    assert len(str(one)) - len(str(tmp_path)) <= 22
    assert one.stat().st_mode & 0o777 == 0o700


def test_a_sandbox_going_away_after_an_update_does_not_stop_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live: after each update the old gateway's sandbox was still going away when
    AGOS checked, so the agent was stopped for nothing. A mismatch is checked again
    a few times; one that stays still stops the agent."""
    from agos_core.actions import engine as engine_actions
    from agos_core.engine.rules import SandboxCheck

    monkeypatch.setattr(engine_actions, "VERIFY_WAIT_SECONDS", 0.0)
    wrong = SandboxCheck(ok=False, missing=[], unexpected=["/old:/shared/old"])

    class Engine:
        def __init__(self, bad_checks: int) -> None:
            self.left = bad_checks
            self.calls = 0

        def verify(
            self, workspace_id: str, mounts: Any, shared: Any = ()
        ) -> list[tuple[str, SandboxCheck]]:
            self.calls += 1
            if self.left > 0:
                self.left -= 1
                return [("old-sandbox", wrong)]
            return []

    going = Engine(bad_checks=1)
    assert engine_actions._mismatched(going, "argan", []) == [] and going.calls == 2
    stays = Engine(bad_checks=99)
    assert engine_actions._mismatched(stays, "argan", []) == [("old-sandbox", wrong)]
    assert stays.calls == engine_actions.VERIFY_TRIES


def test_a_cofounder_runs_as_hermess_own_gateway_service(tmp_path: Path) -> None:
    """Like Hermes's own gateway: `hermes gateway install` (systemd, Restart=always,
    at boot) then `hermes gateway start`, run IN the workspace's root. That one
    gateway serves its members too: a member never gets a gateway of its own."""
    from agos_core.engine.hermes import HermesEngine

    calls: list[list[str]] = []
    homes: list[str] = []
    spawned: list[list[str]] = []

    class Runner:
        def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
            calls.append(list(args))
            homes.append(str((env or {}).get("HERMES_HOME", "")))
            if list(args)[1:3] == ["gateway", "install"]:
                unit = engine.service_unit("shop")
                unit.parent.mkdir(parents=True, exist_ok=True)
                unit.write_text("[Service]\n")
            if args[0] == "systemctl":
                return "active" if engine.service_unit("shop").is_file() else "inactive"
            return ""

        def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
            spawned.append(list(args))

    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner=Runner(),
    )
    root = engine.root("shop")
    root.mkdir(parents=True)
    # Hermes's own name for the root's unit, kept in AGOS's marker.
    root_unit.remember(root, "hermes-gateway-1a2b3c.service")
    started: list[int] = []
    engine.is_running = lambda _ws: bool(started) or bool(spawned)  # type: ignore[method-assign,assignment]
    real_hermes = engine._hermes

    def hermes(ws: str, *args: str, timeout: float = 60) -> str:
        if args[:2] == ("gateway", "start"):
            started.append(1)
        return real_hermes(ws, *args, timeout=timeout)

    engine._hermes = hermes  # type: ignore[method-assign,assignment]
    engine.start("shop")
    hermes_calls = [c[1:] for c in calls if c[0] == "/bin/hermes"]
    assert hermes_calls[0][:2] == ["gateway", "install"] and "--start-on-login" in hermes_calls[0]
    assert hermes_calls[1] == ["gateway", "start"]
    assert {h for h, c in zip(homes, calls, strict=True) if c[0] == "/bin/hermes"} == {str(root)}
    assert spawned == []  # never `gateway run` by AGOS for a Co-Founder
    assert engine.service_unit("shop").name == "hermes-gateway-1a2b3c.service"
    before = len(calls)
    engine.start("shop--a-writer")
    assert spawned == []  # the root's one gateway serves its members
    assert not [c for c in calls[before:] if c[0] == "/bin/hermes"]


def test_an_agos_stop_is_quiet_and_leaves_no_drain_behind(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live: every reload made Hermes post "Hermes is shutting down" in the Co-Founder's
    chat. AGOS's own stops set Hermes's quiet drain first and remove it after, so
    the next gateway takes work; a drain someone else set is never touched."""
    from agos_core.engine import hermes as hermes_engine

    client, _runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core = client.app.state.core  # type: ignore[attr-defined]
    engine = core.engine
    home = engine.profile_home(ws)
    marker = home / ".drain_request.json"
    seen: list[bool] = []

    def quiet(at: Path, *, on: bool) -> bool:  # Hermes's drain_control, in its runtime
        assert at == home
        if on:
            marker.write_text(json.dumps({"principal": hermes_engine.QUIET_PRINCIPAL}))
        else:
            marker.unlink()
        return True

    def running(workspace_id: str) -> bool:
        seen.append(marker.exists())
        return False

    monkeypatch.setattr(engine, "_quiet_drain", quiet)
    monkeypatch.setattr(engine, "is_running", running)
    engine.stop(ws)
    assert seen and seen[0] is True  # the marker was there while the gateway went down
    assert not marker.exists()  # and is gone for the next start
    marker.write_text(json.dumps({"principal": "dashboard"}))
    assert hermes_engine.quiet_drain_set(home) is False  # never AGOS's to remove


def test_the_screen_picture_is_hermess_running_screen_in_its_own_sandbox(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Screen tab shows the screen Hermes has running: Hermes's own record
    (bot-desktop/sandbox.json) names its container, and only this workspace's
    own sandbox is ever looked into."""
    from agos_core.engine import hermes as engine_module

    client, runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    runner.fake_sandbox("c1", "agos-argan")
    runner.fake_sandbox("c9", "agos-other")
    grabbed: list[list[str]] = []

    def grab(args: list[str], *, timeout: float) -> bytes:
        grabbed.append(args)
        return b"\xff\xd8 picture"

    monkeypatch.setattr(engine_module, "_run_bytes", grab)
    # Hermes has no screen running: nothing is grabbed.
    assert client.get(f"/workspaces/{ws}/screen.jpg").status_code == 204
    assert grabbed == []
    engine = client.app.state.core.engine  # type: ignore[attr-defined]
    record = engine.profile_home(ws) / "bot-desktop" / "sandbox.json"
    record.parent.mkdir(parents=True)
    # A record naming another workspace's sandbox is never followed.
    record.write_text(json.dumps({"backend": "DockerEnvironment", "container": "c9"}))
    assert client.get(f"/workspaces/{ws}/screen.jpg").status_code == 204
    assert grabbed == []
    record.write_text(json.dumps({"backend": "DockerEnvironment", "container": "c1"}))
    r = client.get(f"/workspaces/{ws}/screen.jpg")
    assert r.status_code == 200 and r.content.startswith(b"\xff\xd8")
    assert grabbed[0][1:3] == ["exec", "c1"]
    assert "hermes-bot-desktop/default/env" in grabbed[0][5]  # Hermes's _remote_dir
    assert client.get(f"/workspaces/{other}/screen.jpg").status_code == 204


def test_two_starts_of_one_root_spawn_one_gateway(tmp_path: Path) -> None:
    """Two threads starting a root's gateway at once (a member's sync and the keep
    loop): one gateway. A newer Hermes lets neither of two run ("already owns
    profile")."""
    import threading
    import time as _time

    from agos_core.engine.hermes import HermesEngine

    spawned: list[str] = []

    class Runner:
        def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
            _time.sleep(0.2)  # the gateway takes a moment to say it runs
            spawned.append(str(args))

    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
            gateway_supervisor="spawn",
        ),
        runner=Runner(),  # type: ignore[arg-type]
    )
    engine.is_running = lambda _ws: bool(spawned)  # type: ignore[method-assign,assignment]
    starts = [threading.Thread(target=engine.start, args=(key,)) for key in ("ws", "ws--a-x")]
    for t in starts:
        t.start()
    for t in starts:
        t.join(10)
    assert len(spawned) == 1


def test_a_stopped_workspace_whose_setup_is_applied_is_not_rewritten(tmp_path: Path) -> None:
    """C3: the apply stamp holds for a gateway that isn't running too. A stopped
    (archived, crashed) workspace whose setup is the one applied last writes no
    Hermes setting and drops no sandbox at its next sync; a changed setup still
    writes."""
    from agos_core.engine.hermes import HermesEngine

    home = tmp_path / ".hermes"
    home.mkdir()
    runner = FakeRunner(home)
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
    )
    engine.is_running = lambda workspace_id: False  # type: ignore[method-assign]
    ws_files = tmp_path / "data" / "workspaces" / "a" / "files"
    ws_files.mkdir(parents=True)

    def apply(read_only: bool = False) -> list[list[str]]:
        runner.calls.clear()
        engine.apply(
            "a",
            files_dir=ws_files,
            workspaces_dir=tmp_path / "data" / "workspaces",
            agos_data=tmp_path / "data",
            grants=[],
            files_read_only=read_only,
        )
        return [
            c
            for c in runner.calls
            if c[1:3] == ["config", "set"]
            or (
                Path(c[0]).name == "docker"
                and c[1] in ("ps", "rm")
                and not any("agos-egress" in a or "agos-mcp" in a for a in c)
            )
        ]

    assert any(c[1:3] == ["config", "set"] for c in apply())  # a new profile: written
    assert apply() == []  # same setup, gateway stopped: nothing rewritten
    assert any(c[1:3] == ["config", "set"] for c in apply(read_only=True))  # changed: written


def _stopped_engine(tmp_path: Path) -> tuple[Any, FakeRunner, Path]:
    from agos_core.engine.hermes import HermesEngine

    home = tmp_path / ".hermes"
    home.mkdir()
    runner = FakeRunner(home)
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
    )
    engine.is_running = lambda workspace_id: False  # type: ignore[method-assign]
    files = tmp_path / "data" / "workspaces" / "a" / "files"
    files.mkdir(parents=True)
    return engine, runner, files


def _sets_of_apply(engine: Any, runner: FakeRunner, files: Path, tmp_path: Path) -> list[list[str]]:
    runner.calls.clear()
    engine.apply(
        "a",
        files_dir=files,
        workspaces_dir=tmp_path / "data" / "workspaces",
        agos_data=tmp_path / "data",
        grants=[],
    )
    return [c for c in runner.calls if c[1:3] == ["config", "set"]]


def test_a_new_owner_zone_makes_no_workspace_rewrite_or_restart_at_its_next_sync(
    tmp_path: Path,
) -> None:
    """C4: the zone reaches each sandbox through set_zone's own terminal.docker_env
    write (Hermes reads it per new terminal session); the apply stamp leaves it
    out, so the next sync re-writes nothing and restarts nothing. A stamp written
    before (zone included) still counts, and takes the new form."""
    engine, runner, files = _stopped_engine(tmp_path)
    managed = engine.settings.managed_home
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "config.yaml").write_text("timezone: Europe/Paris\n")
    assert _sets_of_apply(engine, runner, files, tmp_path)  # a new profile: written
    (managed / "config.yaml").write_text("timezone: Africa/Casablanca\n")
    assert _sets_of_apply(engine, runner, files, tmp_path) == []
    # A stamp from before this change: the whole setup's digest, zone included.
    import hashlib

    from agos_core.engine.rules import profile_config

    stamp = engine.profile_home("a") / ".agos-applied"
    from agos_core.engine import network as net

    old = profile_config(
        image="img:1",
        mounts=_mounts_of(engine, files, tmp_path),
        network=net.sandbox_settings(engine.profile("a")) if engine.egress else None,
        model=None,
        container_key=engine.profile("a"),
        zone="Africa/Casablanca",
    )
    stamp.write_text(hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest())
    assert _sets_of_apply(engine, runner, files, tmp_path) == []
    assert stamp.read_text().startswith("3:")


def test_a_new_model_alone_is_written_without_stopping_the_gateway(tmp_path: Path) -> None:
    """A profile whose model alone moved since its last sync (a member following its
    workspace's new model, or its own pick) gets the model's keys and nothing else:
    Hermes's gateway reads model.* for each turn (gateway/run_turn.py
    _load_gateway_config), so the gateway is not stopped for it and the sandboxes
    stay. A changed sandbox setup (its folders, also when changed in Hermes: the
    owner's setup wins, C3) still stops the gateway, drops the sandboxes and starts
    it again; a stopped gateway is never started; an unchanged setup writes nothing."""
    from agos_core.engine.rules import model_pairs

    engine, runner, files = _stopped_engine(tmp_path)
    running = [True]
    verbs: list[str] = []
    engine.is_running = lambda workspace_id: running[0]
    engine.stop = lambda workspace_id, **_: verbs.append(f"stop {workspace_id}")
    engine.start = lambda workspace_id, **_: verbs.append(f"start {workspace_id}")
    first = ("anthropic", "claude-sonnet-5", "medium")
    second = ("openrouter", "x/two", "high")

    def apply(
        model: tuple[str, str, str], read_only: bool = False
    ) -> tuple[set[str], int, list[str]]:
        runner.calls.clear()
        verbs.clear()
        engine.apply(
            "a",
            files_dir=files,
            workspaces_dir=tmp_path / "data" / "workspaces",
            agos_data=tmp_path / "data",
            grants=[],
            model=model,
            files_read_only=read_only,
        )
        sets = {
            next(a for a in c[3:] if a != "--force")
            for c in runner.calls
            if c[1:3] == ["config", "set"]
        }
        drops = sum(
            1
            for c in runner.calls
            if Path(c[0]).name == "docker"
            and c[1] in ("ps", "rm")
            and not any("agos-egress" in a or "agos-mcp" in a for a in c)
        )
        return sets, drops, list(verbs)

    sets, drops, did = apply(first)  # a new profile: its whole setup
    assert "terminal.docker_volumes" in sets and drops and did == ["stop a", "start a"]
    assert apply(first) == (set(), 0, [])  # the same setup: nothing
    # A stamp of the form before (the whole setup, model included, without the zone)
    # still counts.
    import hashlib

    from agos_core.engine import network as net
    from agos_core.engine.rules import profile_config

    stamp = engine.profile_home("a") / ".agos-applied"
    whole = profile_config(
        image="img:1",
        mounts=_mounts_of(engine, files, tmp_path),
        network=net.sandbox_settings(engine.profile("a")) if engine.egress else None,
        model=first,
        container_key=engine.profile("a"),
    )
    stamp.write_text("2:" + hashlib.sha256(json.dumps(whole, sort_keys=True).encode()).hexdigest())
    assert apply(first) == (set(), 0, []) and stamp.read_text().startswith("3:")
    # The model alone: its keys, the gateway runs on, the sandboxes stay.
    assert apply(second) == (set(model_pairs(*second)), 0, [])
    assert apply(second) == (set(), 0, [])
    # Hermes's folder list changed in Hermes: the owner's comes back, and the running
    # gateway is restarted to take it.
    engine._hermes("a", "config", "set", "terminal.docker_volumes", "[]")
    sets, drops, did = apply(second)
    assert "terminal.docker_volumes" in sets and drops and did == ["stop a", "start a"]
    # Stopped: a new model is written alone; a new folder setup is written and its
    # sandboxes dropped; nothing is started.
    running[0] = False
    assert apply(first) == (set(model_pairs(*first)), 0, [])
    assert apply(first) == (set(), 0, [])
    sets, drops, did = apply(first, read_only=True)
    assert "terminal.docker_volumes" in sets and drops and did == []


def _mounts_of(engine: Any, files: Path, tmp_path: Path) -> Any:
    from agos_core.engine.rules import build_mounts

    return build_mounts(
        files,
        [],
        workspaces_dir=tmp_path / "data" / "workspaces",
        forbidden=engine.forbidden(tmp_path / "data"),
    )


def test_the_sandbox_zone_write_waits_for_the_homes_write_lock(tmp_path: Path) -> None:
    """C4: owner_time's `config set terminal.docker_env` takes the home's write lock
    (it ran without it: a concurrent writer of that home could lose a write)."""
    import threading
    import types

    from agos_core.actions import owner_time
    from agos_core.engine.hermes import home_write_lock

    engine, runner, files = _stopped_engine(tmp_path)
    _sets_of_apply(engine, runner, files, tmp_path)
    home = engine.profile_home("a")
    core: Any = types.SimpleNamespace(engine=engine)
    held, done = threading.Event(), threading.Event()
    release = threading.Event()

    def holder() -> None:
        with home_write_lock(home):
            held.set()
            release.wait(5)

    def writer() -> None:
        owner_time.write_home(core, home, "Asia/Tokyo")
        done.set()

    threading.Thread(target=holder).start()
    held.wait(5)
    threading.Thread(target=writer).start()
    assert not done.wait(0.3)  # waits behind the other writer
    release.set()
    assert done.wait(5)


def test_a_folder_click_writes_its_one_changed_key_in_one_hermes_process(
    env: tuple[TestClient, FakeRunner, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C2: folder add (then access change) of a workspace: the sandbox keys of the
    apply go through engine.config_writes, only terminal.docker_volumes changes."""
    from conftest import hermes_config_batch

    client, runner, tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    reports, notes = tmp / "Reports", tmp / "Notes"
    reports.mkdir()
    notes.mkdir()
    runner.calls.clear()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)}).status_code == 201
    before = [c for c in runner.calls if c[1:3] == ["config", "set"]]
    starts = hermes_config_batch(monkeypatch)
    runner.calls.clear()
    assert client.post(f"/workspaces/{ws}/folders", json={"path": str(notes)}).status_code == 201
    assert [c for c in runner.calls if c[1:3] == ["config", "set"]] == []
    applied = [s for s in starts if "terminal.docker_volumes" in s]
    assert len(applied) == 1 and applied[0][1:] == ["terminal.docker_volumes"]
    vols = json.loads(runner.config["agos-argan"]["terminal.docker_volumes"])
    assert f"{notes.resolve()}:/shared/notes:ro" in vols
    print(f"C2 folder add: {len(before)} Hermes CLI before -> {len(starts)} Hermes process after")
