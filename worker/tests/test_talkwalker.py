from datetime import date, datetime, timezone

import pytest

from app.domain.talkwalker import RejectedRow, map_row, url_identity
from app.infrastructure.ingest_source import rows_from_file


MAPPING = [
    {"campo_destino": "url", "columnas_origen": ["url"], "transformacion": "directo", "requerido": True},
    {"campo_destino": "fecha_publicacion", "columnas_origen": ["published"], "transformacion": "fecha", "requerido": True},
    {"campo_destino": "texto", "columnas_origen": ["content", "content_snippet"], "transformacion": "coalesce", "requerido": False},
    {"campo_destino": "red_id", "columnas_origen": ["source_type"], "transformacion": "red_desde_source_type", "requerido": False},
    {"campo_destino": "likes", "columnas_origen": ["likes"], "transformacion": "entero", "requerido": False},
]


def test_real_csv_stream_and_mapping(tmp_path):
    file = tmp_path / "datos.csv"
    file.write_text("url,published,content,source_type,likes\n"
                    'https://example.test/a,07/10/26 12:46:00,Texto,"SOCIALMEDIA,SOCIALMEDIA_TWITTER",12\n',
                    encoding="utf-8")
    raw = next(rows_from_file(file, "csv", "utf-8", ","))
    result = map_row(raw, MAPPING, {"x": 1, "medios": 6}, "America/Mexico_City", date(2015, 1, 1))
    assert result["red_id"] == 1
    assert result["likes"] == 12
    assert result["fecha_publicacion"] == datetime(2026, 10, 7, 18, 46, tzinfo=timezone.utc)
    assert len(result["url_hash"]) == 32


def test_rejects_unconfirmed_old_date_and_unknown_social_network():
    raw = {"url": "https://example.test/a", "published": "26/10/07 12:46:00",
           "content": "Texto", "source_type": "SOCIALMEDIA,SOCIALMEDIA_TWITTER"}
    with pytest.raises(RejectedRow, match="anterior al mínimo"):
        map_row(raw, MAPPING, {"x": 1}, "America/Mexico_City", date(2015, 1, 1))
    raw["published"] = "07/10/26 12:46:00"
    raw["source_type"] = "SOCIALMEDIA,SOCIALMEDIA_DESCONOCIDA"
    with pytest.raises(RejectedRow, match="desconocida"):
        map_row(raw, MAPPING, {"x": 1}, "America/Mexico_City", date(2015, 1, 1))


@pytest.mark.parametrize("value", ["31/02/26 14:30:00", "2026-10-25 14:30", "25/10/26 25:00:00"])
def test_invalid_dates_are_rejected(value):
    raw = {"url": "https://example.test/a", "published": value,
           "source_type": "SOCIALMEDIA,SOCIALMEDIA_TWITTER"}
    with pytest.raises(RejectedRow, match="Fecha incompatible"):
        map_row(raw, MAPPING, {"x": 1}, "America/Mexico_City", date(2015, 1, 1))


@pytest.mark.parametrize("value", ["03/04/22 02:30:00", "30/10/22 01:30:00"])
def test_nonexistent_or_ambiguous_mexico_local_time_is_rejected(value):
    raw = {"url": "https://example.test/a", "published": value,
           "source_type": "SOCIALMEDIA,SOCIALMEDIA_TWITTER"}
    with pytest.raises(RejectedRow, match="inexistente o ambigua"):
        map_row(raw, MAPPING, {"x": 1}, "America/Mexico_City", date(2015, 1, 1))


def test_year_boundary_and_optional_columns():
    raw = {"url": "https://example.test/a", "published": "31/12/26 23:30:00",
           "source_type": "SOCIALMEDIA,SOCIALMEDIA_TWITTER"}
    result = map_row(raw, MAPPING, {"x": 1}, "America/Mexico_City", date(2015, 1, 1))
    assert result["fecha_publicacion"] == datetime(2027, 1, 1, 5, 30, tzinfo=timezone.utc)
    assert result["texto"] is None
    assert result["likes"] is None


def test_only_url_and_published_headers_are_required(tmp_path):
    file = tmp_path / "minimal.csv"
    file.write_text("url,published\nhttps://example.test/a,07/10/26 12:46:00\n", encoding="utf-8")
    assert len(list(rows_from_file(file, "csv", "utf-8", ","))) == 1
    file.write_text("url\nhttps://example.test/a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Faltan columnas obligatorias: published"):
        list(rows_from_file(file, "csv", "utf-8", ","))


@pytest.mark.parametrize("source_type", ["OTHER", "SOCIALMEDIA,SOCIALMEDIA_BLUESKY",
                                          "ONLINENEWS,ONLINENEWS_UNRECOGNIZED", "", None])
def test_unknown_or_unconfigured_network_is_rejected(source_type):
    raw = {"url": "https://example.test/a", "published": "07/10/26 12:46:00",
           "source_type": source_type}
    with pytest.raises(RejectedRow, match="desconocida"):
        map_row(raw, MAPPING, {"x": 1, "medios": 6}, "America/Mexico_City", date(2015, 1, 1))


def test_known_news_category_maps_to_configured_media():
    raw = {"url": "https://example.test/a", "published": "07/10/26 12:46:00",
           "source_type": "ONLINENEWS,ONLINENEWS_NEWSPAPER"}
    result = map_row(raw, MAPPING, {"medios": 6}, "America/Mexico_City", date(2015, 1, 1))
    assert result["red_id"] == 6


def test_url_equivalence_and_distinct_resources():
    first = url_identity(" http://example.test/Nota/?id=7 ")
    second = url_identity("https://example.test/Nota?id=7")
    assert first[:2] == second[:2]
    assert url_identity("https://example.test/nota?id=7")[1] != second[1]
    assert url_identity("https://example.test/Nota?id=8")[1] != second[1]
    assert len(first[2]) >= 4


@pytest.mark.parametrize("value", ["ftp://example.test/a", "https://", "https://example.test/a b",
                                           "https://example.test:bad/a"])
def test_invalid_url_is_rejected(value):
    with pytest.raises(RejectedRow, match="URL inválida"):
        url_identity(value)
