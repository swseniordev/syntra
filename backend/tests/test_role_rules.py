"""El catálogo de Roles aplica mínimo privilegio en servidor."""

import pytest

from app.modules.roles.domain.rules import (
    APPROVED_PAIRS, InvalidRolePermissions, authorize_assignment, parse_permissions,
)


def test_catalog_contains_exactly_67_approved_pairs():
    assert len(APPROVED_PAIRS) == 67
    assert ("dashboard", "ver") in APPROVED_PAIRS
    assert ("mediciones", "exportar") not in APPROVED_PAIRS


def test_rejects_unknown_pair_and_non_list_action():
    with pytest.raises(InvalidRolePermissions):
        parse_permissions({"mediciones": ["exportar"]})
    with pytest.raises(InvalidRolePermissions):
        parse_permissions({"clientes": "ver"})


def test_rejects_escalation_even_if_pair_is_in_catalog():
    requested = parse_permissions({"clientes": ["ver", "crear"]})
    with pytest.raises(InvalidRolePermissions):
        authorize_assignment(requested, frozenset({"clientes:ver"}), requested_ver_todas=False, actor_ver_todas=False)
    with pytest.raises(InvalidRolePermissions):
        authorize_assignment(parse_permissions({"clientes": ["ver"]}), frozenset({"clientes:ver"}), requested_ver_todas=True, actor_ver_todas=False)


def test_accepts_only_actor_owned_pairs():
    requested = parse_permissions({"clientes": ["ver", "crear"]})
    authorize_assignment(requested, frozenset({"clientes:ver", "clientes:crear"}), requested_ver_todas=False, actor_ver_todas=False)
