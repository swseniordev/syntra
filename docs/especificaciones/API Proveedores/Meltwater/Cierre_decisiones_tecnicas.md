# Syntra — Meltwater: cierre de decisiones técnicas previas a implementación

**Fecha:** 27 de octubre de 2026  
**Estado:** propuesta técnica revisable; implementación no autorizada.  
**Antecedente:** [diseño consolidado](Diseno_tecnico_consolidado.md) y [propuesta previa](../../../Propuesta_integracion_API_Meltwater.md). Ambos se conservan intactos.

> **Convenciones:** **Comprobado** = evidencia en repo/documentación pública o decisión confirmada por responsable; **Propuesta** = recomendación no implementada; **Pendiente de validar** = depende de contrato, tenant o prueba autorizada; **Bloqueador** = impide afirmar seguridad/garantía.

## 1. Resumen

**Comprobado.** El runtime Syntra inspeccionado no implementa el cliente/processor Meltwater ni scheduler. `worker/app/infrastructure/ingest_queue.py` reclama `carga_archivo`; `worker/app/application/runner.py` ejecuta consumidores en `ThreadPoolExecutor`; `worker/app/config.py` limita `SYNTRA_WORKER_CONCURRENCY` por proceso. OpenAPI describe rutas que no aparecen en routers reales. `med.programacion_meltwater` persiste programación, pero no se encontró consumidor de `proxima_ejecucion`.

**Aprobado por responsable:** cuota compartida de la cuenta: 30.000 documentos por mes, 50 exportaciones por mes, 50 llamadas diarias. Estos valores no están pendientes de aprobación; deben quedar como configuración administrable y ser reconciliados con el uso de la cuenta. Una sola credencial puede servir múltiples clientes, manteniendo separación estricta.

**Recomendación principal:** dos entidades durables relacionadas, un `operation` por solicitud lógica/proceso y varios `attempts` de llamada al proveedor, con cargos de cuota por dimensión y ventana. Puede alojarse en una tabla de operaciones y una tabla de movimientos (dos entidades), evitando una tabla por endpoint o una única fila mutable que pierda historial. Un ledger append-only pequeño permite recuperar incertidumbre y reconciliar consumo externo.

**Límite no eliminable con el código actual:** las fuentes públicas documentan `POST /v3/exports/one-time`, GET de colección y GET por ID, pero no se encontró garantía documentada de idempotency key para el POST. Si la conexión se corta después de enviar el POST y antes de recibir el ID, una exportación pudo crearse. La lista de exports permite buscar un candidato, pero no prueba que sea el único; no se debe prometer “exactamente una exportación”.

Esta fase solo propone diseño. No se consultó PostgreSQL, no se llamó a Meltwater y no se modificó código, OpenAPI, SQL, configuración funcional ni datos.

## 2. Evidencia prioritaria

### 2.1 Runtime y persistencia Syntra

**Comprobado en archivos locales:**

- `worker/app/main.py`: composición de consumidores; `q.ingesta` usa consumidor de archivos.
- `worker/app/infrastructure/ingest_queue.py`: claim con `FOR UPDATE SKIP LOCKED`, procesa `carga_archivo`; no contiene processor Meltwater.
- `worker/app/application/runner.py`: ThreadPoolExecutor, futures, ciclo de claim/proceso, heartbeat/recuperación.
- `worker/app/config.py`: `SYNTRA_WORKER_CONCURRENCY` se aplica por proceso (1–32), no entre réplicas.
- `backend/app/api/routers/mediciones.py`, `measurement_files.py`, `ops.py` y `backend/app/main.py`: rutas activas; no hay router Meltwater. `ops.py` presenta colas/workers, no rutas de `/ops/parametros` descritas por OpenAPI.
- `backend/app/modules/mediciones/infrastructure/postgres.py`: persistencia de fuentes y `med.programacion_meltwater`; no ejecuta programación.
- SQL oficial: `prc.proceso`, `prc.proceso_tarea`, `med.programacion_meltwater`, `dat.ejecucion`, `dat.registro`, `dat.registro_huella`, `dat.registro_evento`, `ops.parametro`, `ops.politica_reintento`, `ops.worker`.
- `docs/especificaciones/API Proveedores/Meltwater/meltwater_export.py`: ejemplo usa `POST /v3/exports/one-time`, consulta GET por ID y descarga desde `data_url`; el helper usa polling/sleep bloqueante y no es worker productivo.

**Limitación:** modelo SQL y código no demuestran objetos, grants ni configuración efectivos de una instancia desplegada. Esa inspección requiere autorización separada; no forma parte de este documento.

### 2.2 Fuentes públicas consultadas

