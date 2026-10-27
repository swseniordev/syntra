"""Casos de uso y reglas puras sin FastAPI ni PostgreSQL."""

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.modules.clientes.application.errors import ClientProblem, ProblemKind
from app.modules.clientes.application.ports import DuplicateName
from app.modules.clientes.application.service import ClientUseCases
from app.modules.clientes.application.versioning import version_tag
from app.modules.clientes.domain.rules import (
    ClientRuleError,
    ensure_deletable,
    ensure_editable_fields,
    ensure_restorable,
    ensure_vigente_state,
    normalize_fields,
)


def _row(name="Cliente", state=1, identifier=10):
    return {"id": identifier, "nombre": name, "estado_id": state, "actualizado_en": datetime(2026, 1, 1, tzinfo=timezone.utc)}


def _cases():
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.clients.name_exists.return_value = False
    return ClientUseCases(uow), uow


def _problem(kind, operation):
    with pytest.raises(ClientProblem) as caught:
        operation()
    assert caught.value.kind is kind


def test_domain_normalization_states_and_version():
    assert normalize_fields({
        "nombre": "  José\t  Pérez\n", "sector": "  acción\t pública\n",
        "rfc": "\n RFC  12\tB \n", "contacto": " correo@example.test \n",
    }) == {
        "nombre": "José Pérez", "sector": "ACCIÓN PÚBLICA", "rfc": "RFC  12\tB", "contacto": "correo@example.test",
    }
    assert normalize_fields({"rfc": " \n", "sector": "\t", "contacto": "  "}) == {"rfc": None, "sector": None, "contacto": None}
    with pytest.raises(ClientRuleError, match="Nombre obligatorio"):
        normalize_fields({"nombre": "\t\n"})
    with pytest.raises(ClientRuleError, match="correo válido"):
        normalize_fields({"contacto": "correo @example.test"})
    with pytest.raises(ClientRuleError, match="cuentas asociadas activas"):
        ensure_deletable([0, 1])
    with pytest.raises(ClientRuleError, match="no editable"):
        ensure_editable_fields({"estado_id": -1})
    ensure_deletable([-1, 0])
    with pytest.raises(ClientRuleError, match="cliente eliminado"):
        ensure_restorable(1)
    ensure_restorable(-1)
    with pytest.raises(ClientRuleError, match="Estado de cliente inválido"):
        ensure_vigente_state(-1)
    ensure_vigente_state(0)
    ensure_vigente_state(1)
    assert version_tag(_row()).startswith('"')


def test_create_normalizes_checks_duplicates_and_audits():
    cases, uow = _cases()
    created = _row("José Pérez")
    uow.clients.create.return_value = created
    result = cases.create({"nombre": " José\t Pérez\n", "sector": " acción\n social ", "rfc": " \nA  B\tC\n", "contacto": "   " , "estado_id": 1}, 7)
    assert result is created
    values = uow.clients.create.call_args.args[0]
    assert (values["nombre"], values["sector"], values["rfc"], values["contacto"]) == ("José Pérez", "ACCIÓN SOCIAL", "A  B\tC", None)
    uow.clients.name_exists.assert_called_once_with("José Pérez")
    uow.audit.record.assert_called_once_with(7, "crear", created)
    uow.commit.assert_called_once()

    duplicate, blocked = _cases()
    blocked.clients.name_exists.return_value = True
    _problem(ProblemKind.CONFLICT, lambda: duplicate.create({"nombre": "  José  Pérez " , "estado_id": 1}, 7))
    blocked.clients.create.assert_not_called()
    blocked.commit.assert_not_called()


def test_edit_checks_version_then_duplicate_and_audits():
    cases, uow = _cases()
    previous = _row()
    changed = _row("Cliente nuevo")
    uow.clients.get_for_update.return_value = previous
    uow.clients.update.return_value = changed
    _problem(ProblemKind.PRECONDITION_REQUIRED, lambda: cases.edit(10, {"nombre": "X"}, None, 7))
    uow.clients.get_for_update.assert_not_called()
    _problem(ProblemKind.PRECONDITION_FAILED, lambda: cases.edit(10, {"nombre": "X"}, '"anterior"', 7))
    uow.clients.update.assert_not_called()
    _problem(ProblemKind.VALIDATION, lambda: cases.edit(10, {"estado_id": -1}, version_tag(previous), 7))
    uow.clients.update.assert_not_called()

    row = cases.edit(10, {"nombre": " Cliente\t nuevo\n", "sector": "  salud\t pública  "}, version_tag(previous), 7)
    assert row is changed
    assert uow.clients.update.call_args.args == (10, {"nombre": "Cliente nuevo", "sector": "SALUD PÚBLICA"}, 7)
    uow.audit.record.assert_called_once_with(7, "editar", changed, previous)
    uow.commit.assert_called_once()

    uow.reset_mock()
    uow.__enter__.return_value = uow
    uow.clients.get_for_update.return_value = previous
    uow.clients.name_exists.return_value = True
    _problem(ProblemKind.CONFLICT, lambda: cases.edit(10, {"nombre": " Otro\t nombre"}, version_tag(previous), 7))
    uow.clients.update.assert_not_called()
    uow.commit.assert_not_called()


