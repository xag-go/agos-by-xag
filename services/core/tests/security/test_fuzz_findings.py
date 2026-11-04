"""Server errors the nightly API fuzzing (tests/security/test_api_fuzz.py) found, each
pinned by a test so it stays fixed."""

from typing import Any

from test_library import env as env
from test_library import ws

TOO_BIG = 2**64  # past SQLite's 64-bit INTEGER


def test_an_id_too_big_for_sqlite_is_an_invalid_value_not_a_server_error(env: Any) -> None:
    client, _core, _runner, _home = env
    a = ws(client, "Alpha")
    for answer in (
        client.post(f"/library/items/{TOO_BIG}/duplicate", json={"name": "Copy"}),
        client.get(f"/workspaces/{a}/skills/{TOO_BIG}/versions"),
    ):
        assert answer.status_code == 400, answer.text
        assert answer.json()["detail"] == "The request contains an invalid value."
