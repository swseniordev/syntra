-- =====================================================================================
-- SYNTRA · MODELO DE DATOS POSTGRESQL COMPLETO (BASE + COMPLEMENTO)
-- Objetivo: PostgreSQL 18 (compatible 16+) en servidor propio
-- =====================================================================================

-- =====================================================================================
--  SYNTRA · Modelo de datos PostgreSQL
--  Objetivo: PostgreSQL 18 instalado en servidor propio (IaaS DigitalOcean, Ubuntu 24.04, paquetes PGDG) · compatible 16+
--  Este archivo es para VALIDACIÓN del diseño (no es la migración final).
--  Convenciones:
--    · Esquemas por dominio: cat (catálogos) · seg (seguridad) · cfg (configuración)
--      med (mediciones) · dat (datos/registros, particionado) · ana (análisis IA)
--      prc (procesos y LLM) · rep (agregados de informes) · aud (auditoría) · ops (operación)
--      stg (staging UNLOGGED para cargas y actualizaciones masivas)
--    · estado_id: 1 activo · 0 inactivo · -1 eliminado lógico
--    · Estados de paso por registro (st_*): 0 pendiente · 1 en curso · 2 ok · 3 error · 4 no aplica
--    · Toda tabla de configuración lleva creado_en/por y actualizado_en/por
--  Particionamiento de datos: dat.* por LIST(cuenta_id) → LIST(medicion_id) → LIST(periodo)
--    periodo = AAAAMM de la fecha del post (hora de Bogotá). Una hoja por medición y mes.
--    Las hojas se crean con ops.fn_preparar_medicion (al crear la medición) y
--    ops.fn_asegurar_periodos (antes de cada carga). El archivado mensual mueve hojas
--    completas a la BD histórica (copia + DETACH CONCURRENTLY + DROP: sin DELETE masivo).
--  Series de tiempo (llamados LLM, logs, auditoría): RANGE mensual por fecha.
--  Sin Redis: la cola de trabajo es prc.proceso_tarea (FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY).
-- =====================================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;          -- gen_random_uuid, digest
CREATE EXTENSION IF NOT EXISTS pg_trgm;           -- búsqueda «texto contiene»
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- pgvector se instala con el paquete postgresql-18-pgvector; aquí se crea de forma condicional
-- para que el archivo también corra en un PostgreSQL de desarrollo sin la extensión.

CREATE SCHEMA IF NOT EXISTS cat;
CREATE SCHEMA IF NOT EXISTS seg;
CREATE SCHEMA IF NOT EXISTS cfg;
CREATE SCHEMA IF NOT EXISTS med;
CREATE SCHEMA IF NOT EXISTS dat;
CREATE SCHEMA IF NOT EXISTS ana;
CREATE SCHEMA IF NOT EXISTS prc;
CREATE SCHEMA IF NOT EXISTS rep;
CREATE SCHEMA IF NOT EXISTS aud;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS stg;

-- -------------------------------------------------------------------------------------
-- 1. CATÁLOGOS (códigos cortos smallint para que los registros sean angostos)
-- -------------------------------------------------------------------------------------
CREATE TABLE cat.red (id smallint PRIMARY KEY, codigo text UNIQUE NOT NULL, nombre text NOT NULL, abreviatura text NOT NULL);
CREATE TABLE cat.origen (id smallint PRIMARY KEY, codigo text UNIQUE NOT NULL, nombre text NOT NULL);
CREATE TABLE cat.estado_paso (id smallint PRIMARY KEY, codigo text UNIQUE NOT NULL, nombre text NOT NULL);
CREATE TABLE cat.paso (id smallint PRIMARY KEY, codigo text UNIQUE NOT NULL, nombre text NOT NULL);
CREATE TABLE cat.tipo_proceso (codigo text PRIMARY KEY, nombre text NOT NULL, cola text NOT NULL, sla_100k_s int NOT NULL, sla_1m_s int NOT NULL);
CREATE TABLE cat.estado_proceso (codigo text PRIMARY KEY, nombre text NOT NULL, terminal boolean NOT NULL);
CREATE TABLE cat.modulo (codigo text PRIMARY KEY, nombre text NOT NULL);
CREATE TABLE cat.accion (codigo text PRIMARY KEY, nombre text NOT NULL);

-- -------------------------------------------------------------------------------------
-- 2. SEGURIDAD (JWT: los permisos viajan en el access token; la sesión guarda el refresh)
-- -------------------------------------------------------------------------------------
CREATE TABLE seg.rol (
  id            int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre        text NOT NULL,
  descripcion   text,
  ver_todas     boolean NOT NULL DEFAULT false,          -- ignora grupos: ve todas las cuentas
  estado_id     smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en     timestamptz NOT NULL DEFAULT now(), creado_por int,
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int
);
CREATE UNIQUE INDEX ux_rol_nombre ON seg.rol (lower(nombre)) WHERE estado_id <> -1;

CREATE TABLE seg.rol_permiso (
  rol_id int NOT NULL REFERENCES seg.rol(id),
  modulo text NOT NULL REFERENCES cat.modulo(codigo),
  accion text NOT NULL REFERENCES cat.accion(codigo),
  PRIMARY KEY (rol_id, modulo, accion)
);

CREATE TABLE seg.usuario (
  id             int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre         text NOT NULL,
  email          text NOT NULL,
  telefono       text,
  password_hash  text,                                   -- argon2id; null si solo SSO
  rol_id         int NOT NULL REFERENCES seg.rol(id),
  ultimo_acceso  timestamptz,
  version_token  int NOT NULL DEFAULT 1,                 -- subirlo invalida todos los JWT del usuario
  intentos_fallidos smallint NOT NULL DEFAULT 0,          -- bloqueo progresivo de login (antes en Redis)
  bloqueado_hasta timestamptz,
  estado_id      smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en      timestamptz NOT NULL DEFAULT now(), creado_por int,
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int
);
CREATE UNIQUE INDEX ux_usuario_email ON seg.usuario (lower(email)) WHERE estado_id <> -1;

CREATE TABLE seg.sesion (                                 -- refresh tokens rotativos
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  familia_id    uuid NOT NULL,                            -- detecta reutilización de refresh robado
  usuario_id    int NOT NULL REFERENCES seg.usuario(id),
  refresh_hash  bytea NOT NULL,                           -- sha256 del refresh (nunca el token)
  creado_en     timestamptz NOT NULL DEFAULT now(),
  expira_en     timestamptz NOT NULL,
  revocado_en   timestamptz,
  ip            inet, user_agent text
);
CREATE INDEX ix_sesion_usuario ON seg.sesion (usuario_id) WHERE revocado_en IS NULL;

CREATE TABLE seg.grupo (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre text NOT NULL, descripcion text,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int,
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int
);
CREATE TABLE seg.grupo_usuario (grupo_id int REFERENCES seg.grupo(id), usuario_id int REFERENCES seg.usuario(id), PRIMARY KEY (grupo_id, usuario_id));

