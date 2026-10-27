from app.application.ingest_notice import finished_upload_notice


def test_finished_upload_notice_uses_persisted_outcome():
    assert finished_upload_notice(7, 12, "completado", 0) == (
        "Carga completada", "La carga de la medición #7 terminó correctamente.",
        "/mediciones/7?tab=cargas", "ok",
    )
    title, body, link, kind = finished_upload_notice(7, 12, "completado", 4)
    assert (title, link, kind) == ("Carga con advertencias", "/mediciones/7?tab=cargas", "warn")
    assert "4 registros rechazados" in body
    assert finished_upload_notice(7, 12, "error", 0)[3] == "err"