def test_delete_restore_and_state_respect_rules_and_events():
    cases, uow = _cases()
    active = _row()
    deleted = _row(state=-1)
    inactive = _row(state=0)
    uow.clients.get_for_update.return_value = active
    uow.accounts.locked_states_for_client.return_value = [0, 1]
    _problem(ProblemKind.CONFLICT, lambda: cases.delete(10, 7))
    uow.clients.soft_delete.assert_not_called()

    uow.accounts.locked_states_for_client.return_value = [0, -1]
    uow.clients.soft_delete.return_value = deleted
    cases.delete(10, 7)
    uow.clients.soft_delete.assert_called_once_with(10, 7)
    uow.audit.record.assert_called_with(7, "eliminar", deleted, active)
    uow.commit.assert_called_once()

    uow.reset_mock()
    uow.__enter__.return_value = uow
    uow.clients.get_for_update.return_value = deleted
    uow.clients.restore.return_value = inactive
    assert cases.restore(10, 7) is inactive
    uow.clients.get_for_update.assert_called_with(10, include_deleted=True)
    uow.audit.record.assert_called_once_with(7, "restaurar", inactive, deleted)

    uow.reset_mock()
    uow.__enter__.return_value = uow
    uow.clients.get_for_update.return_value = active
    _problem(ProblemKind.VALIDATION, lambda: cases.restore(10, 7))
    uow.clients.restore.assert_not_called()
    assert cases.change_state(10, 1, 7) is active
    uow.clients.change_state.assert_not_called()
    uow.clients.change_state.return_value = inactive
    assert cases.change_state(10, 0, 7) is inactive
    uow.audit.record.assert_called_with(7, "cambio_estado", inactive, active)


def test_repository_and_audit_failures_never_commit():
    cases, uow = _cases()
    uow.clients.create.side_effect = DuplicateName()
    _problem(ProblemKind.CONFLICT, lambda: cases.create({"nombre": "Cliente", "estado_id": 1}, 7))
    uow.commit.assert_not_called()

    cases, uow = _cases()
    uow.clients.get_for_update.return_value = _row(state=-1)
    uow.clients.restore.side_effect = DuplicateName()
    _problem(ProblemKind.VALIDATION, lambda: cases.restore(10, 7))
    uow.commit.assert_not_called()

    cases, uow = _cases()
    uow.clients.create.return_value = _row()
    uow.audit.record.side_effect = RuntimeError("auditoría indisponible")
    with pytest.raises(RuntimeError, match="auditoría indisponible"):
        cases.create({"nombre": "Cliente", "estado_id": 1}, 7)
    uow.commit.assert_not_called()
    assert uow.__exit__.call_args.args[0] is RuntimeError


def test_list_detail_sectors_and_invalid_cursor():
    cases, uow = _cases()
    uow.clients.list.return_value = (3, [_row(identifier=1), _row(identifier=2)])
    result = cases.list(" buscar ", "vigentes", None, " salud ", None, 1)
    assert result["total_aprox"] == 3 and len(result["items"]) == 1 and result["siguiente"]
    assert uow.clients.list.call_args.args == ("buscar", "vigentes", "salud", None, 2)
    cases.list(" buscar ", "vigentes", None, " salud ", result["siguiente"], 1)
    assert uow.clients.list.call_args.args[3] == 1
    _problem(ProblemKind.VALIDATION, lambda: cases.list("otro", "vigentes", None, "salud", result["siguiente"], 1))
    _problem(ProblemKind.VALIDATION, lambda: cases.list("", "vigentes", "nombre", "", None, 1))
    uow.clients.sectors.return_value = ["SALUD"]
    assert cases.sectors() == {"items": ["SALUD"]}
    uow.clients.get.return_value = None
    _problem(ProblemKind.NOT_FOUND, lambda: cases.get(999))


def test_inner_layers_do_not_import_http_or_postgres():
    module_root = Path(__file__).resolve().parents[1] / "app" / "modules" / "clientes"
    for layer in ("domain", "application"):
        for source in (module_root / layer).glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            assert not any(name and (name.startswith("fastapi") or name.startswith("psycopg") or ".infrastructure" in name) for name in imports), source

    router = ast.parse((module_root.parents[1] / "api" / "routers" / "clientes.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"execute", "commit", "rollback"} for node in ast.walk(router))
