"""Reparte a q.llm los registros incorporados por un proceso de ingesta terminado.

Orquesta sin conocer PostgreSQL: lee el proceso origen, decide si hay algo que
calcular, crea un proceso hijo de cómputo (idempotente por ``idempotencia``) y
encola una tarea q.llm por ventana keyset. Re-ejecutar es inocuo: si el hijo ya
existe, no se vuelve a repartir.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.fanout import compute_proceso_tipo, fanout_needed, plan_chunks


class FanoutPort(Protocol):
    def source_proceso(self, proceso_id: int) -> dict[str, Any] | None: ...
    def pending_stats(self, cuenta_id: int, medicion_id: int, source_id: int) -> list[dict]: ...
    def create_child(self, source: dict, tipo: str) -> int | None: ...
    def enqueue_chunks(self, child_id: int, cuenta_id: int, medicion_id: int,
                       tipo: str, chunks: list[dict]) -> None: ...


class PlanCompute:
    def __init__(self, persistence: FanoutPort, chunk_size: int):
        self.persistence = persistence
        self.chunk_size = chunk_size

    def execute(self, proceso_id: int) -> int:
        source = self.persistence.source_proceso(proceso_id)
        if source is None or not fanout_needed(source["options"]):
            return 0
        tipo = compute_proceso_tipo(source["options"])
        child_id = self.persistence.create_child(source, tipo)
        if child_id is None:
            return 0  # ya se repartió antes: idempotente
        chunks: list[dict] = []
        for stat in self.persistence.pending_stats(
                source["cuenta_id"], source["medicion_id"], proceso_id):
            chunks.extend(plan_chunks(stat["periodo"], stat["min_id"], stat["max_id"],
                                      stat["count"], self.chunk_size))
        self.persistence.enqueue_chunks(child_id, source["cuenta_id"],
                                        source["medicion_id"], tipo, chunks)
        return len(chunks)
