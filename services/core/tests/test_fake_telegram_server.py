"""The fake Telegram server must take a burst of callers without resetting any of them.

`test_a_chat_gets_its_own_telegram_topic` failed once in a while with `Connection reset by peer`
on its `createForumTopic` call. The stdlib server listens with a backlog of 5; when other tests'
background threads and the test's own calls connect at the same moment, the kernel's accept queue
overflows and the client is reset. This pins the cause: a burst far bigger than 5 gets answered.
"""

import threading
from typing import Any

import httpx
from channels_rig import TOKEN
from channels_rig import fake_telegram as fake_telegram
from conftest import FAKE_TELEGRAM

BURST = 64
ROUNDS = 5


def test_a_burst_of_calls_is_answered_not_reset(fake_telegram: Any) -> None:
    url = f"{FAKE_TELEGRAM['url']}/bot{TOKEN}/getMe"
    failures: list[str] = []

    def call() -> None:
        try:
            httpx.post(url, json={}, timeout=10)
        except httpx.HTTPError as exc:  # a reset surfaces as httpx.ReadError
            failures.append(repr(exc))

    for _ in range(ROUNDS):
        threads = [threading.Thread(target=call) for _ in range(BURST)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert failures == []
