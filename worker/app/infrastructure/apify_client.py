"""Adaptador del SDK de Apify al puerto ScrapeProvider.

El token NUNCA está en el repo: se lee de un archivo en disco cuya ruta llega
por ``SYNTRA_APIFY_TOKEN_FILE`` (ver :class:`app.config.WorkerSettings`). El SDK
``apify-client`` se importa de forma perezosa para que las demás colas y los
tests que no scrapean no necesiten tenerlo instalado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ApifyScrapeProvider:
    def __init__(self, token_file: Path):
        token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""
        if not token:
            raise ValueError("Falta el token de Apify: configure SYNTRA_APIFY_TOKEN_FILE")
        from apify_client import ApifyClient  # import perezoso: dependencia solo de q.apify

        self._client = ApifyClient(token)

    def start_run(self, actor: str, run_input: dict[str, Any], memory_mb: int) -> str:
        run = self._client.actor(actor).start(run_input=run_input, memory_mbytes=memory_mb)
        return run["id"]

    def run_status(self, run_id: str) -> dict[str, Any]:
        run = self._client.run(run_id).get() or {}
        return {"status": run.get("status"), "defaultDatasetId": run.get("defaultDatasetId")}

    def dataset_items(self, dataset_id: str) -> list[dict[str, Any]]:
        return list(self._client.dataset(dataset_id).iterate_items())
