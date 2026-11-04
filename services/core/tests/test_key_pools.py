"""Settings → Models → several keys per provider: Hermes's own credential pool. The
extra keys are numbered lines of Hermes's managed .env (one place, read by every
home); the strategy is one line of its managed config.yaml. Nothing is copied into
the homes (stubbed: the fake runner has no runtime; the scripts were probed
against Hermes, test_hermes_writes_live.py runs them)."""

import json
import re
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_managed, key_pools
from agos_core.engine import config_file
from agos_core.engine import hermes as engine_module

BASE = "OPENROUTER_API_KEY"


def _managed_env(core: Any) -> Path:
    return Path(core.engine.settings.managed_home) / ".env"


def _fake_hermes(core: Any) -> list[tuple[str, dict[str, Any]]]:
    """Hermes as far as the pool goes: the shared home's pool = its General key plus
    one env:<BASE>_n row per managed line (agent/credential_pool.py
    _env_key_var_candidates), plus any hand-added rows in a home's auth.json."""
    jobs: list[tuple[str, dict[str, Any]]] = []
    folder = Path(core.engine.settings.managed_home)

    def lines() -> dict[str, str]:
        return config_file.read_env(folder)

    def write(values: dict[str, str]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        _managed_env(core).write_text("".join(f"{k}={v}\n" for k, v in values.items()))

    def numbered() -> list[int]:
        have, n = [], 2
        while lines().get(f"{BASE}_{n}"):
            have.append(n)
            n += 1
        return have

    def managed_keys(job: dict[str, Any]) -> dict[str, Any]:
        jobs.append(("managed", job))
        held = lines()
        out: dict[str, Any] = {}
        if job["do"] == "add":
            same = next((k for k, v in held.items() if v == job["key"]), None)
            end = len(numbered()) + 2
            at = int(job.get("at") or end)
            at = at if 2 <= at <= end else end
            if not same:
                for n in range(end - 1, at - 1, -1):
                    held[f"{BASE}_{n + 1}"] = held[f"{BASE}_{n}"]
                held[f"{job['base']}_{at}"] = job["key"]
            out["name"] = same or f"{job['base']}_{at}"
        elif job["do"] == "remove":
            have = numbered()
            for n in range(job["n"], have[-1]):
                held[f"{BASE}_{n}"] = held[f"{BASE}_{n + 1}"]
            held.pop(f"{BASE}_{have[-1]}")
        elif job["do"] == "swap":
            a, b = (f"{BASE}_{n}" for n in job["n"])
            held[a], held[b] = held[b], held[a]
        write(held)
        return {**out, "names": sorted(held)}

    def manual(home: Path) -> list[dict[str, Any]]:
        try:
            pool = json.loads((home / "auth.json").read_text())["credential_pool"]
        except (OSError, KeyError, ValueError):
            return []
        return [e for e in pool.get("openrouter", []) if e.get("source") == "manual"]

    def credential_pool(home: Path, job: dict[str, Any]) -> dict[str, Any]:
        jobs.append((str(home), job))
        if job["do"] == "drop":
            data = json.loads((home / "auth.json").read_text())
            data["credential_pool"]["openrouter"] = [
                e
                for e in data["credential_pool"]["openrouter"]
                if "fp:" + e.get("access_token", "") not in job["fps"]
            ]
            (home / "auth.json").write_text(json.dumps(data))
        entries = [
            {
                "label": BASE,
                "auth_type": "api_key",
                "source": f"env:{BASE}",
                "priority": 0,
                "token_preview": "sk-o...0000",
                "request_count": 3,
                "last_status": "ok",
            },
            *(
                {
                    "label": f"{BASE}_{n}",
                    "auth_type": "api_key",
                    "source": f"env:{BASE}_{n}",
                    "priority": n,
                    "token_preview": lines()[f"{BASE}_{n}"][-4:],
                    "request_count": 0,
                    "last_status": None,
                }
                for n in numbered()
            ),
            # A row whose line went (Hermes keeps it, out of rotation): not shown.
            {"label": "OLD", "auth_type": "api_key", "source": "env:OLD", "token_preview": ""},
            *(
                {
                    "label": e["label"],
                    "auth_type": "api_key",
                    "source": "manual",
                    "priority": 9,
                    "token_preview": e["access_token"][-4:],
                }
                for e in manual(home)
            ),
        ]
        out: dict[str, Any] = {
            "pool": {"providers": [{"provider": "openrouter", "entries": entries}]},
            "strategies": ["fill_first", "least_used", "random", "round_robin"],
            "strategy": {"openrouter": "fill_first"},
            "bases": {"openrouter": BASE, "nous": None},
        }
        if job["do"] == "manual":
            out["manual"] = {
                "openrouter": [
                    {"label": e["label"], "key": e["access_token"], "fp": "fp:" + e["access_token"]}
                    for e in manual(home)
                ]
            }
        return out

    core.engine.credential_pool = credential_pool
    core.engine.managed_keys = managed_keys
    return jobs


def _ours(core: Any) -> dict[str, str]:
    held = config_file.read_env(core.engine.settings.managed_home)
    return {k: v for k, v in held.items() if k.startswith(BASE)}


def _labels(body: dict[str, Any]) -> list[str]:
    return [e["label"] for e in body["providers"][0]["entries"]]


def test_extra_keys_are_numbered_lines_of_the_managed_env_never_home_copies(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    jobs = _fake_hermes(core)
    body = client.get("/models/key-pools").json()
    assert _labels(body) == [BASE]  # the row without a line isn't shown
    assert body["providers"][0]["entries"][0]["removable"] is False
    one, two = "sk-or-v1-" + "a" * 40 + "1111", "sk-or-v1-" + "b" * 40 + "2222"
    r = client.post("/models/key-pools/openrouter", json={"key": one})
    assert r.status_code == 200, r.text
    assert one not in r.text
    r = client.post("/models/key-pools/openrouter", json={"key": two})
    assert _labels(r.json()) == [BASE, f"{BASE}_2", f"{BASE}_3"]
    added = r.json()["providers"][0]["entries"][1]
    assert added["removable"] and added["movable"] and added["source"] == "manual"
    assert _ours(core) == {
        f"{BASE}_2": one,
        f"{BASE}_3": two,
    }
    # Nothing went into any home: only the managed .env writer got the key.
    assert not [j for h, j in jobs if h != "managed" and j["do"] != "list"]
    assert [j["key"] for h, j in jobs if h == "managed"] == [one, two]
    for home in key_pools.homes(core):
        assert one not in (home / ".env").read_text() if (home / ".env").exists() else True
    # Up/down: the numbers swap; General's key never moves.
    r = client.put(f"/models/key-pools/openrouter/{BASE}_3/priority", json={"priority": 1})
    assert r.status_code == 200, r.text
    assert _ours(core)[f"{BASE}_2"] == two
    r = client.put(f"/models/key-pools/openrouter/{BASE}_2/priority", json={"priority": 0})
    assert r.status_code == 409
    # Removing one: the later ones move up a number (Hermes reads _2.. until a gap).
    r = client.delete(f"/models/key-pools/openrouter/{BASE}_2")
    assert r.status_code == 200, r.text
    assert _ours(core) == {f"{BASE}_2": one}
    assert client.delete(f"/models/key-pools/openrouter/{BASE}").status_code == 409
    # A provider Hermes reads no .env key for: said plainly.
    assert client.post("/models/key-pools/nous", json={"key": one}).status_code == 422


def test_the_strategy_is_one_line_of_the_managed_config(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    _fake_hermes(core)
    r = client.put("/models/key-pools/openrouter/strategy", json={"strategy": "round_robin"})
    assert r.status_code == 200, r.text
    assert hermes_managed.value(core, "credential_pool_strategies.openrouter") == "round_robin"
    for home in (core.engine.profile_home(a), core.engine.settings.hermes_home):
        assert "credential_pool_strategies" not in config_file.read(home)
    assert key_pools.STRATEGY_KEY in hermes_managed.by_card()


def test_old_per_home_strategies_move_into_the_managed_config_once(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    core.engine.managed_write([], [key_pools.STRATEGY_KEY])
    for key in (a, b):
        core.engine.unmanaged_hermes(
            key, "config", "set", f"{key_pools.STRATEGY_KEY}.openrouter", "least_used"
        )
    core.engine.unmanaged_in(
        core.engine.settings.hermes_home,
        "config",
        "set",
        f"{key_pools.STRATEGY_KEY}.openrouter",
        "least_used",
    )
    assert key_pools.STRATEGY_KEY in hermes_managed.move_once(core)
    assert hermes_managed.value(core, "credential_pool_strategies.openrouter") == "least_used"
    hermes_managed.settle(core)
    for home in (core.engine.profile_home(a), core.engine.profile_home(b)):
        assert key_pools.STRATEGY_KEY not in config_file.read(home)
    assert key_pools.STRATEGY_KEY not in config_file.read(core.engine.settings.hermes_home)


def _hand_added(home: Path, *tokens: str) -> None:
    data = {
        "credential_pool": {
            "openrouter": [
                {
                    "label": f"Key {i + 2}",
                    "source": "manual",
                    "auth_type": "api_key",
                    "access_token": t,
                }
                for i, t in enumerate(tokens)
            ]
        }
    }
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(json.dumps(data))


def test_hand_added_copies_move_into_the_managed_env_once(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    jobs = _fake_hermes(core)
    shared = core.engine.settings.hermes_home
    one = "sk-or-v1-" + "c" * 40 + "3333"
    for home in (shared, core.engine.profile_home(a), core.engine.profile_home(b)):
        _hand_added(home, one)
    # Beta's gateway was started before AGOS gave it the scope: its copy waits.
    core.engine.gateway_managed = lambda root: root != b
    assert key_pools.move_once(core) == 1
    assert _ours(core) == {f"{BASE}_2": one}
    assert key_pools._manual_in(core, core.engine.profile_home(a)) == set()
    assert key_pools._manual_in(core, core.engine.profile_home(b)) == {"openrouter"}
    assert key_pools._manual_in(core, shared) == {"openrouter"}  # the move's source, kept
    # Next start (Beta's gateway now reads the scope): the rest goes, no new line.
    core.engine.gateway_managed = lambda root: None
    assert key_pools.move_once(core) == 1
    assert _ours(core) == {f"{BASE}_2": one}
    assert key_pools._manual_in(core, core.engine.profile_home(b)) == set()
    assert key_pools._manual_in(core, shared) == set()
    before = len(jobs)
    assert key_pools.move_once(core) == 0  # done: no Hermes call at all
    assert len(jobs) == before


def test_the_pool_scripts_use_hermes_own_functions() -> None:
    script = engine_module._POOL
    for name in (
        "load_hermes_dotenv",
        "remove_credential_pool_entry",
        "list_credential_pool",
        "fingerprint_secret_value",
        "get_pool_strategy",
    ):
        assert name in script
    keys = engine_module._MANAGED_KEYS
    assert "save_env_value" in keys and "remove_env_value" in keys
    # No AGOS per-home writes left: no add/move of pool entries in any home.
    assert "add_credential_pool_entry" not in script and "move_entry" not in script
    src = Path(key_pools.__file__).read_text()
    assert not re.search(r'"config",\s*"set"', src)


def test_each_workspace_shows_its_own_roots_pool_as_hermes_has_it(env: Any) -> None:  # noqa: F811
    """#36: the page lists each workspace's pool as that root's Hermes has it (its
    own .env keys included, H: agent/credential_pool.py load_pool), read in that
    root, not only the shared home's."""
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Bravo")
    jobs = _fake_hermes(core)
    shared = core.engine.credential_pool
    root_a = core.engine.profile_home(a)

    def per_root(home: Path, job: dict[str, Any]) -> dict[str, Any]:
        found = shared(home, job)
        if home == root_a:  # Alpha's own key, in its root's .env only
            found["pool"]["providers"][0]["entries"].append(
                {
                    "label": "OPENROUTER_API_KEY_9",
                    "auth_type": "api_key",
                    "source": "env:OPENROUTER_API_KEY_9",
                    "priority": 9,
                    "token_preview": "sk-o...9999",
                }
            )
        if home == core.engine.profile_home(b):
            raise engine_module.EngineError("Hermes's runtime did not answer")
        return dict(found)

    core.engine.credential_pool = per_root
    body = client.get("/models/key-pools").json()
    by_ws = {w["workspaceId"]: w for w in body["workspaces"]}
    assert set(by_ws) == {a, b}
    assert by_ws[a]["name"] == "Alpha"
    labels = [e["label"] for e in by_ws[a]["providers"][0]["entries"]]
    assert labels == [BASE, "OPENROUTER_API_KEY_9"]
    assert by_ws[a]["providers"][0]["entries"][1]["preview"] == "sk-o...9999"
    assert by_ws[a]["problem"] == ""
    assert by_ws[b]["providers"] == [] and "did not answer" in by_ws[b]["problem"]
    read_in = {h for h, j in jobs if j["do"] == "list"}
    assert {str(root_a), str(core.engine.profile_home(b))} <= read_in
