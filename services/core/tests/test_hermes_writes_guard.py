"""Guards: Hermes's own files are written by Hermes, or by AGOS only in the one
module allowed to, the way Hermes does it. Each guard fails when the old way
comes back. A write is seen when a module writes, moves over, removes, opens for
writing or opens as a writable SQLite database a path naming one of the files
(directly, through a name bound to it, a constant, a function returning it, or a
helper that writes the path it is given). Allowed modules are listed in ALLOWED
with the reason; see docs/hermes-ownership.md.

- `.env`: only engine/envfile.py (under Hermes's .env lock, the flock its
  save_env_value takes).
- `profile.yaml`: only engine/profile_meta.py, for `ui_meta.agos` (Hermes has no
  setter for it); `display_name` is Hermes's write_profile_meta.
- `cron/jobs.json`: never (Hermes's cron.jobs writes it, through engine/cron.py).
- `config.yaml`, `state.db`, `kanban.db`, `SOUL.md`, `MEMORY.md`, `USER.md`,
  `webhook_subscriptions.json`: see ALLOWED.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
REPO = Path(__file__).resolve().parents[3]

ALLOWED = {
    ".env": {"engine/envfile.py"},
    "profile.yaml": {"engine/profile_meta.py"},
    "jobs.json": set(),
    # Hermes's `gateway stop|start` writes it; AGOS only when the root's gateway is
    # down (actions/team.py park, through profile_meta.set_parked).
    "gateway.parked": {"engine/profile_meta.py"},
    # `hermes config set` (engine.set_setting / _hermes) or Hermes's own save_config in
    # its runtime; AGOS edits a config.yaml only on the COPY a root move makes
    # (migrate_root._drop_standalone, a one-time move; the old profile is untouched).
    # engine/env_probe.py copies a profile's and the managed scope's config.yaml into
    # a THROWAWAY home and scope (the YAML-only side of the .env probe); the profile
    # and the scope themselves are untouched.
    "config.yaml": {"migrate_root.py", "engine/env_probe.py"},
    # Hermes's sessions: written by Hermes alone (AGOS reads it with mode=ro).
    "state.db": set(),
    # Hermes's board: `hermes kanban …`; AGOS only copies it once into a root and
    # points the copy's paths at the root (hermes_gateway/kanban_move.py, one-time move).
    "kanban.db": {"hermes_gateway/kanban_move.py"},
    # The same atomic write as Hermes's dashboard PUT /api/profiles/{name}/soul
    # (hermes_cli/web_routers/profiles.py:1018): Hermes has no CLI for it.
    "SOUL.md": {"engine/identity.py"},
    # Under Hermes's own memory-file lock (`hermes memory` is provider setup only):
    # identity.write_memory, and the owner's marked rules in USER.md (owner_rules).
    "MEMORY.md": {"engine/identity.py"},
    "USER.md": {"engine/identity.py", "actions/owner_rules.py"},
    # Hermes's webhook routes: its own _mutate_subscriptions, run in its runtime.
    "webhook_subscriptions.json": set(),
    # Hermes's names laid over its channel directory (gateway/channel_directory.py
    # _apply_channel_aliases reads it; Hermes has no writer, no CLI): AGOS's Telegram
    # entries, written atomically keeping every other entry (engine/hermes_directory).
    "channel_aliases.json": {"engine/hermes_directory.py"},
}
# Calls that change a file: a write, a move over it, its removal.
_WRITE_METHODS = {
    "write_text",
    "write_bytes",
    "replace",
    "rename",
    "unlink",
    "touch",
    "symlink_to",
    "hardlink_to",
}
_WRITE_FUNCS = {"replace", "rename", "remove", "unlink", "copy", "copyfile", "copy2", "move"}


def _modules() -> dict[str, ast.Module]:
    found = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(("db/migrations", "hermes_plugin/")):
            continue  # SQL text; the plugin runs inside Hermes (its own process)
        found[rel] = ast.parse(path.read_text(), filename=rel)
    return found


def _hermes_name(value: ast.expr) -> str | None:
    """A Hermes file named by a constant: a string, or a dict/tuple/list of them."""
    if isinstance(value, ast.Constant) and value.value in ALLOWED:
        return str(value.value)
    if isinstance(value, (ast.Dict, ast.Tuple, ast.List, ast.Set)):
        items = value.values if isinstance(value, ast.Dict) else value.elts
        return next((h for v in items if v is not None and (h := _hermes_name(v))), None)
    return None


def _constants(modules: dict[str, ast.Module]) -> dict[str, str]:
    """Module-level names bound to one of the files' names (PROFILE_YAML = ...), or to
    a dict/tuple of them (FILES = {"memory": "MEMORY.md", ...})."""
    out = {}
    for tree in modules.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and (hit := _hermes_name(node.value)):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = hit
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and isinstance(node.target, ast.Name)
                and (hit := _hermes_name(node.value))
            ):
                out[node.target.id] = hit
    return out


def _mentions(node: ast.AST, tainted: dict[str, str], consts: dict[str, str]) -> str | None:
    """Which Hermes file the expression points at, if any (`returns`: functions of
    the module whose result is such a path, e.g. `_path(home, "memory")`)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value in ALLOWED:
            return str(sub.value)
        if isinstance(sub, ast.Name) and (sub.id in tainted or sub.id in consts):
            return tainted.get(sub.id) or consts[sub.id]
        if isinstance(sub, ast.Attribute) and sub.attr in consts:
            return consts[sub.attr]
        if isinstance(sub, ast.Call) and (
            name := getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
        ) in _RETURNS.get("", {}):
            return _RETURNS[""][str(name)]
    return None


