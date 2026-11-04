"""Webhooks are signed by default (security audit F8, 5.5).

A new webhook gets a random signing secret: the owner sees it once (the answer of
the save that made it), never again. A webhook without a secret (made before, or
the owner removed it) keeps working and says it is unsigned; the owner can give it
a secret any time ("Make a new secret"), shown once too.

A secret AGOS made while saving the automation itself (its own page's save, the
Co-Founder's create / update) is kept sealed until the owner shows it once in the
webhook's dialog (`secretWaiting`): never thrown away, never in an agent's answer
(read-vs-act review M9).
"""

from test_automation_hooks import deliver, hermes_route, hook_on
from test_automation_team import create, team  # noqa: F401 - fixture
from work_env import Env, env, fake_board  # noqa: F401 - fixtures

from agos_core.actions import hooks


def test_a_new_webhook_gets_a_secret_shown_once(team: Env) -> None:  # noqa: F811
    client, _fake, core, ws = team
    aid = create(client, ws, name="Leads", schedule="0 9 * * *")
    made = hook_on(client, ws, aid)
    secret = made["newSecret"]
    assert made["signed"] is True and isinstance(secret, str) and len(secret) >= 32
    route = hermes_route(core, ws, made["path"])
    assert route is not None and route["secret"] == secret
    # Never shown again: not in the automation, not in the next save.
    shown = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert shown["signed"] is True and shown.get("newSecret") is None
    again = hook_on(client, ws, aid, events=["lead.created"])
    assert again.get("newSecret") is None
    assert hermes_route(core, ws, made["path"])["secret"] == secret  # type: ignore[index]
    # Deliveries need it.
    assert deliver(client, made["path"], b'{"a": 1}', secret=None).status_code == 401
    assert deliver(client, made["path"], b'{"a": 1}', secret=secret).status_code == 200


def test_a_webhook_made_with_the_automation_is_signed_too(team: Env) -> None:  # noqa: F811
    client, _fake, core, ws = team
    aid = create(client, ws, name="Rows", schedule="0 9 * * *", hook=True)
    path = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]["path"]
    route = hermes_route(core, ws, path)
    assert route is not None and route["secret"] != hooks.INSECURE


def test_an_unsigned_webhook_keeps_working_and_can_be_signed(team: Env) -> None:  # noqa: F811
    client, _fake, core, ws = team
    aid = create(client, ws, name="Old", schedule="0 9 * * *")
    path = hook_on(client, ws, aid, secret="")["path"]  # his explicit choice: unsigned
    assert hermes_route(core, ws, path)["secret"] == hooks.INSECURE  # type: ignore[index]
    shown = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert shown["signed"] is False
    assert deliver(client, path, b'{"a": 1}', secret=None).status_code == 200
    # "Make a new secret": signed from now on, the secret shown once.
    upgraded = hook_on(client, ws, aid, newSecret=True)
    assert upgraded["signed"] is True and upgraded["path"] == path
    assert hermes_route(core, ws, path)["secret"] == upgraded["newSecret"]  # type: ignore[index]
    # His own secret pasted from the other app still wins over a made one.
    pasted = "whsec_" + "b" * 30
    hook_on(client, ws, aid, secret=pasted)
    assert hermes_route(core, ws, path)["secret"] == pasted  # type: ignore[index]


def test_a_secret_made_with_the_automation_waits_for_him_to_show_it_once(
    team: Env,  # noqa: F811
) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, name="Rows", schedule="0 9 * * *", hook=True)
    shown = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert shown["signed"] is True and shown["secretWaiting"] is True
    assert shown.get("newSecret") is None  # never in a plain read (an agent's either)
    r = client.post(f"/workspaces/{ws}/automations/{aid}/hook/secret")
    assert r.status_code == 200, r.text
    secret = r.json()["newSecret"]
    route = hermes_route(core, ws, shown["path"])
    assert route is not None and route["secret"] == secret
    assert deliver(client, shown["path"], b'{"a": 1}', secret=secret).status_code == 200
    # Once only.
    assert client.post(f"/workspaces/{ws}/automations/{aid}/hook/secret").status_code == 404
    after = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert after["secretWaiting"] is False


def test_a_secret_shown_in_the_dialog_is_not_waiting(team: Env) -> None:  # noqa: F811
    client, _fake, _core, ws = team
    aid = create(client, ws, name="Leads", schedule="0 9 * * *")
    made = hook_on(client, ws, aid)
    assert made["newSecret"] and made["secretWaiting"] is False
    assert client.post(f"/workspaces/{ws}/automations/{aid}/hook/secret").status_code == 404
