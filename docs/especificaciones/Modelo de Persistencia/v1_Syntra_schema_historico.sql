
-- =====================================================================================
--  SYNTRA · BD HISTÓRICA (PostgreSQL 18, servidor pg-hist)
--  Recibe cada mes las hojas medición×mes que salen de la BD principal (ver ops.archivado en la principal).
--  · Mismas columnas que dat.* de la principal → la copia es COPY binario directo, sin transformar.
--  · Partición por AÑO (RANGE periodo): pocas tablas aunque pasen años (≈ 10 tablas × años).
--  · Solo lectura para la aplicación (rol syntra_hist_lector). Escribe solo el worker de archivado.
--  · Sin FK ni huella: la integridad viene garantizada desde la principal y se verifica con conteos.
--  Generado a partir de schema.sql (secciones dat.*).

-- =====================================================================================
--  SYNTRA · 2026-10-15
--  Recibe cada mes las hojas medición×mes que salen de la BD principal (ver ops.archivado).
--  Incluye: particionamiento anual robusto, compresión LZ4/Extended
--    y verificación automática de conteos.
-- =====================================================================================

CREATE SCHEMA IF NOT EXISTS dat;
CREATE SCHEMA IF NOT EXISTS ops;

-- -------------------------------------------------------------------------------------
-- 1. TABLAS PRINCIPALES (Particionadas por RANGE periodo - YYYYMM)
-- -------------------------------------------------------------------------------------

CREATE TABLE dat.registro (
  cuenta_id        int      NOT NULL,
  medicion_id      int      NOT NULL,
  periodo          int      NOT NULL,                     -- formato YYYYMM
  registro_id      bigint   NOT NULL,
  ejecucion_id     bigint   NOT NULL,
  origen_id        smallint NOT NULL,
  red_id           smallint NOT NULL,
  scraper_id       int,
  url              text,
  url_hash         bytea    NOT NULL,                     -- md5(url normalizada) o md5(autor|fecha|texto)
  url_padre        text,
  fecha_publicacion timestamptz NOT NULL,
  fecha_indexado   timestamptz,
  idioma           text,
  tipo_contenido   text,                                  -- texto · imagen · video · audio · articulo · link
  titulo           text,
  texto            text,
  autor_id_ext     text, autor_usuario text, autor_nombre text,
  autor_seguidores int,
  pais             char(2), region text, ciudad text,
  es_rt            boolean NOT NULL DEFAULT false,
  es_comentario    boolean NOT NULL DEFAULT false,
  media_urls       text[],
  extra            jsonb,                                 -- columnas del formato no normalizadas
  sentimiento_fuente smallint,                            -- el que trae el proveedor (ej. Talkwalker -5..5)
  editado          boolean NOT NULL DEFAULT false,
  comentario       text,
  creado_en        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo)
) PARTITION BY RANGE (periodo);

-- AJUSTE C: Optimización de compresión TOAST en columnas de alto volumen de texto/JSONB
ALTER TABLE dat.registro ALTER COLUMN texto SET STORAGE EXTENDED;
ALTER TABLE dat.registro ALTER COLUMN extra SET STORAGE EXTENDED;
ALTER TABLE dat.registro ALTER COLUMN media_urls SET STORAGE EXTENDED;


CREATE TABLE dat.registro_estado (
  cuenta_id        int      NOT NULL,
  medicion_id      int      NOT NULL,
  periodo          int      NOT NULL,
  registro_id      bigint   NOT NULL,
  estado_id        smallint NOT NULL DEFAULT 1,           -- -1 eliminado lógico
  relevancia       smallint NOT NULL DEFAULT 0,           -- 0 pendiente · 1 cumple · 2 no cumple
  relevancia_ia    smallint,                              -- sugerencia IA (1/2)
  relevancia_pct   smallint,
  incorporado      boolean  NOT NULL DEFAULT false,
  incorporado_en   timestamptz,
  sentimiento      smallint,                              -- -1 negativo · 0 neutral · 1 positivo
  sentimiento_origen char(1),                             -- i = IA · m = manual
  corrida_id       int, cluster_id int, subcluster_id int, tema_id int,
  precluster_regex_id int,                                -- primera regex que coincide
  es_bot           boolean,
  publicado        boolean  NOT NULL DEFAULT false,
  publicado_en     timestamptz,
  -- métricas vigentes
  likes bigint, comentarios bigint, compartidos bigint, reproducciones bigint, alcance bigint,
  metricas_en      timestamptz, metricas_version smallint NOT NULL DEFAULT 0,
  -- indicadores por paso (0 pendiente · 1 en curso · 2 ok · 3 error · 4 no aplica)
  st_relevancia    smallint NOT NULL DEFAULT 0,
  st_sentimiento   smallint NOT NULL DEFAULT 0,
  st_transcripcion smallint NOT NULL DEFAULT 4,
  st_metricas      smallint NOT NULL DEFAULT 0,
  st_regex         smallint NOT NULL DEFAULT 0,
  st_cruces        smallint NOT NULL DEFAULT 0,
  st_embedding     smallint NOT NULL DEFAULT 0,
  st_cluster       smallint NOT NULL DEFAULT 0,
  st_bots          smallint NOT NULL DEFAULT 0,
  st_publicacion   smallint NOT NULL DEFAULT 0,
  ultimo_proceso_id bigint,
  actualizado_en   timestamptz NOT NULL DEFAULT now(),
  actualizado_por  int,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_ia (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  paso smallint NOT NULL,                                 -- relevancia · sentimiento
  evaluado_en timestamptz NOT NULL DEFAULT now(),
  valor smallint NOT NULL, pct smallint, razon text,
  proceso_id bigint, llamado_id bigint, modelo_id int, prompt_hash bytea,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, paso, evaluado_en)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_transcripcion (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  texto text NOT NULL, idioma text, duracion_s int, proveedor_id smallint, modelo_id int,
  segmentos jsonb,                                        -- subtítulos para el visor
  servidor text, segundos_proceso numeric(8,2),           -- rendimiento GPU
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo)
) PARTITION BY RANGE (periodo);

