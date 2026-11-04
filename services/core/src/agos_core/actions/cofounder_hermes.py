"""The Co-Founder's chat actions for Hermes's own settings and stores: the Hermes
settings page (change one setting, back to Hermes's default), Held-back writes
(approve, reject), the key pools (add, remove, order, strategy) and Health. Each one
runs through the same code as the owner's own page, and its card's Undo puts back
the Hermes value it found (actions/cofounder_actions.py calls do/undo).

Read-only ones (show_hermes_setting, list_held_writes, list_pool_keys, hermes_health,
secrets_check: this workspace only, never another one's findings) answer with
Hermes's own data and have nothing to undo. A key added or removed from
chat is kept only sealed (AGOS's master key, security/secrets.py), for its Undo.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core

SETTINGS = ("change_hermes_setting", "reset_hermes_setting")
HELD = ("approve_held_write", "reject_held_write")
POOLS = ("add_pool_key", "remove_pool_key", "move_pool_key", "set_pool_strategy")
REPORTS = (
    "show_hermes_setting",
    "list_held_writes",
    "list_pool_keys",
    "hermes_health",
    "secrets_check",
)
DOES = (*SETTINGS, *HELD, *POOLS)
_SEAL = "cofounder_action.pool_key"
# The seal's label before step 44: a key sealed by an action still pending at the
# rename (its copy lives only until the action settles) opens with it.
_OLD_SEAL = "manager_action.pool_key"


def seal(core: Core, key: str) -> str:
    from agos_core.security.secrets import encrypt_secret

    return encrypt_secret(core.master_key, key, _SEAL)


def _unseal(core: Core, sealed: str) -> str:
    from cryptography.exceptions import InvalidTag

    from agos_core.security.secrets import decrypt_secret

    try:
        return decrypt_secret(core.master_key, sealed, _SEAL)
    except InvalidTag:
        return decrypt_secret(core.master_key, sealed, _OLD_SEAL)


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "yes", "on", "1")


def _value(field_type: str, raw: Any) -> Any:
    """The Co-Founder's value (text in the tool call) as the page's own type."""
    if field_type == "boolean":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "on", "yes", "1"):
            return True
        if text in ("false", "off", "no", "0"):
            return False
        raise ActionError("Use true or false.")
    if field_type == "number":
        text = str(raw).strip()
        if text.lower() in ("", "null", "none"):
            return None
        try:
            number = float(text)
        except ValueError as error:
            raise ActionError("Use a number.") from error
        return int(number) if number.is_integer() and "." not in text else number
    if field_type in ("list", "object"):
        try:
            return json.loads(str(raw))
        except ValueError as error:
            raise ActionError("Write the value as JSON.") from error
    return "" if raw is None else str(raw)


def _row(core: Core, key: str) -> dict[str, Any]:
    from agos_core.actions import hermes_all_settings as hall

    found = next((r for r in hall.read(core)["settings"] if r["key"] == key), None)
    if found is None:
        raise ActionError(f"{key} isn't one of Hermes's settings.", status=404)
    return dict(found)


def _shown(row: dict[str, Any]) -> str:
    value = json.dumps(row["value"], ensure_ascii=False)
    if row["same"]:
        return value
    parts = [
        f"{w['name']}: {json.dumps(w['value'], ensure_ascii=False)}" for w in row["workspaces"]
    ]
    return f"{value} in most; " + "; ".join(parts)


# ---- doing ----------------------------------------------------------------------------


def do(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> dict[str, Any]:
    """Runs one of these actions; returns what its Undo needs (or its report)."""
    if action in SETTINGS:
        return _setting(core, workspace_id, action, p)
    if action in HELD:
        return _held(core, workspace_id, action == "approve_held_write", p)
    if action in POOLS:
        return _pool(core, action, p)
    return {"report": report(core, workspace_id, action, p)}


def _setting(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions import hermes_all_settings as hall

    key = str(p["key"]).strip()
    here = workspace_id if _flag(p.get("only_here")) else None
    reset = action == "reset_hermes_setting"
    if not reset and "value" not in p:
        raise ActionError("Give the new value.")
    value = None if reset else _value(_row(core, key)["type"], p.get("value"))
    before: dict[str, Any] = {}
    try:
        row = hall.write(core, key, value, workspace_id=here, reset=reset, before=before)
    except ActionError as error:
        # A key an AGOS card owns: name the Co-Founder's own action for that card (the
        # page's "Changed on Workspace → Default model" read as "not from chat").
        kind = CARD_KINDS.get(str((_row(core, key).get("rule") or {}).get("card") or ""))
        if error.status != 409 or not kind:
            raise
        raise ActionError(f"{error.message} From chat: agos_action {kind}.", 409) from error
    return {"before": before, "now": _shown(row)}


# The Co-Founder's action for each AGOS card that owns Hermes keys
# (hermes_all_settings.CARD_LABELS); the others are the owner's own.
CARD_KINDS: dict[str, str] = {
    "time-limits": "set_time_limits",
    "limits": "set_hermes_limits",
    "fallback": "set_fallback",
    "timezone": "set_timezone",
    "voice": "set_voice",
    "workspace-settings": "set_workspace_settings (values)",
    "models": "set_workspace_settings (model)",
    "helper-models": "set_helper_models",
    "bot": "set_bot_reactions",
    "pools": "add_pool_key / remove_pool_key / move_pool_key",
}


def _held(core: Core, workspace_id: str, approve: bool, p: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions import held_writes

    item = held_writes.find(core, workspace_id, str(p["id"]))
    done = held_writes.decide(
        core,
        workspace_id,
        item["profile"],
        item["subsystem"],
        item["id"],
        approve,
        keep=True,
    )
    return {
        "profile": item["profile"],
        "subsystem": item["subsystem"],
        "kept": done.get("undo"),
        "said": str(done.get("said") or "")[:2000],
    }


def _pool(core: Core, action: str, p: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions import key_pools

    provider = str(p["provider"]).strip().lower()
    if action == "add_pool_key":
        key = _unseal(core, str(p["key_sealed"])) if p.get("key_sealed") else ""
        if not key:
            raise ActionError("Give the key to add.")
        # A new numbered line of Hermes's managed .env (its name is the label).
        found = key_pools.add(core, provider, key)
        return {"provider": provider, "label": found["label"]}
    if action == "set_pool_strategy":
        was_set = key_pools.strategy_set(core, provider)
        key_pools.set_strategy(core, provider, str(p["strategy"]).strip())
        return {"provider": provider, "before": was_set}
    label = str(p["label"]).strip()
    if action == "remove_pool_key":
        kept: dict[str, Any] = {}
        key_pools.remove(core, provider, label, kept=kept)
        out: dict[str, Any] = {"provider": provider, "label": label}
        if kept.get("key"):
            out["sealed"] = seal(core, str(kept["key"]))
            out["at"] = int(kept.get("at") or 0)
        return out
    # move_pool_key: the two keys trade numbers; Undo trades them back.
    try:
        position = int(str(p["position"]).strip()) - 1  # 1 = first, as the owner says it
    except ValueError as error:
        raise ActionError("Say the position as a number (1 = first).") from error
    found = key_pools.move(core, provider, label, max(0, position))
    first, other = [*list(found.get("swapped") or []), label, label][:2]
    return {"provider": provider, "label": first, "other": other}


def undo(core: Core, workspace_id: str, action: str, result: dict[str, Any]) -> None:
    from agos_core.actions import held_writes, key_pools

    if action in SETTINGS:
        from agos_core.actions import hermes_all_settings as hall

        if result.get("before", {}).get("values"):
            hall.restore(core, result["before"])
        return
    if action in HELD:
        held_writes.undo(
            core, workspace_id, str(result["profile"]), str(result["subsystem"]), result["kept"]
        )
        return
    provider = str(result["provider"])
    if action == "add_pool_key":
        key_pools.remove(core, provider, str(result["label"]))
    elif action == "remove_pool_key":
        if not result.get("sealed"):
            raise ActionError("Hermes gave no key back to put in again.", status=409)
        # The same key at its old number (the later ones move down again).
        key_pools.add(
            core,
            provider,
            _unseal(core, str(result["sealed"])),
            at=int(result.get("at") or 0) or None,
        )
    elif action == "move_pool_key":
        key_pools.swap(core, provider, str(result["label"]), str(result["other"]))
    elif action == "set_pool_strategy":
        key_pools.set_strategy(core, provider, result.get("before"))


# ---- reading --------------------------------------------------------------------------


def report(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> str:
    """What the Co-Founder is told (and the card shows) for a read-only action."""
    if action == "show_hermes_setting":
        row = _row(core, str(p["key"]).strip())
        rule = row.get("rule") or {}
        lines = [
            f"{row['key']} ({row['type']}): {_shown(row)}",
            f"Hermes's default: {json.dumps(row['default'], ensure_ascii=False)}",
            f"Hermes says: {row['description']}",
        ]
        if rule:
            lines.append(f"AGOS: {rule.get('kind')} — {rule.get('reason')}")
        lines.append(
            "You can change it (change_hermes_setting)."
            if row["editable"]
            else "It can't be changed from a chat."
        )
        return "\n".join(lines)
    if action == "list_held_writes":
        from agos_core.actions import held_writes

        found = held_writes.read(core, workspace_id)
        gates = ", ".join(f"{k}: {'on' if v else 'off'}" for k, v in found["gates"].items())
        items = [
            f"- {i['id']} · {i['agent']} · {i['subsystem']} {i['action']} · {i['summary']}"
            for i in found["items"]
        ]
        return f"Hermes's write approval ({gates})\n" + ("\n".join(items) or "- nothing held")
    if action == "list_pool_keys":
        from agos_core.actions import key_pools

        found = key_pools.read(core)
        lines = []
        for prov in found["providers"]:
            lines.append(f"{prov['provider']} (strategy {prov['strategy']}):")
            for n, e in enumerate(prov["entries"], 1):  # Hermes's order
                lines.append(
                    f"  {n}. {e['label']} · {e['preview']} · {e['status'] or 'not used yet'}"
                    + ("" if e["removable"] else " · from Settings → Models")
                )
        strategies = ", ".join(found["strategies"])
        return ("\n".join(lines) or "No keys in Hermes's pools.") + f"\nStrategies: {strategies}"
    if action == "secrets_check":
        from agos_core.actions import secrets_check

        # Its own workspace only: workspaces are closed off from each other.
        return secrets_check.as_text(secrets_check.run(core, workspace_id))
    from agos_core.actions import hermes_health

    here = None if _flag(p.get("everywhere")) else workspace_id
    # The owner asked for the checks now: new reports, waited for.
    return hermes_health.as_text(hermes_health.read(core, here, fresh=True, wait=True))
