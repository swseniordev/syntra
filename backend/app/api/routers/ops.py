"""Endpoints contractuales de estado de colas y workers aprobados."""

from fastapi import APIRouter, Depends

from app.api.dependencies.operacion import operations_monitor
from app.core.identity import Principal, require
from app.modules.operacion.application.monitor import OperationsMonitor

router = APIRouter(prefix="/api/v1/ops", tags=["Operación"])


@router.get("/colas")
def colas(principal: Principal = Depends(require("procesos:ver")),
          monitor: OperationsMonitor = Depends(operations_monitor)):
    return monitor.queues()


@router.get("/workers")
def workers(principal: Principal = Depends(require("procesos:ver")),
            monitor: OperationsMonitor = Depends(operations_monitor)):
    return monitor.workers()