CREATE TABLE seg.usuario_tarjeta (                        -- configuración de tarjetas del informe
  usuario_id int PRIMARY KEY REFERENCES seg.usuario(id),
  tarjetas jsonb NOT NULL,                                -- [{"k":"menciones","on":true}, ...]
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------------------------
-- 3. CONFIGURACIÓN
-- -------------------------------------------------------------------------------------
CREATE TABLE cfg.cliente (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre text NOT NULL, rfc text, sector text, contacto text,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE UNIQUE INDEX ux_cliente_nombre ON cfg.cliente (lower(nombre)) WHERE estado_id <> -1;

CREATE TABLE cfg.cuenta (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cliente_id int NOT NULL REFERENCES cfg.cliente(id),
  nombre text NOT NULL,
  actor_principal text,                                   -- p. ej. «el gobernador Salazar»
  entidad text,                                           -- entidad federativa
  taxonomia text,                                         -- gobierno / comparativo / electoral
  prompt_clusters text NOT NULL,
  prompt_temas text NOT NULL,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE UNIQUE INDEX ux_cuenta_nombre ON cfg.cuenta (lower(nombre)) WHERE estado_id <> -1;
CREATE TABLE seg.grupo_cuenta (grupo_id int REFERENCES seg.grupo(id), cuenta_id int REFERENCES cfg.cuenta(id), PRIMARY KEY (grupo_id, cuenta_id));
CREATE INDEX ix_grupo_cuenta_cuenta ON seg.grupo_cuenta (cuenta_id);

CREATE TABLE cfg.prompt (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tipo text NOT NULL CHECK (tipo IN ('cluster','temas','relevancia','sentimiento','etiqueta_cluster')),
  red_id smallint REFERENCES cat.red(id),                 -- null = general
  nombre text NOT NULL,
  por_defecto boolean NOT NULL DEFAULT false,
  version_actual int NOT NULL DEFAULT 1,
  contenido text NOT NULL,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE UNIQUE INDEX ux_prompt_defecto ON cfg.prompt (tipo, coalesce(red_id,0)) WHERE por_defecto AND estado_id = 1;
CREATE TABLE cfg.prompt_version (
  prompt_id int REFERENCES cfg.prompt(id), version int, contenido text NOT NULL,
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  PRIMARY KEY (prompt_id, version)
);

CREATE TABLE cfg.cruce (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre text NOT NULL, categoria text, color char(7) NOT NULL DEFAULT '#1293F8',
  modo text NOT NULL DEFAULT 'texto_hashtags' CHECK (modo IN ('texto_hashtags','hashtags','texto')),
  incluye_autor boolean NOT NULL DEFAULT true, descripcion text,
  version int NOT NULL DEFAULT 1,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE TABLE cfg.cruce_item (
  cruce_id int REFERENCES cfg.cruce(id) ON DELETE CASCADE,
  item text NOT NULL CHECK (item ~ '^[@#][[:alnum:]_.]+$'),
  PRIMARY KEY (cruce_id, item)
);

CREATE TABLE cfg.regex (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre text NOT NULL,
  condicion text NOT NULL,                                -- dialecto RE2 (seguro, tiempo lineal)
  flags text NOT NULL DEFAULT 'i',
  texto_prueba text NOT NULL,                             -- obligatorio: la regex debe cumplir aquí
  descripcion text,
  version int NOT NULL DEFAULT 1,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE TABLE cfg.regex_version (
  regex_id int REFERENCES cfg.regex(id), version int, condicion text NOT NULL, flags text NOT NULL,
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  PRIMARY KEY (regex_id, version)
);

CREATE TABLE cfg.pais (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nombre text NOT NULL, codigo char(2) NOT NULL CHECK (codigo ~ '^[A-Z]{2}$'),
  idioma text NOT NULL DEFAULT 'es-419',                  -- hl de Google News; ceid = codigo:idioma
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE UNIQUE INDEX ux_pais_codigo ON cfg.pais (codigo) WHERE estado_id <> -1;

CREATE TABLE cfg.actor_scraping (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  red_id smallint NOT NULL REFERENCES cat.red(id),
  uso text NOT NULL DEFAULT 'busqueda' CHECK (uso IN ('busqueda','metricas','perfil')),
  nombre text NOT NULL, actor text NOT NULL,              -- usuario/actor en Apify
  max_registros int NOT NULL DEFAULT 1000,
  max_urls_por_corrida int NOT NULL DEFAULT 1000,         -- para actualización de métricas
  memoria_mb int NOT NULL DEFAULT 4096,                   -- memoria por corrida (consume el plan Apify)
  nota text,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);

CREATE TABLE cfg.formato_archivo (
  id text PRIMARY KEY,                                    -- 'talkwalker_simple', 'meltwater', 'plantilla_syntra'...
  nombre text NOT NULL, descripcion text,
  extensiones text[] NOT NULL,
  delimitador char(1) DEFAULT ',', codificacion text NOT NULL DEFAULT 'utf-8',
  formato_fecha text NOT NULL,                            -- explícito: evita que dd/mm/yy se lea como yy/mm/dd
  zona_horaria text NOT NULL DEFAULT 'UTC',
  fecha_min date NOT NULL DEFAULT '2015-01-01',           -- validación de plausibilidad
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE TABLE cfg.formato_columna (                        -- mapeo columna origen → campo de dat.registro
  formato_id text REFERENCES cfg.formato_archivo(id) ON DELETE CASCADE,
  campo_destino text NOT NULL,                            -- url, fecha_publicacion, texto, likes...
  columnas_origen text[] NOT NULL,                        -- coalesce/suma en orden
  transformacion text NOT NULL DEFAULT 'directo',         -- directo | coalesce | suma | red_desde_source_type | fecha | json | lista
  requerido boolean NOT NULL DEFAULT false,
  PRIMARY KEY (formato_id, campo_destino)
);

-- Proveedores, modelos y llaves LLM (las llaves NUNCA en texto plano en BD: solo referencia al gestor de secretos)
CREATE TABLE cfg.llm_proveedor (
  id smallint PRIMARY KEY, codigo text UNIQUE NOT NULL, nombre text NOT NULL,
  prioridad smallint NOT NULL,                            -- 1 principal · 2 respaldo
  base_url text, estado_id smallint NOT NULL DEFAULT 1
);
CREATE TABLE cfg.llm_modelo (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proveedor_id smallint NOT NULL REFERENCES cfg.llm_proveedor(id),
  nombre text NOT NULL,
  uso text NOT NULL CHECK (uso IN ('clasificacion','embedding','etiquetado','transcripcion')),
  precio_in_1m numeric(10,4), precio_cache_1m numeric(10,4), precio_out_1m numeric(10,4), precio_minuto numeric(10,4),
  registros_por_llamado smallint NOT NULL DEFAULT 25,     -- tamaño del lote por llamado (1 = unitario)
  dimensiones smallint,                                   -- embeddings
  prioridad smallint NOT NULL DEFAULT 1,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), actualizado_en timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cfg.llm_llave (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proveedor_id smallint NOT NULL REFERENCES cfg.llm_proveedor(id),
  alias text NOT NULL,
  secreto_ref text NOT NULL,                              -- ruta en el gestor de secretos (K8s Secret / Vault)
  ultimos4 char(4) NOT NULL,
  organizacion text, proyecto text,                       -- el límite real es por organización/proyecto, no por llave
  rpm_limite int NOT NULL, tpm_limite bigint NOT NULL,
  prioridad smallint NOT NULL DEFAULT 1,
  circuito text NOT NULL DEFAULT 'cerrado' CHECK (circuito IN ('cerrado','abierto','semiabierto')),
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);

CREATE TABLE ops.politica_reintento (                     -- reintentos configurables por operación
  operacion text PRIMARY KEY,                             -- apify.run, apify.dataset, meltwater.get, llm.clasificar, llm.embedding, s3.get, gnews.get, transcripcion
  max_intentos smallint NOT NULL,
  backoff_base_ms int NOT NULL, backoff_max_ms int NOT NULL,
  timeout_ms int NOT NULL,
  usar_respaldo boolean NOT NULL DEFAULT false,           -- tras agotar intentos, pasa al proveedor de respaldo
  circuito_umbral smallint NOT NULL DEFAULT 20,           -- fallos consecutivos para abrir el circuito
  notas text,
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.parametro (                              -- parámetros de operación editables sin desplegar
  clave text PRIMARY KEY,                                 -- 'archivo.meses_principal', 'cola.llm.concurrencia'...
  valor jsonb NOT NULL, descripcion text,
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int
);

-- Procesos worker vivos (reemplaza el registro que antes vivía en Redis). Cada worker hace «latido»
-- cada 15 s. El limitador de LLM reparte la cuota de cada llave entre los workers vivos de q.llm.
CREATE TABLE ops.worker (
  id text PRIMARY KEY,                                    -- 'proc-01:q.llm:2'
  servidor text NOT NULL, colas text[] NOT NULL, pid int,
  version text, iniciado_en timestamptz NOT NULL DEFAULT now(), latido timestamptz NOT NULL DEFAULT now(),
  tareas_en_curso int NOT NULL DEFAULT 0, detalle jsonb
);

-- Control del archivado mensual: una fila por hoja (medición × mes) movida a la BD histórica.
CREATE TABLE ops.archivado (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proceso_id bigint,                                      -- proceso 'archivado' del mes
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL,
  estado text NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente','copiando','copiado','desprendiendo','archivado','omitido','error','rehidratado')),
  filas jsonb NOT NULL DEFAULT '{}',                      -- {"registro":[origen,destino], "registro_estado":[...], ...}
  verificacion jsonb,                                     -- conteos + suma de control por tabla
  intentos smallint NOT NULL DEFAULT 0,
  iniciado_en timestamptz, finalizado_en timestamptz, error text,
  UNIQUE (cuenta_id, medicion_id, periodo)
);

-- -------------------------------------------------------------------------------------
-- 4. MEDICIONES Y SU CONFIGURACIÓN
-- -------------------------------------------------------------------------------------
CREATE TABLE med.medicion (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cuenta_id int NOT NULL REFERENCES cfg.cuenta(id),
  nombre text NOT NULL,
  coyuntura boolean NOT NULL DEFAULT false,
  num_clusters smallint NOT NULL DEFAULT 15 CHECK (num_clusters BETWEEN 2 AND 30),
  num_subclusters smallint NOT NULL DEFAULT 3 CHECK (num_subclusters BETWEEN 1 AND 10),
  tipo_analisis text NOT NULL DEFAULT 'temas_sentimiento' CHECK (tipo_analisis IN ('temas_sentimiento','sentimiento_medios')),
  instrucciones text,
  ventana_desde timestamptz,                              -- null = toda la historia
  precluster_activo boolean NOT NULL DEFAULT false,
  precluster_separar_temas boolean NOT NULL DEFAULT false,
  precluster_aplicar_bots boolean NOT NULL DEFAULT false,
  x_num_menciones int NOT NULL DEFAULT 0,                 -- 0 = calculado desde los datos
  x_num_cuentas int NOT NULL DEFAULT 50,
  x_confirmado_en timestamptz, x_confirmado_por int REFERENCES seg.usuario(id),
  auto_publicar boolean NOT NULL DEFAULT false,           -- publicar tablero tras análisis automático
  transcripcion text NOT NULL DEFAULT 'relevantes'        -- cuándo transcribir videos/audios
    CHECK (transcripcion IN ('siempre','relevantes','bajo_demanda','nunca')),
  guardar_video boolean NOT NULL DEFAULT false,            -- false: se guarda solo el audio (.opus) en S3
  tablero_publicado_en timestamptz, tablero_registros int NOT NULL DEFAULT 0,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id)
);
CREATE INDEX ix_medicion_cuenta ON med.medicion (cuenta_id) WHERE estado_id <> -1;

CREATE TABLE med.medicion_fuente (                        -- archivo · meltwater · manual (scrapers van aparte)
  medicion_id int REFERENCES med.medicion(id),
  origen_id smallint REFERENCES cat.origen(id),
  activo boolean NOT NULL DEFAULT true,
  config jsonb NOT NULL DEFAULT '{}',                     -- p. ej. {"busqueda_id":"MW-2214587"}
  post_incorporar boolean NOT NULL DEFAULT true,          -- «Al cargar»
  post_relevancia boolean NOT NULL DEFAULT false,
  post_sentimiento boolean NOT NULL DEFAULT true,
  post_clusters boolean NOT NULL DEFAULT false,
  post_bots boolean NOT NULL DEFAULT false,
  PRIMARY KEY (medicion_id, origen_id)
);
CREATE TABLE med.programacion_meltwater (
  medicion_id int PRIMARY KEY REFERENCES med.medicion(id),
  activa boolean NOT NULL DEFAULT true,
  inicio timestamptz NOT NULL, fin timestamptz NOT NULL CHECK (fin > inicio),
  frecuencia_min int NOT NULL CHECK (frecuencia_min >= 15),
  proxima_ejecucion timestamptz
);
CREATE TABLE med.medicion_prompt (
  medicion_id int REFERENCES med.medicion(id),
  tipo text NOT NULL CHECK (tipo IN ('cluster','temas','relevancia','sentimiento')),
  red_id smallint NOT NULL DEFAULT 0,                     -- 0 = general; >0 = ajuste por red
  origen text NOT NULL CHECK (origen IN ('defecto','cuenta','propio')),
  prompt_id int REFERENCES cfg.prompt(id), prompt_version int,
  contenido text NOT NULL,                                -- copia congelada usada en los procesos
  PRIMARY KEY (medicion_id, tipo, red_id)
);
CREATE TABLE med.medicion_cruce (medicion_id int REFERENCES med.medicion(id), cruce_id int REFERENCES cfg.cruce(id), PRIMARY KEY (medicion_id, cruce_id));
CREATE TABLE med.medicion_regex (                         -- el orden define el preclustering
  medicion_id int REFERENCES med.medicion(id), regex_id int REFERENCES cfg.regex(id),
  orden smallint NOT NULL,
  PRIMARY KEY (medicion_id, regex_id), UNIQUE (medicion_id, orden)
);
CREATE TABLE med.medicion_bots (
  medicion_id int PRIMARY KEY REFERENCES med.medicion(id),
  activo boolean NOT NULL DEFAULT true,
  identificar boolean NOT NULL DEFAULT true,
  rt_negativos boolean NOT NULL DEFAULT true,
  neg_pos boolean NOT NULL DEFAULT true,
  criterios_min smallint NOT NULL DEFAULT 3,
  criterios text[] NOT NULL DEFAULT '{antiguedad,ratio,frecuencia,duplicado}',
  criterio_texto text
);

CREATE TABLE med.scraper (                                -- N procesos de scraping por medición
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  medicion_id int NOT NULL REFERENCES med.medicion(id),
  nombre text NOT NULL,
  ejecucion_auto boolean NOT NULL DEFAULT true,           -- false = solo manual
  inicio timestamptz NOT NULL, fin timestamptz NOT NULL CHECK (fin > inicio),
  frecuencia_min int CHECK (frecuencia_min IS NULL OR frecuencia_min >= 15),
  proxima_ejecucion timestamptz,
  actualizar_interacciones boolean NOT NULL DEFAULT true,
  transcribir boolean NOT NULL DEFAULT true,
  mismas_palabras boolean NOT NULL DEFAULT true,
  gn_activo boolean NOT NULL DEFAULT false,
  gn_registros smallint NOT NULL DEFAULT 50 CHECK (gn_registros BETWEEN 1 AND 100),
  gn_periodo text NOT NULL DEFAULT 'ultimo_dia' CHECK (gn_periodo IN ('ultima_hora','ultimo_dia','ultima_semana','rango')),
  post_incorporar boolean NOT NULL DEFAULT false,
  post_relevancia boolean NOT NULL DEFAULT true,
  post_sentimiento boolean NOT NULL DEFAULT true,
  post_clusters boolean NOT NULL DEFAULT false,
  post_bots boolean NOT NULL DEFAULT false,
  prompt_rel_origen text NOT NULL DEFAULT 'medicion' CHECK (prompt_rel_origen IN ('medicion','defecto','propio')),
  prompt_rel_id int REFERENCES cfg.prompt(id), prompt_rel_contenido text,
  prompt_sen_origen text NOT NULL DEFAULT 'medicion' CHECK (prompt_sen_origen IN ('medicion','defecto','propio')),
  prompt_sen_id int REFERENCES cfg.prompt(id), prompt_sen_contenido text,
  estado_id smallint NOT NULL DEFAULT 1 CHECK (estado_id IN (-1,0,1)),
  creado_en timestamptz NOT NULL DEFAULT now(), creado_por int REFERENCES seg.usuario(id),
  actualizado_en timestamptz NOT NULL DEFAULT now(), actualizado_por int REFERENCES seg.usuario(id),
  CHECK (NOT ejecucion_auto OR frecuencia_min IS NOT NULL)
);
CREATE INDEX ix_scraper_agenda ON med.scraper (proxima_ejecucion) WHERE estado_id = 1 AND ejecucion_auto;
CREATE TABLE med.scraper_red (
  scraper_id int REFERENCES med.scraper(id) ON DELETE CASCADE,
  red_id smallint REFERENCES cat.red(id),
  activo boolean NOT NULL DEFAULT true,
  registros int NOT NULL CHECK (registros > 0),
  actor_id int REFERENCES cfg.actor_scraping(id),         -- null = actor vigente de la red
  PRIMARY KEY (scraper_id, red_id)
);
CREATE TABLE med.scraper_pais (scraper_id int REFERENCES med.scraper(id) ON DELETE CASCADE, pais_id int REFERENCES cfg.pais(id), PRIMARY KEY (scraper_id, pais_id));
CREATE TABLE med.scraper_palabra (
  scraper_id int REFERENCES med.scraper(id) ON DELETE CASCADE,
  fuente text NOT NULL,                                   -- código de red o 'googlenews'
  palabra text NOT NULL,
  PRIMARY KEY (scraper_id, fuente, palabra)
);

CREATE TABLE med.archivo (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  medicion_id int NOT NULL REFERENCES med.medicion(id),
  nombre text NOT NULL, formato_id text NOT NULL REFERENCES cfg.formato_archivo(id),
  s3_bucket text NOT NULL, s3_key text NOT NULL, tamano_bytes bigint, sha256 bytea,
  filas_leidas int, filas_validas int, filas_rechazadas int,
  estado text NOT NULL DEFAULT 'subido' CHECK (estado IN ('subido','procesando','procesado','error')),
  error text,
  subido_por int REFERENCES seg.usuario(id), subido_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_archivo_medicion ON med.archivo (medicion_id, subido_en DESC);
CREATE UNIQUE INDEX ux_archivo_hash ON med.archivo (medicion_id, sha256) WHERE estado <> 'error';  -- mismo archivo dos veces

-- -------------------------------------------------------------------------------------
-- 5. PROCESOS (cabecera del trabajo asíncrono, sub-tareas paralelas y log)
-- -------------------------------------------------------------------------------------
CREATE TABLE prc.proceso (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  medicion_id int REFERENCES med.medicion(id),
  cuenta_id int REFERENCES cfg.cuenta(id),
  tipo text NOT NULL REFERENCES cat.tipo_proceso(codigo),
  modo text NOT NULL CHECK (modo IN ('manual','automatico')),
  estado text NOT NULL DEFAULT 'en_cola' REFERENCES cat.estado_proceso(codigo),
  prioridad smallint NOT NULL DEFAULT 5,
  padre_id bigint REFERENCES prc.proceso(id),             -- encadenamiento (carga → transcripción → análisis → publicación)
  scraper_id int REFERENCES med.scraper(id),
  opciones jsonb NOT NULL DEFAULT '{}',                   -- al incorporar, métricas sí/no, tareas, filtros, alcance
  total int NOT NULL DEFAULT 0, procesados int NOT NULL DEFAULT 0, ok int NOT NULL DEFAULT 0, errores int NOT NULL DEFAULT 0,
  progreso smallint NOT NULL DEFAULT 0 CHECK (progreso BETWEEN 0 AND 100),
  stats jsonb NOT NULL DEFAULT '{}',
  sla_ms int,                                             -- presupuesto calculado al crear (según volumen)
  creado_en timestamptz NOT NULL DEFAULT now(), iniciado_en timestamptz, finalizado_en timestamptz,
  duracion_ms int GENERATED ALWAYS AS ((extract(epoch FROM (finalizado_en - iniciado_en)) * 1000)::int) STORED,
  creado_por int REFERENCES seg.usuario(id),              -- null = sistema
  idempotencia text,                                      -- header Idempotency-Key: evita dobles clics
  detalle text
);
CREATE INDEX ix_proceso_medicion ON prc.proceso (medicion_id, creado_en DESC);
CREATE INDEX ix_proceso_activo ON prc.proceso (estado, creado_en) WHERE estado IN ('en_cola','en_ejecucion');
CREATE UNIQUE INDEX ux_proceso_idem ON prc.proceso (idempotencia) WHERE idempotencia IS NOT NULL;

CREATE TABLE prc.proceso_tarea (                          -- unidad paralela: red · país · archivo · chunk de registros
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proceso_id bigint NOT NULL REFERENCES prc.proceso(id) ON DELETE CASCADE,
  clave text NOT NULL,                                    -- 'red:tiktok' · 'pais:MX' · 'archivo:12' · 'chunk:000123'
  tipo text NOT NULL,
  estado text NOT NULL DEFAULT 'en_cola' REFERENCES cat.estado_proceso(codigo),
  intentos smallint NOT NULL DEFAULT 0,
  rango_desde bigint, rango_hasta bigint,                 -- chunk por registro_id (keyset)
  objetivo int, ok int NOT NULL DEFAULT 0, errores int NOT NULL DEFAULT 0,
  ref_externa text,                                       -- run id de Apify, dataset id, request id...
  iniciado_en timestamptz, finalizado_en timestamptz,
  error_codigo text, error_mensaje text, worker text,
  -- Cola (sin Redis): la tarea ES el trabajo encolado
  cola text NOT NULL DEFAULT 'q.datos',                   -- q.ingesta · q.apify · q.llm · q.analisis · q.regex · q.media · q.transcripcion · q.datos · q.reportes · q.mantenimiento
  prioridad smallint NOT NULL DEFAULT 5,                  -- 1 = urgente (acción de usuario) · 9 = batch
  disponible_en timestamptz NOT NULL DEFAULT now(),       -- backoff de reintento: no se toma antes de esta hora
  latido timestamptz,                                     -- el worker lo renueva; si se vence, la tarea vuelve a la cola
  payload jsonb NOT NULL DEFAULT '{}',
  UNIQUE (proceso_id, clave)
);
CREATE INDEX ix_tarea_pendiente ON prc.proceso_tarea (proceso_id) WHERE estado IN ('en_cola','en_ejecucion','error');
CREATE INDEX ix_tarea_cola ON prc.proceso_tarea (cola, prioridad, disponible_en, id) WHERE estado = 'en_cola';
CREATE INDEX ix_tarea_latido ON prc.proceso_tarea (latido) WHERE estado = 'en_ejecucion';

-- Despierta a los workers de la cola sin esperar al sondeo (NOTIFY por sentencia, no por fila)
CREATE OR REPLACE FUNCTION prc.fn_notificar_cola() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE c text;
BEGIN
  FOR c IN SELECT DISTINCT cola FROM nuevas WHERE estado = 'en_cola' LOOP
    PERFORM pg_notify('cola', c);
  END LOOP;
  RETURN NULL;
END $fn$;
CREATE TRIGGER tg_tarea_notificar AFTER INSERT ON prc.proceso_tarea
  REFERENCING NEW TABLE AS nuevas FOR EACH STATEMENT EXECUTE FUNCTION prc.fn_notificar_cola();

CREATE TABLE prc.proceso_log (
  proceso_id bigint NOT NULL, creado_en timestamptz NOT NULL DEFAULT now(),
  nivel char(1) NOT NULL CHECK (nivel IN ('i','o','w','e')), mensaje text NOT NULL, datos jsonb
) PARTITION BY RANGE (creado_en);
CREATE INDEX ix_proceso_log ON prc.proceso_log (proceso_id, creado_en);

-- Lote (ejecución) de datos cargados: un lote por tarea de carga (red, país, archivo, captura manual)
CREATE TABLE dat.ejecucion (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cuenta_id int NOT NULL REFERENCES cfg.cuenta(id),
  medicion_id int NOT NULL REFERENCES med.medicion(id),
  proceso_id bigint REFERENCES prc.proceso(id), tarea_id bigint REFERENCES prc.proceso_tarea(id),
  origen_id smallint NOT NULL REFERENCES cat.origen(id),
  red_id smallint REFERENCES cat.red(id),
  scraper_id int REFERENCES med.scraper(id), archivo_id bigint REFERENCES med.archivo(id),
  detalle text,
  post jsonb NOT NULL,                                    -- foto de «Al incorporar» usada en esta carga
  n_leidos int NOT NULL DEFAULT 0, n_nuevos int NOT NULL DEFAULT 0, n_duplicados int NOT NULL DEFAULT 0, n_rechazados int NOT NULL DEFAULT 0,
  fecha_min timestamptz, fecha_max timestamptz,
  s3_raw_key text,                                        -- respuesta cruda (JSONL.gz) para trazabilidad/reproceso
  creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ejecucion_medicion ON dat.ejecucion (medicion_id, creado_en DESC);

-- -------------------------------------------------------------------------------------
-- 6. DATOS (registros) · LIST(cuenta_id) → LIST(medicion_id) → LIST(periodo)
--    Todas las tablas dat.registro_* llevan (cuenta_id, medicion_id, periodo, registro_id): así una
--    hoja medición×mes se mueve completa (con su estado, IA, regex, eventos…) al histórico.
-- -------------------------------------------------------------------------------------
CREATE SEQUENCE dat.registro_id_seq AS bigint CACHE 1000;   -- cache: menos contención en cargas paralelas

-- periodo AAAAMM de una fecha, en hora de Bogotá (la misma regla en el cargador Python)
CREATE OR REPLACE FUNCTION ops.fn_periodo(t timestamptz) RETURNS int
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT (to_char(t AT TIME ZONE 'America/Bogota', 'YYYYMM'))::int $$;

-- 6.0 HUELLA: deduplicación por URL dentro de la medición, para datos vivos Y archivados.
--     Queda siempre en la principal (≈ 60 bytes por registro). Sin esto, al archivar un mes la
--     misma URL podría volver a cargarse como nueva.
CREATE TABLE dat.registro_huella (
  cuenta_id int NOT NULL, medicion_id int NOT NULL,
  url_hash bytea NOT NULL,
  registro_id bigint NOT NULL, periodo int NOT NULL,
  ubicacion char(1) NOT NULL DEFAULT 'p' CHECK (ubicacion IN ('p','h')),   -- p principal · h histórico
  PRIMARY KEY (cuenta_id, medicion_id, url_hash)
) PARTITION BY LIST (cuenta_id);
-- 6.1 CONTENIDO (casi inmutable: se inserta en la carga; solo cambia si un analista edita el texto)
CREATE TABLE dat.registro (
  cuenta_id        int      NOT NULL,
  medicion_id      int      NOT NULL,
  periodo          int      NOT NULL,                     -- ops.fn_periodo(fecha_publicacion)
  registro_id      bigint   NOT NULL DEFAULT nextval('dat.registro_id_seq'),
  ejecucion_id     bigint   NOT NULL,
  origen_id        smallint NOT NULL,
  red_id           smallint NOT NULL,
  scraper_id       int,
  url              text,
  url_hash         bytea    NOT NULL,                     -- md5(url normalizada) o md5(autor|fecha|texto) si no hay url
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
  extra            jsonb,                                 -- columnas del formato no normalizadas (solo no vacías)
  sentimiento_fuente smallint,                            -- el que trae el proveedor (p. ej. Talkwalker -5..5)
  editado          boolean NOT NULL DEFAULT false,
  comentario       text,
  creado_en        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo),
  CHECK (periodo = ops.fn_periodo(fecha_publicacion))
  -- La deduplicación por URL vive en dat.registro_huella (un UNIQUE aquí tendría que incluir periodo).
) PARTITION BY LIST (cuenta_id);
CREATE INDEX ix_reg_fecha ON dat.registro (medicion_id, fecha_publicacion DESC);
CREATE INDEX ix_reg_autor ON dat.registro (medicion_id, autor_usuario);
CREATE INDEX ix_reg_ejec  ON dat.registro (ejecucion_id);
-- Sin índice trigram en el camino caliente: triplica el costo de carga (medido: 82 s vs 27 s por 1M filas).
-- «Texto contiene» se resuelve con escaneo paralelo de la hoja (~2 s por 1M en 2 vCPU). Si algún día se
-- requiere búsqueda global, se agrega un índice de búsqueda fuera de la base (OpenSearch/Meilisearch).

-- 6.2 ESTADO (mutable y angosto, 1:1 con registro): aquí escriben todos los procesos masivos.
--     Separarlo del contenido hace que actualizar 1M filas tome ~5 s en lugar de ~87 s (medido).
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
  precluster_regex_id int,                                -- primera regex que coincide (null = sin match)
  es_bot           boolean,
  publicado        boolean  NOT NULL DEFAULT false,
  publicado_en     timestamptz,
  -- métricas vigentes (historial en registro_metrica_hist)
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
) PARTITION BY LIST (cuenta_id);
-- Único índice adicional: la cola de fiscalización (pequeño y parcial). Las columnas st_* no se indexan.
CREATE INDEX ix_est_fisc ON dat.registro_estado (medicion_id, registro_id) WHERE NOT incorporado AND relevancia = 0 AND estado_id <> -1;

-- 6.3 Resultado de cada evaluación IA (append-only): razón mostrada en la UI y trazabilidad de la decisión
CREATE TABLE dat.registro_ia (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  paso smallint NOT NULL,                                 -- relevancia · sentimiento
  evaluado_en timestamptz NOT NULL DEFAULT now(),
  valor smallint NOT NULL, pct smallint, razon text,
  proceso_id bigint, llamado_id bigint, modelo_id int, prompt_hash bytea,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, paso, evaluado_en)
) PARTITION BY LIST (cuenta_id);

CREATE TABLE dat.registro_transcripcion (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  texto text NOT NULL, idioma text, duracion_s int, proveedor_id smallint, modelo_id int,
  segmentos jsonb,                                        -- [{"i":0.0,"f":4.2,"t":"…"}] para subtítulos en el visor
  servidor text, segundos_proceso numeric(8,2),           -- qué GPU y cuánto tardó (capacidad)
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo),
  FOREIGN KEY (cuenta_id, medicion_id, registro_id, periodo) REFERENCES dat.registro ON DELETE CASCADE
) PARTITION BY LIST (cuenta_id);

CREATE TABLE dat.registro_media (                         -- videos/imágenes descargados a S3
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, orden smallint NOT NULL,
  tipo text NOT NULL CHECK (tipo IN ('video','imagen','audio')),
  url_origen text NOT NULL,
  s3_key text,                                            -- original (solo si med.medicion.guardar_video o es imagen)
  s3_key_audio text,                                      -- audio .opus 16 kHz mono (~0,25 MB/min): lo que usa Whisper
  bytes bigint, bytes_audio bigint, duracion_s int,
  estado smallint NOT NULL DEFAULT 0,                     -- cat.estado_paso
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, orden),
  FOREIGN KEY (cuenta_id, medicion_id, registro_id, periodo) REFERENCES dat.registro ON DELETE CASCADE
) PARTITION BY LIST (cuenta_id);

CREATE TABLE dat.registro_regex (                         -- asociación registro ↔ regex (upsert con desactivación)
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, regex_id int NOT NULL,
  regex_version int NOT NULL, activo boolean NOT NULL DEFAULT true,
  coincidencias smallint NOT NULL DEFAULT 1,
  creado_en timestamptz NOT NULL DEFAULT now(), actualizado_en timestamptz NOT NULL DEFAULT now(), proceso_id bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, regex_id)
  -- Sin FOREIGN KEY a propósito: la verificación fila a fila hacía el upsert de 1M filas 11× más lento (186 s vs 16 s).
  -- La integridad la garantiza el proceso (los registro_id salen de la misma hoja) y el borrado es por partición.
) PARTITION BY LIST (cuenta_id);
CREATE INDEX ix_regrx_regex ON dat.registro_regex (medicion_id, regex_id) WHERE activo;

CREATE TABLE dat.registro_cruce (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL, cruce_id int NOT NULL,
  items text[] NOT NULL, activo boolean NOT NULL DEFAULT true,
  actualizado_en timestamptz NOT NULL DEFAULT now(), proceso_id bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, cruce_id)   -- sin FK (ver registro_regex)
) PARTITION BY LIST (cuenta_id);
CREATE INDEX ix_regcr_cruce ON dat.registro_cruce (medicion_id, cruce_id) WHERE activo;

CREATE TABLE dat.registro_metrica_hist (                  -- cada actualización de métricas deja un punto
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  capturado_en timestamptz NOT NULL, proceso_id bigint,
  likes bigint, comentarios bigint, compartidos bigint, reproducciones bigint,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, capturado_en)
) PARTITION BY LIST (cuenta_id);

CREATE SEQUENCE dat.evento_id_seq AS bigint CACHE 1000;
CREATE TABLE dat.registro_evento (                        -- detalle de errores, reintentos y cambios por registro y paso
  cuenta_id int NOT NULL, medicion_id int NOT NULL,
  periodo int NOT NULL,                                   -- del registro; filas rechazadas: periodo de la carga
  evento_id bigint NOT NULL DEFAULT nextval('dat.evento_id_seq'),
  registro_id bigint,                                     -- null = fila rechazada en la carga (aún no es registro)
  paso smallint NOT NULL,                                 -- cat.paso
  proceso_id bigint, tarea_id bigint,
  intento smallint NOT NULL DEFAULT 1,
  estado smallint NOT NULL,                               -- cat.estado_paso
  codigo_error text, mensaje text,
  detalle jsonb,                                          -- fila original, respuesta del proveedor, llamado_id...
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, evento_id, periodo)
) PARTITION BY LIST (cuenta_id);
CREATE INDEX ix_evento_registro ON dat.registro_evento (medicion_id, registro_id, creado_en DESC);
CREATE INDEX ix_evento_proceso  ON dat.registro_evento (proceso_id) WHERE estado = 3;

-- Atribución de tokens LLM a cada registro (en modo lote se prorratea el prompt compartido)
CREATE TABLE dat.llm_uso_registro (
  cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
  llamado_id bigint NOT NULL, llamado_en timestamptz NOT NULL,
  paso smallint NOT NULL,
  tokens_in int NOT NULL, tokens_out int NOT NULL,
  costo_usd numeric(12,8) NOT NULL DEFAULT 0,
  PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, llamado_id)
) PARTITION BY LIST (cuenta_id);