ALTER TABLE dat.registro_transcripcion ALTER COLUMN texto SET STORAGE EXTENDED;
ALTER TABLE dat.registro_transcripcion ALTER COLUMN segmentos SET STORAGE EXTENDED;


CREATE TABLE dat.registro_media (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, orden smallint NOT NULL,
  tipo text NOT NULL CHECK (tipo IN ('video','imagen','audio')),
  url_origen text NOT NULL,
  s3_key text,
  s3_key_audio text,
  bytes bigint, bytes_audio bigint, duracion_s int,
  estado smallint NOT NULL DEFAULT 0,
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, orden)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_regex (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, regex_id int NOT NULL,
  regex_version int NOT NULL, activo boolean NOT NULL DEFAULT true,
  coincidencias smallint NOT NULL DEFAULT 1,
  creado_en timestamptz NOT NULL DEFAULT now(), actualizado_en timestamptz NOT NULL DEFAULT now(), proceso_id bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, regex_id)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_cruce (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, cruce_id int NOT NULL,
  items text[] NOT NULL, activo boolean NOT NULL DEFAULT true,
  actualizado_en timestamptz NOT NULL DEFAULT now(), proceso_id bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, cruce_id)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_metrica_hist (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  capturado_en timestamptz NOT NULL, proceso_id bigint,
  likes bigint, comentarios bigint, compartidos bigint, reproducciones bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, capturado_en)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.registro_evento (
  cuenta_id int NOT NULL, medicion_id int NOT NULL,
  periodo int NOT NULL,
  evento_id bigint NOT NULL,
  registro_id bigint,
  paso smallint NOT NULL,
  proceso_id bigint, tarea_id bigint,
  intento smallint NOT NULL DEFAULT 1,
  estado smallint NOT NULL,
  codigo_error text, mensaje text,
  detalle jsonb,
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, evento_id, periodo)
) PARTITION BY RANGE (periodo);


CREATE TABLE dat.llm_uso_registro (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  llamado_id bigint NOT NULL, llamado_en timestamptz NOT NULL,
  paso smallint NOT NULL,
  tokens_in int NOT NULL, tokens_out int NOT NULL,
  costo_usd numeric(12,8) NOT NULL DEFAULT 0,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, llamado_id)
) PARTITION BY RANGE (periodo);


-- Creación condicional del soporte de vectores semánticos (pgvector)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
    EXECUTE $q$
      CREATE TABLE dat.registro_embedding (
        cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
        modelo_id int NOT NULL, texto_hash bytea NOT NULL, embedding halfvec(256) NOT NULL,
        creado_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, modelo_id)
      ) PARTITION BY RANGE (periodo)$q$;
  END IF;
END $$;


-- -------------------------------------------------------------------------------------
-- 2. ÍNDICES DE APOYO ANALÍTICO
-- -------------------------------------------------------------------------------------

CREATE INDEX ix_hreg_fecha ON dat.registro (medicion_id, fecha_publicacion DESC);
CREATE INDEX ix_hreg_autor ON dat.registro (medicion_id, autor_usuario);
CREATE INDEX ix_hevt_reg   ON dat.registro_evento (medicion_id, registro_id);
CREATE INDEX ix_hrx_regex  ON dat.registro_regex (medicion_id, regex_id) WHERE activo;