- [Export API — creación y consulta de one-time exports](https://developer.meltwater.com/docs/meltwater-api/listening/export-api/)
- [Migration to API V3 — inventario de rutas, incluido GET colección](https://developer.meltwater.com/help/migration-to-v3/)
- [FAQ — estados, cola, export concurrente y retención](https://developer.meltwater.com/help/faqs/)
- [Usage limits](https://developer.meltwater.com/guides/getting-started/usage-limits/)
- [Usage statistics](https://developer.meltwater.com/guides/getting-started/accessing-usage-statistics/)

La guía V3 documenta `GET /v3/exports/one-time`, `GET /v3/exports/one-time/{id}`, `POST /v3/exports/one-time` y `DELETE .../{id}`. El tutorial muestra en objeto de export campos como ID, estado, rango, searches, template, `inserted_at` y `data_url`; no se asume que el GET de colección exponga todos esos campos ni filtros/paginación, hasta verificar la especificación descargable vigente y el contrato de la cuenta.

## 3. Ledger: entidades y granularidad recomendadas

### 3.1 Por qué dos entidades

Una ejecución de medición puede consultar varios endpoints varias veces, puede reintentar una fase, recibir un ID remoto y quedar `uncertain`; un mismo intento puede afectar varias dimensiones (request rate, analytics diaria y export mensual, según endpoint). Una fila por tarea no representa intentos/consumos parciales; una fila por reserva no representa la operación lógica y dificulta el estado final.

**Propuesta:**

1. **`ops.proveedor_operacion` (1 fila por export lógico)**: une `proceso_id`, `proceso_tarea_id`, `cuenta_id`, `medicion_id`, credencial opaca, ventana, fingerprint de solicitud, ID remoto, estado remoto/local, fechas/deadline y error resumido. Su clave idempotente local es única para la ventana/programación o el comando manual.
2. **`ops.proveedor_movimiento` (N filas por reserva/intento/dimensión)**: ledger append-only para reservar/confirmar/liberar/reconciliar cada unidad por dimensión y ventana. Cada request/attempt tiene `attempt_id` local y FK a operación. Para una request que consume varios buckets, registrar un movimiento por bucket, en la misma transacción corta.

No crear una tabla independiente para cada cuota ni guardar snapshots JSON arbitrarios. Configuración de límites/costes va en configuración versionada; cada consumo, en ledger. Una actualización de estado puede ocurrir en operación, pero no reescribir movimientos históricos.

### 3.2 Modelo lógico (sin SQL ejecutable)

**Operación** — campos candidatos:

- ID; proveedor=`meltwater`; referencia opaca a credencial/configuración (nunca token); `proceso_id`, `proceso_tarea_id`, `cuenta_id`, `medicion_id`.
- `idempotency_key` local; fingerprint SHA-256 de parámetros canónicos (search IDs, período UTC, template, sample y opciones; no guardar consulta/token si es sensible).
- `window_start`, `window_end`, `requested_at`, `post_started_at`, `remote_export_id`, `remote_status`, `local_state`, `next_poll_at`, `deadline_at`, `finished_at`.
- Último error como código/categoría y mensaje redactado; contador de documentos estimado/recibido/transformado si está disponible; resultado de reconciliación.
- Unique local sobre `(credencial_ref, idempotency_key)` y unique remoto `(credencial_ref, remote_export_id)` cuando remoto no sea nulo. FK hacia proceso/tarea y cuenta/medición según restricciones reales del esquema.

**Movimiento** — campos candidatos:

- ID, `operation_id`, `attempt_id`, dimensión (`documents_month`, `exports_month`, `analytics_day`, `requests_minute`, `requests_hour_ip`, `export_post_minute`, `remote_export_slot`), bucket/ventana, unidades reservadas, unidades confirmadas, estado, instante de creación/transición, `reconciled_at`, fuente (`local`, `header`, `usage_api`, `operator`) y correlación externa no secreta.
- Unique idempotency por `(attempt_id, dimension, bucket_start, action)` para no duplicar movimientos al reintentar una transacción local.
- Índices por `(credential_ref/dimension/bucket/state)`, operación y `remote_export_id`/estado. Los índices exactos requieren validar carga y consultas.

**Aprobación requerida:** nombres, FKs, restricciones, retención y si grants existentes pueden exponer los campos sin ampliar de más. No se propone alterar el modelo oficial sin aprobación.

### 3.3 Estado y transiciones

Estados locales de operación: `queued → submitting → submitted → pending → downloading → ingesting → succeeded`; terminales alternos: `failed`, `cancelled`, `incomplete`, `uncertain`, `needs_operator`. El estado remoto del proveedor se conserva por separado (`PENDING`, `FINISHED`, `INCOMPLETE`, `CANCELLED` u otros documentados). No colapsar estado local y remoto en una sola columna.

Estados de movimiento: `reserved → sent → confirmed → reconciled`; alternativas terminales `released`; `uncertain` si el envío/consumo no pudo determinarse. Transiciones se anexan como movimientos o eventos y no se retroceden destructivamente. Una liberación solo se permite si se demuestra que no hubo consumo o que el proveedor rechazó antes de ejecutar. La expiración del lease local no prueba que el proveedor no aceptó el request.

### 3.4 Cuotas configurables vs contadores transaccionales

- Límites configurables y versionados: 30.000 documentos/mes, 50 exports/mes, 50 analytics llamadas/día (decisión aprobada); límites publicados adicionales por endpoint/IP solo si el contrato/configuración los confirma; max concurrent exports=1 como control conservador mientras dure validación; límites de Syntra por clase y deadlines.
- Contadores: suma de reserva activa + consumo confirmado según dimensión/periodo, restando solamente reserva liberada demostrablemente. Mantener aparte `observed_remaining` de headers/usage y `external_usage_delta` por consumos fuera de Syntra.
- Los buckets deben usar el período real del límite: exports/documents según reset mensual proveedor; daily analytics inicia en la primera llamada después del reset según docs, no asumir medianoche local; request rate usa ventanas y scope de header/proveedor.
- Reservas por llamada compiten entre workers dentro de transacción. Un advisory lock por bucket o fila de bucket con `SELECT ... FOR UPDATE` es apropiado; movimiento + contador/bucket se actualizan atómicamente. Nunca abrir transacción mientras se espera HTTP.

### 3.5 Ejemplos conceptuales de transacción

**Reservar un export mensual y un slot remoto:** en una transacción corta, bloquear bucket de exports por credential+mes y el slot remoto; comparar `confirmado + reservado` con límite; buscar operación por idempotency key; insertar operación/movimiento de reserva y lease exclusivo; commit. Si se agotó, no se envía HTTP y se reprograma con fecha de reset/config.

**Enviar POST:** fuera de DB, registrar durablemente intento `post_started`/`sent` con attempt ID antes de I/O, enviar una vez; si se recibe ID, transacción corta persiste `remote_export_id`, marca export enviado/confirmado según semantics reconciliadas y libera slot de ejecución local (el slot de export remoto se mantiene). Si hay timeout ambiguo, operación `uncertain`, cuota no liberada.

**Confirmar documento:** tras descargar y procesar, usar contadores reportados por export, si existen, y reconciliar contra `usage/me/metrics`; agregar movimiento confirmado del bucket mensual. No deducir consumo solo de filas persistidas por Syntra: proveedor puede contar documentos que Syntra rechaza o deduplica.

**Liberar:** una respuesta inequívoca no aceptada (validación 4xx salvo 429; comprobar status específico) deja movimiento `released`; transacción verifica estado actual y añade transición idempotente. No borrar intento.

**Conciliar:** consultar estadísticas por ventana y feature; guardar observación con timestamp/source, distribuir delta contra movimientos pendientes siguiendo regla de conciliación determinista; si global company usage incluye otras integraciones, la diferencia permanece externa/no asignada. No atribuir consumo desconocido a un cliente arbitrario.
### 3.6 Retención, auditoría e identidades

**Propuesta (retención inicial):** mantener los intentos y movimientos 13 meses después de que la operación quede terminal: cubre el horizonte de estadísticas públicas de hasta 12 meses más un mes de conciliación. Mantener indefinidamente mientras `uncertain`, `needs_operator` o export no terminal; no purgar cuota que aún no se pudo reconciliar. El plazo no es requisito legal ni política Syntra aprobada y debe alinearse con retención corporativa antes del DDL. Tras 13 meses, conservar un agregado auditado por período/credencial sin parámetros sensibles, solo si política de auditoría lo permite.

**Auditoría:** guardar actor/servicio que cambia límites, estado de conciliación manual, motivo, fecha y operación; no registrar secreto, URL completa de descarga, response body ni filtros de búsqueda con PII. Cambios de configuración deben versionarse/autorizarse en configuración auditada ya existente o extensión aprobada; `ops.parametro` runtime no está implementado en código revisado.

**Permisos mínimos propuestos:** API puede insertar operación/tarea y leer operaciones autorizadas por ámbito; no escribir movimientos de consumo del proveedor. Worker Meltwater puede reclamar tareas de su tipo, leer/actualizar operaciones asignadas y añadir movimientos; no modificar límites ni borrar historial. Worker de archivos no recibe acceso a la credencial ni a movimientos Meltwater. Rol de administración configura límites y revisa reconciliación con permisos separados. Evitar grants de tabla global cuando basten columnas/funciones; probar con identidades NOLOGIN/LOGIN mínimas en una DB descartable antes de migrar.

## 4. Recuperación de exportación incierta

### 4.1 Garantías documentadas y límite

**Comprobado en documentación pública:** V3 expone `GET /v3/exports/one-time` para listar one-time exports, `GET /v3/exports/one-time/{id}` para consultar una exportación identificada, `DELETE .../{id}` y POST para crear. El tutorial muestra un objeto con `id`, `status`, fechas, searches, template, `inserted_at` y `data_url`. Usage endpoints permiten reconciliar contadores agregados por feature/periodo; `GET /usage/me/requests` ofrece uso de requests. FAQ documenta estados y retención de 30 días.

**No comprobado:** idempotency key soportada por POST; filtros/paginación/orden/retención exacta del GET de colección; campos que devuelve la lista; query API para localizar por parámetros o correlation ID; coste por llamada de reconciliación. No se encontró garantía de idempotencia en tutorial, API reference consultado ni script local. Esto no prueba que el proveedor jamás la ofrezca; necesita confirmación de soporte/contrato y la OpenAPI V3 vigente.

**Recuperación candidata:** enumerar GET colección después de un POST incierto y comparar ID/campos de la petición canonicalizada (searches, ventana UTC, template, sample) y `inserted_at` contra intervalo del intento. Solo si el contrato confirma que la lista incluye esos campos y su cobertura/paginación, un único candidato exacto puede asociarse automáticamente como “probable recuperado”. Un GET de usage ayuda a reconciliar el número, pero no identifica cuál export corresponde a Syntra.

**Límite:** dado que la credencial es compartida, otro sistema/persona puede crear export con parámetros iguales. Incluso una lista completa con un match no es prueba matemática de causalidad. No prometer exactly-once ni reintentar automáticamente POST ambiguo.

### 4.2 Matriz de recuperación

| Situación | Evidencia/garantía | Acción durable propuesta | ¿Crear otro export automáticamente? |
|---|---|---|---|
| Error demostrado antes de enviar (DNS falla/conexión no establecida antes de write) | No hay evidencia de request recibido; debe instrumentarlo el cliente HTTP. | Mantener mismo operation key; nuevo attempt tras política, devolver reserva solo con evidencia. | Sí, bajo retry policy. |
| Timeout/desconexión tras posible envío, sin ID | POST puede haber sido aceptado; no se documentó idempotencia. | Estado `uncertain`; retener cuota; `GET` colección y comparar solo con correlación exacta y lista completa. Si hay 1 candidato, asociar con marca de recuperación heurística; si 0/varios, detener y escalar. | **No**, no a ciegas. |
| Respuesta POST exitosa con ID | ID identifica export. | Commit ID y parámetros; poll por GET ID. Si caída antes de persistir ID, vuelve al caso incierto. | No. |
| `PENDING` | Estado oficial significa en espera o en proceso; una sola export se procesa y las demás esperan según FAQ. | Persistir status y `next_poll_at`; liberar hilo/slot local; retener cuota mensual y slot remoto. | No. |
| `FINISHED` | Resultado listo; data_url disponible. | Descargar; si falla temporalmente, volver a GET por ID para recuperar metadata/URL; procesar idempotente/checkpoints. | No. |
| `INCOMPLETE` | FAQ: one-time terminó incompleto; para set completo se requiere recrear. | Terminal `incomplete`; conservar diagnóstico/consumo. Crear nueva operación solo después de autorización/política, reservar export mensual, contar como nuevo POST. | No automático sin política/aprobación de coste. |
| `CANCELLED` | Export cancelado; datos ya no están disponibles. | Terminal/cancelado; registrar reason; confirmar cuota consumida vía usage. Operador decide si nueva solicitud. | No. |
| Reinicio antes de POST | Ledger solo reservado, no marcado `sent`; evidencia local puede permitir release/retry. | Recuperar lease vencido, comprobar no existe attempt enviado, reutilizar operation. | Sí después de prueba de no envío. |
| Reinicio durante POST o tras envío, antes de ID | Resultado incierto. | Tratar igual que timeout ambiguo; reconciliar listado y escalar en ambigüedad. | No. |
| Reinicio con ID guardado/poll pendiente | ID y estado durable permanecen. | Reanudar GET ID cuando `next_poll_at` vence. | No. |
| Reinicio durante descarga | Export ID sigue; descarga puede reintentarse si link válido; archivo temporal se descarta/retoma según soporte. | Solicitar metadata actual por GET ID para URL nueva; almacenamiento temporal aislado con TTL; reanudar/descargar sin POST nuevo. | No. |
| Reinicio durante persistencia | Checkpoint/lotes y upsert idempotente. | Reanudar desde checkpoint; no duplicar rows; cerrar ejecución al completar. | No. |
| data_url expiró/retorna error | Documentación muestra URL, pero duración del link no se confirma. | Hacer GET por ID para conseguir metadata actual y URL; si expiración no renovable, escalar a soporte; preservar ID. | No crear export nuevo automáticamente. |

**Propuesta operativa segura para POST incierto:** pausar esa operación, mantener reserved/uncertain y no descontar como disponible. Reconciliar lista de exports y usage; si no hay una correlación única, una persona autorizada revisa cuenta Meltwater/soporte, decide asociar un ID o autorizar nueva exportación con conocimiento de cuota. La acción queda auditada con actor y motivo, nunca con credencial.

## 5. Dispatcher y concurrencia compartida

### 5.1 Algoritmo conceptual

1. Un ciclo de cada worker calcula capacidad libre global y cuotas por tipo usando leases/slots durables PostgreSQL. La reserva es corta.
2. Selecciona tareas elegibles por clase (`carga_archivo`, fase Meltwater lista para ejecutar), respetando un scheduler fair y aging de tareas antiguas. Poll remoto no ejecutable hasta `next_poll_at` no consume slot.
3. Reclama fila con transacción corta `FOR UPDATE SKIP LOCKED`; valida lease, cuenta/medición/tarea y estado; marca claim y reserva slot global y de tipo atómicamente. Para Meltwater, además adquiere slot lógico por credencial si va a iniciar/consultar operación que cuente como export concurrente.
4. Commit antes de I/O. Ejecuta una unidad acotada de trabajo; HTTP/parseo fuera de transacción.
5. Persiste checkpoint/estado/next attempt en transacción corta y libera slot de ejecución local. Para export PENDING, conserva solo slot remoto/cupo según la regla del proveedor, no worker thread.
6. Errores se aíslan por tarea; no abortan runner. Heartbeat/lease se renuevan mientras la unidad local trabaja; reaper rescata tareas con lease vencido. Reaper jamás interpreta lease expirado como ausencia de export remoto.

`FOR UPDATE SKIP LOCKED` impide que dos workers reclamen simultáneamente la misma fila bajo las restricciones de la transacción, pero no limita el número total ejecutándose ni administra fairness, provider quota o idempotencia externa. Hace falta una reserva global explícita/recurso lógico compartido. La opción exacta (tabla slot/lease o reserva sobre registros operativos existentes) depende de DDL aprobado.

### 5.2 Límites y progreso

- `G`: capacidad global durable a través de todas las réplicas.
- `A`: cuota global de ejecuciones locales de archivo, con reserva de progreso cuando hay backlog.
- `M`: cuota de operaciones locales Meltwater (submit/poll/download/transform puede tener subcuotas distintas).
- `E`: cantidad máxima de exports remotas sin resolver por credential; proponer inicialmente `1` como conservación de comportamiento por límite documentado, sujeto a alcance del tenant.
- Request rate/analytics/documents/exports: ledger separado del slot de worker.

**No se fijan valores finales para G/A/M**; dependen de benchmark, recursos QA, réplicas, DB connection pool, egress IP y proveedor. `SYNTRA_WORKER_CONCURRENCY` actual es por proceso y no basta. Si no se habilita infraestructura para slots globales, documentar el máximo agregado estimado y limitar réplicas operacionalmente; no describirlo como garantía distribuida.

**Fairness propuesta:** reservar como mínimo un slot global para archivo siempre que haya tarea de archivo elegible (y global capacity configurada); limitar ráfagas por tipo mediante round-robin ponderado/aging. No prestar slot reservado a una espera remota. En caso de cuota Meltwater agotada, reprogramar fase al próximo reset/ventana y permitir archivo. En 429, guardar Retry-After y omitir esa operación hasta fecha; continuar las demás tareas.

### 5.3 Ejemplo con dos workers

Supuesto ilustrativo: G=2; no es valor aprobado. W1 reclama archivo F y W2 reclama tarea M (submit) en transacciones separadas; W2 obtiene remote ID y el proveedor deja export en `PENDING`. W2 guarda `next_poll_at` en futuro y libera slot de worker; el slot remoto `E=1` continúa asignado. El próximo archivo puede reclamarse aunque M espere. Al vencer poll, uno de los workers adquiere slot local y consulta el ID.

Si W1 reinicia durante F, lease vence, W2 u otro replica puede reclamar F. El claim `SKIP LOCKED` evita doble reclamo simultáneo; checkpoint + idempotencia recuperan la ejecución. Si W2 reinicia con M pending, otro worker consulta el mismo ID (no POST). Si W2 cae durante POST antes de ID, el ledger queda `uncertain`; lease expiry no autoriza nuevo POST. Slot remoto se reconcilia/lista antes de liberarse.

**Pruebas obligatorias:** dos workers compiten por una fila, solo uno la reclama; varias tareas mixtas progresan; export pendiente no retiene el único slot; fallar una tarea no detiene la otra; reinicios por fase no crean POST duplicado ni mezclan clientes.
## 6. Programación y ventanas omitidas

**Comprobado:** `med.programacion_meltwater` contiene una fila por medición (`medicion_id` PK), activa, inicio/fin, `frecuencia_min` con mínimo 15 y `proxima_ejecucion`. El runtime inspeccionado persiste esa configuración, no la ejecuta. La política de atrasos no está implementada ni aprobada.

| Estrategia | Ventaja | Riesgo |
|---|---|---|
| Recuperar solo la ventana más reciente y marcar anteriores omitidas | Limita backlog y consumo al volver. | Pierde recuperación automática de períodos. |
| Encolar todas las ventanas omitidas | Completa cada ventana. | Puede agotar cuota/export single-flight y saturar workers. |
| Consolidar ventanas en un rango amplio | Menos exports. | Cambia semántica, volumen y dedupe; no es equivalente. |

**Recomendación:** catch-up secuencial de ventanas originales hasta `max_catchup_windows` configurable; al alcanzar máximo, mantener programación bloqueada/atrasada y pedir resolución operativa explícita (reprocesar o marcar omitidas con motivo). No eliminar ventanas antiguas ni consolidarlas silenciosamente. **Valor del máximo pendiente de medir/aprobar.** Registrar cada ventana omitida o procesada para no perder trazabilidad; el esquema actual quizá requiere ampliar modelo si no cabe en proceso/tarea y programación.

- Idempotency key: `meltwater:{medicion_id}:{window_start_utc}:{window_end_utc}:v1`; la cuenta también debe validarse como ámbito aunque la medición sea sujeta a FKs. Manual/inmediata usa clave estable por comando y rango; una solicitud explícita nueva crea nueva operación, no colisiona con programación.
- En una transacción corta, lock/claim de fila de programación, confirmar que sigue activa y vencida, insertar proceso+tarea con unique idempotency key, avanzar `proxima_ejecucion` al siguiente límite original, y commit. Si alguna inserción falla, rollback deja ambos sin avance parcial.
- Dos schedulers compiten vía `FOR UPDATE SKIP LOCKED`/advisory lock breve; unique key es defensa adicional. Ningún lock se mantiene al ejecutar HTTP.
- Reinicio antes del commit: rollback y scheduler vuelve a observar ventana vencida. Reinicio después: operación existente por idempotency key y próxima ejecución avanzada; no duplica.
- Pausar evita nuevos procesos; no borra/cancela la exportación activa. Reanudar según política catch-up.
- Si una ejecución inmediata coincide con la ventana programada, reutilizar misma operación solo si fingerprint, rango y sentido son idénticos y política permite coalescencia; de lo contrario deben ser distintas, visibles y sujetas a cuota. **Aprobación funcional pendiente** sobre coalescencia.
- No usar la programación recurrente nativa de Meltwater como scheduler de medición: la API produce export recurrente que sobrescribe `data_url`, lo cual complica historial y atribución de cada corrida.

## 7. Mapping candidato y rechazos

Los nombres de origen a continuación se observaron en los ejemplos de Meltwater. El modelo consultado es el SQL oficial, no una instancia desplegada. Campo exacto y obligatoriedad se deben comprobar frente a la respuesta real del template `api.json` contratado antes de implementar.

| Campo de origen | Destino oficial candidato | Obligación | Normalización/validación | Rechazo / `extra` | Evidencia/pendiente |
|---|---|---|---|---|---|
| `url` | `dat.registro.url`; huella `dat.registro.url_hash`/`dat.registro_huella.url_hash` | Obligatorio por decisión de identidad URL | Trim, parsear/validar URL según reglas Syntra; normalización/hash compatible aprobada. No remover query ni cambiar path arbitrariamente. | Sin URL válida: rechazar con código, sin usar ID externo. No duplicar en `extra`. | Campo de muestra; regla funcional aprobada. Confirmar URL relativa/encoding/canonicalization y mappings existentes. |
| `published_date` | `dat.registro.fecha_publicacion` | Requerido para construir periodo/check `ops.fn_periodo`; proveedor debe aportar fecha utilizable | Interpretar offset/timezone y precisión exactamente; almacenar UTC `timestamptz`. | Nulo/ambiguo/invalid sin timezone seguro: rechazar; no corregir. No conservar raw date en extra. | El esquema requiere NOT NULL; significado/formato exacto del proveedor pendiente. |
| `content.body` | `dat.registro.texto` | Texto válido obligatorio según decisión | Mantener texto; límites/documentation; no cambiar significado. | Vacío/nulo: rechazo trazable. No guardar el objeto `content` completo. | Campo visto en JSON; prioridad/fallback respecto a title requiere confirmación de formato. |
| `content.title` | `dat.registro.titulo` | Opcional como título | Trim si convención Syntra existente lo establece; preservar texto. | Si no existe, queda NULL. No usar como sustituto de `content.body` sin decisión. | Campo visto; semántica plausible pero confirmar template. |
| `source` / subcampos | `dat.registro.origen_id`, `red_id` vía catálogos | Origen requerido por constraint; red requerida en `dat.registro` | Mapear solo códigos configurados; no inferir red desconocida. | Si red/origen no mapea: rechazar con razón. Nombre exacto subcampo y mapping pendientes. | Muestra incluye estructura `source`; catálogo oficial existe. |
| `external_id` / `id` | Ninguna columna de identidad; candidato `extra` solo si soporte requiere | Opcional | Tratar como identificador proveedor, no como identidad Syntra. | Excluir por defecto; allowlist y retención por aprobar. | Existe en muestra; decisión aprobada prohíbe reemplazar URL. |
| `url_parent` / referencia padre | `dat.registro.url_padre` | Opcional | Validar como URL separada; no cambia dedupe. | Invalid opcional: null o rechazo según reglas de calidad por aprobar; no inventar. | Campo canónico existe; origen exacto por confirmar. |
| `language` | `dat.registro.idioma` | Opcional | Código conforme catálogo/convenio actual. | Desconocido no debe crear catálogo; conservar solo si política permite. | Mapping fuente por validar. |
| tipo de documento | `dat.registro.tipo_contenido` | Opcional | Mapear valores conocidos a tipos oficiales. | Desconocido: null o rechazo según constraint; confirmar enum real. | La columna es texto; no consta lista cerrada en evidencia revisada. |
| autor, ubicación, país | `autor_id_ext`, `autor_usuario`, `autor_nombre`, `autor_seguidores`, `pais`, `region`, `ciudad` | Opcionales | Allowlist por campo, normalizar códigos de país conforme existente. | Excluir atributos personales no necesarios; country inválido no se corrige silenciosamente. | Columnas existen; equivalencia con subcampos proveedor requiere validación. |
| sentimiento del proveedor | `sentimiento_fuente` | Opcional | Aceptar solo rango/escala documentados y normalizar mediante conversión aprobada. | Fuera de rango: rechazar valor o fila conforme regla por decidir. | Semántica/escala varía por API; no mapear sin contrato. |
| métricas (`metrics.*`) | Posibles columnas de `dat.registro_estado` o historial de métricas | Opcional | Mapear sólo dimensiones soportadas y timestamps reales. | No meter agregados sin significado/unidad; no reemplazar métricas calculadas/manuales. | Campos y unidades del template requieren confirmación; no se recomienda en primera versión. |
| campos desconocidos | `dat.registro.extra` JSONB | Opcionales, sujeto a allowlist | Sanitizar y limitar tamaño, profundidad, cardinalidad y longitud. | No guardar JSON crudo, secretos, PII innecesaria, URLs firmadas ni campos no aprobados. | `extra` existe; política detallada pendiente. |

### 7.1 Reglas de validación y recuentos

- Parseo válido y filas leídas se cuentan antes de validación. `n_leidos` es número de documentos fuente procesados; no cuenta encabezado CSV ni request envelope.
- Rechazados: fila con URL ausente/inválida, fecha no segura, texto vacío u origen/red sin mapping. Registrar código/mensaje breve en `dat.registro_evento`, `registro_id=NULL`, período de carga y proceso/tarea; el `detalle` solo contiene datos técnicos mínimos, no el JSON raw ni la fila completa.
- Nuevos: inserciones canónicas que crean identidad en ámbito medición+cuenta.
- Duplicados: matches por identidad/huella en archivo o dataset existentes; distingue repetición interna del archivo de existencia previa en métricas/reportes mediante detalle separado, sin sumar una fila dos veces.
- Aceptados: resultado agregado derivado como `leídos - rechazados` (si cada documento termina en exactamente un resultado válido); no sumarlo con `n_nuevos`/`n_duplicados`, que son desglose. El esquema oficial no contiene `n_aceptados`; exponer el derivado sin migración si el contrato permite. **Pendiente:** distinguir upsert/update de duplicado si la API/UI exige desglose; `dat.ejecucion` no tiene contador de actualizados.
- Para conservar categorías exhaustivas y no ambiguas, documentar outcome por fila `new | updated | duplicate_preserved | rejected` en resultados/eventos permitidos; el total aceptado es agregado. No contar `updated` como `new`. Si hace falta persistir nuevo contador, requiere cambio de modelo y aprobación.
- No actualizar históricos por URL coincidente. Si registro inconsistente o estado histórico no demostrable, conservar sin cambio y registrar razón operativa conforme el flujo existente.

## 8. SLA y reintentos propuestos

### 8.1 Métricas separadas

| Fase | Métrica | SLA inicial propuesto |
|---|---|---|
| Aceptación HTTP | p95 desde solicitud hasta respuesta con proceso/tarea durable | **Propuesta:** ≤2 s bajo carga normal; probar en QA. |
| Espera cola interna | enqueue hasta primer claim | **Propuesta:** p95 ≤60 s cuando hay capacidad y sin pausa/cuota agotada; separar por tipo. |
| Submit de export | duración HTTP de POST | **Propuesta:** deadline 30 s, un envío; timeout incierto requiere recuperación. No es E2E. |
| Espera de preparación remota | submit aceptado hasta FINISHED | **Propuesta QA:** objetivo p95 ≤30 min para export de volumen/ventana acordados; timeout máximo provisional 60 min, luego `needs_operator` (no cancelar/recrear automáticamente). La FAQ indica típicamente pocos minutos hasta 30 min; tutorial de export menciona desde 1 min hasta 1 h para exports grandes. Validar contrato/tamaño antes de fijarlo. |
| Poll status | cada fase HTTP | **Propuesta:** 15–60 s inicial adaptativo, ampliar cuando siga PENDING y respetar rate limits. La espera se agenda durablemente. |
| Descarga | desde GET URL hasta descarga completa | **Pendiente de volumen/red.** Timeout por inactividad y deadline separados; re-GET metadata si link expira. |
| Transformación | docs descargados a filas validadas | Medir por n y tamaño; establecer percentiles QA. |
| Persistencia | lote transformado a commit/checkpoint | Medir DB y contención; transacción por bloque. |
| E2E | solicitud hasta import concluida | Reportar separado con y sin espera remota. **No fijar contractual hasta pruebas de tenant.** |

**Propuesta.** Los SLAs aprobados de archivos (100k/180s, 1M/<1.799s en Entrega 5) siguen sin cambio y no se usan como SLA de generación remota. RNF oficiales conservan sus objetivos documentales; discrepancias con objetivos de carga deben permanecer reportadas.

### 8.2 Retries

Usar `ops.politica_reintento` como fuente persistente, pero leer política efectiva antes de ejecutar; el seed y `meltwater_export.py` no son configuración instalada ni aprobación. Clasificar conexión pre-send, timeout uncertain post-send, 429, 5xx, 4xx definitivo, `INCOMPLETE`, expiración de data URL y fallos locales de parse/DB.

- `Retry-After` tiene precedencia para 429; persistir next-attempt y respetarlo hasta deadline; añadir jitter positivo, nunca acortar espera del proveedor.
- Si no hay header, backoff exponencial configurado con jitter y tope; máximo total y por etapa configurables/auditables.
- Wait/backoff va en `prc.proceso_tarea.disponible_en`; no dormir el hilo. Mantener intent count alineado con operación lógica y registrar intentos HTTP separadamente en ledger.
- GET status/download pueden reintentarse con seguridad según política; POST sólo pre-send probado o después de recuperar/decidir uncertain. Error terminal conserva causa segura.
- Cuota agotada no se considera error transitorio rápido: agendar tras reset o dejar `blocked_quota`; habilitar carga de archivos mientras tanto.

## 9. Aprobaciones antes de implementar

### Aprobado y cerrado

- URL como identidad; sin URL y sin texto se rechaza.
- Credencial compartida, con aislamiento por cliente.
- Ventana derivada de medición.
- Ejecución inmediata y programada.
- No retener JSON original; resultados transformados y metadatos mínimos.
- Reutilizar política Syntra adaptada por error.
- Cuotas de cuenta confirmadas: 30.000 documentos/mes, 50 exports/mes, 50 llamadas/día.
- Límites globales y por tipo deben existir (los números no están aprobados).

### Recomendación técnica

- Ledger de dos entidades: operación + movimiento append-only.
- Coordinator DB con reservas cortas por credencial/bucket; ningún lock durante HTTP.
- Dispatcher fair con cuotas globales compartidas; polling como fases durables; archivo mantiene slot reservado.
- Catch-up secuencial de ventanas exactas con tope configurable y acción explícita ante backlog.
- No automatic POST retry en uncertain; listar exports y requerir reconciliación/operador en ambigüedad.
- Mapping canónico y extra allowlist; no raw JSON, no inferir mapping de métricas/fecha.

### Decisiones que la responsable debe aprobar para iniciar implementación

1. **Cambio SQL:** crear tablas lógicas operación/movimientos (o aceptar alternativa menos confiable); política de retención, claves/índices y roles. Esta es la decisión estructural principal.
2. **Recovery de POST incierto:** aceptar el flujo “listar/correlacionar si único; si no, detener para operador; nunca re-POST automático”. Confirmar si soporte Meltwater puede garantizar idempotency key/correlation.
3. **Objetivos operativos:** medir y aprobar `G`, cuotas por tipo, máximo de réplicas, máximo exports pendientes por credential (recomendación temporal 1), márgenes y política cuando la cuota está casi agotada.
4. **Programación:** catch-up máximo numérico, qué hacer con períodos más antiguos y si una ejecución inmediata idéntica a una programada se coalesce.
5. **SLA QA:** aceptar o ajustar valores provisionales de tabla 8.1 después de conocer dataset/ventana; definir timeout total y qué se considera `needs_operator`.
6. **Mapping:** confirmar fuente de fecha/hora y zona del campo publicado; prioridad body/title; subcampo que determina source/red; reglas de campos métricos y allowlist PII de `extra`.
7. **Respuesta API:** acordar semántica de “aceptado”, “nuevo”, “duplicado”, “rechazado”, si se requiere contador `actualizados`, endpoints y permisos. Cambiar OpenAPI solo tras aprobación.
8. **Uso provider:** confirmar con administración del contrato que cuotas 30k/50/50 están disponibles en token compartido, que la lista V3 es visible, retención/paginación y consumo endpoint por endpoint; acceso autorizado a usage APIs para reconciliar.
9. **Alcance cancelación:** decidir si UI permitirá cancelar export remota; DELETE está documentado, pero efectos/consumo deben confirmarse antes de habilitarlo.

## 10. Matriz final de estado

| Elemento | Clasificación | Evidencia/salida |
|---|---|---|
| Cuotas 30k docs/mes, 50 exports/mes, 50 llamadas/día | **Aprobado** | Confirmación responsable; también coincide con allowance Inclusive pública. Configurar, no hardcodear. |
| API V3 permite GET colección y GET export por ID | **Comprobado públicamente** | Migration guide lista ambas rutas; tutorial describe status/export fields. |
| POST one-time ofrece idempotencia documentada | **No comprobado / bloqueador** | No se encontró garantía en docs consultadas ni ejemplo repo; no afirmar que no exista sin confirmar contrato. |
| Ledger operación+movimientos | **Recomendado; DDL pendiente** | Necesidad: múltiples fases, dimensiones, incertidumbre, reconciliación. |
| `SKIP LOCKED` evita double claim de la misma fila | **Comprobado en implementación** | No reemplaza slots globales/quotas. |
| Límite global agregado hoy | **No existe evidenciado** | Configuración actual por proceso; se necesita coordinación DB. |
| Scheduler operativo | **No localizado** | Tabla y RF existen; no uso de `proxima_ejecucion` hallado. |
| Mapping de fecha/source/métricas | **Pendiente de validar** | Nombres de muestra no definen semántica, zona ni catálogo. |
| Catch-up policy y SLA exacto | **Pendiente** | Recomendaciones sujetas a capacidad/QA/aprobación. |
| DDL, código, API, DB, config funcional | **No realizado** | Fase exclusivamente documental. |

## 11. Referencias

### Repositorio

- [Diseño técnico consolidado](Diseno_tecnico_consolidado.md)
- [Propuesta técnica anterior](../../../Propuesta_integracion_API_Meltwater.md)
- [Script de ejemplo](meltwater_export.py)
- [OpenAPI Syntra](../../Syntra_openapi.yaml) · [Arquitectura](../../Syntra_Arquitectura.html) · [Mockup](../../Syntra_mockup_v0.4.html)
- [Esquema SQL oficial](../../Modelo%20de%20Persistencia/v1_Syntra_schema.sql) · [RF/RNF](../../Actores_RF_RNF.xlsx)
- `worker/app/main.py`, `worker/app/application/runner.py`, `worker/app/config.py`, `worker/app/infrastructure/ingest_queue.py`
- `backend/app/api/routers/mediciones.py`, `measurement_files.py`, `ops.py`, `backend/app/modules/mediciones/infrastructure/postgres.py`

### Meltwater

- [Export API](https://developer.meltwater.com/docs/meltwater-api/listening/export-api/)
- [Inventario de rutas V3](https://developer.meltwater.com/help/migration-to-v3/)
- [FAQ de estados, exportaciones concurrentes y retención](https://developer.meltwater.com/help/faqs/)
- [Usage limits](https://developer.meltwater.com/guides/getting-started/usage-limits/)
- [Usage statistics](https://developer.meltwater.com/guides/getting-started/accessing-usage-statistics/)

## 12. Confirmación de alcance

Solo se creó este documento de cierre técnico. No se modificaron código, frontend, backend, workers, OpenAPI, RF/RNF, SQL/esquema, permisos, bases de datos ni configuración funcional. No se hicieron llamadas a Meltwater. No se implementó el scheduler ni se iniciaron tareas automáticas. Se detiene aquí para revisión y aprobación.
