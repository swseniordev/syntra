from fastapi import APIRouter

router = APIRouter(tags=["Salud"])


@router.get("/salud", summary="Comprobar disponibilidad de la API")
def health() -> dict[str, str]:
    """Indica únicamente que el proceso API responde; no comprueba dependencias."""
    return {"estado": "disponible"}