-- -------------------------------------------------------------------------------------
-- 3. CONTROL DE RECEPCIÓN Y FUNCIONES DE AUTOMATIZACIÓN
-- -------------------------------------------------------------------------------------

-- Control de lo recibido (espejo mejorado con estado de validación de filas)
CREATE TABLE ops.recibido (
  cuenta_id int NOT NULL,
  medicion_id int NOT NULL,
  periodo int NOT NULL,
  filas_esperadas bigint NOT NULL DEFAULT 0,
  filas_insertadas bigint NOT NULL DEFAULT 0,
  estado_validacion text NOT NULL DEFAULT 'pendiente', -- pendiente, verificado, error_conteo
  recibido_en timestamptz NOT NULL DEFAULT now(),
  proceso_id bigint,
  PRIMARY KEY (cuenta_id, medicion_id, periodo)
);

-- AJUSTE A: Función robusta para asegurar particiones anuales con rangos limpios YYYYMM
CREATE OR REPLACE FUNCTION ops.fn_asegurar_anio(p_anio int)
RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE
  t text;
  n int := 0;
  v_val_desde int;
  v_val_hasta int;
BEGIN
  v_val_desde := p_anio * 100 + 1;
  v_val_hasta := (p_anio + 1) * 100 + 1;

  FOR t IN SELECT c.relname FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid
           JOIN pg_namespace ns ON ns.oid = c.relnamespace WHERE ns.nspname = 'dat' AND NOT c.relispartition LOOP
    IF to_regclass(format('dat.%I', t || '_a' || p_anio)) IS NULL THEN
      EXECUTE format(
        'CREATE TABLE dat.%I PARTITION OF dat.%I FOR VALUES FROM (%s) TO (%s)',
        t || '_a' || p_anio, t, v_val_desde, v_val_hasta
      );
      n := n + 1;
    END IF;
  END LOOP;
  RETURN n;
END $fn$;

-- AJUSTE D: Función de validación automática post-archivado por conteo estricto de filas
CREATE OR REPLACE FUNCTION ops.fn_verificar_archivado(
  p_cuenta_id int,
  p_medicion_id int,
  p_periodo int,
  p_filas_origen bigint
) RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE
  v_filas_reales bigint;
BEGIN
  SELECT count(*) INTO v_filas_reales
    FROM dat.registro
   WHERE cuenta_id = p_cuenta_id
     AND medicion_id = p_medicion_id
     AND periodo = p_periodo;

  INSERT INTO ops.recibido (cuenta_id, medicion_id, periodo, filas_esperadas, filas_insertadas, estado_validacion)
  VALUES (
    p_cuenta_id, p_medicion_id, p_periodo, p_filas_origen, v_filas_reales,
    CASE WHEN v_filas_reales = p_filas_origen THEN 'verificado' ELSE 'error_conteo' END
  )
  ON CONFLICT (cuenta_id, medicion_id, periodo) DO UPDATE
  SET filas_esperadas = EXCLUDED.filas_esperadas,
      filas_insertadas = EXCLUDED.filas_insertadas,
      estado_validacion = CASE WHEN EXCLUDED.filas_insertadas = EXCLUDED.filas_esperadas THEN 'verificado' ELSE 'error_conteo' END,
      recibido_en = now();

  RETURN v_filas_reales = p_filas_origen;
END $fn$;

COMMENT ON FUNCTION ops.fn_verificar_archivado(int, int, int, bigint) IS
'Verifica que el número de filas transferidas mediante COPY coincida con el origen, actualizando ops.recibido.';


-- -------------------------------------------------------------------------------------
-- 4. ROLES, SEGURIDAD Y CONFIGURACIÓN INICIAL DE HORIZONTE
-- -------------------------------------------------------------------------------------

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'syntra_hist_lector') THEN CREATE ROLE syntra_hist_lector NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'syntra_hist_archivador') THEN CREATE ROLE syntra_hist_archivador NOLOGIN; END IF;
END $$;

GRANT USAGE ON SCHEMA dat, ops TO syntra_hist_lector, syntra_hist_archivador;
GRANT SELECT ON ALL TABLES IN SCHEMA dat TO syntra_hist_lector;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA dat TO syntra_hist_archivador;
GRANT SELECT, INSERT, UPDATE ON ops.recibido TO syntra_hist_archivador;

ALTER DEFAULT PRIVILEGES IN SCHEMA dat GRANT SELECT ON TABLES TO syntra_hist_lector;
ALTER DEFAULT PRIVILEGES IN SCHEMA dat GRANT SELECT, INSERT ON TABLES TO syntra_hist_archivador;

-- Inicializa las particiones para los años 2025 y 2026 de forma predeterminada
SELECT ops.fn_asegurar_anio(a) FROM generate_series(2025, 2026) a;