-- Embeddings (pgvector halfvec): se calculan una vez por registro y se reutilizan en cada re-clustering
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
    EXECUTE $q$
      CREATE TABLE dat.registro_embedding (
        cuenta_id int NOT NULL, medicion_id int NOT NULL, periodo int NOT NULL, registro_id bigint NOT NULL,
        modelo_id int NOT NULL, texto_hash bytea NOT NULL,      -- si el texto cambia se recalcula
        embedding halfvec(256) NOT NULL,
        creado_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (cuenta_id, medicion_id, registro_id, periodo, modelo_id)
      ) PARTITION BY LIST (cuenta_id)$q$;
  ELSE
    RAISE NOTICE 'pgvector no disponible en este servidor: se omite dat.registro_embedding (en producción: apt install postgresql-18-pgvector)';
  END IF;
END $$;

-- -------------------------------------------------------------------------------------
-- 7. LLM: cada llamado con sus tokens (serie de tiempo mensual) + consumo agregado
-- -------------------------------------------------------------------------------------
CREATE SEQUENCE prc.llamado_id_seq AS bigint CACHE 1000;
CREATE TABLE prc.llm_llamado (
  id            bigint NOT NULL DEFAULT nextval('prc.llamado_id_seq'),
  creado_en     timestamptz NOT NULL DEFAULT now(),
  proceso_id    bigint, tarea_id bigint,
  cuenta_id     int, medicion_id int,
  paso          smallint NOT NULL,                        -- relevancia · sentimiento · embedding · etiqueta_cluster · tema · transcripcion
  proveedor_id  smallint NOT NULL, modelo_id int NOT NULL, llave_id int NOT NULL,
  intento       smallint NOT NULL DEFAULT 1,
  es_respaldo   boolean NOT NULL DEFAULT false,           -- true si se usó el proveedor secundario
  registros_n   smallint NOT NULL DEFAULT 1,              -- registros incluidos en el llamado (lote)
  tokens_in     int NOT NULL DEFAULT 0, tokens_in_cache int NOT NULL DEFAULT 0, tokens_out int NOT NULL DEFAULT 0,
  tokens_total  int GENERATED ALWAYS AS (tokens_in + tokens_out) STORED,
  segundos_audio int,                                     -- transcripción
  costo_usd     numeric(12,6) NOT NULL DEFAULT 0,
  latencia_ms   int,
  http_status   smallint,
  estado        text NOT NULL CHECK (estado IN ('ok','error','reintento','respaldo')),
  error_codigo  text, error_mensaje text,
  request_id    text,                                     -- id del proveedor para soporte
  prompt_hash   bytea,                                    -- qué versión de prompt se usó
  PRIMARY KEY (creado_en, id)
) PARTITION BY RANGE (creado_en);
CREATE INDEX ix_llamado_proceso ON prc.llm_llamado (proceso_id);
CREATE INDEX ix_llamado_med ON prc.llm_llamado (medicion_id, creado_en);

CREATE TABLE prc.llm_consumo_dia (                        -- se alimenta al cerrar cada proceso (upsert)
  fecha date NOT NULL, cuenta_id int NOT NULL, medicion_id int NOT NULL, paso smallint NOT NULL,
  proveedor_id smallint NOT NULL, modelo_id int NOT NULL, llave_id int NOT NULL,
  llamados int NOT NULL, errores int NOT NULL, registros int NOT NULL,
  tokens_in bigint NOT NULL, tokens_out bigint NOT NULL, costo_usd numeric(14,6) NOT NULL,
  PRIMARY KEY (fecha, cuenta_id, medicion_id, paso, proveedor_id, modelo_id, llave_id)
);

