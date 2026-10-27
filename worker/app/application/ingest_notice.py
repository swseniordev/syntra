"""Contenido público de la notificación de una carga terminada."""


def finished_upload_notice(measurement_id: int, process_id: int,
                           state: str, rejected: int) -> tuple[str, str, str, str]:
    if state == "error":
        title = "Carga con error"
        body = f"La carga de la medición #{measurement_id} terminó con error. Revisa el proceso #{process_id}."
        kind = "err"
    elif rejected:
        title = "Carga con advertencias"
        body = (f"La carga de la medición #{measurement_id} terminó con "
                f"{rejected} registro{'s' if rejected != 1 else ''} rechazado{'s' if rejected != 1 else ''}.")
        kind = "warn"
    else:
        title = "Carga completada"
        body = f"La carga de la medición #{measurement_id} terminó correctamente."
        kind = "ok"
    return title, body, f"/mediciones/{measurement_id}?tab=cargas", kind
