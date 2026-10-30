"""Caso de uso: ejecutar ahora un proceso de scraping (encola en q.apify).

Crea un ``prc.proceso`` de tipo ``carga_scraper`` y una ``prc.proceso_tarea`` por
cada red activa del scraper (``tipo='apify'``, ``clave='red:<codigo>'``) en la cola
``q.apify`` que consume el worker.

Google News (``tipo='googlenews'``) todavía **no tiene consumidor** en ``q.apify``:
no se encolan sus tareas para no dejar el proceso colgado (``prc.proceso`` cuenta
todas sus tareas para cerrar). Un scraper con solo Google News se rechaza. Cuando
exista el consumidor, reactivar aquí el encolado por país.

La ejecución es idempotente por ``Idempotency-Key``: reintentar la misma solicitud
devuelve el proceso ya creado en vez de duplicarlo.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.modules.scrapers.application.ports import ScraperUnitOfWork


class ScraperProblemKind(Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class ScraperProblem(Exception):
    def __init__(self, kind: ScraperProblemKind, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def _effective_options(scraper: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Las opciones de ESTA ejecución; por defecto, las del scraper."""
    incorporate = body.get("al_incorporar") or {}
    return {
        "al_incorporar": {
            "incorporar": bool(incorporate.get("incorporar", scraper["post_incorporar"])),
            "relevancia": bool(incorporate.get("relevancia", scraper["post_relevancia"])),
            "sentimiento": bool(incorporate.get("sentimiento", scraper["post_sentimiento"])),
            "clusters": bool(incorporate.get("clusters", scraper["post_clusters"])),
            "bots": bool(incorporate.get("bots", scraper["post_bots"])),
        },
        "metricas": body.get("metricas") or {},
    }


class ScraperUseCases:
    def __init__(self, uow: ScraperUnitOfWork):
        self.uow = uow

    def list(self, medicion_id: int) -> dict[str, Any]:
        return {"items": self.uow.runs.list_for_measurement(medicion_id)}

    def execute(self, scraper_id: int, body: dict[str, Any], idempotency: str, actor_id: int) -> dict[str, Any]:
        if not idempotency or not 16 <= len(idempotency) <= 128:
            raise ScraperProblem(ScraperProblemKind.VALIDATION, "Se requiere un Idempotency-Key de 16 a 128 caracteres")
        with self.uow:
            existing = self.uow.runs.existing_process(idempotency)
            if existing is not None:
                return {"proceso_id": existing["id"], "estado": existing["estado"], "reutilizado": True}
            scraper = self.uow.runs.load(scraper_id)
            if scraper is None or scraper["estado_id"] == -1:
                raise ScraperProblem(ScraperProblemKind.NOT_FOUND, "Proceso de scraping no encontrado")
            if scraper["estado_id"] != 1:
                raise ScraperProblem(ScraperProblemKind.CONFLICT, "El scraper está inactivo; actívalo antes de ejecutar")
            reds = self.uow.runs.active_reds(scraper_id)
            countries = self.uow.runs.countries(scraper_id) if scraper["gn_activo"] else []
            if not reds and not countries:
                raise ScraperProblem(ScraperProblemKind.VALIDATION,
                                     "El scraper no tiene redes activas ni Google News configurado")
            # Google News aún no tiene consumidor en q.apify: NO se encolan sus tareas,
            # porque quedarían 'en_cola' para siempre y dejarían el proceso colgado
            # (prc.proceso cuenta todas sus tareas para cerrar). Si solo hay Google News,
            # no hay nada ejecutable todavía: se rechaza en vez de crear un proceso vacío.
            if not reds:
                raise ScraperProblem(ScraperProblemKind.VALIDATION,
                                     "El scraping por Google News aún no está disponible; activa al menos una red")
            options = _effective_options(scraper, body)
            total = len(reds)
            process_id = self.uow.runs.create_process(scraper, options, total, idempotency, actor_id)
            for red in reds:
                self.uow.runs.add_task(process_id, f"red:{red['codigo']}", "apify", int(red["registros"]))
            self.uow.audit.record(actor_id=actor_id, module="scrapers", action="ejecutar",
                                  entity_type="Scraper", entity_id=str(scraper_id),
                                  entity_name=scraper["nombre"], after={"proceso_id": process_id, "tareas": total})
            self.uow.commit()
        return {"proceso_id": process_id, "estado": "en_cola", "reutilizado": False}
