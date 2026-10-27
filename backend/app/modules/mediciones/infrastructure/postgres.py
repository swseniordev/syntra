"""Persistencia transaccional de Mediciones y registro durable de preparación."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.modules.auditoria.infrastructure.postgres import PostgresAuditWriter


def _truth(value: Any, default: bool = False) -> bool:
    return default if value is None else bool(value)


class PostgresMeasurementRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def _account(self, account_id: int, actor_id: int, global_access: bool) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT c.id,c.cliente_id,c.nombre,c.estado_id,c.prompt_clusters,c.prompt_temas "
            "FROM cfg.cuenta c WHERE c.id=%s "
            "AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v "
            "WHERE v.cuenta_id=c.id AND v.usuario_id=%s)) FOR SHARE",
            (account_id, global_access, actor_id),
        ).fetchone()
        if row is None:
            raise LookupError("La cuenta no existe o no está disponible para este usuario")
        if row["estado_id"] != 1:
            raise LookupError("Seleccione una cuenta activa")
        return row

    def _resolve_prompt(self, item: dict[str, Any], account: dict[str, Any]) -> tuple[int | None, int | None, str, int]:
        kind = item["tipo"]
        origin = item["origen"]
        network = item.get("red")
        red_id = 0
        if network:
            red = self.conn.execute("SELECT id FROM cat.red WHERE codigo=%s", (network,)).fetchone()
            if red is None:
                raise LookupError("La red del prompt no está disponible")
            red_id = red["id"]
        if origin == "cuenta":
            content_key = {"cluster": "prompt_clusters", "temas": "prompt_temas"}.get(kind)
            content = account.get(content_key) if content_key else None
            if not content:
                raise LookupError("La cuenta no tiene un prompt configurado para este tipo")
            return None, None, content, red_id
        prompt_id = item.get("prompt_id")
        if prompt_id is None:
            content = item.get("contenido")
            if origin == "propio" and isinstance(content, str) and content.strip():
                return None, None, content, red_id
            raise LookupError("Seleccione explícitamente un prompt activo y una versión")
        version = item.get("version")
        if type(version) is not int or version < 1:
            raise LookupError("Seleccione explícitamente la versión del prompt")
        row = self.conn.execute(
            "SELECT p.id,p.version_actual,v.version,v.contenido FROM cfg.prompt p "
            "JOIN cfg.prompt_version v ON v.prompt_id=p.id "
            "WHERE p.id=%s AND p.tipo=%s AND p.estado_id=1 "
            "AND (p.red_id IS NULL OR p.red_id IS NOT DISTINCT FROM %s::smallint) AND v.version=%s",
            (prompt_id, kind, red_id or None, version),
        ).fetchone()
        if row is None:
            raise LookupError("El prompt o la versión seleccionada no está activa")
        if origin == "defecto" and not self.conn.execute(
            "SELECT 1 FROM cfg.prompt WHERE id=%s AND por_defecto AND estado_id=1", (prompt_id,),
        ).fetchone():
            raise LookupError("El prompt seleccionado ya no es el predeterminado")
        return prompt_id, row["version"], row["contenido"], red_id

    def _insert_cross(self, item: dict[str, Any], actor_id: int) -> int:
        row = self.conn.execute(
            "INSERT INTO cfg.cruce(nombre,categoria,color,modo,incluye_autor,descripcion,creado_por,actualizado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (item["nombre"].strip(), item.get("categoria"), item.get("color", "#1293F8"),
             item.get("modo", "texto_hashtags"), _truth(item.get("incluye_autor"), True),
             item.get("descripcion"), actor_id, actor_id),
        ).fetchone()
        for value in item.get("items", []):
            self.conn.execute("INSERT INTO cfg.cruce_item(cruce_id,item) VALUES (%s,%s)", (row["id"], value.strip()))
        return row["id"]

    def _insert_scraper(self, measurement_id: int, item: dict[str, Any], actor_id: int) -> None:
        auto = _truth(item.get("ejecucion_auto"), True)
        frequency = item.get("frecuencia_min")
        if auto and (type(frequency) is not int or frequency < 15):
            raise LookupError("La frecuencia automática del scraper debe ser de al menos 15 minutos")
        google = item.get("google_news") or {}
        networks = item.get("redes") or []
        words_by_source = item.get("palabras") or {}
        if google.get("activo") and not google.get("pais_ids"):
            raise LookupError("Google News requiere al menos un país activo")
        for network in networks:
            code = network["red"]
            if network.get("activo", True) and not words_by_source.get(code):
                raise LookupError("Cada red activa requiere al menos una palabra de búsqueda")
            selected_actor_id = network.get("actor_id")
            actor = self.conn.execute(
                "SELECT max_registros FROM cfg.actor_scraping a JOIN cat.red r ON r.id=a.red_id "
                "WHERE a.id=%s AND r.codigo=%s AND a.estado_id=1",
                (selected_actor_id, code),
            ).fetchone() if selected_actor_id is not None else None
            if selected_actor_id is not None and actor is None:
                raise LookupError("El actor de scraping no está activo para la red seleccionada")
            if actor is not None and network["registros"] > actor["max_registros"]:
                raise LookupError("La cantidad solicitada supera el máximo del actor de scraping")
        if google.get("activo") and not words_by_source.get("googlenews"):
            raise LookupError("Google News requiere al menos una palabra de búsqueda")
        prompts = item.get("prompts") or {}
        rel = self._resolve_scraper_prompt(measurement_id, "relevancia", prompts.get("relevancia") or {})
        sentiment = self._resolve_scraper_prompt(measurement_id, "sentimiento", prompts.get("sentimiento") or {})
        row = self.conn.execute(
            "INSERT INTO med.scraper(medicion_id,nombre,ejecucion_auto,inicio,fin,frecuencia_min,"
            "actualizar_interacciones,transcribir,mismas_palabras,gn_activo,gn_registros,gn_periodo,"
            "post_incorporar,post_relevancia,post_sentimiento,post_clusters,post_bots,"
            "prompt_rel_origen,prompt_rel_id,prompt_rel_contenido,prompt_sen_origen,prompt_sen_id,prompt_sen_contenido,"
            "estado_id,creado_por,actualizado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s) RETURNING id",
            (measurement_id, item["nombre"].strip(), auto, item["inicio"], item["fin"], frequency,
             _truth(item.get("actualizar_interacciones"), True), _truth(item.get("transcribir"), True),
             _truth(item.get("mismas_palabras"), True), _truth(google.get("activo")), google.get("registros", 50),
             google.get("periodo", "ultimo_dia"), *self._actions(item.get("al_incorporar")),
             rel.get("origen", "medicion"), rel.get("prompt_id"), rel.get("contenido"),
             sentiment.get("origen", "medicion"), sentiment.get("prompt_id"), sentiment.get("contenido"), actor_id, actor_id),
        ).fetchone()
        scraper_id = row["id"]
        for network in networks:
            network_row = self.conn.execute("SELECT id FROM cat.red WHERE codigo=%s", (network["red"],)).fetchone()
            if network_row is None:
                raise LookupError("Una red del scraper no está disponible")
            actor_id_for_network = network.get("actor_id")
            if actor_id_for_network is not None and not self.conn.execute(
                "SELECT 1 FROM cfg.actor_scraping WHERE id=%s AND red_id=%s AND estado_id=1",
                (actor_id_for_network, network_row["id"]),
            ).fetchone():
                raise LookupError("El actor de scraping no está activo para la red seleccionada")
            self.conn.execute(
                "INSERT INTO med.scraper_red(scraper_id,red_id,activo,registros,actor_id) VALUES (%s,%s,%s,%s,%s)",
                (scraper_id, network_row["id"], _truth(network.get("activo"), True), network["registros"], actor_id_for_network),
            )
        for country_id in google.get("pais_ids", []):
            if not self.conn.execute("SELECT 1 FROM cfg.pais WHERE id=%s AND estado_id=1", (country_id,)).fetchone():
                raise LookupError("El país de Google News no está activo")
            self.conn.execute("INSERT INTO med.scraper_pais(scraper_id,pais_id) VALUES (%s,%s)", (scraper_id, country_id))
        for source, words in words_by_source.items():
            for word in words:
                self.conn.execute("INSERT INTO med.scraper_palabra(scraper_id,fuente,palabra) VALUES (%s,%s,%s)",
                                  (scraper_id, source, word.strip()))

    def _resolve_scraper_prompt(self, measurement_id: int, kind: str, item: dict[str, Any]) -> dict[str, Any]:
        origin = item.get("origen", "medicion")
        if origin == "propio":
            content = item.get("contenido")
            if not isinstance(content, str) or not content.strip():
                raise LookupError("El prompt propio del scraper requiere contenido")
            return {"origen": origin, "prompt_id": None, "contenido": content}
        if origin == "medicion":
            row = self.conn.execute(
                "SELECT prompt_id,contenido FROM med.medicion_prompt WHERE medicion_id=%s AND tipo=%s "
                "ORDER BY (red_id=0) DESC LIMIT 1", (measurement_id, kind),
            ).fetchone()
            if row is None:
                raise LookupError("Configure el prompt correspondiente en la medición o seleccione otro origen")
            return {"origen": origin, "prompt_id": row["prompt_id"], "contenido": row["contenido"]}
        if origin != "defecto":
            raise LookupError("El origen del prompt del scraper no es válido")
        prompt_id = item.get("prompt_id")
        if prompt_id is not None:
            row = self.conn.execute(
                "SELECT p.id,v.contenido FROM cfg.prompt p JOIN cfg.prompt_version v ON v.prompt_id=p.id "
                "WHERE p.id=%s AND p.tipo=%s AND p.por_defecto AND p.estado_id=1 "
                "AND v.version=p.version_actual", (prompt_id, kind),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT p.id,v.contenido FROM cfg.prompt p JOIN cfg.prompt_version v ON v.prompt_id=p.id "
                "WHERE p.tipo=%s AND p.por_defecto AND p.estado_id=1 AND p.red_id IS NULL "
                "AND v.version=p.version_actual", (kind,),
            ).fetchone()
        if row is None:
            raise LookupError("No hay un prompt predeterminado activo para el scraper")
        return {"origen": origin, "prompt_id": row["id"], "contenido": row["contenido"]}

    @staticmethod
    def _actions(value: dict[str, Any] | None) -> tuple[bool, bool, bool, bool, bool]:
        value = value or {}
        return tuple(_truth(value.get(key), default) for key, default in (
            ("incorporar", True), ("relevancia", False), ("sentimiento", True), ("clusters", False), ("bots", False)))

    def create(self, values: dict[str, Any], actor_id: int, global_access: bool) -> dict[str, Any]:
        account = self._account(values["cuenta_id"], actor_id, global_access)
        clusters = values.get("clusters") or {}
        bots = values.get("bots") or {}
        x = values.get("parametros_x") or {}
        regex = values.get("regex") or {}
        media = values.get("medios") or {}
        state = values.get("estado_id", 1)
        measurement = self.conn.execute(
            "INSERT INTO med.medicion(cuenta_id,nombre,coyuntura,num_clusters,num_subclusters,tipo_analisis,instrucciones,"
            "ventana_desde,precluster_activo,precluster_separar_temas,precluster_aplicar_bots,x_num_menciones,x_num_cuentas,"
            "auto_publicar,transcripcion,guardar_video,estado_id,creado_por,actualizado_por) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,cuenta_id,nombre,coyuntura,"
            "num_clusters,num_subclusters,tipo_analisis,instrucciones,ventana_desde,precluster_activo,precluster_separar_temas,"
            "precluster_aplicar_bots,x_num_menciones,x_num_cuentas,auto_publicar,transcripcion,guardar_video,estado_id,creado_en",
            (account["id"], values["nombre"].strip(), values.get("coyuntura", False), clusters.get("num_clusters", 15),
             clusters.get("num_subclusters", 3), clusters.get("tipo_analisis", "temas_sentimiento"), values.get("instrucciones"),
             values.get("ventana_desde"), regex.get("precluster_activo", False), regex.get("separar_temas", False),
             regex.get("aplicar_en_bots", False), x.get("num_menciones", 0), x.get("num_cuentas", 50),
             values.get("auto_publicar", False), media.get("transcripcion", "relevantes"), media.get("guardar_video", False),
             state, actor_id, actor_id),
        ).fetchone()
        mid = measurement["id"]

        for source in values.get("fuentes", []):
            source_id = self.conn.execute("SELECT id FROM cat.origen WHERE codigo=%s", (source["origen"],)).fetchone()
            if source_id is None:
                raise LookupError("El origen de datos no está disponible")
            self.conn.execute(
                "INSERT INTO med.medicion_fuente(medicion_id,origen_id,activo,config,post_incorporar,post_relevancia,post_sentimiento,post_clusters,post_bots) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (mid, source_id["id"], _truth(source.get("activo"), True), Jsonb(source.get("config") or {}),
                 *self._actions(source.get("al_cargar"))),
            )
        scheduling = values.get("programacion_meltwater") or {}
        if scheduling.get("activa"):
            if not any(s.get("origen") == "meltwater" and s.get("activo", True) for s in values.get("fuentes", [])):
                raise LookupError("Active Meltwater como fuente antes de programar consultas")
            self.conn.execute(
                "INSERT INTO med.programacion_meltwater(medicion_id,activa,inicio,fin,frecuencia_min) VALUES (%s,true,%s,%s,%s)",
                (mid, scheduling["inicio"], scheduling["fin"], scheduling["frecuencia_min"]),
            )

        for prompt in values.get("prompts", []):
            prompt_id, version, content, red_id = self._resolve_prompt(prompt, account)
            self.conn.execute(
                "INSERT INTO med.medicion_prompt(medicion_id,tipo,red_id,origen,prompt_id,prompt_version,contenido) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (mid, prompt["tipo"], red_id, prompt["origen"], prompt_id, version, content),
            )

        cross_ids = list((clusters.get("cruce_ids") or []))
        for cross in values.get("cruces", []):
            cross_ids.append(self._insert_cross(cross, actor_id))
        if len(cross_ids) != len(set(cross_ids)):
            raise LookupError("No repita cruces")
        for cross_id in cross_ids:
            if not self.conn.execute("SELECT 1 FROM cfg.cruce WHERE id=%s AND estado_id=1", (cross_id,)).fetchone():
                raise LookupError("Uno de los cruces seleccionados no está activo")
            self.conn.execute("INSERT INTO med.medicion_cruce(medicion_id,cruce_id) VALUES (%s,%s)", (mid, cross_id))
        for order, regex_id in enumerate(regex.get("regex_ids_ordenados", []), 1):
            if not self.conn.execute("SELECT 1 FROM cfg.regex WHERE id=%s AND estado_id=1", (regex_id,)).fetchone():
                raise LookupError("Una expresión regular seleccionada no está activa")
            self.conn.execute("INSERT INTO med.medicion_regex(medicion_id,regex_id,orden) VALUES (%s,%s,%s)", (mid, regex_id, order))
        self.conn.execute(
            "INSERT INTO med.medicion_bots(medicion_id,activo,identificar,rt_negativos,neg_pos,criterios_min,criterios,criterio_texto) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (mid, _truth(bots.get("activo"), True), _truth(bots.get("identificar"), True),
             _truth(bots.get("rt_negativos"), True), _truth(bots.get("neg_pos"), True),
             bots.get("criterios_min", 3), bots.get("criterios", ["antiguedad", "ratio", "frecuencia", "duplicado"]),
             bots.get("criterio_texto")),
        )
        for scraper in values.get("scrapers", []):
            self._insert_scraper(mid, scraper, actor_id)

        process = self.conn.execute(
            "INSERT INTO prc.proceso(medicion_id,cuenta_id,tipo,modo,estado,prioridad,opciones,total,creado_por,idempotencia) "
            "VALUES (%s,%s,'preparar_medicion','automatico','en_cola',2,%s,1,%s,%s) RETURNING id",
            (mid, account["id"], Jsonb({"kind": "preparacion_medicion", "measurement_id": mid}), actor_id,
             f"medicion-preparacion:{mid}"),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO prc.proceso_tarea(proceso_id,clave,tipo,cola,payload) "
            "VALUES (%s,'preparar','preparar_medicion','q.mantenimiento',%s)",
            (process["id"], Jsonb({"medicion_id": mid, "cuenta_id": account["id"],
                                   "actor_id": actor_id, "estado_solicitado": state})),
        )
        return {**measurement, "proceso_preparacion_id": process["id"]}

    def list(self, actor_id: int, global_access: bool, limit: int,
             after: tuple[str, int] | None = None,
             filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        rows = self.conn.execute(
            "SELECT m.id,m.cuenta_id,c.nombre AS cuenta_nombre,m.nombre,m.coyuntura,m.estado_id,m.creado_en, "
            "c.cliente_id,ARRAY(SELECT o.codigo FROM med.medicion_fuente mf JOIN cat.origen o ON o.id=mf.origen_id "
            "WHERE mf.medicion_id=m.id AND mf.activo ORDER BY o.codigo) AS fuentes, "
            "(SELECT p.estado FROM prc.proceso p WHERE p.medicion_id=m.id AND p.tipo='preparar_medicion' "
            "ORDER BY p.id DESC LIMIT 1) AS preparacion_estado "
            "FROM med.medicion m JOIN cfg.cuenta c ON c.id=m.cuenta_id "
            "WHERE (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s)) "
            "AND (%s='' OR m.nombre ILIKE ('%%'||%s||'%%') OR c.nombre ILIKE ('%%'||%s||'%%')) "
            "AND ((%s=-99 AND m.estado_id<>-1) OR m.estado_id=%s) AND (%s::int IS NULL OR m.cuenta_id=%s) "
            "AND (%s::int IS NULL OR c.cliente_id=%s) AND (%s::boolean IS NULL OR m.coyuntura=%s) "
            "AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM med.medicion_fuente mf JOIN cat.origen o ON o.id=mf.origen_id "
            "WHERE mf.medicion_id=m.id AND mf.activo AND o.codigo=%s) OR (%s='scraper' AND EXISTS "
            "(SELECT 1 FROM med.scraper s WHERE s.medicion_id=m.id AND s.estado_id=1)) OR "
            "(%s='googlenews' AND EXISTS (SELECT 1 FROM med.scraper s WHERE s.medicion_id=m.id "
            "AND s.estado_id=1 AND s.gn_activo))) "
            "AND (%s::timestamptz IS NULL OR (m.creado_en,m.id)>(%s,%s)) "
            "ORDER BY m.creado_en,m.id LIMIT %s",
            (global_access, actor_id, filters.get("q", ""), filters.get("q", ""), filters.get("q", ""),
             filters.get("estado_id"), filters.get("estado_id"), filters.get("cuenta_id"), filters.get("cuenta_id"),
             filters.get("cliente_id"), filters.get("cliente_id"), filters.get("coyuntura"), filters.get("coyuntura"),
             filters.get("fuente"), filters.get("fuente"), filters.get("fuente"), filters.get("fuente"),
             after[0] if after else None, after[0] if after else None, after[1] if after else None, limit),
        ).fetchall()
        return rows

    def get(self, measurement_id: int, actor_id: int, global_access: bool) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT m.id,m.cuenta_id,c.nombre AS cuenta_nombre,m.nombre,m.coyuntura,m.num_clusters,m.num_subclusters,"
            "m.tipo_analisis,m.instrucciones,m.ventana_desde,m.precluster_activo,m.precluster_separar_temas,"
            "m.precluster_aplicar_bots,m.x_num_menciones,m.x_num_cuentas,m.auto_publicar,m.transcripcion,m.guardar_video,"
            "m.estado_id,m.creado_en,m.actualizado_en,p.id AS proceso_preparacion_id,p.estado AS preparacion_estado "
            "FROM med.medicion m JOIN cfg.cuenta c ON c.id=m.cuenta_id LEFT JOIN LATERAL ("
            "SELECT id,estado FROM prc.proceso WHERE medicion_id=m.id AND tipo='preparar_medicion' ORDER BY id DESC LIMIT 1) p ON true "
            "WHERE m.id=%s AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s))",
            (measurement_id, global_access, actor_id),
        ).fetchone()
        if row is None:
            return None
        row["fuentes"] = self._sources(measurement_id)
        schedule = self.conn.execute(
            "SELECT activa,inicio,fin,frecuencia_min FROM med.programacion_meltwater WHERE medicion_id=%s",
            (measurement_id,),
        ).fetchone()
        row["programacion_meltwater"] = schedule or {"activa": False, "inicio": None, "fin": None,
                                                     "frecuencia_min": None}
        return row

    def source_summary(self, measurement_id: int) -> list[dict[str, Any]]:
        # La vista oficial cuenta registros de todas las cargas de la medición;
        # los duplicados omitidos viven en dat.ejecucion, incluso si el lote falló.
        rows = self.conn.execute(
            "SELECT origen,cargados,por_fiscalizar,cumplen_sin_incorporar,descartados,"
            "incorporados,con_metricas,transcritos,analizados,en_tablero,eliminados,con_error "
            "FROM dat.v_estado_medicion WHERE medicion_id=%s", (measurement_id,),
        ).fetchall()
        duplicates = self.conn.execute(
            "SELECT o.codigo AS origen,coalesce(sum(e.n_duplicados),0)::bigint AS duplicados "
            "FROM dat.ejecucion e JOIN cat.origen o ON o.id=e.origen_id "
            "WHERE e.medicion_id=%s GROUP BY o.codigo", (measurement_id,),
        ).fetchall()
        by_origin = {row["origen"]: dict(row) for row in rows}
        for row in duplicates:
            by_origin.setdefault(row["origen"], {"origen": row["origen"]})["duplicados"] = row["duplicados"]
        return [{**{"cargados": 0, "por_fiscalizar": 0, "cumplen_sin_incorporar": 0,
                    "descartados": 0, "incorporados": 0, "con_metricas": 0,
                    "transcritos": 0, "analizados": 0, "en_tablero": 0,
                    "eliminados": 0, "con_error": 0, "duplicados": 0}, **row}
                for _, row in sorted(by_origin.items())]

    def get_for_update(self, measurement_id: int, actor_id: int, global_access: bool) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT m.id,m.cuenta_id,c.nombre AS cuenta_nombre,m.nombre,m.coyuntura,m.num_clusters,m.num_subclusters,"
            "m.tipo_analisis,m.instrucciones,m.ventana_desde,m.precluster_activo,m.precluster_separar_temas,"
            "m.precluster_aplicar_bots,m.x_num_menciones,m.x_num_cuentas,m.auto_publicar,m.transcripcion,m.guardar_video,"
            "m.estado_id,m.creado_en,m.actualizado_en,p.id AS proceso_preparacion_id,p.estado AS preparacion_estado "
            "FROM med.medicion m JOIN cfg.cuenta c ON c.id=m.cuenta_id LEFT JOIN LATERAL ("
            "SELECT id,estado FROM prc.proceso WHERE medicion_id=m.id AND tipo='preparar_medicion' ORDER BY id DESC LIMIT 1) p ON true "
            "WHERE m.id=%s AND (%s OR EXISTS (SELECT 1 FROM seg.v_usuario_cuenta v WHERE v.cuenta_id=m.cuenta_id AND v.usuario_id=%s)) "
            "FOR UPDATE OF m",
            (measurement_id, global_access, actor_id),
        ).fetchone()
        if row is None:
            return None
        row["fuentes"] = self._sources(measurement_id)
        row["programacion_meltwater"] = self.conn.execute(
            "SELECT activa,inicio,fin,frecuencia_min FROM med.programacion_meltwater WHERE medicion_id=%s",
            (measurement_id,),
        ).fetchone() or {"activa": False, "inicio": None, "fin": None, "frecuencia_min": None}
        return row

    def _sources(self, measurement_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT o.codigo AS origen,mf.activo,mf.config,mf.post_incorporar,mf.post_relevancia,"
            "mf.post_sentimiento,mf.post_clusters,mf.post_bots FROM med.medicion_fuente mf "
            "JOIN cat.origen o ON o.id=mf.origen_id WHERE mf.medicion_id=%s ORDER BY o.codigo",
            (measurement_id,),
        ).fetchall()
        return [{"origen": row["origen"], "activo": row["activo"], "config": row["config"],
                 "al_cargar": {"incorporar": row["post_incorporar"], "relevancia": row["post_relevancia"],
                               "sentimiento": row["post_sentimiento"], "clusters": row["post_clusters"],
                               "bots": row["post_bots"]}} for row in rows]

    def update_configuration(self, measurement_id: int, changes: dict[str, Any], actor_id: int) -> dict[str, Any]:
        if "fuentes" in changes:
            self.conn.execute("DELETE FROM med.medicion_fuente WHERE medicion_id=%s", (measurement_id,))
            for source in changes["fuentes"]:
                origin = self.conn.execute("SELECT id FROM cat.origen WHERE codigo=%s", (source["origen"],)).fetchone()
                if origin is None:
                    raise LookupError("El origen de datos no está disponible")
                self.conn.execute(
                    "INSERT INTO med.medicion_fuente(medicion_id,origen_id,activo,config,post_incorporar,post_relevancia,post_sentimiento,post_clusters,post_bots) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (measurement_id, origin["id"], _truth(source.get("activo"), True),
                     Jsonb(source.get("config") or {}), *self._actions(source.get("al_cargar"))),
                )
        if "programacion_meltwater" in changes:
            schedule = changes["programacion_meltwater"] or {}
            self.conn.execute("DELETE FROM med.programacion_meltwater WHERE medicion_id=%s", (measurement_id,))
            if schedule.get("activa"):
                self.conn.execute(
                    "INSERT INTO med.programacion_meltwater(medicion_id,activa,inicio,fin,frecuencia_min) "
                    "VALUES (%s,true,%s,%s,%s)",
                    (measurement_id, schedule["inicio"], schedule["fin"], schedule["frecuencia_min"]),
                )
        assignments = []
        params: list[Any] = []
        if "auto_publicar" in changes:
            assignments.append("auto_publicar=%s")
            params.append(changes["auto_publicar"])
        assignments.extend(("actualizado_en=GREATEST(clock_timestamp(),actualizado_en + interval '1 microsecond')",
                            "actualizado_por=%s"))
        params.extend((actor_id, measurement_id))
        self.conn.execute(f"UPDATE med.medicion SET {', '.join(assignments)} WHERE id=%s", params)
        result = self.get(measurement_id, actor_id, True)
        assert result is not None
        return result


class PostgresMeasurementUnitOfWork:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.measurements = PostgresMeasurementRepository(conn)
        self.audit = PostgresAuditWriter(conn)
        self._committed = False

    def __enter__(self) -> "PostgresMeasurementUnitOfWork":
        self._committed = False
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is not None or not self._committed:
            self.conn.rollback()

    def commit(self) -> None:
        self.conn.commit()
        self._committed = True
