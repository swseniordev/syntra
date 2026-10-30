"""HTTP de Scrapers: ejecutar ahora (encola en q.apify)."""

from typing import Callable, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from app.api.dependencies.scrapers import scraper_use_cases
from app.core.identity import Principal, require
from app.modules.scrapers.application.service import (ScraperProblem, ScraperProblemKind, ScraperUseCases)

router = APIRouter(prefix="/api/v1/scrapers", tags=["Scrapers"])
T = TypeVar("T")
HTTP_STATUS = {
    ScraperProblemKind.VALIDATION: 400,
    ScraperProblemKind.NOT_FOUND: 404,
    ScraperProblemKind.CONFLICT: 409,
}


def _run(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ScraperProblem as exc:
        raise HTTPException(HTTP_STATUS[exc.kind], exc.detail) from exc


class AlIncorporar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incorporar: bool | None = None
    relevancia: bool | None = None
    sentimiento: bool | None = None
    clusters: bool | None = None
    bots: bool | None = None


class EjecucionCarga(BaseModel):
    model_config = ConfigDict(extra="forbid")
    al_incorporar: AlIncorporar | None = None
    metricas: dict | None = None


@router.get("")
def listar(
    medicion_id: int = Query(alias="medicion_id"),
    principal: Principal = Depends(require("mediciones:ver")),
    cases: ScraperUseCases = Depends(scraper_use_cases),
):
    return _run(lambda: cases.list(medicion_id))


@router.post("/{id}/ejecutar", status_code=202)
def ejecutar(
    id: int, response: Response,
    body: EjecucionCarga = EjecucionCarga(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("mediciones:ejecutar")),
    cases: ScraperUseCases = Depends(scraper_use_cases),
):
    if idempotency_key is None:
        raise HTTPException(400, "Se requiere la cabecera Idempotency-Key")
    result = _run(lambda: cases.execute(id, body.model_dump(exclude_none=True),
                                        idempotency_key, principal.user["id"]))
    response.headers["Location"] = f"/api/v1/procesos/{result['proceso_id']}"
    return result
