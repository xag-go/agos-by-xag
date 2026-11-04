"""A migration that ran on a live database must never change: the live database
would never get the change (user_version is past it). Add a NEW entry instead, then
append its hash here."""

import hashlib

from agos_core.db.migrations import MIGRATIONS

SHIPPED = [
    "d78720e08f1cfc78",
    "99f87c876fcfeb81",
    "900e72a2acb1a068",
    "8378d9b7182afdef",
    "8f96fe2ddda6c545",
    "c690b2605a9b0210",
    "da682d585eddf3c6",
    "b971e777edbddcc0",
    "bfa72dc40898d693",
    "b13aa86bfd7747db",
    "bdd870ca2cacac7b",
    "21c9b5a6e6897f07",
    "696954a5d64624e7",
    "2f09388fbe280e15",
    "dc55803510dc5037",
    "e860b5f651a4b028",
    "b6be75667ad17a26",
    "137f5b5f78d93030",
    "30c185d09ff19007",
    "fc277c7a58d056c9",
    "79e85cd505b0b2eb",
    "8a8c2e0aa1c90136",
    "480a4d55ab38d0d2",
    "426d472fc73f855a",
    "77e45b27aad9c77b",
    "fa6d70bc48a24886",
    "8c4944affbc404c4",
    "27c553e40813502a",
    "8abe26aadd2d5d57",
    "c8a07dfd369f82d0",
    "ab8fc7ae547dfce8",
    "c0120fd2555f678d",
    "ef6323c7557eb04b",
    "c4ddaee8224887af",
    "95443f69dc4396d7",
    "d93a38d7b7e4fb37",
    "771e3af884778492",
    "69b51778f837ca77",
    "4bbe6ff5b7073732",
    "e1ad119ff840399c",
    "02a4175896d80ee4",
    "5247271e08571d3c",
    "f33e1b55cb5a93c4",
    "58c890ab1fb24ada",
    "26d84dc93d7d1995",
    "73fc7bd29df994f4",
    "784f8c474f471a90",
    "a1549a9928f75ec5",
]


def test_shipped_migrations_never_change() -> None:
    now = [hashlib.sha256(m.encode()).hexdigest()[:16] for m in MIGRATIONS]
    assert len(now) >= len(SHIPPED), "a migration was removed"
    for i, (old, new) in enumerate(zip(SHIPPED, now, strict=False)):
        assert old == new, f"migration {i} was edited after it shipped: add a new one instead"