-- -------------------------------------------------------------------------------------
-- 8. ANÁLISIS (corridas de clusters/temas versionadas)
-- -------------------------------------------------------------------------------------
CREATE TABLE ana.corrida (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  medicion_id int NOT NULL REFERENCES med.medicion(id),
  proceso_id bigint REFERENCES prc.proceso(id),
  modelo_embedding_id int REFERENCES cfg.llm_modelo(id),
  algoritmo text NOT NULL DEFAULT 'kmeans_jerarquico',
  k int NOT NULL, k_sub int NOT NULL,
  precluster boolean NOT NULL DEFAULT false,
  parametros jsonb NOT NULL DEFAULT '{}',
  registros int, vigente boolean NOT NULL DEFAULT false,
  creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_corrida_vigente ON ana.corrida (medicion_id) WHERE vigente;
CREATE TABLE ana.cluster (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  corrida_id int NOT NULL REFERENCES ana.corrida(id) ON DELETE CASCADE,
  padre_id int REFERENCES ana.cluster(id),                -- null = cluster; con padre = subcluster
  nivel smallint NOT NULL CHECK (nivel IN (1,2)),
  orden smallint NOT NULL,
  precluster_regex_id int REFERENCES cfg.regex(id),
  nombre text NOT NULL, descripcion text, registros int NOT NULL DEFAULT 0
);
CREATE TABLE ana.tema (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  corrida_id int NOT NULL REFERENCES ana.corrida(id) ON DELETE CASCADE,
  nombre text NOT NULL, resumen text, sentimiento_predominante smallint, riesgo text CHECK (riesgo IN ('bajo','medio','alto'))
);
CREATE TABLE ana.cluster_tema (cluster_id int REFERENCES ana.cluster(id) ON DELETE CASCADE, tema_id int REFERENCES ana.tema(id) ON DELETE CASCADE, PRIMARY KEY (cluster_id, tema_id));

-- -------------------------------------------------------------------------------------
-- 9. INFORMES: agregados que se recalculan al publicar el tablero (consultas en milisegundos)
-- -------------------------------------------------------------------------------------
CREATE TABLE rep.agg_dia (
  medicion_id int NOT NULL, fecha date NOT NULL, red_id smallint NOT NULL, origen_id smallint NOT NULL,
  sentimiento smallint NOT NULL, cluster_id int NOT NULL DEFAULT 0, tema_id int NOT NULL DEFAULT 0,
  precluster_regex_id int NOT NULL DEFAULT 0, es_bot boolean NOT NULL DEFAULT false,
  registros int NOT NULL, autores int NOT NULL, alcance bigint NOT NULL, interacciones bigint NOT NULL, reproducciones bigint NOT NULL,
  PRIMARY KEY (medicion_id, fecha, red_id, origen_id, sentimiento, cluster_id, tema_id, precluster_regex_id, es_bot)
);
CREATE TABLE rep.agg_cruce (
  medicion_id int NOT NULL, cruce_id int NOT NULL, item text NOT NULL, sentimiento smallint NOT NULL, registros int NOT NULL,
  PRIMARY KEY (medicion_id, cruce_id, item, sentimiento)
);
CREATE TABLE rep.agg_autor (
  medicion_id int NOT NULL, autor_usuario text NOT NULL, red_id smallint NOT NULL,
  registros int NOT NULL, alcance bigint NOT NULL, positivos int NOT NULL, neutrales int NOT NULL, negativos int NOT NULL, es_bot boolean NOT NULL,
  PRIMARY KEY (medicion_id, autor_usuario, red_id)
);
CREATE TABLE rep.exportacion (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  medicion_id int NOT NULL REFERENCES med.medicion(id), proceso_id bigint REFERENCES prc.proceso(id),
  formato text NOT NULL CHECK (formato IN ('xlsx','pptx','pdf','csv')),
  secciones text[] NOT NULL, filtros jsonb NOT NULL DEFAULT '{}',
  x_num_menciones int NOT NULL, x_num_cuentas int NOT NULL,   -- valores confirmados usados en este informe
  s3_key text, bytes bigint, creado_por int REFERENCES seg.usuario(id), creado_en timestamptz NOT NULL DEFAULT now(), expira_en timestamptz
);

-- -------------------------------------------------------------------------------------
-- 10. AUDITORÍA Y NOTIFICACIONES
-- -------------------------------------------------------------------------------------
CREATE TABLE aud.auditoria (
  id bigint GENERATED BY DEFAULT AS IDENTITY,
  fecha timestamptz NOT NULL DEFAULT now(),
  usuario_id int, modulo text NOT NULL, accion text NOT NULL,
  entidad_tipo text NOT NULL, entidad_id text, entidad_nombre text,
  antes jsonb, despues jsonb, detalle text,
  ip inet, user_agent text, request_id text,
  PRIMARY KEY (fecha, id)
) PARTITION BY RANGE (fecha);
CREATE INDEX ix_aud_entidad ON aud.auditoria (entidad_tipo, entidad_id, fecha DESC);
CREATE INDEX ix_aud_usuario ON aud.auditoria (usuario_id, fecha DESC);

CREATE TABLE aud.notificacion (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario_id int NOT NULL REFERENCES seg.usuario(id),
  titulo text NOT NULL, cuerpo text, enlace text,
  tipo text NOT NULL CHECK (tipo IN ('ok','warn','err','info')),
  proceso_id bigint, leida boolean NOT NULL DEFAULT false, creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_notif_usuario ON aud.notificacion (usuario_id, creado_en DESC) WHERE NOT leida;

-- -------------------------------------------------------------------------------------
-- 11. STAGING UNLOGGED (plantillas). Cada proceso crea su copia:
--     CREATE UNLOGGED TABLE stg.carga_p123 (LIKE stg.carga INCLUDING DEFAULTS); … COPY … ; DROP al terminar.
-- -------------------------------------------------------------------------------------
CREATE UNLOGGED TABLE stg.carga (
  fila int, url text, url_hash bytea, url_padre text, fecha_publicacion timestamptz, fecha_indexado timestamptz,
  red_id smallint, idioma text, tipo_contenido text, titulo text, texto text,
  autor_id_ext text, autor_usuario text, autor_nombre text, autor_seguidores int, pais char(2), region text, ciudad text,
  es_rt boolean, es_comentario boolean, media_urls text[], extra jsonb, sentimiento_fuente smallint,
  likes bigint, comentarios bigint, compartidos bigint, reproducciones bigint, alcance bigint
);
CREATE UNLOGGED TABLE stg.resultado (                     -- resultados de LLM / regex / métricas para UPDATE … FROM
  registro_id bigint NOT NULL, valor smallint, pct smallint, razon text,
  likes bigint, comentarios bigint, compartidos bigint, reproducciones bigint, error text
);
CREATE UNLOGGED TABLE stg.match_regex (registro_id bigint NOT NULL, regex_id int NOT NULL, coincidencias smallint NOT NULL);

-- -------------------------------------------------------------------------------------
-- 12. MANTENIMIENTO DE PARTICIONES Y COLA
--     Funciones propias: pg_partman no maneja bien el árbol cuenta → medición → mes.
-- -------------------------------------------------------------------------------------
-- Árbol de particiones de dat.*:
--   dat.registro                         raíz        PARTITION BY LIST (cuenta_id)
--   └ dat.registro_c6                    cuenta      PARTITION BY LIST (medicion_id)
--     └ dat.registro_c6_m4               medición    PARTITION BY LIST (periodo)
--       └ dat.registro_c6_m4_p202610     hoja        (datos de octubre 2026)
-- dat.registro_huella llega solo hasta medición (no se archiva).
--
-- Cada nivel se crea APARTE y luego se adjunta con ATTACH PARTITION: ATTACH toma un bloqueo
-- SHARE UPDATE EXCLUSIVE sobre el padre (no bloquea lecturas ni escrituras de otras mediciones),
-- mientras que CREATE TABLE … PARTITION OF tomaría ACCESS EXCLUSIVE sobre el padre.
-- Quien llama fija antes: SET lock_timeout = '5s' y reintenta si vence (nunca hace fila detrás de un bloqueo).

CREATE OR REPLACE FUNCTION ops.fn_tablas_dat() RETURNS SETOF text
LANGUAGE sql STABLE AS $fn$
  SELECT c.relname::text
  FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'dat' AND NOT c.relispartition
  ORDER BY (c.relname <> 'registro'), c.relname           -- registro primero
$fn$;

-- Crea en dat.<tabla> una partición vacía con la misma estructura y la adjunta al padre.
CREATE OR REPLACE FUNCTION ops.fn_crear_y_adjuntar(p_padre text, p_hija text, p_valor int, p_subparticion text, p_opciones text)
RETURNS boolean LANGUAGE plpgsql AS $fn$
BEGIN
  IF to_regclass(format('dat.%I', p_hija)) IS NOT NULL THEN RETURN false; END IF;
  EXECUTE format('CREATE TABLE dat.%I (LIKE dat.%I INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING STORAGE)%s%s',
                 p_hija, p_padre,
                 CASE WHEN p_subparticion IS NOT NULL THEN format(' PARTITION BY LIST (%I)', p_subparticion) ELSE '' END,
                 CASE WHEN p_opciones IS NOT NULL THEN ' WITH (' || p_opciones || ')' ELSE '' END);
  EXECUTE format('ALTER TABLE dat.%I ATTACH PARTITION dat.%I FOR VALUES IN (%s)', p_padre, p_hija, p_valor);
  RETURN true;
END $fn$;

-- Paso 1 al crear una CUENTA (o, si no existe, al crear su primera medición).
CREATE OR REPLACE FUNCTION ops.fn_preparar_cuenta(p_cuenta int)
RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE t text; n int := 0;
BEGIN
  FOR t IN SELECT ops.fn_tablas_dat() LOOP
    IF ops.fn_crear_y_adjuntar(t, format('%s_c%s', t, p_cuenta), p_cuenta, 'medicion_id', NULL) THEN n := n + 1; END IF;
  END LOOP;
  RETURN n;
END $fn$;

-- Paso 2 al crear una MEDICIÓN: nivel medición en todas las tablas (+ meses iniciales si se conocen).
CREATE OR REPLACE FUNCTION ops.fn_preparar_medicion(p_cuenta int, p_medicion int, p_periodos int[] DEFAULT NULL)
RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE t text; n int := 0;
BEGIN
  PERFORM ops.fn_preparar_cuenta(p_cuenta);
  FOR t IN SELECT ops.fn_tablas_dat() LOOP
    IF ops.fn_crear_y_adjuntar(format('%s_c%s', t, p_cuenta), format('%s_c%s_m%s', t, p_cuenta, p_medicion), p_medicion,
                               CASE WHEN t = 'registro_huella' THEN NULL ELSE 'periodo' END, NULL) THEN n := n + 1; END IF;
  END LOOP;
  IF p_periodos IS NOT NULL THEN n := n + ops.fn_asegurar_periodos(p_cuenta, p_medicion, p_periodos); END IF;
  RETURN n;
END $fn$;

-- Paso 3, ANTES de cada carga: crea las hojas de los meses que trae el lote (SELECT DISTINCT periodo FROM staging).
-- Idempotente y barato si ya existen. Las hojas de estado nacen con fillfactor 80 (más actualizaciones HOT).
CREATE OR REPLACE FUNCTION ops.fn_asegurar_periodos(p_cuenta int, p_medicion int, p_periodos int[])
RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE t text; p int; n int := 0;
BEGIN
  FOREACH p IN ARRAY p_periodos LOOP
    IF p < 200001 OR p > 210012 OR p % 100 NOT BETWEEN 1 AND 12 THEN RAISE EXCEPTION 'periodo inválido: %', p; END IF;
    FOR t IN SELECT x FROM ops.fn_tablas_dat() x WHERE x <> 'registro_huella' LOOP
      IF ops.fn_crear_y_adjuntar(format('%s_c%s_m%s', t, p_cuenta, p_medicion), format('%s_c%s_m%s_p%s', t, p_cuenta, p_medicion, p), p, NULL,
           CASE WHEN t = 'registro_estado' THEN 'fillfactor = 80, autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02' END) THEN
        n := n + 1;
      END IF;
    END LOOP;
  END LOOP;
  RETURN n;
END $fn$;

-- Compatibilidad con la versión anterior del diseño
CREATE OR REPLACE FUNCTION ops.fn_asegurar_particiones(p_cuenta int, p_medicion int)
RETURNS void LANGUAGE sql AS $fn$ SELECT ops.fn_preparar_medicion(p_cuenta, p_medicion, ARRAY[ops.fn_periodo(now())]) $fn$;

-- Hojas (medición × mes) de la principal anteriores al corte: candidatas al archivado mensual.
CREATE OR REPLACE FUNCTION ops.fn_hojas_archivables(p_corte int)
RETURNS TABLE (cuenta_id int, medicion_id int, periodo int, filas_aprox bigint, bytes bigint)
LANGUAGE sql STABLE AS $fn$
  SELECT m[1]::int, m[2]::int, m[3]::int, greatest(c.reltuples, 0)::bigint, pg_total_relation_size(c.oid)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
       LATERAL regexp_match(c.relname, '^registro_c(\d+)_m(\d+)_p(\d{6})$') m
  WHERE n.nspname = 'dat' AND c.relkind = 'r' AND m IS NOT NULL AND m[3]::int < p_corte
  ORDER BY 1, 2, 3
$fn$;

-- Sentencias para soltar una hoja de TODAS las tablas dat (después de copiarla y verificarla en el histórico).
-- DETACH … CONCURRENTLY no puede ir dentro de una transacción: el worker ejecuta cada sentencia por separado.
-- Primero las tablas con FK hacia dat.registro; dat.registro al final.
CREATE OR REPLACE FUNCTION ops.fn_sql_soltar_hoja(p_cuenta int, p_medicion int, p_periodo int)
RETURNS SETOF text LANGUAGE sql STABLE AS $fn$
  WITH t AS (
    SELECT x AS tabla, (x = 'registro') AS ultimo FROM ops.fn_tablas_dat() x WHERE x <> 'registro_huella'
  ), h AS (
    SELECT tabla, ultimo, format('%s_c%s_m%s', tabla, p_cuenta, p_medicion) AS padre,
           format('%s_c%s_m%s_p%s', tabla, p_cuenta, p_medicion, p_periodo) AS hoja
    FROM t WHERE to_regclass(format('dat.%I', format('%s_c%s_m%s_p%s', tabla, p_cuenta, p_medicion, p_periodo))) IS NOT NULL
  )
  SELECT q FROM h, LATERAL (VALUES (1, format('ALTER TABLE dat.%I DETACH PARTITION dat.%I CONCURRENTLY', padre, hoja)),
                                   (2, format('DROP TABLE dat.%I', hoja))) v(o, q)
  ORDER BY h.ultimo, h.tabla, v.o
$fn$;

-- Crea particiones mensuales (actual + N meses) de las series de tiempo. Lo ejecuta el scheduler a diario.
CREATE OR REPLACE FUNCTION ops.fn_particiones_mensuales(p_desde date, p_meses int)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE r record; m date; nom text;
BEGIN
  FOR r IN SELECT * FROM (VALUES ('prc','llm_llamado'),('prc','proceso_log'),('aud','auditoria')) v(esq, tab) LOOP
    FOR i IN 0..p_meses LOOP
      m := (date_trunc('month', p_desde) + make_interval(months => i))::date;
      nom := format('%s_%s', r.tab, to_char(m, 'YYYYMM'));
      IF to_regclass(format('%I.%I', r.esq, nom)) IS NULL THEN
        EXECUTE format('CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
                       r.esq, nom, r.esq, r.tab, m, (m + interval '1 month')::date);
      END IF;
    END LOOP;
  END LOOP;
END $fn$;

-- ---------- Cola de trabajo sobre PostgreSQL (reemplaza Redis/Celery) ----------
-- Un worker toma hasta N tareas de su cola sin chocar con los demás (SKIP LOCKED) y las marca en ejecución.
CREATE OR REPLACE FUNCTION prc.fn_tomar_tareas(p_cola text, p_worker text, p_n int DEFAULT 1)
RETURNS SETOF prc.proceso_tarea LANGUAGE sql AS $fn$
  UPDATE prc.proceso_tarea t
     SET estado = 'en_ejecucion', worker = p_worker, latido = now(),
         iniciado_en = coalesce(t.iniciado_en, now()), intentos = t.intentos + 1
   WHERE t.id IN (SELECT id FROM prc.proceso_tarea
                   WHERE cola = p_cola AND estado = 'en_cola' AND disponible_en <= now()
                   ORDER BY prioridad, disponible_en, id
                   LIMIT p_n FOR UPDATE SKIP LOCKED)
  RETURNING t.*
$fn$;

-- El planificador la ejecuta cada 30 s: si un worker murió (sin latido), su tarea vuelve a la cola.
CREATE OR REPLACE FUNCTION prc.fn_rescatar_tareas(p_segundos int DEFAULT 60)
RETURNS int LANGUAGE sql AS $fn$
  WITH r AS (
    UPDATE prc.proceso_tarea SET estado = 'en_cola', worker = NULL, disponible_en = now(),
           error_codigo = 'WORKER_PERDIDO', error_mensaje = 'Sin latido por más de ' || p_segundos || ' s; se reencola'
     WHERE estado = 'en_ejecucion' AND latido < now() - make_interval(secs => p_segundos)
    RETURNING 1)
  SELECT count(*)::int FROM r
$fn$;

-- ---------- Archivado mensual (ver ops.archivado) ----------
-- Corte: se conservan en la principal el mes en curso y los N meses anteriores (ops.parametro 'archivo.meses_principal').
-- Ej.: N = 3 y hoy 2026-11-01 → corte 202608 → se archivan julio 2026 y anteriores.
CREATE OR REPLACE FUNCTION ops.fn_corte_archivo(p_hoy date DEFAULT current_date)
RETURNS int LANGUAGE sql STABLE AS $fn$
  SELECT to_char(date_trunc('month', p_hoy) - make_interval(months => coalesce(
           (SELECT (valor #>> '{}')::int FROM ops.parametro WHERE clave = 'archivo.meses_principal'), 3)), 'YYYYMM')::int
$fn$;

-- -------------------------------------------------------------------------------------
-- 13. VISTAS DE APOYO
-- -------------------------------------------------------------------------------------
CREATE VIEW seg.v_usuario_cuenta AS                        -- qué cuentas puede ver cada usuario (filtro de seguridad)
  SELECT u.id AS usuario_id, c.id AS cuenta_id
  FROM seg.usuario u JOIN seg.rol r ON r.id = u.rol_id CROSS JOIN cfg.cuenta c
  WHERE r.ver_todas AND u.estado_id = 1 AND c.estado_id <> -1
  UNION
  SELECT gu.usuario_id, gc.cuenta_id
  FROM seg.grupo_usuario gu JOIN seg.grupo g ON g.id = gu.grupo_id AND g.estado_id = 1
  JOIN seg.grupo_cuenta gc ON gc.grupo_id = g.id;

CREATE VIEW dat.v_estado_medicion AS                       -- la matriz «estado por fuente» del mockup
  SELECT r.medicion_id, o.codigo AS origen,
         count(*)                                                                             AS cargados,
         count(*) FILTER (WHERE e.estado_id <> -1 AND NOT e.incorporado AND e.relevancia = 0) AS por_fiscalizar,
         count(*) FILTER (WHERE e.estado_id <> -1 AND NOT e.incorporado AND e.relevancia = 1) AS cumplen_sin_incorporar,
         count(*) FILTER (WHERE e.estado_id <> -1 AND NOT e.incorporado AND e.relevancia = 2) AS descartados,
         count(*) FILTER (WHERE e.estado_id <> -1 AND e.incorporado)                          AS incorporados,
         count(*) FILTER (WHERE e.incorporado AND e.st_metricas = 2)                          AS con_metricas,
         count(*) FILTER (WHERE e.incorporado AND e.st_transcripcion = 2)                     AS transcritos,
         count(*) FILTER (WHERE e.incorporado AND e.st_sentimiento = 2)                       AS analizados,
         count(*) FILTER (WHERE e.publicado)                                                  AS en_tablero,
         count(*) FILTER (WHERE e.estado_id = -1)                                             AS eliminados,
         count(*) FILTER (WHERE 3 IN (e.st_relevancia, e.st_sentimiento, e.st_transcripcion, e.st_metricas, e.st_regex, e.st_cluster)) AS con_error
  FROM dat.registro r
  JOIN dat.registro_estado e USING (cuenta_id, medicion_id, periodo, registro_id)
  JOIN cat.origen o ON o.id = r.origen_id
  GROUP BY r.medicion_id, o.codigo;

CREATE VIEW prc.v_consumo_llm AS                           -- consumo por cuenta/medición/paso/modelo/llave
  SELECT date_trunc('day', l.creado_en)::date AS fecha, l.cuenta_id, l.medicion_id, p.codigo AS paso,
         pr.codigo AS proveedor, mo.nombre AS modelo, k.alias AS llave,
         count(*) AS llamados, count(*) FILTER (WHERE l.estado = 'error') AS errores,
         count(*) FILTER (WHERE l.es_respaldo) AS por_respaldo,
         sum(l.registros_n) AS registros, sum(l.tokens_in) AS tokens_in, sum(l.tokens_out) AS tokens_out,
         sum(l.tokens_total) AS tokens_total, sum(l.costo_usd) AS costo_usd
  FROM prc.llm_llamado l
  JOIN cat.paso p ON p.id = l.paso JOIN cfg.llm_proveedor pr ON pr.id = l.proveedor_id
  JOIN cfg.llm_modelo mo ON mo.id = l.modelo_id JOIN cfg.llm_llave k ON k.id = l.llave_id
  GROUP BY 1,2,3,4,5,6,7;

-- -------------------------------------------------------------------------------------
-- 13b. ROLES POR SERVICIO (una de las razones de usar esquemas: permisos por dominio)
--      Cada servicio se conecta con su propio usuario de BD y solo ve lo que necesita.
--      Un error o un cambio en un servicio no puede escribir en las tablas de otro.
-- -------------------------------------------------------------------------------------
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['svc_api','svc_ingesta','svc_llm','svc_analisis','svc_media','svc_transcripcion','svc_archivo','svc_lectura'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN', r); END IF;
  END LOOP;
END $$;
GRANT USAGE ON SCHEMA cat, seg, cfg, med, dat, ana, prc, rep, aud, ops, stg
  TO svc_api, svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo, svc_lectura;
GRANT SELECT ON ALL TABLES IN SCHEMA cat, cfg, med TO svc_api, svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo, svc_lectura;
-- API: administra configuración, seguridad y mediciones; lee datos; crea procesos/tareas (nunca escribe dat masivamente)
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA seg, cfg, med, prc, rep TO svc_api;
GRANT SELECT, UPDATE ON ALL TABLES IN SCHEMA dat TO svc_api;                 -- ediciones puntuales de analistas
GRANT INSERT ON ALL TABLES IN SCHEMA aud TO svc_api; GRANT SELECT, UPDATE ON aud.notificacion TO svc_api;
-- Workers de datos: escriben dat y su staging; actualizan su avance en prc
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA dat, stg TO svc_ingesta, svc_llm, svc_analisis, svc_media;
GRANT CREATE ON SCHEMA stg TO svc_ingesta, svc_llm, svc_analisis, svc_media;  -- staging UNLOGGED por proceso
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA prc TO svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ana, rep TO svc_analisis;
-- Transcripción (servidor GPU): solo sus tablas
GRANT SELECT ON dat.registro_media TO svc_transcripcion;
GRANT SELECT, INSERT, UPDATE ON dat.registro_transcripcion, dat.registro_estado, dat.registro_evento TO svc_transcripcion;
-- Archivado: lee todo dat, mantiene huella y particiones (dueño de las hojas vía SECURITY DEFINER en producción)
GRANT SELECT ON ALL TABLES IN SCHEMA dat TO svc_archivo;
GRANT UPDATE ON dat.registro_huella TO svc_archivo; GRANT SELECT, INSERT, UPDATE ON ops.archivado TO svc_archivo;
-- Lectura (réplica): informes y exportaciones
GRANT SELECT ON ALL TABLES IN SCHEMA dat, ana, rep, prc TO svc_lectura;
GRANT SELECT, INSERT, UPDATE ON ops.worker TO svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo;
GRANT SELECT ON ops.parametro, ops.politica_reintento TO svc_api, svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo;
-- Auditoría: nadie puede modificarla ni borrarla (solo INSERT)
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA aud FROM PUBLIC;

-- =====================================================================================
-- 14. DATOS DE EJEMPLO (los mismos del mockup HTML)
-- =====================================================================================
INSERT INTO cat.red VALUES (1,'x','X','X'),(2,'tiktok','TikTok','TT'),(3,'youtube','YouTube','YT'),(4,'facebook','Facebook','FB'),(5,'instagram','Instagram','IG'),(6,'medios','Medios y web','MD');
INSERT INTO cat.origen VALUES (1,'archivo','Archivos (Excel/CSV)'),(2,'meltwater','API Meltwater'),(3,'scrapper','Scrapper (Apify)'),(4,'googlenews','Google News'),(5,'manual','Manual');
INSERT INTO cat.estado_paso VALUES (0,'pendiente','Pendiente'),(1,'en_curso','En curso'),(2,'ok','Correcto'),(3,'error','Error'),(4,'no_aplica','No aplica');
INSERT INTO cat.paso VALUES (1,'carga','Carga'),(2,'relevancia','Relevancia'),(3,'sentimiento','Sentimiento'),(4,'transcripcion','Transcripción'),(5,'metricas','Métricas'),(6,'regex','Regex'),(7,'cruces','Cruces'),(8,'embedding','Embedding'),(9,'cluster','Clusters'),(10,'tema','Temas'),(11,'bots','Bots'),(12,'publicacion','Publicación'),(13,'etiqueta_cluster','Etiqueta de cluster');
INSERT INTO cat.tipo_proceso VALUES
 ('carga_archivo','Carga de archivos','q.ingesta',60,600),('carga_meltwater','Consulta Meltwater','q.ingesta',120,600),
 ('carga_scraper','Proceso de scraping (Apify + Google News)','q.apify',120,600),('carga_manual','Registro manual','q.ingesta',5,5),
 ('fiscalizacion_ia','Fiscalización con IA','q.llm',180,600),('incorporacion','Incorporación','q.datos',30,120),
 ('actualizacion_masiva','Actualización masiva (Excel)','q.datos',60,300),('metricas','Actualización de métricas','q.apify',300,600),
 ('descarga_medios','Descarga de videos/imágenes a S3','q.media',600,3600),('transcripcion','Transcripción (Whisper local, servidor GPU)','q.transcripcion',3600,14400),('relevancia','Relevancia IA','q.llm',180,600),
 ('sentimiento','Sentimiento IA','q.llm',180,600),('analisis','Análisis IA (clusters, temas, sentimiento, bots)','q.analisis',300,600),
 ('reaplicar_regex','Reaplicación de regex y cruces','q.regex',180,600),('publicacion','Actualización del tablero','q.datos',60,300),
 ('exportacion','Exportación de informe','q.reportes',120,600),
 ('archivado','Archivado mensual a la BD histórica','q.mantenimiento',3600,3600),('rehidratacion','Traer un mes del histórico a la principal','q.mantenimiento',600,1800);
INSERT INTO cat.estado_proceso VALUES ('en_cola','En cola',false),('en_ejecucion','En ejecución',false),('completado','Completado',true),('advertencia','Con advertencias',true),('error','Error',true),('cancelado','Cancelado',true);
INSERT INTO cat.modulo VALUES ('dashboard','Inicio'),('clientes','Clientes'),('cuentas','Cuentas'),('usuarios','Usuarios'),('roles','Roles y accesos'),('grupos','Grupos de usuarios'),('prompts','Prompts por defecto'),('cruces','Cruces'),('regex','Regex'),('paises','Países'),('actores','Actores de scraping'),('formatos','Formatos de archivo'),('llm','Proveedores y llaves LLM'),('mediciones','Mediciones'),('fiscalizacion','Fiscalización'),('registros','Registros'),('procesos','Procesos'),('informes','Informes'),('auditoria','Auditoría');
INSERT INTO cat.accion VALUES ('ver','Ver'),('crear','Crear'),('editar','Editar'),('eliminar','Eliminar'),('ejecutar','Ejecutar'),('exportar','Exportar');

INSERT INTO seg.rol (nombre, descripcion, ver_todas, estado_id) VALUES
 ('Administrador','Control total de la plataforma.',true,1),
 ('Líder de análisis','Gestiona clientes, cuentas y mediciones. Ve todas las cuentas.',true,1),
 ('Analista','Carga, fiscaliza y procesa datos de las cuentas de sus grupos.',false,1),
 ('Consultor cliente','Solo lectura de registros e informes de sus grupos.',false,1),
 ('Auditor','Consulta del log de auditoría.',true,0);
INSERT INTO seg.rol_permiso SELECT 1, m.codigo, a.codigo FROM cat.modulo m CROSS JOIN cat.accion a;
INSERT INTO seg.rol_permiso SELECT 2, m.codigo, a.codigo FROM cat.modulo m CROSS JOIN cat.accion a WHERE m.codigo NOT IN ('roles','llm') OR a.codigo = 'ver';
INSERT INTO seg.rol_permiso SELECT 3, m, a FROM (VALUES ('dashboard','ver'),('clientes','ver'),('cuentas','ver'),('prompts','ver'),('prompts','crear'),('prompts','editar'),('cruces','ver'),('cruces','crear'),('cruces','editar'),('regex','ver'),('regex','crear'),('regex','editar'),('paises','ver'),('actores','ver'),('formatos','ver'),('mediciones','ver'),('mediciones','crear'),('mediciones','editar'),('mediciones','ejecutar'),('mediciones','exportar'),('fiscalizacion','ver'),('fiscalizacion','editar'),('fiscalizacion','ejecutar'),('fiscalizacion','exportar'),('registros','ver'),('registros','editar'),('registros','eliminar'),('registros','exportar'),('procesos','ver'),('procesos','ejecutar'),('informes','ver'),('informes','exportar')) v(m,a);
INSERT INTO seg.rol_permiso SELECT 4, m, a FROM (VALUES ('dashboard','ver'),('cuentas','ver'),('mediciones','ver'),('registros','ver'),('procesos','ver'),('informes','ver'),('informes','exportar')) v(m,a);
INSERT INTO seg.rol_permiso SELECT 5, m.codigo, 'ver' FROM cat.modulo m;

INSERT INTO seg.usuario (nombre, email, rol_id, telefono, estado_id) VALUES
 ('Natt Becerril','natt.becerril@syntra.co',1,'+52 55 1200 3400',1),
 ('Andrés Restrepo','andres.restrepo@syntra.co',2,'+52 81 2211 9087',1),
 ('Camila Ríos','camila.rios@syntra.co',3,'+52 33 4410 2231',1),
 ('Santiago Mejía','santiago.mejia@observatorioelectoral.mx',4,'+52 55 7781 1290',1),
 ('Valentina Ortiz','valentina.ortiz@syntra.co',3,'+52 22 5530 1874',1),
 ('Julián Cárdenas','julian.cardenas@syntra.co',3,'+52 81 6620 4410',0),
 ('Mariana Duque','mariana.duque@syntra.co',3,'+52 55 3301 7765',-1);

INSERT INTO cfg.cliente (nombre, rfc, sector, contacto, estado_id, creado_por, actualizado_por) VALUES
 ('Ágora Consultores Políticos','ACP150312KX1','Consultoría política','proyectos@agoraconsultores.mx',1,1,1),
 ('Observatorio Electoral MX','OEM180905PL3','Sociedad civil','datos@observatorioelectoral.mx',1,2,2),
 ('Comunicación Social Estatal (demo)','CSE200115AB7','Gobierno estatal','monitoreo@comunicacion-estatal.mx',1,2,2),
 ('Partido Renovación Nacional (ficticio)','PRN210701QW2','Partido político','estrategia@renovacion-nacional.mx',1,1,1),
 ('Grupo Editorial Norte','GEN990420HJ5','Medios de comunicación','redaccion@editorialnorte.mx',0,1,1),
 ('Campaña municipal 2024','CMU240101ZZ9','Campaña electoral','—',-1,1,1);

INSERT INTO cfg.prompt (tipo, red_id, nombre, por_defecto, version_actual, contenido, creado_por) VALUES
 ('cluster',NULL,'Clusters temáticos v3',true,3,'Eres analista senior de escucha social política de Syntra. A partir de las menciones sobre {{cuenta}}, agrupa el contenido en {{num_clusters}} clusters y {{num_subclusters}} subclusters. Devuelve JSON.',2),
 ('cluster',NULL,'Clusters para coyuntura',false,2,'Contexto de COYUNTURA política para {{cuenta}}. Agrupa las menciones en {{num_clusters}} clusters priorizando detonante, afectación, respuesta y amplificación.',2),
 ('temas',NULL,'Temas finales ejecutivos v2',true,2,'Consolida los clusters de {{cuenta}} en temas finales ejecutivos (máximo 6) con resumen, sentimiento y riesgo.',1),
 ('relevancia',NULL,'Relevancia general v2',true,2,'Evalúa si cada registro es RELEVANTE para la medición de {{cuenta}}. Responde por id: {cumple, porcentaje, razon}.',2),
 ('relevancia',2,'Relevancia TikTok (video + transcripción)',false,1,'Para videos de TikTok: evalúa relevancia usando descripción, hashtags y TRANSCRIPCIÓN del audio.',3),
 ('sentimiento',NULL,'Sentimiento político v3',true,3,'Clasifica el sentimiento HACIA {{cuenta}}: positivo, neutral o negativo. Ironía = negativo.',2),
 ('sentimiento',6,'Sentimiento editorial en medios',false,1,'Para medios: sentimiento editorial de la nota hacia {{cuenta}} (titular, encuadre, fuentes).',5);
INSERT INTO cfg.prompt_version (prompt_id, version, contenido, creado_por) SELECT id, version_actual, contenido, creado_por FROM cfg.prompt;

INSERT INTO cfg.cuenta (cliente_id, nombre, actor_principal, entidad, taxonomia, prompt_clusters, prompt_temas, estado_id, creado_por) VALUES
 (1,'Gob. Nuevo León · Ricardo Salazar','el gobernador Salazar','Nuevo León','gobierno',(SELECT contenido FROM cfg.prompt WHERE id=2),(SELECT contenido FROM cfg.prompt WHERE id=3),1,2),
 (1,'Gob. Jalisco · Lucía Navarro','la gobernadora Navarro','Jalisco','gobierno',(SELECT contenido FROM cfg.prompt WHERE id=1),(SELECT contenido FROM cfg.prompt WHERE id=3),1,2),
 (2,'Gob. Veracruz · Héctor Domínguez','el gobernador Domínguez','Veracruz','gobierno',(SELECT contenido FROM cfg.prompt WHERE id=1),(SELECT contenido FROM cfg.prompt WHERE id=3),1,2),
 (2,'Ranking nacional de gobernadores','los gobernadores','México','comparativo',(SELECT contenido FROM cfg.prompt WHERE id=1),(SELECT contenido FROM cfg.prompt WHERE id=3),1,5),
 (3,'Gob. Estado de México · Andrea Cervantes','la gobernadora Cervantes','Estado de México','gobierno',(SELECT contenido FROM cfg.prompt WHERE id=1),(SELECT contenido FROM cfg.prompt WHERE id=3),1,5),
 (4,'Partido Renovación Nacional · Reputación','Renovación Nacional','México','electoral',(SELECT contenido FROM cfg.prompt WHERE id=1),(SELECT contenido FROM cfg.prompt WHERE id=3),1,1);

INSERT INTO seg.grupo (nombre, descripcion, creado_por) VALUES ('Gobernadores Norte-Occidente','Nuevo León y Jalisco',1),('Observatorio y comparativos','Veracruz y ranking',2),('Edomex y partidos','Edomex y reputación partidista',2);
INSERT INTO seg.grupo_usuario VALUES (1,3),(1,6),(2,4),(2,5),(3,5);
INSERT INTO seg.grupo_cuenta VALUES (1,1),(1,2),(2,3),(2,4),(3,5),(3,6);

INSERT INTO cfg.cruce (nombre, categoria, color, modo, incluye_autor, descripcion, creado_por) VALUES
 ('Gabinete estatal NL','Gobierno','#1293F8','texto_hashtags',true,'Cuentas oficiales del gobierno de Nuevo León.',1),
 ('Oposición en el Congreso NL','Oposición','#7850EE','texto_hashtags',true,'Legisladores y dirigencias opositoras.',1),
 ('Hashtags de la crisis del agua','Coyuntura','#04B8FB','hashtags',false,'Etiquetas usadas por la ciudadanía.',1),
 ('Medios regionales','Medios','#3655D2','texto_hashtags',true,'Cuentas de medios con cobertura regional.',1);
INSERT INTO cfg.cruce_item VALUES (1,'@RicardoSalazarNL'),(1,'@GobiernoNL'),(1,'@AguaDrenajeMty'),(2,'@PRN_NuevoLeon'),(2,'#OposiciónNL'),(3,'#AguaNL'),(3,'#SinAguaMty'),(3,'#PipasYa'),(4,'@NoticiasRegioMX'),(4,'@CanalSieteMTY');

INSERT INTO cfg.regex (nombre, condicion, flags, texto_prueba, descripcion, version, creado_por) VALUES
 ('Crisis del agua', '\b(agua|pipas?|sequ[ií]a|tandeo|acueducto)\b','i','Tres días sin agua en mi colonia y las pipas no llegan.','Escasez y abasto de agua.',2,3),
 ('Protestas y bloqueos', '\b(bloque\w+|protesta\w*|manifestaci[oó]n|marcha)\b','i','Vecinos bloquean avenida para exigir agua.','Movilizaciones ciudadanas.',1,3),
 ('Seguridad y violencia', '\b(homicidi\w*|violencia|inseguridad|balacera|desaparec\w+)\b','i','Otra balacera anoche y la inseguridad no para.','Seguridad pública.',4,2),
 ('Corrupción y opacidad', '\b(corrup\w+|desv[ií]o|adjudicaci[oó]n directa|nepotismo)\b','i','Contratos por adjudicación directa en el gobierno.','Señalamientos de corrupción.',3,3),
 ('Derechos humanos', '\b(derechos humanos|CDHCM|CNDH|queja\w*)\b','i','La CDHCM investiga quejas por violaciones a derechos humanos.','Quejas y organismos de DD. HH.',1,1);
INSERT INTO cfg.regex_version (regex_id, version, condicion, flags, creado_por) SELECT id, version, condicion, flags, creado_por FROM cfg.regex;

INSERT INTO cfg.pais (nombre, codigo, idioma, estado_id) VALUES ('México','MX','es-419',1),('Estados Unidos','US','es-419',1),('España','ES','es',1),('Colombia','CO','es-419',1),('Argentina','AR','es-419',1),('Perú','PE','es-419',0);

INSERT INTO cfg.actor_scraping (red_id, uso, nombre, actor, max_registros, max_urls_por_corrida, nota) VALUES
 (1,'busqueda','X · búsqueda de tweets','apidojo/tweet-scraper',1000,1000,'Operadores de búsqueda avanzada.'),
 (2,'busqueda','TikTok · búsqueda y hashtags','clockworks/tiktok-scraper',1000,500,'Búsqueda difusa.'),
 (3,'busqueda','YouTube · videos','streamers/youtube-scraper',500,500,NULL),
 (4,'busqueda','Facebook · publicaciones','apify/facebook-posts-scraper',500,300,'Páginas públicas.'),
 (5,'busqueda','Instagram · posts y reels','apify/instagram-scraper',500,300,NULL),
 (2,'metricas','TikTok · métricas por URL','clockworks/tiktok-scraper',1000,1000,'Recibe lista de URLs (postURLs).');

INSERT INTO cfg.formato_archivo (id, nombre, descripcion, extensiones, delimitador, codificacion, formato_fecha, zona_horaria) VALUES
 ('talkwalker_simple','Formato simple (DBFormatoSimple)','Exportación de 101 columnas tipo Talkwalker. Horas en UTC−6 (verificado con los IDs de los tweets)','{csv,xlsx}',',','utf-8','YYYY-MM-DD HH24:MI','America/Mexico_City'),
 ('meltwater','Meltwater (export)','Excel — exportación Explore','{xlsx,xls}',NULL,'utf-8','DD-Mon-YYYY HH12:MIAM','America/Mexico_City'),
 ('plantilla_syntra','Plantilla Syntra','Plantilla de captura propia','{xlsx,csv}',',','utf-8','YYYY-MM-DD HH24:MI','America/Mexico_City');
INSERT INTO cfg.formato_columna (formato_id, campo_destino, columnas_origen, transformacion, requerido) VALUES
 ('talkwalker_simple','url','{url}','directo',true),
 ('talkwalker_simple','fecha_publicacion','{published}','fecha',true),
 ('talkwalker_simple','fecha_indexado','{indexed}','fecha',false),
 ('talkwalker_simple','titulo','{title}','directo',false),
 ('talkwalker_simple','texto','{content,content_snippet}','coalesce',true),
 ('talkwalker_simple','idioma','{lang}','directo',false),
 ('talkwalker_simple','red_id','{source_type}','red_desde_source_type',true),
 ('talkwalker_simple','tipo_contenido','{post_type}','directo',false),
 ('talkwalker_simple','url_padre','{parent_url}','directo',false),
 ('talkwalker_simple','autor_id_ext','{extra_author_attributes.id}','directo',false),
 ('talkwalker_simple','autor_usuario','{extra_author_attributes.short_name}','directo',false),
 ('talkwalker_simple','autor_nombre','{extra_author_attributes.name}','directo',false),
 ('talkwalker_simple','autor_seguidores','{source_extended_attributes.twitter_followers,source_extended_attributes.facebook_followers,source_extended_attributes.instagram_followers,source_extended_attributes.youtube_subscribers}','coalesce',false),
 ('talkwalker_simple','pais','{extra_article_attributes.world_data.country_code}','mayusculas',false),
 ('talkwalker_simple','region','{extra_article_attributes.world_data.region}','directo',false),
 ('talkwalker_simple','ciudad','{extra_article_attributes.world_data.city}','directo',false),
 ('talkwalker_simple','sentimiento_fuente','{sentiment}','entero',false),
 ('talkwalker_simple','likes','{article_extended_attributes.twitter_likes,article_extended_attributes.facebook_likes,article_extended_attributes.instagram_likes,article_extended_attributes.youtube_likes}','coalesce',false),
 ('talkwalker_simple','comentarios','{article_extended_attributes.num_comments,article_extended_attributes.twitter_replies}','suma',false),
 ('talkwalker_simple','compartidos','{article_extended_attributes.twitter_retweets,article_extended_attributes.twitter_quote_tweets,article_extended_attributes.facebook_shares,article_extended_attributes.linkedin_shares}','suma',false),
 ('talkwalker_simple','reproducciones','{article_extended_attributes.youtube_views,article_extended_attributes.twitter_video_views,article_extended_attributes.url_views}','coalesce',false),
 ('talkwalker_simple','alcance','{reach}','entero',false),
 ('talkwalker_simple','media_urls','{images.url,videos.url}','lista',false),
 ('talkwalker_simple','es_rt','{tags_internal}','contiene:isRepost',false),
 ('talkwalker_simple','es_comentario','{tags_internal}','contiene:isComment',false),
 ('talkwalker_simple','extra','{matched_profile,tags_internal,entity_urls,engagement,extra_author_attributes.description,extra_author_attributes.joined_date}','json',false);

INSERT INTO cfg.llm_proveedor VALUES (1,'openai','OpenAI',1,'https://api.openai.com/v1',1),(2,'gemini','Google Gemini',2,'https://generativelanguage.googleapis.com',1);
INSERT INTO cfg.llm_modelo (proveedor_id, nombre, uso, precio_in_1m, precio_cache_1m, precio_out_1m, registros_por_llamado, dimensiones, prioridad) VALUES
 (1,'gpt-5.6-luna','clasificacion',0.20,0.02,1.20,25,NULL,1),
 (1,'text-embedding-3-small','embedding',0.02,NULL,NULL,512,256,1),
 (1,'gpt-5.6-terra','etiquetado',NULL,NULL,NULL,1,NULL,1),
 (2,'gemini-flash','clasificacion',NULL,NULL,NULL,25,NULL,2),
 (2,'gemini-embedding','embedding',NULL,NULL,NULL,250,256,2);
INSERT INTO cfg.llm_llave (proveedor_id, alias, secreto_ref, ultimos4, organizacion, proyecto, rpm_limite, tpm_limite, prioridad, creado_por) VALUES
 (1,'openai-syntra-prod-1','k8s://syntra/llm/openai-1','a9F2','org-syntra','proj-clasificacion',30000,180000000,1,1),
 (1,'openai-syntra-prod-2','k8s://syntra/llm/openai-2','Q7c1','org-syntra','proj-embeddings',30000,180000000,1,1),
 (2,'gemini-syntra-prod-1','k8s://syntra/llm/gemini-1','p0Zx','gcp-syntra','syntra-llm',2000,8000000,2,1);

INSERT INTO ops.politica_reintento VALUES
 ('llm.clasificar',3,500,8000,60000,true,20,'Tras 3 intentos con OpenAI pasa a Gemini; si falla, error en registro y en llm_llamado', now()),
 ('llm.embedding',3,500,8000,60000,false,20,'Sin respaldo por registro: los vectores de modelos distintos no son comparables (el respaldo cambia toda la corrida)', now()),
 ('apify.run',3,5000,60000,900000,false,5,'Reinicia la corrida del actor (por red)', now()),
 ('apify.dataset',5,1000,15000,30000,false,10,'Lectura paginada del dataset', now()),
 ('gnews.get',4,1000,20000,20000,false,10,'Por país × palabra clave', now()),
 ('meltwater.get',4,2000,30000,60000,false,5,NULL, now()),
 ('s3.get',5,200,5000,30000,false,10,NULL, now()),
 ('transcripcion',3,2000,30000,300000,false,10,'Whisper local en el servidor GPU. Si el servidor no responde, las tareas esperan en cola (respaldo por API opcional)', now()),
 ('media.descarga',4,2000,30000,120000,false,10,'Descarga de video/imagen; las URLs de las redes caducan en horas: se descarga apenas llega el registro', now()),
 ('archivo.hoja',3,60000,600000,1800000,false,3,'Copia de una hoja medición×mes a la BD histórica', now());

INSERT INTO med.medicion (cuenta_id, nombre, coyuntura, num_clusters, num_subclusters, instrucciones, ventana_desde, precluster_activo, precluster_separar_temas, x_num_menciones, x_num_cuentas, x_confirmado_en, x_confirmado_por, auto_publicar, creado_por) VALUES
 (1,'Crisis del agua en Monterrey — octubre 2026',true,15,3,'Separar menciones de medios de las de ciudadanos.','2026-10-07 06:00-06',true,true,394,70,now(),1,true,2),
 (2,'Percepción de la gobernadora — Q4 2026',false,15,3,NULL,NULL,false,false,0,50,NULL,NULL,false,2),
 (4,'Ranking nacional de gobernadores — octubre',false,6,3,'Un cluster por gobernador.',NULL,false,false,0,50,NULL,NULL,false,5),
 (6,'Cuadrangular política · Marcha 2 de octubre',true,10,3,'Carga desde formato simple (DBFormatoSimple.csv).',NULL,false,false,0,50,NULL,NULL,false,1);

INSERT INTO med.medicion_fuente (medicion_id, origen_id, activo, config, post_incorporar, post_relevancia, post_sentimiento, post_clusters, post_bots) VALUES
 (1,1,true,'{}',true,false,true,true,true),(1,2,true,'{"busqueda_id":"MW-2214587"}',true,false,true,true,true),(1,5,true,'{}',true,false,true,true,false),
 (2,1,true,'{}',true,false,true,false,false),(2,2,true,'{"busqueda_id":"MW-2201190"}',true,false,true,false,false),
 (3,1,true,'{}',true,false,true,false,false),(4,1,true,'{}',true,true,true,false,false);
INSERT INTO med.programacion_meltwater VALUES (1,true,'2026-10-07 08:00-05','2026-10-17 08:00-05',30,now() + interval '12 min'),(2,true,'2026-09-10 08:00-05','2026-12-19 08:00-05',720,now() + interval '5 h');
INSERT INTO med.medicion_prompt (medicion_id, tipo, red_id, origen, prompt_id, prompt_version, contenido)
 SELECT 1, p.tipo, coalesce(p.red_id,0), 'defecto', p.id, p.version_actual, p.contenido FROM cfg.prompt p WHERE p.id IN (2,3,4,5,6,7);
INSERT INTO med.medicion_cruce VALUES (1,1),(1,2),(1,3),(1,4);
INSERT INTO med.medicion_regex VALUES (1,1,1),(1,2,2),(1,3,3),(1,4,4),(4,5,1),(4,2,2);
INSERT INTO med.medicion_bots (medicion_id) VALUES (1),(2),(3),(4);

INSERT INTO med.scraper (medicion_id, nombre, ejecucion_auto, inicio, fin, frecuencia_min, proxima_ejecucion, gn_activo, gn_registros, gn_periodo, post_incorporar, post_relevancia, post_sentimiento, post_clusters, post_bots, mismas_palabras, creado_por) VALUES
 (1,'Monitoreo continuo · crisis del agua',true,'2026-10-07 08:00-05','2026-10-17 08:00-05',30,now() + interval '24 min',true,50,'ultimo_dia',false,true,true,true,true,false,2),
 (1,'Coyuntura · bloqueos y protestas',true,'2026-10-09 08:00-05','2026-10-13 08:00-05',120,now() + interval '2 h',true,30,'ultima_hora',false,true,true,false,true,true,3),
 (1,'YouTube · conferencias y noticieros',false,'2026-10-07 08:00-05','2026-10-17 08:00-05',NULL,NULL,false,50,'ultimo_dia',false,true,false,false,false,true,2),
 (3,'Prensa nacional · aprobación de gobernadores',true,'2026-09-24 08:00-05','2026-10-30 08:00-05',1440,now() + interval '9 h',true,100,'ultimo_dia',true,false,true,false,false,true,5);
UPDATE med.scraper SET prompt_rel_origen = 'propio', prompt_rel_contenido = 'Para videos de YouTube: cumple si título, descripción o transcripción hablan de la gestión del agua en Nuevo León.' WHERE id = 3;
INSERT INTO med.scraper_red VALUES (1,1,true,200,NULL),(1,2,true,100,NULL),(1,4,true,100,NULL),(1,5,true,100,NULL),(2,1,true,150,NULL),(2,2,true,50,NULL),(3,3,true,30,NULL);
INSERT INTO med.scraper_pais VALUES (1,1),(2,1),(2,2),(4,1),(4,2),(4,3);
INSERT INTO med.scraper_palabra VALUES
 (1,'x','Salazar agua'),(1,'x','#AguaNL'),(1,'tiktok','Salazar agua'),(1,'tiktok','#AguaNL'),(1,'facebook','crisis del agua Monterrey'),(1,'instagram','#AguaNL'),
 (1,'googlenews','Salazar crisis agua Nuevo León'),(1,'googlenews','Monterrey sin agua'),
 (2,'x','bloqueo agua Monterrey'),(2,'x','#SinAguaMty'),(2,'tiktok','bloqueo agua Monterrey'),(2,'googlenews','bloqueo agua Monterrey'),
 (3,'youtube','Salazar conferencia agua'),(4,'googlenews','gobernador aprobación encuesta'),(4,'googlenews','ranking gobernadores');

-- Particiones de ejemplo (lo hace medCrear al crear cada medición; las hojas de cada mes, el cargador)
SELECT ops.fn_preparar_medicion(m.cuenta_id, m.id,
         ARRAY(SELECT DISTINCT p FROM unnest(ARRAY[202610, ops.fn_periodo(now()), ops.fn_periodo(now() - interval '3 h')]) p))
FROM med.medicion m;
SELECT ops.fn_particiones_mensuales('2026-09-01', 3);

INSERT INTO ops.parametro (clave, valor, descripcion) VALUES
 ('archivo.meses_principal', '3', 'Meses completos que se quedan en la BD principal además del mes en curso'),
 ('archivo.dia_hora', '"01 01:00 America/Bogota"', 'Cuándo corre el archivado mensual (día del mes y hora)'),
 ('archivo.hojas_en_paralelo', '4', 'Hojas medición×mes que se copian a la vez'),
 ('cola.sondeo_ms', '2000', 'Respaldo de LISTEN/NOTIFY: cada cuánto revisa la cola un worker ocioso'),
 ('cola.latido_s', '15', 'Cada cuánto renueva el worker el latido de sus tareas'),
 ('cola.rescate_s', '60', 'Latido vencido tras el cual la tarea vuelve a la cola'),
 ('llm.concurrencia_por_worker', '300', 'Llamados LLM simultáneos por proceso worker de q.llm (asyncio)'),
 ('transcripcion.lote', '16', 'Audios por lote en la GPU'),
 ('transcripcion.modelo', '"large-v3-turbo"', 'Modelo Whisper (faster-whisper, int8_float16)');

INSERT INTO ops.worker (id, servidor, colas, pid, version, tareas_en_curso) VALUES
 ('proc-01:q.ingesta:1','proc-01','{q.ingesta,q.datos}',4101,'1.0.0',0),
 ('proc-01:q.llm:1','proc-01','{q.llm}',4102,'1.0.0',0),
 ('proc-01:q.llm:2','proc-01','{q.llm}',4103,'1.0.0',0),
 ('proc-01:q.apify:1','proc-01','{q.apify}',4104,'1.0.0',0),
 ('proc-01:q.regex:1','proc-01','{q.regex,q.analisis}',4105,'1.0.0',0),
 ('gpu-01:q.transcripcion:1','gpu-01','{q.transcripcion}',2201,'1.0.0',0);

-- Ejemplo de un mes ya archivado (medición 1 no tiene datos de junio; la fila muestra el formato del control)
INSERT INTO ops.archivado (cuenta_id, medicion_id, periodo, estado, filas, verificacion, intentos, iniciado_en, finalizado_en) VALUES
 (2,2,202606,'archivado','{"registro":[18240,18240],"registro_estado":[18240,18240],"registro_ia":[21011,21011],"registro_regex":[9310,9310],"registro_evento":[112,112]}',
  '{"metodo":"conteo + suma de registro_id por tabla","ok":true}',1,'2026-10-01 01:00-05','2026-10-01 01:04-05');

-- Archivo cargado con el formato simple y su proceso
INSERT INTO med.archivo (medicion_id, nombre, formato_id, s3_bucket, s3_key, tamano_bytes, filas_leidas, filas_validas, filas_rechazadas, estado, subido_por)
 VALUES (4,'DBFormatoSimple.csv','talkwalker_simple','syntra-cargas','c6/m4/2026/10/11/DBFormatoSimple.csv',12045,2,2,0,'procesado',1);

INSERT INTO prc.proceso (medicion_id, cuenta_id, tipo, modo, estado, opciones, total, procesados, ok, progreso, stats, sla_ms, creado_en, iniciado_en, finalizado_en, creado_por, detalle) VALUES
 (4,6,'carga_archivo','manual','advertencia','{"post":{"incorporar":true,"relevancia":true,"sentimiento":true,"clusters":false,"bots":false}}',2,2,2,100,'{"leidos":2,"nuevos":2,"duplicados":0,"rechazados":0,"fechas_corregidas":2}',60000, now() - interval '20 min', now() - interval '20 min', now() - interval '19 min 58 s',1,'Carga de 1 archivo · 2 fechas corregidas (revisar el archivo de origen)'),
 (1,1,'carga_scraper','automatico','completado','{"run":{"metadata":true,"transcripcion":true}}',148,148,145,100,'{"leidos":156,"nuevos":148,"duplicados":8,"fisc":148}',120000, now() - interval '35 min', now() - interval '35 min', now() - interval '33 min 40 s',NULL,'Monitoreo continuo · crisis del agua · programación cada 30 min'),
 (1,1,'relevancia','automatico','completado','{"modo_llm":"lote","registros_por_llamado":25}',148,148,147,100,'{"llamados":6,"tokens_in":31200,"tokens_out":4100,"respaldo":1,"errores":1}',180000, now() - interval '33 min', now() - interval '33 min', now() - interval '32 min 10 s',NULL,'Relevancia al incorporar (carga anterior)');
UPDATE prc.proceso SET scraper_id = 1 WHERE id = 2;
UPDATE prc.proceso SET padre_id = 2 WHERE id = 3;
INSERT INTO prc.proceso_tarea (proceso_id, clave, tipo, estado, intentos, objetivo, ok, ref_externa, iniciado_en, finalizado_en, cola, prioridad, worker) VALUES
 (1,'archivo:1','archivo','completado',1,2,2,NULL, now() - interval '20 min', now() - interval '19 min 58 s','q.ingesta',1,'proc-01:q.ingesta:1'),
 (2,'red:x','apify','completado',1,60,58,'apify-run-Gk2x9',now() - interval '35 min', now() - interval '34 min','q.apify',5,'proc-01:q.apify:1'),
 (2,'red:tiktok','apify','completado',2,40,38,'apify-run-Tt8a1',now() - interval '35 min', now() - interval '33 min 50 s','q.apify',5,'proc-01:q.apify:1'),
 (2,'pais:MX','googlenews','completado',1,30,29,NULL,now() - interval '35 min', now() - interval '34 min 30 s','q.apify',5,'proc-01:q.apify:1'),
 (3,'chunk:0000','llm','completado',1,148,147,NULL,now() - interval '33 min', now() - interval '32 min 10 s','q.llm',5,'proc-01:q.llm:1');
UPDATE prc.proceso_tarea SET error_codigo = 'HTTP_429', error_mensaje = 'Primer intento: límite de solicitudes del actor (reintento automático OK)' WHERE clave = 'red:tiktok';
INSERT INTO prc.proceso_log (proceso_id, nivel, mensaje) VALUES
 (1,'i','Proceso en cola · Carga de archivos · 1 archivo'),(1,'o','DBFormatoSimple.csv: 2 filas leídas (101 columnas, formato talkwalker_simple)'),
 (1,'w','2 filas con fecha 2007-10-26 (< fecha_min del formato): corregidas a 2026-10-07 al invertir aa/mm/dd → dd/mm/aa; confirmado con la fecha del ID del tweet'),
 (2,'o','red:x · 58 registros'),(2,'w','red:tiktok · HTTP 429 → reintento 1/3 en 5 s'),(2,'o','red:tiktok · 38 registros'),(2,'o','pais:MX · 29 notas');

INSERT INTO dat.ejecucion (cuenta_id, medicion_id, proceso_id, tarea_id, origen_id, red_id, archivo_id, detalle, post, n_leidos, n_nuevos, fecha_min, fecha_max, s3_raw_key)
 VALUES (6,4,1,1,1,1,1,'DBFormatoSimple.csv','{"incorporar":true,"relevancia":true,"sentimiento":true}',2,2,'2026-10-07 11:37-06','2026-10-07 12:46-06','syntra-raw/c6/m4/p1/archivo-1.parquet'),
        (1,1,2,2,3,1,NULL,'Monitoreo continuo · X (apidojo/tweet-scraper)','{"incorporar":false,"relevancia":true,"sentimiento":true}',60,58,now() - interval '1 day',now() - interval '40 min','syntra-raw/c1/m1/p2/red-x.jsonl.gz');
UPDATE dat.ejecucion SET scraper_id = 1 WHERE id = 2;

-- Registros: los 2 del CSV (con su fecha sospechosa) y 3 del scraper del mockup
INSERT INTO dat.registro (cuenta_id, medicion_id, periodo, ejecucion_id, origen_id, red_id, scraper_id, url, url_hash, url_padre, fecha_publicacion, fecha_indexado, idioma, tipo_contenido, texto, autor_id_ext, autor_usuario, autor_nombre, autor_seguidores, pais, region, ciudad, es_rt, es_comentario, extra, sentimiento_fuente)
VALUES
 (6,4,202610,1,1,1,NULL,'http://twitter.com/yoanapower/status/2107905307280068787', decode(md5('http://twitter.com/yoanapower/status/2107905307280068787'),'hex'),'http://twitter.com/D_S_Iglesias/status/2107885857327956089','2026-10-07 12:46-06','2026-10-07 12:46-06','es','TEXT','RT @D_S_Iglesias: ☕️🖋️La vivienda necesita mayorías. La mentira necesita que olvidemos quién vota qué y quién gobierna dónde… (texto completo en el CSV)','tw:399487472','yoanapower','yoanapower',1580,'ES','Community of Madrid','Madrid',true,true,'{"matched_profile":"SEARCH / Cuadrangular Política / Tema 2: Marcha 2 oct","tags_internal":"isComment,isRepost,isQuestion","fecha_original":"2007-10-26 12:46"}',0),
 (6,4,202610,1,1,1,NULL,'http://twitter.com/SociedadN_/status/2107887931549745259', decode(md5('http://twitter.com/SociedadN_/status/2107887931549745259'),'hex'),'http://twitter.com/SociedadN_/status/2107887931549745259','2026-10-07 11:37-06','2026-10-07 11:37-06','es','LINK','CDHCM investiga ocho quejas por presuntas violaciones a derechos humanos durante la marcha del 2 de octubre en Tlatelolco y el Zócalo. Dos corresponden a periodistas. #PeriodismoParaTi #SociedadNoticias https://t.co/dzYBKberlt','tw:1367991524999503880','SociedadN_','Sociedad Noticias',566,'MX','Mexico City','Mexico City',false,false,'{"matched_profile":"SEARCH / Cuadrangular Política / Tema 2: Marcha 2 oct","entity_urls":[{"expanded_url":"https://sociedad-noticias.com/2026/10/07/cdhcm-investiga-ocho-quejas-por-presuntas-violaciones-durante-marcha-del-2-de-octubre/"}],"fecha_original":"2007-10-26 11:37"}',-5),
 (1,1,ops.fn_periodo(now() - interval '3 h'),2,3,1,1,'https://x.com/vecinos_cumbres/status/1880000000000000001', decode(md5('https://x.com/vecinos_cumbres/status/1880000000000000001'),'hex'),NULL, now() - interval '3 h', now() - interval '2 h','es','texto','Tres días sin agua en mi colonia. ¿Dónde está el gobernador Salazar? #SinAguaMty','x:9911','vecinos_cumbres','Vecinos Cumbres',2310,'MX','Nuevo León','Monterrey',false,false,NULL,NULL),
 (1,1,ops.fn_periodo(now() - interval '2 h'),2,3,1,1,'https://x.com/bot_alerta_9921/status/1880000000000000002', decode(md5('https://x.com/bot_alerta_9921/status/1880000000000000002'),'hex'),NULL, now() - interval '2 h', now(),'es','texto','El gobernador Salazar = corrupción, no se dejen engañar #AguaNL','x:5512','bot_alerta_9921','bot_alerta_9921',38,'MX',NULL,NULL,true,false,NULL,NULL),
 (1,1,ops.fn_periodo(now() - interval '1 h'),2,3,1,1,'https://x.com/promo_gym_mty/status/1880000000000000003', decode(md5('https://x.com/promo_gym_mty/status/1880000000000000003'),'hex'),NULL, now() - interval '1 h', now(),'es','texto','Promo de gimnasio: inscripción gratis todo octubre 💪','x:7781','promo_gym_mty','Gym MTY',9100,'MX',NULL,NULL,false,false,NULL,NULL);
-- Huella de deduplicación (la carga la escribe primero: INSERT … ON CONFLICT DO NOTHING RETURNING)
INSERT INTO dat.registro_huella (cuenta_id, medicion_id, url_hash, registro_id, periodo)
SELECT cuenta_id, medicion_id, url_hash, registro_id, periodo FROM dat.registro;
-- Estado inicial de cada registro (lo crea la carga en el mismo INSERT … SELECT)
INSERT INTO dat.registro_estado (cuenta_id, medicion_id, periodo, registro_id, relevancia, relevancia_ia, relevancia_pct, incorporado, incorporado_en, sentimiento, sentimiento_origen, es_bot, likes, comentarios, compartidos, reproducciones, alcance, st_relevancia, st_sentimiento, st_regex)
SELECT r.cuenta_id, r.medicion_id, r.periodo, r.registro_id, v.rel, v.rel_ia, v.pct, v.inc, CASE WHEN v.inc THEN now() END, v.sent, CASE WHEN v.sent IS NOT NULL THEN 'i' END, v.bot, v.likes, v.com, v.comp, 0, v.alc, v.st_rel, v.st_sen, 2
FROM dat.registro r JOIN (VALUES
  ('yoanapower',     1::smallint, 1::smallint, 71::smallint, true,  -1::smallint, NULL::boolean, 0::bigint, 0::bigint, 0::bigint, 1580::bigint, 2::smallint, 2::smallint),
  ('SociedadN_',     1, 1, 88, true,  -1, NULL,  0, 0, 0,  566, 2, 2),
  ('vecinos_cumbres',0, 1, 93, false, NULL, false, 41, 9, 12, 2900, 2, 0),
  ('bot_alerta_9921',0, 1, 76, false, NULL, true,   0, 0, 3,   40, 2, 0),
  ('promo_gym_mty',  0, 2, 12, false, NULL, false,  5, 0, 0,  300, 3, 0)
) v(autor, rel, rel_ia, pct, inc, sent, bot, likes, com, comp, alc, st_rel, st_sen) ON v.autor = r.autor_usuario;

INSERT INTO dat.registro_regex (cuenta_id, medicion_id, periodo, registro_id, regex_id, regex_version, coincidencias, proceso_id)
 SELECT r.cuenta_id, r.medicion_id, r.periodo, r.registro_id, 5, 1, 2, 1 FROM dat.registro r WHERE r.autor_usuario = 'SociedadN_'
 UNION ALL SELECT r.cuenta_id, r.medicion_id, r.periodo, r.registro_id, 2, 1, 1, 1 FROM dat.registro r WHERE r.autor_usuario = 'SociedadN_'
 UNION ALL SELECT r.cuenta_id, r.medicion_id, r.periodo, r.registro_id, 1, 2, 1, 2 FROM dat.registro r WHERE r.autor_usuario = 'vecinos_cumbres';
UPDATE dat.registro_estado e SET precluster_regex_id = 5 FROM dat.registro r WHERE r.registro_id = e.registro_id AND r.autor_usuario = 'SociedadN_';   -- primera en el orden de la medición 4
UPDATE dat.registro_estado e SET precluster_regex_id = 1 FROM dat.registro r WHERE r.registro_id = e.registro_id AND r.autor_usuario = 'vecinos_cumbres';
INSERT INTO dat.registro_cruce (cuenta_id, medicion_id, periodo, registro_id, cruce_id, items, proceso_id)
 SELECT cuenta_id, medicion_id, periodo, registro_id, 3, '{#SinAguaMty}', 2 FROM dat.registro WHERE autor_usuario = 'vecinos_cumbres';

-- Llamados LLM del proceso 3 (relevancia en lote de 25): uno falló en OpenAI y se resolvió con Gemini
INSERT INTO prc.llm_llamado (creado_en, proceso_id, tarea_id, cuenta_id, medicion_id, paso, proveedor_id, modelo_id, llave_id, intento, es_respaldo, registros_n, tokens_in, tokens_in_cache, tokens_out, costo_usd, latencia_ms, http_status, estado, error_codigo, request_id) VALUES
 (now() - interval '33 min', 3, 5, 1, 1, 2, 1, 1, 1, 1, false, 25, 5210, 600, 690, 0.001853, 4210, 200, 'ok', NULL, 'req_8Ks1'),
 (now() - interval '33 min', 3, 5, 1, 1, 2, 1, 1, 1, 1, false, 25, 5190, 600, 702, 0.001859, 3980, 429, 'reintento', 'rate_limit', 'req_8Ks2'),
 (now() - interval '33 min', 3, 5, 1, 1, 2, 1, 1, 1, 2, false, 25, 5190, 600, 0, 0, 30000, 504, 'reintento', 'timeout', 'req_8Ks3'),
 (now() - interval '33 min', 3, 5, 1, 1, 2, 1, 1, 1, 3, false, 25, 5190, 600, 0, 0, 30000, 504, 'error', 'timeout', 'req_8Ks4'),
 (now() - interval '32 min', 3, 5, 1, 1, 2, 2, 4, 3, 1, true, 25, 5320, 0, 655, 0.002100, 2890, 200, 'respaldo', NULL, 'gem_44a1');
INSERT INTO dat.llm_uso_registro (cuenta_id, medicion_id, periodo, registro_id, llamado_id, llamado_en, paso, tokens_in, tokens_out, costo_usd)
 SELECT r.cuenta_id, r.medicion_id, r.periodo, r.registro_id, l.id, l.creado_en, 2, 208, 27, 0.0000740
 FROM dat.registro r CROSS JOIN LATERAL (SELECT id, creado_en FROM prc.llm_llamado WHERE estado = 'ok' ORDER BY id LIMIT 1) l WHERE r.medicion_id = 1;
INSERT INTO dat.registro_evento (cuenta_id, medicion_id, periodo, registro_id, paso, proceso_id, tarea_id, intento, estado, codigo_error, mensaje, detalle)
 SELECT cuenta_id, medicion_id, periodo, registro_id, 2, 3, 5, 3, 3, 'LLM_TIMEOUT', 'OpenAI agotó 3 intentos; resuelto con Gemini en el llamado de respaldo', '{"llamados":[2,3,4,5]}'
 FROM dat.registro WHERE autor_usuario = 'promo_gym_mty';
INSERT INTO dat.registro_evento (cuenta_id, medicion_id, periodo, registro_id, paso, proceso_id, intento, estado, codigo_error, mensaje, detalle)
 SELECT cuenta_id, medicion_id, periodo, registro_id, 1, 1, 1, 2, 'FECHA_CORREGIDA',
        'published 2007-10-26 < fecha_min del formato. Se leyó 07/10/26 (dd/mm/aa) como aa/mm/dd; corregida a 2026-10-07. El ID del tweet confirma la fecha (18:46 UTC = 12:46 UTC−6).',
        jsonb_build_object('columna','published','valor_original', extra->>'fecha_original','regla','invertir_aa_dd','verificacion','snowflake_id')
 FROM dat.registro WHERE medicion_id = 4;

INSERT INTO aud.auditoria (fecha, usuario_id, modulo, accion, entidad_tipo, entidad_id, entidad_nombre, antes, despues, detalle, ip) VALUES
 (now() - interval '1 h', 2, 'Scraper', 'Actualización', 'scraper', '1', 'Monitoreo continuo · crisis del agua', '{"frecuencia_min":60}', '{"frecuencia_min":30}', 'Proceso de scraping', '190.85.12.4'),
 (now() - interval '20 min', 1, 'Medición', 'Carga', 'archivo', '1', 'DBFormatoSimple.csv', NULL, '{"filas":2}', 'Carga de archivo', '190.85.12.9'),
 (now() - interval '5 min', 1, 'Medición', 'Actualización', 'medicion', '1', 'Crisis del agua en Monterrey — octubre 2026', '{"x_num_menciones":0,"x_num_cuentas":50}', '{"x_num_menciones":394,"x_num_cuentas":70}', 'Confirmación de parámetros de X antes de generar el informe', '190.85.12.9');
INSERT INTO aud.notificacion (usuario_id, titulo, cuerpo, enlace, tipo, proceso_id) VALUES
 (1,'Carga de archivos: con advertencias','Cuadrangular política · 2 registros · fechas sospechosas','/mediciones/4?tab=procesamiento','warn',1),
 (2,'Registros por fiscalizar','Crisis del agua en Monterrey: 148 registros del scrapper esperan revisión.','/mediciones/1?tab=fiscalizacion','warn',2);

-- Consumo agregado (lo hace el cierre de cada proceso)
INSERT INTO prc.llm_consumo_dia
 SELECT creado_en::date, cuenta_id, medicion_id, paso, proveedor_id, modelo_id, llave_id, count(*), count(*) FILTER (WHERE estado IN ('error','reintento')), sum(registros_n), sum(tokens_in), sum(tokens_out), sum(costo_usd)
 FROM prc.llm_llamado GROUP BY 1,2,3,4,5,6,7;


-- =====================================================================================
-- SYNTRA · Syntra_schema.sql
-- Aplicar DESPUÉS del modelo base. Compatible objetivo PostgreSQL 16+.
-- Este archivo complementa el modelo; no es un reemplazo íntegro del SQL base.
--
-- Decisiones respetadas:
--   * Se conservan los GRANT ampliados existentes.
--   * La validación relacional de alto volumen no se amplía en tablas operacionales.
--   * Los CHECK operacionales se agregan NOT VALID: protegen nuevas escrituras sin
--     escanear todo el histórico durante esta migración. Su validación histórica se
--     puede hacer después, en mantenimiento.
--   * El control de cuotas/circuitos es una primitiva centralizada: todos los adaptadores
--     worker deben reservar antes de llamar al LLM y reportar su resultado después.
-- =====================================================================================

BEGIN;

-- -------------------------------------------------------------------------------------
-- 1.A · LISTEN/NOTIFY: avisar también cuando una tarea vuelve a en_cola por UPDATE.
--      Las notificaciones solo despiertan; prc.proceso_tarea sigue siendo la fuente de verdad.
-- -------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS tg_tarea_notificar ON prc.proceso_tarea;
DROP TRIGGER IF EXISTS tg_tarea_notificar_reencolada ON prc.proceso_tarea;

CREATE OR REPLACE FUNCTION prc.fn_notificar_cola_insert()
RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE c text;
BEGIN
  FOR c IN SELECT DISTINCT n.cola FROM nuevas n WHERE n.estado = 'en_cola' LOOP
    PERFORM pg_notify('cola', c);
  END LOOP;
  RETURN NULL;
END
$fn$;

CREATE OR REPLACE FUNCTION prc.fn_notificar_cola_update()
RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE c text;
BEGIN
  FOR c IN
    SELECT DISTINCT n.cola
    FROM nuevas n
    JOIN antiguas a ON a.id = n.id
    WHERE n.estado = 'en_cola'
      AND a.estado IS DISTINCT FROM n.estado
  LOOP
    PERFORM pg_notify('cola', c);
  END LOOP;
  RETURN NULL;
END
$fn$;

CREATE TRIGGER tg_tarea_notificar
AFTER INSERT ON prc.proceso_tarea
REFERENCING NEW TABLE AS nuevas
FOR EACH STATEMENT EXECUTE FUNCTION prc.fn_notificar_cola_insert();

CREATE TRIGGER tg_tarea_notificar_reencolada
AFTER UPDATE ON prc.proceso_tarea
REFERENCING OLD TABLE AS antiguas NEW TABLE AS nuevas
FOR EACH STATEMENT EXECUTE FUNCTION prc.fn_notificar_cola_update();

COMMENT ON FUNCTION prc.fn_notificar_cola_update() IS
'Notifica las tareas que pasan a en_cola mediante UPDATE. El worker también debe sondear periódicamente para cubrir notificaciones perdidas.';

-- -------------------------------------------------------------------------------------
-- 1.B · Recuperación con límite de intentos y backoff exponencial.
--       La operación se identifica con proceso_tarea.tipo y se busca en ops.politica_reintento.
-- -------------------------------------------------------------------------------------
ALTER TABLE ops.politica_reintento
  ADD COLUMN IF NOT EXISTS circuito_espera_ms int NOT NULL DEFAULT 30000;

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'ops.politica_reintento'::regclass AND conname = 'ck_politica_reintento_valores') THEN
    ALTER TABLE ops.politica_reintento
      ADD CONSTRAINT ck_politica_reintento_valores
      CHECK (max_intentos >= 1 AND backoff_base_ms >= 0 AND backoff_max_ms >= backoff_base_ms
             AND timeout_ms > 0 AND circuito_umbral >= 1 AND circuito_espera_ms > 0) NOT VALID;
  END IF;
END
$do$;

CREATE OR REPLACE FUNCTION prc.fn_rescatar_tareas(p_segundos int DEFAULT 60)
RETURNS int LANGUAGE sql AS $fn$
  WITH candidatas AS (
    SELECT t.id, t.intentos,
           COALESCE(p.max_intentos, 3)::int AS max_intentos,
           COALESCE(p.backoff_base_ms, 1000)::int AS backoff_base_ms,
           COALESCE(p.backoff_max_ms, 30000)::int AS backoff_max_ms
    FROM prc.proceso_tarea t
    LEFT JOIN ops.politica_reintento p ON p.operacion = COALESCE(t.payload->>'operacion', t.tipo)
    WHERE t.estado = 'en_ejecucion'
      AND COALESCE(t.latido, t.iniciado_en) < clock_timestamp() - make_interval(secs => GREATEST(p_segundos, 1))
    ORDER BY COALESCE(t.latido, t.iniciado_en), t.id
    LIMIT 1000
    FOR UPDATE OF t SKIP LOCKED
  ), rescatadas AS (
    UPDATE prc.proceso_tarea t
       SET estado = CASE WHEN c.intentos >= c.max_intentos THEN 'error' ELSE 'en_cola' END,
           worker = NULL,
           latido = NULL,
           disponible_en = CASE
             WHEN c.intentos >= c.max_intentos THEN t.disponible_en
             ELSE clock_timestamp() + make_interval(secs =>
               (LEAST(c.backoff_max_ms::numeric,
                      c.backoff_base_ms::numeric * power(2::numeric, LEAST(GREATEST(c.intentos - 1, 0), 20))) / 1000.0)::double precision)
           END,
           finalizado_en = CASE WHEN c.intentos >= c.max_intentos THEN clock_timestamp() ELSE NULL END,
           error_codigo = CASE WHEN c.intentos >= c.max_intentos THEN 'MAX_INTENTOS_WORKER_PERDIDO' ELSE 'WORKER_PERDIDO' END,
           error_mensaje = CASE
             WHEN c.intentos >= c.max_intentos THEN 'Worker perdido; se agotó el máximo de intentos configurado.'
             ELSE 'Worker perdido; tarea reencolada con backoff.'
           END
      FROM candidatas c
     WHERE t.id = c.id
    RETURNING t.id
  )
  SELECT count(*)::int FROM rescatadas
$fn$;

COMMENT ON FUNCTION prc.fn_rescatar_tareas(int) IS
'Recupera tareas cuyo latido venció. Respeta ops.politica_reintento.max_intentos y backoff; las tareas agotadas pasan a error. Se recomienda ejecutarla desde el scheduler.';

-- -------------------------------------------------------------------------------------
-- 2. Particiones · concurrencia segura al preparar hojas y particiones mensuales iniciales.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.fn_crear_y_adjuntar(
  p_padre text, p_hija text, p_valor int, p_subparticion text, p_opciones text
) RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE
  v_padre regclass;
  v_hija regclass;
BEGIN
  -- Serializa intentos concurrentes para la misma pareja padre/hija.
  PERFORM pg_advisory_xact_lock(
    hashtextextended(format('syntra:partition:dat.%s:dat.%s', p_padre, p_hija), 0)
  );

  v_padre := to_regclass(format('dat.%I', p_padre));
  IF v_padre IS NULL THEN
    RAISE EXCEPTION 'No existe la tabla padre dat.%', p_padre;
  END IF;

  v_hija := to_regclass(format('dat.%I', p_hija));
  IF v_hija IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM pg_inherits WHERE inhparent = v_padre AND inhrelid = v_hija) THEN
      RETURN false; -- ya está adjunta al padre correcto
    END IF;
    RAISE EXCEPTION 'La tabla dat.% ya existe, pero no está adjunta a dat.%', p_hija, p_padre;
  END IF;

  EXECUTE format(
    'CREATE TABLE dat.%I (LIKE dat.%I INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING CONSTRAINTS INCLUDING STORAGE)%s%s',
    p_hija, p_padre,
    CASE WHEN p_subparticion IS NOT NULL THEN format(' PARTITION BY LIST (%I)', p_subparticion) ELSE '' END,
    CASE WHEN p_opciones IS NOT NULL THEN ' WITH (' || p_opciones || ')' ELSE '' END
  );
  EXECUTE format('ALTER TABLE dat.%I ATTACH PARTITION dat.%I FOR VALUES IN (%s)', p_padre, p_hija, p_valor);
  RETURN true;
END
$fn$;

CREATE OR REPLACE FUNCTION ops.fn_particiones_mensuales(p_desde date, p_meses int)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
  r record;
  m date;
  nom text;
  v_desde_utc text;
  v_hasta_utc text;
BEGIN
  IF p_meses < 0 OR p_meses > 120 THEN
    RAISE EXCEPTION 'p_meses debe estar entre 0 y 120';
  END IF;

  FOR r IN SELECT * FROM (VALUES ('prc','llm_llamado'),('prc','proceso_log'),('aud','auditoria')) v(esq, tab) LOOP
    FOR i IN 0..p_meses LOOP
      m := (date_trunc('month', p_desde)::date + make_interval(months => i))::date;
      nom := format('%s_%s', r.tab, to_char(m, 'YYYYMM'));
      -- Los límites de tablas timestamptz quedan explícitamente en UTC, sin depender de TimeZone de sesión.
      v_desde_utc := to_char(m, 'YYYY-MM-DD') || ' 00:00:00+00';
      v_hasta_utc := to_char((m + interval '1 month')::date, 'YYYY-MM-DD') || ' 00:00:00+00';

      PERFORM pg_advisory_xact_lock(hashtextextended(format('syntra:monthly:%s.%s', r.esq, nom), 0));
      IF to_regclass(format('%I.%I', r.esq, nom)) IS NULL THEN
        EXECUTE format(
          'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L::timestamptz) TO (%L::timestamptz)',
          r.esq, nom, r.esq, r.tab, v_desde_utc, v_hasta_utc
        );
      END IF;
    END LOOP;
  END LOOP;
END
$fn$;

-- Inicializa el mes actual de Bogotá y los tres meses siguientes durante la instalación.
-- El scheduler debe mantener el horizonte actualizado cada día.
SELECT ops.fn_particiones_mensuales((now() AT TIME ZONE 'America/Bogota')::date, 3);

-- -------------------------------------------------------------------------------------
-- 3. Integridad de datos maestros, sin nuevos FK entre tablas operacionales de alto volumen.
--    No se modifican los GRANT ampliados aprobados.
-- -------------------------------------------------------------------------------------
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'med.medicion_prompt'::regclass AND conname = 'ck_medicion_prompt_version_pareja') THEN
    ALTER TABLE med.medicion_prompt
      ADD CONSTRAINT ck_medicion_prompt_version_pareja
      CHECK ((prompt_id IS NULL AND prompt_version IS NULL) OR
             (prompt_id IS NOT NULL AND prompt_version IS NOT NULL)) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'med.medicion_prompt'::regclass AND conname = 'fk_medicion_prompt_version') THEN
    ALTER TABLE med.medicion_prompt
      ADD CONSTRAINT fk_medicion_prompt_version
      FOREIGN KEY (prompt_id, prompt_version)
      REFERENCES cfg.prompt_version(prompt_id, version) NOT VALID;
  END IF;
END
$do$;

COMMENT ON TABLE med.medicion_prompt IS
'Prompts congelados por medición. Si prompt_id tiene valor, prompt_version debe identificar una versión existente; contenido conserva la copia exacta usada.';

-- -------------------------------------------------------------------------------------
-- 4. Medición de duración por etapa (proceso) y por paso de cada publicación.
-- -------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prc.proceso_paso (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proceso_id bigint NOT NULL REFERENCES prc.proceso(id) ON DELETE CASCADE,
  paso_id smallint NOT NULL REFERENCES cat.paso(id),
  secuencia smallint NOT NULL DEFAULT 1,
  estado smallint NOT NULL DEFAULT 0 CHECK (estado BETWEEN 0 AND 4),
  iniciado_en timestamptz,
  finalizado_en timestamptz,
  duracion_ms bigint GENERATED ALWAYS AS (
    CASE WHEN iniciado_en IS NULL OR finalizado_en IS NULL THEN NULL
         ELSE (extract(epoch FROM (finalizado_en - iniciado_en)) * 1000)::bigint END
  ) STORED,
  total_registros bigint NOT NULL DEFAULT 0,
  procesados bigint NOT NULL DEFAULT 0,
  ok bigint NOT NULL DEFAULT 0,
  errores bigint NOT NULL DEFAULT 0,
  tareas_totales int NOT NULL DEFAULT 0,
  tareas_completadas int NOT NULL DEFAULT 0,
  stats jsonb NOT NULL DEFAULT '{}',
  error_codigo text,
  error_mensaje text,
  creado_en timestamptz NOT NULL DEFAULT now(),
  actualizado_en timestamptz NOT NULL DEFAULT now(),
  UNIQUE (proceso_id, paso_id, secuencia),
  CHECK (finalizado_en IS NULL OR iniciado_en IS NULL OR finalizado_en >= iniciado_en)
);
CREATE INDEX IF NOT EXISTS ix_proceso_paso_proceso ON prc.proceso_paso (proceso_id, secuencia, paso_id);
CREATE INDEX IF NOT EXISTS ix_proceso_paso_activos ON prc.proceso_paso (estado, iniciado_en) WHERE estado IN (0,1,3);

ALTER TABLE prc.proceso_tarea
  ADD COLUMN IF NOT EXISTS proceso_paso_id bigint;
ALTER TABLE prc.proceso_tarea
  ADD COLUMN IF NOT EXISTS duracion_ms bigint GENERATED ALWAYS AS (
    CASE WHEN iniciado_en IS NULL OR finalizado_en IS NULL THEN NULL
         ELSE (extract(epoch FROM (finalizado_en - iniciado_en)) * 1000)::bigint END
  ) STORED;
-- Relación lógica sin FK operacional adicional; el worker valida que el ID de etapa pertenezca al proceso.
CREATE INDEX IF NOT EXISTS ix_tarea_proceso_paso ON prc.proceso_tarea (proceso_paso_id) WHERE proceso_paso_id IS NOT NULL;

-- Tiempo individual por registro y paso. Se particiona siguiendo el árbol de dat.*; sin FK a
-- dat.registro para no añadir comprobaciones referenciales en el camino masivo de escritura.
CREATE TABLE IF NOT EXISTS dat.registro_paso_tiempo (
  cuenta_id int NOT NULL,
  medicion_id int NOT NULL,
  periodo int NOT NULL,
  registro_id bigint NOT NULL,
  paso smallint NOT NULL,
  intento smallint NOT NULL DEFAULT 1,
  estado smallint NOT NULL DEFAULT 1,
  iniciado_en timestamptz NOT NULL DEFAULT clock_timestamp(),
  finalizado_en timestamptz,
  duracion_ms bigint GENERATED ALWAYS AS (
    CASE WHEN finalizado_en IS NULL THEN NULL
         ELSE (extract(epoch FROM (finalizado_en - iniciado_en)) * 1000)::bigint END
  ) STORED,
  proceso_id bigint,
  tarea_id bigint,
  worker text,
  error_codigo text,
  error_mensaje text,
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cuenta_id, medicion_id, periodo, registro_id, paso, intento),
  CHECK (estado BETWEEN 0 AND 4),
  CHECK (finalizado_en IS NULL OR finalizado_en >= iniciado_en)
) PARTITION BY LIST (cuenta_id);
CREATE INDEX IF NOT EXISTS ix_reg_paso_tiempo_activo
  ON dat.registro_paso_tiempo (medicion_id, estado, iniciado_en) WHERE estado IN (0,1,3);
CREATE INDEX IF NOT EXISTS ix_reg_paso_tiempo_proceso
  ON dat.registro_paso_tiempo (proceso_id, creado_en DESC);
COMMENT ON TABLE dat.registro_paso_tiempo IS
'Una fila por publicación, paso e intento. Abrir el registro al iniciar; actualizar finalizado_en, estado y duración al concluir. Los workers deben usar INSERT/UPSERT idempotente. La función ops.fn_tablas_dat detectará esta raíz de particiones automáticamente.';

-- -------------------------------------------------------------------------------------
-- 5. Estados st_* y estados operacionales: valores 0..4.
--    NOT VALID evita escanear todo el histórico durante esta instalación; protege nuevas escrituras.
-- -------------------------------------------------------------------------------------
DO $do$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT * FROM (VALUES
      ('dat.registro_estado','ck_re_estado_st_relevancia','st_relevancia BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_sentimiento','st_sentimiento BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_transcripcion','st_transcripcion BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_metricas','st_metricas BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_regex','st_regex BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_cruces','st_cruces BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_embedding','st_embedding BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_cluster','st_cluster BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_bots','st_bots BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_st_publicacion','st_publicacion BETWEEN 0 AND 4'),
      ('dat.registro_estado','ck_re_estado_logico','estado_id IN (-1,0,1)'),
      ('dat.registro_media','ck_registro_media_estado','estado BETWEEN 0 AND 4'),
      ('dat.registro_evento','ck_registro_evento_estado','estado BETWEEN 0 AND 4')
    ) AS x(tabla, restriccion, expresion)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = to_regclass(r.tabla) AND conname = r.restriccion
    ) THEN
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I CHECK (%s) NOT VALID',
                     to_regclass(r.tabla), r.restriccion, r.expresion);
    END IF;
  END LOOP;
END
$do$;

-- -------------------------------------------------------------------------------------
-- 5. Huella: SHA-256 sobre la URL canónica; si no hay URL, usar autor+fecha+texto.
--    El cargador debe aplicar la misma normalización antes de insertar en registro y huella.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.fn_hash_registro(
  p_url text, p_autor text, p_fecha timestamptz, p_texto text
) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
  SELECT digest(
    convert_to(
      CASE
        WHEN NULLIF(btrim(p_url), '') IS NOT NULL THEN
          'url:' || regexp_replace(btrim(p_url), '#.*$', '')
        ELSE
          'sin_url:' || lower(regexp_replace(btrim(COALESCE(p_autor, '')), '\s+', ' ', 'g')) || '|' ||
          COALESCE(to_char(p_fecha AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), '') || '|' ||
          lower(regexp_replace(btrim(COALESCE(p_texto, '')), '\s+', ' ', 'g'))
      END,
      'UTF8'
    ),
    'sha256'
  )
$fn$;
COMMENT ON FUNCTION ops.fn_hash_registro(text,text,timestamptz,text) IS
'Genera huella SHA-256 (32 bytes). La URL debe llegar canónica desde el cargador; la función elimina espacios exteriores y el fragmento #. Si no hay URL, usa autor, fecha UTC y texto normalizado.';
COMMENT ON COLUMN dat.registro.url_hash IS 'Huella SHA-256 (bytea de 32 bytes) de ops.fn_hash_registro; no usar MD5.';
COMMENT ON COLUMN dat.registro_huella.url_hash IS 'Huella SHA-256 (bytea de 32 bytes), compartida entre datos activos e históricos.';

-- -------------------------------------------------------------------------------------
-- 5. Zona horaria: fechas agregadas e informes de consumo en la hora de Bogotá.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.fn_corte_archivo(
  p_hoy date DEFAULT ((now() AT TIME ZONE 'America/Bogota')::date)
) RETURNS int LANGUAGE sql STABLE AS $fn$
  SELECT to_char(
           date_trunc('month', p_hoy) - make_interval(months => coalesce(
             (SELECT (valor #>> '{}')::int FROM ops.parametro WHERE clave = 'archivo.meses_principal'), 3)),
           'YYYYMM'
         )::int
$fn$;

CREATE OR REPLACE VIEW prc.v_consumo_llm AS
  SELECT (l.creado_en AT TIME ZONE 'America/Bogota')::date AS fecha,
         l.cuenta_id, l.medicion_id, p.codigo AS paso,
         pr.codigo AS proveedor, mo.nombre AS modelo, k.alias AS llave,
         count(*) AS llamados,
         count(*) FILTER (WHERE l.estado = 'error') AS errores,
         count(*) FILTER (WHERE l.es_respaldo) AS por_respaldo,
         sum(l.registros_n) AS registros,
         sum(l.tokens_in) AS tokens_in,
         sum(l.tokens_out) AS tokens_out,
         sum(l.tokens_total) AS tokens_total,
         sum(l.costo_usd) AS costo_usd
  FROM prc.llm_llamado l
  JOIN cat.paso p ON p.id = l.paso
  JOIN cfg.llm_proveedor pr ON pr.id = l.proveedor_id
  JOIN cfg.llm_modelo mo ON mo.id = l.modelo_id
  JOIN cfg.llm_llave k ON k.id = l.llave_id
  GROUP BY 1,2,3,4,5,6,7;

COMMENT ON COLUMN prc.llm_consumo_dia.fecha IS 'Fecha de negocio según America/Bogota; el agregador debe derivarla con (creado_en AT TIME ZONE ''America/Bogota'')::date.';

-- -------------------------------------------------------------------------------------
-- 6. LLM · reserva atómica de cuota compartida por organización/proyecto y circuit breaker.
--    Si una llave no declara organización/proyecto, la cuota se aplica solo a esa llave.
-- -------------------------------------------------------------------------------------
ALTER TABLE cfg.llm_llave
  ADD COLUMN IF NOT EXISTS fallos_consecutivos int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS circuito_abierto_hasta timestamptz,
  ADD COLUMN IF NOT EXISTS prueba_en_curso boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS prueba_reservada_en timestamptz,
  ADD COLUMN IF NOT EXISTS ultimo_fallo_en timestamptz;

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'cfg.llm_llave'::regclass AND conname = 'ck_llm_llave_limites_positivos') THEN
    ALTER TABLE cfg.llm_llave ADD CONSTRAINT ck_llm_llave_limites_positivos
      CHECK (rpm_limite > 0 AND tpm_limite > 0 AND fallos_consecutivos >= 0) NOT VALID;
  END IF;
END
$do$;

CREATE TABLE IF NOT EXISTS prc.llm_cuota_minuto (
  scope_key text NOT NULL,
  ventana timestamptz NOT NULL,
  llamadas int NOT NULL DEFAULT 0,
  tokens_reservados bigint NOT NULL DEFAULT 0,
  actualizado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scope_key, ventana),
  CHECK (llamadas >= 0 AND tokens_reservados >= 0)
);

CREATE TABLE IF NOT EXISTS prc.llm_reserva (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  llave_id int NOT NULL REFERENCES cfg.llm_llave(id),
  scope_key text NOT NULL,
  ventana timestamptz NOT NULL,
  tokens_estimados bigint NOT NULL,
  tokens_reales bigint,
  estado text NOT NULL DEFAULT 'reservada' CHECK (estado IN ('reservada','cerrada','liberada')),
  es_prueba boolean NOT NULL DEFAULT false,
  creado_en timestamptz NOT NULL DEFAULT now(),
  cerrado_en timestamptz,
  CHECK (tokens_estimados >= 0),
  CHECK (tokens_reales IS NULL OR tokens_reales >= 0)
);
CREATE INDEX IF NOT EXISTS ix_llm_reserva_abierta ON prc.llm_reserva (creado_en) WHERE estado = 'reservada';

CREATE OR REPLACE FUNCTION prc.fn_candidatos_llm(
  p_operacion text,
  p_uso text,
  p_proveedor_excluido smallint DEFAULT NULL
) RETURNS TABLE (
  proveedor_id smallint,
  proveedor text,
  modelo_id int,
  modelo text,
  llave_id int,
  alias_llave text,
  es_respaldo boolean,
  rpm_limite int,
  tpm_limite bigint
) LANGUAGE sql STABLE AS $fn$
  WITH politica AS (
    SELECT COALESCE((SELECT usar_respaldo FROM ops.politica_reintento WHERE operacion = p_operacion), false) AS usar_respaldo
  )
  SELECT pr.id, pr.codigo, mo.id, mo.nombre, k.id, k.alias,
         (p_proveedor_excluido IS NOT NULL OR pr.prioridad > 1) AS es_respaldo,
         k.rpm_limite, k.tpm_limite
  FROM cfg.llm_proveedor pr
  JOIN cfg.llm_modelo mo ON mo.proveedor_id = pr.id AND mo.estado_id = 1 AND mo.uso = p_uso
  JOIN cfg.llm_llave k ON k.proveedor_id = pr.id AND k.estado_id = 1
  CROSS JOIN politica pol
  WHERE pr.estado_id = 1
    AND (
      (p_proveedor_excluido IS NULL AND pr.prioridad = 1)
      OR
      (p_proveedor_excluido IS NOT NULL AND pol.usar_respaldo AND pr.id <> p_proveedor_excluido)
    )
    AND (k.circuito <> 'abierto' OR k.circuito_abierto_hasta <= now())
  ORDER BY CASE WHEN p_proveedor_excluido IS NULL THEN pr.prioridad ELSE 0 END,
           mo.prioridad, k.prioridad, k.id
$fn$;

CREATE OR REPLACE FUNCTION prc.fn_reservar_llm(
  p_llave_id int,
  p_tokens_estimados bigint
) RETURNS TABLE (
  admitido boolean,
  reserva_id uuid,
  motivo text,
  ventana timestamptz
) LANGUAGE plpgsql AS $fn$
DECLARE
  v_key cfg.llm_llave%ROWTYPE;
  v_rpm int;
  v_tpm bigint;
  v_scope text;
  v_window timestamptz;
  v_probe boolean := false;
  v_probe_time timestamptz;
  v_calls int;
  v_reserva uuid;
BEGIN
  IF p_tokens_estimados IS NULL OR p_tokens_estimados < 0 THEN
    RETURN QUERY SELECT false, NULL::uuid, 'TOKENS_ESTIMADOS_INVALIDOS', NULL::timestamptz;
    RETURN;
  END IF;

  SELECT * INTO v_key FROM cfg.llm_llave WHERE id = p_llave_id;
  IF NOT FOUND OR v_key.estado_id <> 1 THEN
    RETURN QUERY SELECT false, NULL::uuid, 'LLAVE_INACTIVA_O_INEXISTENTE', NULL::timestamptz;
    RETURN;
  END IF;
  IF v_key.rpm_limite <= 0 OR v_key.tpm_limite <= 0 THEN
    RETURN QUERY SELECT false, NULL::uuid, 'CUOTA_MAL_CONFIGURADA', NULL::timestamptz;
    RETURN;
  END IF;

  -- Límites reales compartidos por proveedor/organización/proyecto; sin ámbito, límite por llave.
  IF NULLIF(btrim(v_key.organizacion), '') IS NOT NULL OR NULLIF(btrim(v_key.proyecto), '') IS NOT NULL THEN
    v_scope := jsonb_build_array(v_key.proveedor_id, COALESCE(btrim(v_key.organizacion), ''), COALESCE(btrim(v_key.proyecto), ''))::text;
    SELECT COALESCE(min(k.rpm_limite), v_key.rpm_limite), COALESCE(min(k.tpm_limite), v_key.tpm_limite)
      INTO v_rpm, v_tpm
      FROM cfg.llm_llave k
     WHERE k.proveedor_id = v_key.proveedor_id
       AND NULLIF(btrim(k.organizacion), '') IS NOT DISTINCT FROM NULLIF(btrim(v_key.organizacion), '')
       AND NULLIF(btrim(k.proyecto), '') IS NOT DISTINCT FROM NULLIF(btrim(v_key.proyecto), '')
       AND k.estado_id = 1;
  ELSE
    v_scope := jsonb_build_array('llave', v_key.id)::text;
    v_rpm := v_key.rpm_limite;
    v_tpm := v_key.tpm_limite;
  END IF;

  IF p_tokens_estimados > v_tpm THEN
    RETURN QUERY SELECT false, NULL::uuid, 'LLAMADO_SUPERA_TPM', NULL::timestamptz;
    RETURN;
  END IF;

  -- Solo una prueba de recuperación al pasar de abierto a semiabierto.
  IF v_key.circuito = 'abierto' THEN
    IF v_key.circuito_abierto_hasta IS NULL OR v_key.circuito_abierto_hasta > clock_timestamp() THEN
      RETURN QUERY SELECT false, NULL::uuid, 'CIRCUITO_ABIERTO', NULL::timestamptz;
      RETURN;
    END IF;
    UPDATE cfg.llm_llave k
       SET circuito = 'semiabierto', prueba_en_curso = true, prueba_reservada_en = clock_timestamp()
     WHERE k.id = p_llave_id AND k.circuito = 'abierto' AND k.circuito_abierto_hasta <= clock_timestamp()
     RETURNING k.prueba_reservada_en INTO v_probe_time;
    IF NOT FOUND THEN
      RETURN QUERY SELECT false, NULL::uuid, 'CIRCUITO_CAMBIO_CONCURRENTE', NULL::timestamptz;
      RETURN;
    END IF;
    v_probe := true;
  ELSIF v_key.circuito = 'semiabierto' THEN
    UPDATE cfg.llm_llave k
       SET prueba_en_curso = true, prueba_reservada_en = clock_timestamp()
     WHERE k.id = p_llave_id AND k.circuito = 'semiabierto'
       AND (NOT k.prueba_en_curso OR k.prueba_reservada_en IS NULL OR k.prueba_reservada_en < clock_timestamp() - interval '60 seconds')
     RETURNING k.prueba_reservada_en INTO v_probe_time;
    IF NOT FOUND THEN
      RETURN QUERY SELECT false, NULL::uuid, 'CIRCUITO_PRUEBA_EN_CURSO', NULL::timestamptz;
      RETURN;
    END IF;
    v_probe := true;
  END IF;

  v_window := date_trunc('minute', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';

  INSERT INTO prc.llm_cuota_minuto AS q (scope_key, ventana, llamadas, tokens_reservados, actualizado_en)
  VALUES (v_scope, v_window, 1, p_tokens_estimados, clock_timestamp())
  ON CONFLICT (scope_key, ventana) DO UPDATE
     SET llamadas = q.llamadas + 1,
         tokens_reservados = q.tokens_reservados + EXCLUDED.tokens_reservados,
         actualizado_en = clock_timestamp()
   WHERE q.llamadas < v_rpm
     AND q.tokens_reservados + EXCLUDED.tokens_reservados <= v_tpm
  RETURNING llamadas INTO v_calls;

  IF NOT FOUND THEN
    IF v_probe THEN
      UPDATE cfg.llm_llave SET prueba_en_curso = false, prueba_reservada_en = NULL
       WHERE id = p_llave_id AND circuito = 'semiabierto' AND prueba_reservada_en = v_probe_time;
    END IF;
    RETURN QUERY SELECT false, NULL::uuid, 'LIMITE_RPM_O_TPM', v_window;
    RETURN;
  END IF;

  INSERT INTO prc.llm_reserva (llave_id, scope_key, ventana, tokens_estimados, es_prueba)
  VALUES (p_llave_id, v_scope, v_window, p_tokens_estimados, v_probe)
  RETURNING id INTO v_reserva;

  RETURN QUERY SELECT true, v_reserva, 'OK', v_window;
END
$fn$;

CREATE OR REPLACE FUNCTION prc.fn_finalizar_reserva_llm(
  p_reserva_id uuid,
  p_tokens_reales bigint DEFAULT 0
) RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE v_reserva prc.llm_reserva%ROWTYPE;
BEGIN
  IF p_tokens_reales IS NULL OR p_tokens_reales < 0 THEN
    RAISE EXCEPTION 'p_tokens_reales debe ser >= 0';
  END IF;

  UPDATE prc.llm_reserva r
     SET estado = 'cerrada', tokens_reales = p_tokens_reales, cerrado_en = clock_timestamp()
   WHERE r.id = p_reserva_id AND r.estado = 'reservada'
  RETURNING r.* INTO v_reserva;
  IF NOT FOUND THEN
    RETURN false; -- ya cerrada/liberada: operación idempotente
  END IF;

  UPDATE prc.llm_cuota_minuto q
     SET tokens_reservados = GREATEST(0, q.tokens_reservados + p_tokens_reales - v_reserva.tokens_estimados),
         actualizado_en = clock_timestamp()
   WHERE q.scope_key = v_reserva.scope_key AND q.ventana = v_reserva.ventana;
  RETURN true;
END
$fn$;

CREATE OR REPLACE FUNCTION prc.fn_liberar_reserva_llm(p_reserva_id uuid)
RETURNS boolean LANGUAGE plpgsql AS $fn$
DECLARE v_reserva prc.llm_reserva%ROWTYPE;
BEGIN
  UPDATE prc.llm_reserva r
     SET estado = 'liberada', tokens_reales = 0, cerrado_en = clock_timestamp()
   WHERE r.id = p_reserva_id AND r.estado = 'reservada'
  RETURNING r.* INTO v_reserva;
  IF NOT FOUND THEN RETURN false; END IF;

  UPDATE prc.llm_cuota_minuto q
     SET llamadas = GREATEST(0, q.llamadas - 1),
         tokens_reservados = GREATEST(0, q.tokens_reservados - v_reserva.tokens_estimados),
         actualizado_en = clock_timestamp()
   WHERE q.scope_key = v_reserva.scope_key AND q.ventana = v_reserva.ventana;
  -- Si la reserva era la prueba de recuperación y el HTTP ni siquiera se envió, liberar la prueba.
  UPDATE cfg.llm_llave SET prueba_en_curso = false, prueba_reservada_en = NULL
   WHERE id = v_reserva.llave_id AND circuito = 'semiabierto';
  RETURN true;
END
$fn$;

DROP FUNCTION IF EXISTS prc.fn_registrar_resultado_llm(int,text,boolean);
CREATE OR REPLACE FUNCTION prc.fn_registrar_resultado_llm(
  p_llave_id int,
  p_operacion text,
  p_ok boolean,
  p_reserva_id uuid
) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
  v_umbral int;
  v_espera_ms int;
  v_es_prueba boolean;
BEGIN
  SELECT r.es_prueba INTO v_es_prueba
    FROM prc.llm_reserva r
   WHERE r.id = p_reserva_id AND r.llave_id = p_llave_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'No existe reserva % para la llave %', p_reserva_id, p_llave_id;
  END IF;

  SELECT COALESCE(circuito_umbral, 20), COALESCE(circuito_espera_ms, 30000)
    INTO v_umbral, v_espera_ms
    FROM ops.politica_reintento WHERE operacion = p_operacion;
  IF NOT FOUND THEN
    v_umbral := 20;
    v_espera_ms := 30000;
  END IF;

  IF p_ok THEN
    UPDATE cfg.llm_llave k
       SET fallos_consecutivos = CASE
             WHEN k.circuito = 'cerrado' OR (k.circuito = 'semiabierto' AND v_es_prueba) THEN 0
             ELSE k.fallos_consecutivos
           END,
           circuito = CASE WHEN k.circuito = 'semiabierto' AND v_es_prueba THEN 'cerrado' ELSE k.circuito END,
           circuito_abierto_hasta = CASE WHEN k.circuito = 'semiabierto' AND v_es_prueba THEN NULL ELSE k.circuito_abierto_hasta END,
           prueba_en_curso = CASE WHEN k.circuito = 'semiabierto' AND v_es_prueba THEN false ELSE k.prueba_en_curso END,
           prueba_reservada_en = CASE WHEN k.circuito = 'semiabierto' AND v_es_prueba THEN NULL ELSE k.prueba_reservada_en END
     WHERE k.id = p_llave_id;
  ELSE
    UPDATE cfg.llm_llave k
       SET fallos_consecutivos = k.fallos_consecutivos + 1,
           ultimo_fallo_en = clock_timestamp(),
           circuito = CASE
             WHEN (k.circuito = 'semiabierto' AND v_es_prueba)
               OR k.circuito = 'abierto'
               OR k.fallos_consecutivos + 1 >= v_umbral THEN 'abierto'
             ELSE k.circuito
           END,
           circuito_abierto_hasta = CASE
             WHEN (k.circuito = 'semiabierto' AND v_es_prueba)
               OR k.circuito = 'abierto'
               OR k.fallos_consecutivos + 1 >= v_umbral
               THEN clock_timestamp() + make_interval(secs => (v_espera_ms / 1000.0)::double precision)
             ELSE k.circuito_abierto_hasta
           END,
           prueba_en_curso = CASE WHEN (k.circuito = 'semiabierto' AND v_es_prueba) OR k.circuito = 'abierto' OR k.fallos_consecutivos + 1 >= v_umbral THEN false ELSE k.prueba_en_curso END,
           prueba_reservada_en = CASE WHEN (k.circuito = 'semiabierto' AND v_es_prueba) OR k.circuito = 'abierto' OR k.fallos_consecutivos + 1 >= v_umbral THEN NULL ELSE k.prueba_reservada_en END
     WHERE k.id = p_llave_id;
  END IF;
END
$fn$;

COMMENT ON FUNCTION prc.fn_candidatos_llm(text,text,smallint) IS
'Entrega candidatos principales o candidatos de respaldo según ops.politica_reintento.usar_respaldo. El worker debe agotar sus reintentos configurados antes de pedir candidatos excluyendo al proveedor fallido.';
COMMENT ON FUNCTION prc.fn_reservar_llm(int,bigint) IS
'Reserva atómicamente RPM/TPM compartidos por proveedor-organización-proyecto (o por llave si no hay ámbito) y limita a una la prueba del circuito semiabierto. Debe invocarse en una transacción breve y confirmarse antes de cada llamada externa; no mantener la transacción abierta durante HTTP.';
COMMENT ON FUNCTION prc.fn_registrar_resultado_llm(int,text,boolean,uuid) IS
'Registra el resultado asociado a una reserva; solo una prueba exitosa en semiaabierto cierra un circuito abierto.';

-- Mantiene el esquema de permisos ampliados existente y agrega acceso a los objetos nuevos.
-- No se revocan permisos ni se estrechan los GRANT previos.
GRANT SELECT, INSERT, UPDATE ON prc.proceso_paso, prc.llm_cuota_minuto, prc.llm_reserva
  TO svc_api, svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo;
GRANT SELECT ON dat.registro_paso_tiempo TO svc_api, svc_lectura;
GRANT SELECT, INSERT, UPDATE ON dat.registro_paso_tiempo
  TO svc_ingesta, svc_llm, svc_analisis, svc_media, svc_transcripcion, svc_archivo;
GRANT SELECT, UPDATE ON cfg.llm_llave TO svc_llm;

COMMIT;

-- OPERACIÓN Y DESPLIEGUE
-- 1. Los workers deben implementar esta secuencia en el adaptador LLM:
--    candidatos -> fn_reservar_llm -> llamada con timeout -> fn_finalizar_reserva_llm
--    -> fn_registrar_resultado_llm(llave_id, operacion, ok, reserva_id); en caso de error tras una llamada real, no liberar RPM;
--    usar fn_finalizar_reserva_llm(reserva_id, tokens_reales o 0). fn_liberar_reserva_llm
--    se usa únicamente si la llamada externa NO llegó a enviarse.
-- 2. Después de agotar ops.politica_reintento.max_intentos en el proveedor actual, el worker
--    solo debe usar fn_candidatos_llm(p_operacion,p_uso,proveedor_fallido) si usar_respaldo=true.
-- 3. El scheduler debe mantener las particiones mensuales por delante de la fecha de Bogotá.
-- 4. El scheduler puede limpiar prc.llm_cuota_minuto con ventanas antiguas; no borrar reservas
--    abiertas. Configurar una retención para reservas cerradas según necesidades de auditoría.
-- 5. En producción, ejecutar gradualmente VALIDATE CONSTRAINT para los CHECK NOT VALID, en una
--    ventana de mantenimiento. No ejecutar validación global sin revisar tamaño/carga.
