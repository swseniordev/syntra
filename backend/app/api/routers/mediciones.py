"""HTTP de Mediciones y catálogos necesarios para su asistente."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
import json
from typing import Any, Literal
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies.mediciones import measurement_use_cases
from app.core.db import connection
from app.core.identity import Principal, require
from app.core.security import sign_format_template_download, verify_format_template_download
from app.modules.mediciones.application.service import MeasurementProblem, MeasurementUseCases
from app.modules.mediciones.infrastructure.format_template import build_xlsx_template, source_columns
from app.modules.mediciones.application.versioning import version_tag

router = APIRouter(prefix="/api/v1", tags=["Mediciones"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _AlCargar(_StrictModel):
    incorporar: bool = True
    relevancia: bool = False
    sentimiento: bool = True
    clusters: bool = False
    bots: bool = False


class _Fuente(_StrictModel):
    origen: Literal["archivo", "meltwater", "manual"]
    activo: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    al_cargar: _AlCargar = Field(default_factory=_AlCargar)


class _ProgramacionMeltwater(_StrictModel):
    activa: bool = False
    inicio: datetime | None = None
    fin: datetime | None = None
    frecuencia_min: int | None = Field(default=None, ge=15)


class MedicionPatch(_StrictModel):
    """Edición recuperable del alcance paso 2 ya persistido."""
    fuentes: list[_Fuente] | None = None
    programacion_meltwater: _ProgramacionMeltwater | None = None
    auto_publicar: bool | None = None

    @field_validator("fuentes")
    @classmethod
    def unique_sources(cls, values: list[_Fuente] | None) -> list[_Fuente] | None:
        if values is not None and len({source.origen for source in values}) != len(values):
            raise ValueError("No repita fuentes de la medición")
        return values


class _Prompt(_StrictModel):
    tipo: Literal["cluster", "temas", "relevancia", "sentimiento"]
    red: str | None = None
    origen: Literal["defecto", "cuenta", "propio"]
    prompt_id: int | None = Field(default=None, ge=1)
    version: int | None = Field(default=None, ge=1)
    contenido: str | None = None


class _Cruce(_StrictModel):
    nombre: str = Field(min_length=1)
    categoria: str | None = None
    color: str = "#1293F8"
    modo: Literal["texto_hashtags", "hashtags", "texto"] = "texto_hashtags"
    incluye_autor: bool = True
    descripcion: str | None = None
    items: list[str] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def valid_items(cls, values: list[str]) -> list[str]:
        import re
        if any(not re.fullmatch(r"[@#][\w.]+", value.strip()) for value in values):
            raise ValueError("Cada elemento debe comenzar con @ o # y contener un identificador válido")
        return values


class _RedScraper(_StrictModel):
    red: Literal["x", "tiktok", "youtube", "facebook", "instagram"]
    activo: bool = True
    registros: int = Field(gt=0)
    actor_id: int | None = Field(default=None, ge=1)


class _GoogleNews(_StrictModel):
    activo: bool = False
    registros: int = Field(default=50, ge=1, le=100)
    periodo: Literal["ultima_hora", "ultimo_dia", "ultima_semana", "rango"] = "ultimo_dia"
    pais_ids: list[int] = Field(default_factory=list)


class _PromptScraper(_StrictModel):
    origen: Literal["medicion", "defecto", "propio"] = "medicion"
    prompt_id: int | None = Field(default=None, ge=1)
    contenido: str | None = None


class _PromptsScraper(_StrictModel):
    relevancia: _PromptScraper = Field(default_factory=_PromptScraper)
    sentimiento: _PromptScraper = Field(default_factory=_PromptScraper)


class _Scraper(_StrictModel):
    nombre: str = Field(min_length=1)
    ejecucion_auto: bool = True
    inicio: datetime
    fin: datetime
    frecuencia_min: int | None = Field(default=None, ge=15)
    redes: list[_RedScraper] = Field(default_factory=list)
    actualizar_interacciones: bool = True
    transcribir: bool = True
    google_news: _GoogleNews = Field(default_factory=_GoogleNews)
    mismas_palabras: bool = True
    palabras: dict[str, list[str]] = Field(default_factory=dict)
    al_incorporar: dict[str, bool] = Field(default_factory=dict)
    prompts: _PromptsScraper = Field(default_factory=_PromptsScraper)


class MedicionIn(_StrictModel):
    cuenta_id: int = Field(ge=1)
    nombre: str = Field(min_length=1)
    coyuntura: bool = False
    estado_id: Literal[0, 1] = 1
    fuentes: list[_Fuente] = Field(default_factory=list)
    programacion_meltwater: _ProgramacionMeltwater = Field(default_factory=_ProgramacionMeltwater)
    prompts: list[_Prompt] = Field(default_factory=list)
    instrucciones: str | None = None
    clusters: dict[str, Any] = Field(default_factory=dict)
    bots: dict[str, Any] = Field(default_factory=dict)
    parametros_x: dict[str, Any] = Field(default_factory=dict)
    regex: dict[str, Any] = Field(default_factory=dict)
    cruces: list[_Cruce] = Field(default_factory=list)
    scrapers: list[_Scraper] = Field(default_factory=list)
    ventana_desde: datetime | None = None
    auto_publicar: bool = False
    medios: dict[str, Any] = Field(default_factory=dict)


def _global(principal: Principal) -> bool:
    return bool(principal.role["ver_todas"])


def _cursor(raw: str | None) -> tuple[str, int] | None:
    if not raw:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        created = datetime.fromisoformat(value["creado_en"])
        identifier = value["id"]
        if created.tzinfo is None or type(identifier) is not int or identifier < 1:
            raise ValueError
        return created.isoformat(), identifier
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise HTTPException(400, "Cursor de mediciones inválido") from None


def _global_error(exc: MeasurementProblem) -> None:
    raise HTTPException(exc.status, exc.detail) from exc


@router.get("/mediciones")
def listar_mediciones(
    response: Response,
    cursor: str | None = None,
    limite: int = Query(25, ge=1, le=200),
    q: str = Query("", max_length=200),
    estado: Literal["vigentes", "activos", "inactivos", "eliminados"] = "vigentes",
    cuenta_id: int | None = Query(None, ge=1),
    cliente_id: int | None = Query(None, ge=1),
    coyuntura: bool | None = None,
    fuente: Literal["archivo", "meltwater", "manual", "scraper", "googlenews"] | None = None,
    principal: Principal = Depends(require("mediciones:ver")),
    cases: MeasurementUseCases = Depends(measurement_use_cases),
):
    state_map = {"vigentes": -99, "activos": 1, "inactivos": 0, "eliminados": -1}
    filters = {"q": q.strip(), "estado_id": state_map[estado], "cuenta_id": cuenta_id,
               "cliente_id": cliente_id, "coyuntura": coyuntura, "fuente": fuente}
    rows = cases.list(principal.user["id"], _global(principal), limite + 1, _cursor(cursor), filters)
    next_cursor = None
    if len(rows) > limite:
        rows = rows[:limite]
        tail = rows[-1]
        encoded = json.dumps({"creado_en": tail["creado_en"].isoformat(), "id": tail["id"]}, separators=(",", ":")).encode()
        next_cursor = base64.urlsafe_b64encode(encoded).decode().rstrip("=")
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return {"items": rows, "siguiente": next_cursor}


@router.post("/mediciones", status_code=201)
def crear_medicion(
    body: MedicionIn, response: Response,
    principal: Principal = Depends(require("mediciones:crear")),
    cases: MeasurementUseCases = Depends(measurement_use_cases),
):
    if body.programacion_meltwater.activa and "mediciones:editar" not in principal.permissions:
        raise HTTPException(403, "Se requiere mediciones:editar para programar consultas Meltwater")
    try:
        row = cases.create(body.model_dump(exclude_unset=True), principal.user["id"], _global(principal))
    except MeasurementProblem as exc:
        _global_error(exc)
    response.headers["Location"] = f"/api/v1/mediciones/{row['id']}"
    return row


@router.get("/mediciones/{id}")
def ver_medicion(
    id: int, response: Response, principal: Principal = Depends(require("mediciones:ver")),
    cases: MeasurementUseCases = Depends(measurement_use_cases),
):
    try:
        row = cases.get(id, principal.user["id"], _global(principal))
        response.headers["ETag"] = version_tag(row)
        return row
    except MeasurementProblem as exc:
        _global_error(exc)


@router.get("/mediciones/{id}/resumen")
def resumen_medicion(
    id: int, principal: Principal = Depends(require("mediciones:ver")),
    cases: MeasurementUseCases = Depends(measurement_use_cases),
):
    try:
        return cases.summary(id, principal.user["id"], _global(principal))
    except MeasurementProblem as exc:
        _global_error(exc)


@router.patch("/mediciones/{id}")
def editar_medicion(
    id: int, body: MedicionPatch, response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require("mediciones:editar")),
    cases: MeasurementUseCases = Depends(measurement_use_cases),
):
    try:
        row = cases.edit(id, body.model_dump(exclude_unset=True), if_match,
                         principal.user["id"], _global(principal))
    except MeasurementProblem as exc:
        _global_error(exc)
    response.headers["ETag"] = version_tag(row)
    return row


@router.get("/cruces")
def listar_cruces(
    conn: psycopg.Connection = Depends(connection),
    _principal: Principal = Depends(require("cruces:ver")),
):
    rows = conn.execute(
        "SELECT c.id,c.nombre,c.categoria,c.color,c.modo,c.incluye_autor,c.descripcion,c.version,c.estado_id "
        "FROM cfg.cruce c WHERE c.estado_id=1 ORDER BY c.nombre,c.id"
    ).fetchall()
    for row in rows:
        row["items"] = [value["item"] for value in conn.execute(
            "SELECT item FROM cfg.cruce_item WHERE cruce_id=%s ORDER BY item", (row["id"],)).fetchall()]
    return rows


@router.get("/formatos")
def listar_formatos(
    conn: psycopg.Connection = Depends(connection),
    _principal: Principal = Depends(require("formatos:ver")),
):
    return conn.execute(
        "SELECT f.id,f.nombre,f.descripcion,f.extensiones,f.delimitador,f.codificacion,f.formato_fecha,f.zona_horaria,f.fecha_min,"
        "EXISTS (SELECT 1 FROM cfg.formato_columna fc WHERE fc.formato_id=f.id) AS mapeado,"
        "COALESCE((SELECT jsonb_agg(jsonb_build_object('campo_destino',fc.campo_destino,"
        "'columnas_origen',fc.columnas_origen,'transformacion',fc.transformacion,'requerido',fc.requerido) "
        "ORDER BY fc.campo_destino) FROM cfg.formato_columna fc WHERE fc.formato_id=f.id),'[]'::jsonb) AS columnas "
        "FROM cfg.formato_archivo f WHERE estado_id=1 ORDER BY nombre,id"
    ).fetchall()


@router.get("/formatos/{id}/plantilla")
def emitir_plantilla_formato(
    id: str,
    response: Response,
    token: str | None = Query(None, min_length=1),
    conn: psycopg.Connection = Depends(connection),
    principal: Principal = Depends(require("formatos:ver")),
):
    """Emite acceso breve y autenticado a una plantilla derivada del mapeo real."""
    row = conn.execute(
        "SELECT f.id,f.nombre,COALESCE(jsonb_agg(jsonb_build_object('campo_destino',fc.campo_destino,"
        "'columnas_origen',fc.columnas_origen,'transformacion',fc.transformacion,'requerido',fc.requerido) "
        "ORDER BY fc.campo_destino) FILTER (WHERE fc.formato_id IS NOT NULL),'[]'::jsonb) AS columnas "
        "FROM cfg.formato_archivo f LEFT JOIN cfg.formato_columna fc ON fc.formato_id=f.id "
        "WHERE f.id=%s AND f.estado_id=1 GROUP BY f.id,f.nombre",
        (id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Formato no encontrado")
    headers = source_columns(row["columnas"])
    if not headers:
        raise HTTPException(409, "El formato no tiene columnas configuradas para generar una planilla")
    digest = hashlib.sha256(json.dumps(row["columnas"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in row["id"])
    filename = f"plantilla_{safe_name}.xlsx"
    if token is None:
        capability = sign_format_template_download(principal.user["id"], principal.session_id, id, digest)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return {"url": f"/api/v1/formatos/{quote(id, safe='')}/plantilla?token={quote(capability, safe='')}",
                "nombre": filename, "expira_en_segundos": 900}
    if not verify_format_template_download(token, principal.user["id"], principal.session_id, id, digest):
        raise HTTPException(403, "Enlace de descarga inválido o vencido")
    try:
        content = build_xlsx_template(headers)
    except ValueError as exc:
        raise HTTPException(409, "El formato no tiene columnas configuradas para generar una planilla") from exc
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})