# Per module being checked: its functions that return a path to a Hermes file.
_RETURNS: dict[str, dict[str, str]] = {}


def _opens_for_write(call: ast.Call) -> bool:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name not in ("open", "fdopen"):
        return False
    texts = [*call.args, *(k.value for k in call.keywords)]
    for value in texts:
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and set(value.value) & set("wax+")
        ):
            return True
        for sub in ast.walk(value):
            if isinstance(sub, ast.Attribute) and sub.attr in ("O_WRONLY", "O_RDWR", "O_CREAT"):
                return True
    return False


def _scopes(tree: ast.Module) -> list[list[ast.AST]]:
    """Each function's body, and the module's own statements: a name points at a
    file only inside the scope that bound it."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    scopes: list[list[ast.AST]] = [[n] for n in ast.walk(tree) if isinstance(n, kinds)]
    scopes.append([n for n in tree.body if not isinstance(n, kinds)])
    return scopes


def _returning(tree: ast.Module, consts: dict[str, str]) -> dict[str, str]:
    """Functions of the module whose return value points at a Hermes file."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    hit = _mentions(sub.value, {}, consts)
                    if hit:
                        out[node.name] = hit
    return out


def writer_helpers(modules: dict[str, ast.Module]) -> dict[str, tuple[set[int], set[str]]]:
    """Functions (by name, in any module) that write the path given as one of their
    parameters: {name: ({parameter positions}, {modules defining it})}
    (e.g. `_atomic_write(path, text)`, `envfile.rewrite(env_file, …)`)."""
    out: dict[str, tuple[set[int], set[str]]] = {}
    for rel, tree in modules.items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = [a.arg for a in node.args.args]
            for index, param in enumerate(params):
                marked = {param: "<param>"}
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign) and _mentions(sub.value, marked, {}):
                        for t in sub.targets:
                            if isinstance(t, ast.Name):
                                marked[t.id] = "<param>"
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and _write_hit(sub, marked, {}, {}):
                        positions, where = out.setdefault(node.name, (set(), set()))
                        positions.add(index)
                        where.add(rel)
    return out


Helpers = dict[str, tuple[set[int], set[str]]]


def writes_to_hermes_files(
    tree: ast.Module, consts: dict[str, str], helpers: Helpers | None = None
) -> list[tuple[str, int]]:
    """(file, line) of each write in the module to one of Hermes's files."""
    _RETURNS[""] = _returning(tree, consts)
    found: set[tuple[str, int]] = set()
    for scope in _scopes(tree):
        nodes = [n for root in scope for n in ast.walk(root)]
        tainted: dict[str, str] = {}
        for node in nodes:  # names bound to such a path in this scope
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                hit = _mentions(node.value, tainted, consts)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if hit and isinstance(target, ast.Name):
                        tainted[target.id] = hit
                    if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                        for t, v in zip(target.elts, node.value.elts, strict=False):
                            one = _mentions(v, tainted, consts)
                            if one and isinstance(t, ast.Name):
                                tainted[t.id] = one
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    hit = _mentions(item.context_expr, tainted, consts)
                    if hit and isinstance(item.optional_vars, ast.Name):
                        tainted[item.optional_vars.id] = hit
        for node in nodes:
            if isinstance(node, ast.Call):
                hit = _write_hit(node, tainted, consts, helpers or {})
                if hit:
                    found.add((hit, node.lineno))
    return sorted(found, key=lambda f: f[1])


def _write_hit(
    node: ast.Call, tainted: dict[str, str], consts: dict[str, str], helpers: Helpers
) -> str | None:
    func = node.func

    def first(args: list[ast.expr]) -> str | None:
        return next((h for a in args if (h := _mentions(a, tainted, consts))), None)

    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if isinstance(func, ast.Attribute) and func.attr in _WRITE_METHODS:
        hit = _mentions(func.value, tainted, consts)
        if hit is None and func.attr in ("replace", "rename"):
            hit = first(node.args)  # a temp file moved over it
        return hit
    if isinstance(func, ast.Attribute) and func.attr in _WRITE_FUNCS:
        return first(node.args)
    if _opens_for_write(node):
        target = [func.value] if isinstance(func, ast.Attribute) else []
        return first([*node.args[:1], *target])
    if name == "connect" and "mode=ro" not in ast.unparse(node):
        return first(node.args[:1])  # sqlite3.connect: a writable database
    if name in helpers:
        positions, where = helpers[name]
        hit = first([a for i, a in enumerate(node.args) if i in positions])
        # A helper of the module allowed to write that file is that module's way.
        return None if hit is None or where & ALLOWED.get(hit, set()) else hit
    return None


