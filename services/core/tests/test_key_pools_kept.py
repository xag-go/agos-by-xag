"""Step 38 B: Settings → Models → several keys per provider asks Hermes once per
home and then not again while what Hermes reads holds. A save anywhere in AGOS
changes a home's .env/config.yaml or the managed scope: the next page asks again
before it shows. Hermes itself rewrites a home's auth.json as its keys are used
(counts, statuses): the page then shows the last list at once and Hermes is asked
again behind it, for that home only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from test_key_pools import BASE, _fake_hermes, _labels
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import read_ahead
from agos_core.engine.read_cache import ReadCache


def _counting_logins(core: Any) -> list[str]:
    asked: list[str] = []

    def hermes_logins(home: Path, *, status: bool = False) -> dict[str, Any]:
        asked.append(str(home))
        return {"pool": [{"provider": "openrouter", "label": BASE, "last_status": "ok"}]}

    core.engine.hermes_logins = hermes_logins
    return asked


def _lists(jobs: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [home for home, job in jobs if job == {"do": "list"}]


def test_the_page_asks_hermes_once_per_home_then_not_while_files_hold(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    ws(client, "Beta")
    jobs = _fake_hermes(core)
    logins = _counting_logins(core)
    first = client.get("/models/key-pools")
    assert first.status_code == 200, first.text
    assert len(_lists(jobs)) == 3  # the shared home and each root
    assert logins  # each home's statuses
    seen = (len(jobs), len(logins))
    again = client.get("/models/key-pools").json()
    assert (len(jobs), len(logins)) == seen  # Hermes not asked again
    assert again == first.json()
    # Hermes rewrites one root's auth.json (a key used): the last list at once, and
    # Hermes asked again behind the page for that home only.
    root = core.engine.profile_home(a)
    (root / "auth.json").write_text(json.dumps({"credential_pool": {}, "used": 1}))
    client.get("/models/key-pools")
    assert ReadCache.settle(10)
    assert _lists(jobs)[3:] == [str(root)]
    assert logins[seen[1] :] == [str(root)]


def test_a_save_shows_on_the_next_page_at_once(env: Any) -> None:  # noqa: F811
    """A new key (the managed .env) is a change of what every home reads: the save's
    own answer and the next page both have it, never the old list."""
    client, core, _runner, _home = env
    ws(client, "Alpha")
    _fake_hermes(core)
    _counting_logins(core)
    client.get("/models/key-pools")
    r = client.post("/models/key-pools/openrouter", json={"key": "sk-or-v1-" + "a" * 40})
    assert r.status_code == 200, r.text
    assert f"{BASE}_2" in _labels(r.json())
    page = client.get("/models/key-pools").json()
    assert f"{BASE}_2" in _labels(page)


def test_the_read_ahead_fills_the_page_one_hermes_run_at_a_time(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    jobs = _fake_hermes(core)
    logins = _counting_logins(core)
    assert "agos_core.actions.key_pools:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.key_pools:read_ahead",))
    seen = (len(jobs), len(logins))
    assert seen[0] == 2 and seen[1] >= 2
    assert client.get("/models/key-pools").status_code == 200
    assert (len(jobs), len(logins)) == seen
