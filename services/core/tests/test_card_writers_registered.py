"""Every Hermes config key an AGOS writer sets is known to Settings → Hermes settings:
either a card's key (read-only there, with a link to the card) or a forced key
(read-only, with its reason). A writer AGOS adds without registering its key would
leave the page offering a second, conflicting editor (the bot card's
`telegram.reactions` / `platforms.telegram.enabled` were missed once).

The writers are found in the source (`hermes config set <key>` argument lists and
`engine.set_setting(ws, <key>, …)`), not listed by hand. A writer whose key is
computed at run time must be in DYNAMIC with what it writes."""

import ast
import importlib
from pathlib import Path

from agos_core.actions import hermes_all_settings as hall

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

# (file, function) → why its key isn't a constant (and where that key is guarded).
DYNAMIC: dict[tuple[str, str], str] = {
    (
        "actions/services/settings/hermes_writes.py",
        "write",
    ): "the page's own writer (editable rows only)",
    (
        "actions/services/settings/hermes_writes.py",
        "give_new_profile",
    ): "copies the page's editable rows",
    (
        "actions/services/settings/hermes_writes.py",
        "restore",
    ): "a Co-Founder card's Undo of write (same keys)",
    ("actions/agent_profiles.py", "_make"): "the workspace's pairs (forced or capabilities keys)",
    (
        "actions/services/library/apply.py",
        "_write",
    ): "library.profile_settings (forced or capabilities keys)",
    ("actions/team.py", "_set"): "a member's model (rules.model_pairs: models card keys)",
    ("actions/engine.py", "set_model"): "rules.model_pairs (models card keys)",
    ("actions/hermes_settings.py", "write"): "hermes_settings.SETTINGS (workspace-settings card)",
    ("actions/access.py", "set_lists"): "access.LISTS (access card keys)",
    ("actions/access.py", "_follow_lists"): "access.LISTS (access card keys)",
    ("actions/autonomy.py", "sync_write_gates"): "autonomy.WRITE_GATES (autonomy card keys)",
    (
        "engine/hermes/commands.py",
        "set_setting",
    ): "the generic writer its callers pass a key to",
    (
        "engine/hermes/managed.py",
        "managed_write",
    ): "Hermes's managed scope (hermes_managed.by_card keys)",
    ("actions/hermes_managed.py", "_commands"): "the profiles' old copies of by_card keys",
    ("engine/hermes/__init__.py", "apply"): "rules.profile_config (forced keys, FORCED_WHY test)",
}


def _imports(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name] = a.name
    return out


def _constants(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value.value, str):
                    out[t.id] = node.value.value
    return out


def _resolve(expr: ast.expr, consts: dict[str, str], imports: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name) and expr.id in consts:
        return consts[expr.id]
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        module = imports.get(expr.value.id)
        if module:
            try:
                value = getattr(importlib.import_module(module), expr.attr)
            except (ImportError, AttributeError):
                return None
            return value if isinstance(value, str) else None
    return None


def _writers() -> list[tuple[str, str, int, str | None]]:
    """(file, function, line, key or None when computed) for every writer."""
    found: list[tuple[str, str, int, str | None]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC))
        if rel.startswith("hermes_plugin/"):
            continue  # runs inside Hermes: never writes Hermes config
        tree = ast.parse(path.read_text())
        consts, imports = _constants(tree), _imports(tree)
        funcs: list[tuple[int, int, str]] = [
            (n.lineno, n.end_lineno or n.lineno, n.name)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        def owner(line: int, funcs: list[tuple[int, int, str]] = funcs) -> str:
            inside = [f for f in funcs if f[0] <= line <= f[1]]
            return min(inside, key=lambda f: f[1] - f[0])[2] if inside else "<module>"

        for node in ast.walk(tree):
            items: list[ast.expr] | None = None
            if isinstance(node, ast.Call):
                items = list(node.args)
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "set_setting"
                    and not (isinstance(func.value, ast.Name) and func.value.id == "db")
                    and len(node.args) >= 2
                    and not (isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "db")
                ):
                    found.append(
                        (
                            rel,
                            owner(node.lineno),
                            node.lineno,
                            _resolve(node.args[1], consts, imports),
                        )
                    )
            elif isinstance(node, (ast.List, ast.Tuple)):
                items = list(node.elts)
            if not items:
                continue
            words = [i.value if isinstance(i, ast.Constant) else None for i in items]
            for at in range(len(words) - 1):
                if words[at] == "config" and words[at + 1] == "set":
                    rest = items[at + 2 :]
                    if rest and isinstance(rest[0], ast.Constant) and rest[0].value == "--force":
                        rest = rest[1:]
                    key = _resolve(rest[0], consts, imports) if rest else None
                    line = getattr(node, "lineno", 0)
                    found.append((rel, owner(line), line, key))
    return found


def test_every_key_an_agos_writer_sets_is_registered_on_the_page() -> None:
    known = set(hall.card_keys()) | hall.forced_keys() | set(hall.choice_keys())
    writers = _writers()
    assert len(writers) > 10  # the scan sees the writers at all
    missing = [
        f"{rel}:{line} ({func}) writes {key}"
        for rel, func, line, key in writers
        if key is not None and key not in known and not key.startswith("platform_toolsets")
    ]
    assert not missing, missing
    dynamic = {(rel, func) for rel, func, _line, key in writers if key is None}
    unexplained = sorted(dynamic - set(DYNAMIC))
    assert not unexplained, unexplained
    stale = sorted(set(DYNAMIC) - dynamic)
    assert not stale, stale


def test_the_bot_cards_keys_link_to_the_bot_card() -> None:
    from agos_core.actions import hermes_channel

    cards = hall.card_keys()
    assert cards[hermes_channel.REACTIONS] == "bot"
    assert cards[hermes_channel.BOT_SWITCH] == "bot"
    assert hall.CARD_LABELS["bot"]
