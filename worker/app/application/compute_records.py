"""Cómputo por registro de relevancia, sentimiento y embedding (cola q.llm).

Procesa registro a registro: por cada paso pendiente llama al proveedor con un
presupuesto de tiempo. Si un paso falla, el registro se conserva y se marca con
problema (st=3) sin tumbar el resto del lote; el embedding solo se recalcula
cuando cambió el texto. Ni esta capa ni el dominio conocen PostgreSQL ni el SDK
del proveedor: dependen únicamente de los protocolos declarados aquí.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from app.domain.compute import (
    EMBEDDING,
    RELEVANCIA,
    SENTIMIENTO,
    embedding_vigente,
    pasos_pendientes,
    relevancia_valida,
    sentimiento_valido,
    texto_fingerprint,
)
from app.domain.tasks import ClaimedTask


class LLMProvider(Protocol):
    """Lo mínimo que el cómputo necesita del proveedor, sin acoplar su SDK."""

    def relevance(self, texto: str, prompt: str, timeout_s: float) -> tuple[int, int | None]: ...
    def sentiment(self, texto: str, prompt: str, timeout_s: float) -> int: ...
    def embedding(self, texto: str, timeout_s: float) -> list[float]: ...


class ComputePort(Protocol):
    def job(self, task: ClaimedTask, worker_id: str) -> dict[str, Any]: ...
    def save_record(self, task: ClaimedTask, worker_id: str, record: dict,
                    resultados: dict, problemas: list[tuple[str, str]]) -> None: ...
    def finish(self, task: ClaimedTask, worker_id: str) -> None: ...


class ComputeRecords:
    def __init__(self, persistence: ComputePort, provider: LLMProvider,
                 clock=time.monotonic):
        self.persistence = persistence
        self.provider = provider
        self._clock = clock

    def execute(self, task: ClaimedTask, worker_id: str, timeout_ms: int) -> None:
        job = self.persistence.job(task, worker_id)
        start = self._clock()
        budget = job["timeout_paso_s"]
        for record in job["records"]:
            if (self._clock() - start) * 1000 >= timeout_ms:
                raise TimeoutError("El cómputo del lote excedió el límite operativo")
            resultados, problemas = self._compute_one(record, job, budget)
            self.persistence.save_record(task, worker_id, record, resultados, problemas)
        self.persistence.finish(task, worker_id)

    def _compute_one(self, record: dict, job: dict, budget: float
                     ) -> tuple[dict, list[tuple[str, str]]]:
        texto = record.get("texto") or ""
        resultados: dict[str, Any] = {}
        problemas: list[tuple[str, str]] = []
        for paso in pasos_pendientes(record["estados"]):
            try:
                if paso == RELEVANCIA:
                    codigo, pct = self.provider.relevance(texto, job["prompt_relevancia"], budget)
                    if not relevancia_valida(codigo):
                        raise ValueError("relevancia fuera de dominio")
                    resultados[RELEVANCIA] = (codigo, pct)
                elif paso == SENTIMIENTO:
                    valor = self.provider.sentiment(texto, job["prompt_sentimiento"], budget)
                    if not sentimiento_valido(valor):
                        raise ValueError("sentimiento fuera de dominio")
                    resultados[SENTIMIENTO] = valor
                elif paso == EMBEDDING:
                    nuevo = texto_fingerprint(texto)
                    if embedding_vigente(record.get("texto_hash"), nuevo):
                        resultados[EMBEDDING] = ("reutilizado", nuevo)
                    else:
                        resultados[EMBEDDING] = (self.provider.embedding(texto, budget), nuevo)
            except Exception as exc:  # noqa: BLE001 — un paso no debe tumbar el lote
                # Solo el nombre de la excepción: el detalle puede contener el texto.
                problemas.append((paso, type(exc).__name__))
        return resultados, problemas