def test_only_the_allowed_modules_write_hermess_files() -> None:
    modules = _modules()
    consts = _constants(modules)
    helpers = writer_helpers(modules)
    wrong = []
    for rel, tree in sorted(modules.items()):
        for file, line in writes_to_hermes_files(tree, consts, helpers):
            if rel not in ALLOWED[file]:
                wrong.append(f"{rel}:{line} writes {file}")
    assert not wrong, "\n".join(wrong)


def test_the_guard_finds_a_direct_write() -> None:
    """The guard itself: each way a module could write one of those files is seen."""
    bad = """
PROFILE = "profile.yaml"
def a(home):
    env_file = home / ".env"
    env_file.write_text("X=1")
def b(home, tmp):
    tmp.replace(home / PROFILE)
def c(home):
    with open(home / "cron" / "jobs.json", "w") as f:
        f.write("{}")
def d(home):
    os.replace("x", home / ".env")
def ok(home):
    return (home / ".env").read_text()
FILES: dict = {"memory": "MEMORY.md"}
def _atomic(path, text):
    path.write_text(text)
def _memory(home):
    return home / "memories" / FILES["memory"]
def e(home):
    _atomic(home / "SOUL.md", "x")
def f(home):
    _atomic(_memory(home), "x")
def g(home):
    sqlite3.connect(home / "state.db").execute("DELETE FROM sessions")
def h(home):
    src, dst = home / "kanban.db", home / "b"
    shutil.copy2(src, dst)
def ok2(home):
    sqlite3.connect(f"file:{home / 'state.db'}?mode=ro", uri=True)
    yaml = home / "config.yaml"
    return yaml.read_text()
def i(home):
    (home / "webhook_subscriptions.json").write_text("{}")
"""
    tree = ast.parse(bad)
    modules = {"bad.py": tree}
    consts = {**_constants(modules)}
    found = sorted(f for f, _ in writes_to_hermes_files(tree, consts, writer_helpers(modules)))
    assert found == [
        ".env",
        ".env",
        "MEMORY.md",
        "SOUL.md",
        "jobs.json",
        "kanban.db",
        "profile.yaml",
        "state.db",
        "webhook_subscriptions.json",
    ]


def test_the_env_writers_all_go_through_envfile() -> None:
    """Every AGOS .env write is envfile.rewrite (Hermes's lock), and envfile takes
    Hermes's lock file, `<.env>.lock` (hermes_cli/config.py `_env_write_lock`)."""
    text = (SRC / "engine" / "envfile.py").read_text()
    assert 'env_file.name + ".lock"' in text and "fcntl.flock" in text
    assert "threading.Lock" not in text  # an in-process lock alone loses Hermes's lines


def _src_text() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): p.read_text()
        for p in SRC.rglob("*.py")
        if not p.relative_to(SRC).as_posix().startswith("db/migrations")
    }


def test_no_second_master_of_a_one_agent_jobs_prompt() -> None:
    """Hermes's job prompt is the one copy: no digest of what AGOS built the job
    from, no rewrite of the job when an AGOS file changes."""
    used = [rel for rel, text in _src_text().items() if "job_digest" in text]
    assert used == []


def test_no_cron_validator_of_agos_own() -> None:
    """Schedules are checked by Hermes's parse_schedule (engine/cron.py)."""
    assert not (SRC / "domain" / "cron.py").exists()
    for rel, text in _src_text().items():
        assert "cron_error" not in text and "croniter" not in text, rel
    assert "parse_schedule" in (SRC / "engine" / "cron.py").read_text()
    for folder in (REPO / "apps" / "web" / "src", REPO / "packages" / "core" / "src"):
        for path in folder.rglob("*.ts*"):
            text = path.read_text()
            assert "cronError" not in text and "fieldRanges" not in text, path


def test_pins_and_display_names_are_hermess_own() -> None:
    """Sessions are pinned with `hermes sessions pin`; a profile's display name is
    written by Hermes's write_profile_meta."""
    for rel, text in _src_text().items():
        assert "set_session_pinned" not in text, rel
    meta = (SRC / "engine" / "profile_meta.py").read_text()
    assert '["display_name"] =' not in meta and "display_name=" not in meta
    engine = SRC / "engine" / "hermes"
    assert '"sessions", "pin"' in (engine / "sessions.py").read_text()
    assert "write_profile_meta(" in (engine / "profiles.py").read_text()


def test_the_log_reads_webhooks_from_hermess_routes() -> None:
    log = (SRC / "actions" / "services" / "system" / "workspace_log.py").read_text()
    assert "hook_token" not in log and "hooks.routes(" in log
