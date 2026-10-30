import logging
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routers.auth import router as auth_router
from app.api.routers.clientes import router as clientes_router
from app.api.routers.cuentas import router as cuentas_router
from app.api.routers.health import router as health_router
from app.api.routers.roles import router as roles_router
from app.api.routers.paises import router as paises_router
from app.api.routers.actores import router as actores_router
from app.api.routers.prompts import router as prompts_router
from app.api.routers.regex import router as regex_router
from app.api.routers.grupos import router as grupos_router
from app.api.routers.usuarios import router as usuarios_router
from app.api.routers.auditoria import router as auditoria_router
from app.api.routers.procesos import router as procesos_router
from app.api.routers.ops import router as ops_router
from app.api.routers.mediciones import router as mediciones_router
from app.api.routers.scrapers import router as scrapers_router
from app.api.routers.measurement_files import router as measurement_files_router
from app.api.routers.notificaciones import router as notifications_router
from app.core.config import settings

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API inicial de Syntra. Los dominios de negocio se incorporarán por entregas.",
)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(clientes_router)
app.include_router(cuentas_router)
app.include_router(roles_router)
app.include_router(paises_router)
app.include_router(actores_router)
app.include_router(prompts_router)
app.include_router(regex_router)
app.include_router(grupos_router)
app.include_router(usuarios_router)
app.include_router(auditoria_router)
app.include_router(procesos_router)
app.include_router(ops_router)
app.include_router(mediciones_router)
app.include_router(scrapers_router)
app.include_router(measurement_files_router)
app.include_router(notifications_router)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = (exc.detail if isinstance(exc.detail, dict)
              and exc.detail.get("codigo") == "archivo_duplicado" else str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        headers=exc.headers,
        content={"type": "about:blank", "title": HTTPStatus(exc.status_code).phrase,
                 "status": exc.status_code, "detail": detail, "instance": request.url.path},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": "Validación fallida", "status": 400,
                 "detail": "; ".join(str(error["msg"]) for error in exc.errors())},
    )
