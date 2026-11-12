"""The operation registry is the single source of the tables its operations appear
in: the Co-Founder's kinds (engine/cofounder_parity KINDS), their read-vs-act rows
(engine/power.py EFFECT), the web parity rows (cofounder_parity DO, OWNER_ONLY),
the Co-Founder's do / undo (page_actions DOES / UNDOES) and the agent tools. A
declaration written once shows up in each of them, exactly as declared, and no
hand-written row says something else about it."""

from __future__ import annotations

from agos_core.actions.services.cofounder import page_actions
from agos_core.api import app  # noqa: F401 - every router, so every service's binding
from agos_core.engine import cofounder_parity, power
from agos_core.ops import catalog
from agos_core.ops.registry import REGISTRY
from agos_core.ops.specs import SPECS


def test_every_declared_operation_is_bound_by_its_service() -> None:
    assert REGISTRY.unbound() == []
    assert [s.name for s in REGISTRY.specs()] == [s.name for s in SPECS]


def test_owner_only_operations_are_owner_only_rows_and_nothing_else() -> None:
    for spec in SPECS:
        if spec.owner_only is None:
            continue
        assert spec.web_action is not None, spec.name
        assert cofounder_parity.OWNER_ONLY[spec.web_action] == spec.owner_only
        assert spec.web_action not in cofounder_parity.DO
        assert spec.web_action not in cofounder_parity.READS
        assert spec.name not in cofounder_parity.KINDS
        assert spec.name not in power.EFFECT
        assert spec.name not in page_actions.DOES


def test_cofounder_operations_appear_in_every_cofounder_table_as_declared() -> None:
    kinds = catalog.kinds(SPECS)
    for spec in SPECS:
        if spec.cofounder_domain is None:
            continue
        assert cofounder_parity.KINDS[spec.name] == kinds[spec.name]
        assert power.EFFECT[spec.name] == spec.effect
        assert spec.name in page_actions.DOES
        assert (spec.name in page_actions.UNDOES) == spec.has_undo
        if spec.web_action is not None:
            assert cofounder_parity.DO[spec.web_action] == f"do:{spec.name}"


def test_the_merges_are_the_catalogues_derivations() -> None:
    """Each table takes the registry's rows whole (so the next declaration lands in
    all of them): the derived rows are a subset of each table."""
    assert catalog.owner_only(SPECS).items() <= cofounder_parity.OWNER_ONLY.items()
    assert catalog.kinds(SPECS).items() <= cofounder_parity.KINDS.items()
    assert catalog.effects(SPECS).items() <= power.EFFECT.items()
    assert catalog.web_do(SPECS).items() <= cofounder_parity.DO.items()
    assert set(catalog.kinds(SPECS)) <= set(page_actions.DOES)


def test_the_registry_holds_real_cofounder_kinds_of_each_service() -> None:
    """Not only the owner's: the Automation, Team, Library, Vision, Settings, Connector
    and Portability services' kinds are declared rows, each with its page's do."""
    kinds = catalog.kinds(SPECS)
    domains = {k.domain for k in kinds.values()}
    assert {"automations", "team", "skills_admin", "workspace"} <= domains
    assert len(kinds) >= 50
    for name in kinds:
        assert cofounder_parity.KINDS[name] is not None
