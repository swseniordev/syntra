# Syntra — Integración Meltwater: diseño técnico consolidado

**Fecha:** 27 de octubre de 2026  
**Estado:** diseño para revisión; implementación no autorizada.  
**Alcance:** inspección del repositorio y documentación, contraste de fuentes públicas oficiales y consolidación de recomendaciones. No se consultaron bases de datos, no se llamaron APIs de Meltwater y no se modificaron código, OpenAPI, SQL, configuración funcional ni datos.

> **Etiquetas de evidencia**  
> **Comprobado:** observado en archivos inspeccionados o confirmado por la responsable.  
> **Propuesta técnica:** recomendación no implementada.  
> **Supuesto por validar:** requiere prueba o evidencia adicional.  
> **Decisión pendiente:** debe resolverse antes de implementar la parte afectada.

## 1. Resumen ejecutivo y alcance

**Comprobado.** La interfaz y algunos artefactos mencionan Meltwater, y el esquema oficial contempla origen, tipo de proceso y programación. El runtime inspeccionado no contiene cliente/processor Meltwater, dispatcher de `carga_meltwater` ni scheduler activo. `q.ingesta` reclama exclusivamente `carga_archivo`. La integración es nueva; los ejemplos no constituyen integración funcional.

**Propuesta técnica.** Separar el adaptador Meltwater del processor de archivos y reutilizar capacidades transversales: `prc.proceso`, `prc.proceso_tarea`, leases y `FOR UPDATE SKIP LOCKED`, checkpoints donde sean adecuados, persistencia canónica y almacenamiento existente. Una exportación remota debe ser una tarea durable por etapas; la espera no debe ocupar una conexión SQL ni el único slot de archivos.

**Propuesta técnica.** La credencial compartida requiere coordinación durable de cuotas, exports en curso y reservas entre todas las réplicas. Los límites en memoria por proceso no lo garantizan. El modelo inspeccionado no muestra un libro de reservas/consumo; recomendamos una tabla transaccional específica, pendiente de aprobación y diseño final.

**Decisión funcional aprobada.** Cuotas de la cuenta Syntra: 30.000 documentos/mes, 50 exports/mes y 50 llamadas diarias. Deben configurarse, no codificarse. Se distinguen de límites públicos por endpoint/IP y de hipótesis de concurrencia.

Este documento consolida el diseño y enlaza el antecedente sin reemplazarlo: [Propuesta previa y anexos](../../../Propuesta_integracion_API_Meltwater.md). El antecedente permanece intacto.

## 2. Fuentes inspeccionadas y límites

### 2.1 Repositorio Syntra

**Comprobado.** Se inspeccionaron:

- `docs/especificaciones/API Proveedores/Meltwater/meltwater_export.py`, `busqueda_29251300.json` y `busqueda_29251300.xlsx`.
- `docs/especificaciones/Syntra_openapi.yaml`, `Syntra_Arquitectura.html`, `Syntra_mockup_v0.4.html`, `Modelo de Persistencia/v1_Syntra_schema.sql` y `Actores_RF_RNF.xlsx`.
- `backend/app/api/routers/mediciones.py`, `measurement_files.py`, `ops.py`, `backend/app/main.py` y `backend/app/modules/mediciones/infrastructure/postgres.py`.
- `worker/app/main.py`, `application/runner.py`, `config.py`, `infrastructure/ingest_queue.py`.
- Definiciones oficiales de `ops.parametro`, `ops.politica_reintento`, `ops.worker`, `prc.proceso`, `prc.proceso_tarea`, `med.programacion_meltwater`, `dat.ejecucion`, `dat.registro`, `dat.registro_huella`, `dat.registro_evento`.
- Antecedente `docs/Propuesta_integracion_API_Meltwater.md`, conservado sin cambios.

**Comprobado.** El JSON de muestra es un arreglo de 2.790 documentos; el XLSX muestra 2.790 filas de datos y 71 columnas. Se revisaron estructuras y nombres, sin exponer valores. Las muestras no prueban límites, semántica contractual ni mapping de producción.

**Limitación.** No se consultaron PostgreSQL, roles, permisos, filas de configuración, workers ni colas. Las definiciones citadas pertenecen al SQL oficial, no a una base desplegada. No se hicieron llamadas al proveedor.

### 2.2 Fuentes oficiales de Meltwater

La documentación pública puede variar y el contrato de la cuenta prevalece. Se consultaron:

- [Usage limits](https://developer.meltwater.com/guides/getting-started/usage-limits/)
- [FAQs](https://developer.meltwater.com/help/faqs/)
- [Accessing usage statistics](https://developer.meltwater.com/guides/getting-started/accessing-usage-statistics/)
- [Export API — exporting mentions](https://developer.meltwater.com/docs/meltwater-api/listening/export-api/)
- [Searching mentions](https://developer.meltwater.com/guides/listening/searching-mentions/)
- [Migration to API v3](https://developer.meltwater.com/help/migration-to-v3/)

**Comprobado en documentación pública:** tiers, límites por tipo de operación, estadísticas y headers `RateLimit-*`; FAQ de exportaciones en cola y estados. **No verificado:** aplicabilidad exacta de todos esos límites al contrato/tenant Syntra; no se obtuvieron métricas de uso.

## 3. Decisiones funcionales aprobadas

| Tema | Decisión vigente | Estado |
|---|---|---|
| Identidad | URL válida según reglas Syntra; no usar ID externo como identidad. Sin URL válida, rechazar con motivo. | **Aprobado** |
| Credencial | Una credencial compartida puede atender varios clientes/mediciones; mantener aislamiento estricto. | **Aprobado** |
| Cuotas | 30.000 documentos/mes; 50 exports/mes; 50 llamadas/día; configurables. | **Aprobado por responsable** |
| Concurrencia | Habrá límites numéricos globales y por tipo; valores de producción pendientes. | **Aprobado + pendiente de valores** |
| Ventana | Derivada de configuración de la medición. | **Aprobado** |
| Disparo | Ejecución inmediata y programada en primera versión. | **Aprobado** |
| Reintentos | Reutilizar política Syntra adaptada a clases de error y límites externos. | **Aprobado** |
| Datos de origen | No conservar JSON original; guardar resultados transformados y metadatos operativos mínimos. | **Aprobado** |
| Texto | Rechazar texto vacío con motivo. | **Aprobado** |
| SLA | Definir SLA propio y validarlo en QA, distinguiendo etapas. | **Aprobado; valores pendientes** |
| Datos adicionales | Conservar campos relevantes con estructura complementaria controlada. | **Aprobado; allowlist pendiente** |
## 4. Auditoría de arquitectura actual

| Componente | Evidencia y estado comprobado | Brecha, cambio propuesto y riesgo |
|---|---|---|
| OpenAPI | **Parcial/documentado.** Define operaciones Meltwater y `/ops/parametros`; el router real no registra rutas Meltwater ni parámetros ops. | Comparar método, seguridad y respuesta de cada ruta. Cambios contractuales solo con autorización. Riesgo: interfaz/SDK esperan operaciones inexistentes. |
| Mediciones | **Parcial.** CRUD, GET/PATCH y resumen; infraestructura persiste fuentes y `med.programacion_meltwater`. | Añadir casos de uso de ejecución y encolado idempotente. Persistir programación no significa ejecutarla. |
| Cola/dispatcher | **Parcial.** `worker/app/main.py` compone consumidores; `IngestQueue` reclama `carga_archivo` en `q.ingesta`. | Despachar tipos con procesadores separados. No mezclar adapter HTTP con parser. Riesgo de regresión/contención de archivos. |
| Reclamo | **Implementado parcialmente.** `FOR UPDATE SKIP LOCKED`, lease/advisory lock. | Evita doble claim de una fila, no cuotas compartidas, slot global de export, scheduler ni dedupe semántico. |
| Runner | **Implementado.** `ThreadPoolExecutor`, registry, heartbeat y recuperación; `SYNTRA_WORKER_CONCURRENCY` 1–32 por proceso. | Límite por proceso, no global; espera síncrona remota puede ocupar hilos. Hace falta fairness/cuotas distribuidas. |
| Scheduler | **Documentado pero runtime no localizado.** RF/CU aluden a scheduler/líder; código revisado no evidencia scheduler ni uso de `proxima_ejecucion`. | Crear scheduler durable, exclusión multi-réplica, política de atrasos e idempotencia. |
| Credenciales | **Solo ejemplo.** `meltwater_export.py` obtiene `MELTWATER_API_KEY` del entorno. No se encontró gestión productiva/rotación en worker. | Reutilizar mecanismo privado existente; nunca payload/log/DB. Definir rotación e identidad técnica. |
| Persistencia | **Base genérica presente.** Procesos/tareas, `med.programacion_meltwater`, `dat.ejecucion`, `dat.registro.extra`, huellas/eventos. | No se encontró ledger de cuotas, reservas, request remoto ni estado durable de export. Revisar mapping sin raw JSON. |
| Reintentos | **Esquema presente.** `ops.politica_reintento`; SQL seed incluye `meltwater.get`, pero no prueba configuración efectiva. | Consultar política efectiva en fase autorizada; persistir `disponible_en`/Retry-After; no asumir valores seed. |
| Monitor | **Parcial.** `/ops/colas`, `/ops/workers`. | Exponer estado de exports/cuotas solo tras definir contrato y permisos. Cola no equivale a worker activo. |
| Aislamiento | **Modelo facilita ámbito.** Proceso/medición/cuenta; huella por cuenta+medición. | Verificar consultas, authorization context, payload y retry en pruebas. Cliente no debe derivarse solo de input no validado. |

### 4.1 Diferencias contrato/runtime

- **Comprobado:** OpenAPI contiene operaciones Meltwater que el backend inspeccionado no implementa.
- **Comprobado:** `/ops/parametros` y `/ops/parametros/{clave}` están documentados; `ops.py` solo implementa `/colas` y `/workers`. `ops.parametro` está en SQL oficial, pero no se halló consumo Python.
- **Comprobado:** `med.programacion_meltwater` guarda activación, ventana, frecuencia mínima 15 minutos y `proxima_ejecucion`; no se encontró scheduler que la evalúe.
- **Comprobado:** `cat.tipo_proceso` tiene seed `carga_meltwater` en `q.ingesta`; el worker filtra `carga_archivo`.
- **Comprobado:** `meltwater_export.py` es ejemplo, no composición productiva.
- **Pendiente:** contrato de alta inmediata, lectura/estado/cancelación, idempotencia y permisos.

## 5. Cuotas de cuenta y consumo por endpoint

### 5.1 Niveles de certeza

| Nivel | Valor | Evidencia y tratamiento |
|---|---|---|
| Cuenta Syntra | 30.000 documentos/mes; 50 exports/mes; 50 llamadas diarias. | **Aprobado por responsable.** Configurar y reconciliar; no re-pedir aprobación. |
| Público, tier Inclusive | Límites publicados coincidentes; resets/export counting y medición descritos en Usage Limits. | **Comprobado públicamente**, no confirma contrato ni consumo actual. |
| Público, solicitudes | 100 solicitudes/min generales; 2.000/h/IP; analítica 5/s y 100/min; POST export con límite publicado de 20/min. | **Publicado; aplicabilidad endpoint/plan por validar.** |
| Export activa | FAQ dice que una exportación se procesa a la vez; adicionales pueden quedar pending. | **Publicado; alcance al tenant Syntra por confirmar.** Usar como límite conservador provisional en QA. |
| Hipótesis | `C_global=3`, dos tareas archivo y una Meltwater, margen de cuota 80%. | **No aprobado**, medir antes de definir producción. |
| Incierto | Coste por endpoint, estimate, páginas y si GETs consumen cuota diaria analítica. | Consultar docs/contrato y estadísticas; no asumir una unidad por llamada. |

La documentación Usage Limits dice que documentos pueden contabilizarse entre exports, searches y streams y no necesariamente deduplicarse; hasta cinco searches/tags por export cuentan como una exportación; existe un máximo publicado de 2M docs/export (superado, se muestrea); headers de rate limit para analítica. FAQ describe `PENDING`, `FINISHED`, `INCOMPLETE`, `CANCELLED`; un `INCOMPLETE` requiere recreación, y one-time exports se retienen 30 días tras ejecución. Aplicabilidad exacta debe confirmarse antes de enforcement productivo.

### 5.2 Matriz endpoint → dimensiones consumidas

| Operación/endpoint observado | Cuotas potenciales | Evidencia y certeza | Reconciliación |
|---|---|---|---|
| `GET /v3/searches` | Request/min, hora/IP; analytics diaria incierta. | Ruta en script/documentación; coste exacto no confirmado. | Control general; `/usage/me/requests`. |
| `GET /v3/searches/{id}/estimate` | Request y analytics posiblemente. | Migration V3 menciona endpoint; coste/precisión sin comprobar para cuenta. | No debitar documentos estimados como confirmados. |
| `POST /v3/exports/one-time` | Request/min, export mensual; documentos posiblemente al terminar. | Script + Export API; limitación POST publicada; consumo de export probable. | Reservar export antes del POST; timeout posterior al envío queda uncertain. |
| `GET /v3/exports/one-time/{id}` | Requests/min/hora; analytics diaria según plan. | Script y Export API. | Polling durable/adaptativo, headers y usage. |
| `GET data_url` | Request/límite descarga posiblemente. | URL firmada en ejemplo; coste de cuota no confirmado. | No filtrar URL; determinar cuota contractual. |
| `GET /usage/me/metrics` y `/requests` | Llamada de reporting; cuota propia incierta. | Documentación oficial de estadísticas. | Reconciliar contadores por ventana/token; no exponer token. |

**Propuesta técnica.** Mantener catálogo revisable `endpoint → buckets/costes/evidencia`; endpoint desconocido se trata conservadoramente. No usar coste universal por llamada.

### 5.3 Coordinación global y headers

**Propuesta técnica.** PostgreSQL como autoridad compartida entre réplicas, con reserva atómica por credencial y ventana (minuto, hora/IP, día, mes de export y mes de documentos, según endpoint). Límites en memoria son solo circuit breaker local.

Registrar `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `RateLimit-Day-Remaining` cuando existan; validar rangos y asociarlos al bucket correcto. Precedencia propuesta: aplicar el más restrictivo entre contrato, reserva conservadora local y remaining informado; un header con más saldo no eleva un contrato inferior. No mezclar scopes distintos.

**429:** respetar `Retry-After`, acotado por deadline, persistir próxima fecha y liberar el worker; jitter evita sincronización. Si header falta/inválido, backoff con jitter conforme política y tope conservador. Un POST ambiguo no se reintenta a ciegas.
## 6. Libro lógico de reservas/consumo (requiere aprobación)

**Comprobado:** `ops.parametro` es configuración JSONB; no sustituye un ledger transaccional. `prc.proceso_tarea` y `prc.proceso` siguen trabajo, no consumos por endpoint/token/periodo. El modelo oficial no mostró un ledger Meltwater.

**Propuesta técnica:** tabla específica (nombre ilustrativo `ops.consumo_proveedor`, aún no aprobado), una fila por intento/operación externa:

- `id`, `proveedor`, `credencial_ref` opaca, `endpoint_clave`, `proceso_tarea_id`, `cuenta_id`, `medicion_id`, `ventana_tipo`, `ventana_inicio`, unidades reservadas/confirmadas, `estado`, clave idempotente local, ID externo, marcas de envío/confirmación/liberación, `retry_after`, headers permitidos, código de error controlado y timestamps.
- Estados `reserved | sent | confirmed | uncertain | released | reconciled`.
- Unicidad idempotente por tarea+fase; índices por credencial+bucket+periodo+estado y por ID externo. Sin body de solicitud, JSON original, token, API key ni URL firmada.
- Retención suficiente para conciliar factura/uso y recuperar exportaciones; duración pendiente de política de auditoría/retención. Roles separados: API encola, worker reserva y actualiza, operaciones lee/configura con permiso específico.

### 6.1 Transiciones y fallos ambiguos

1. `reserved`: reserva atómica creada; solo expira si se demuestra que el request no salió. No devolver consumo confirmado por expiración.
2. `sent`: intento pudo llegar al proveedor.
3. `confirmed`: respuesta inequívoca con ID externo/resultado y coste identificable.
4. `uncertain`: pérdida/timeout tras posible envío; conservar reserva, reconciliar usage/ID, no emitir otro POST automáticamente.
5. `released`: fallo inequívoco pre-envío o rechazo que confirma no aceptación.
6. `reconciled`: consumo cotejado con estadísticas o export ID, conservando diferencia auditada.

Dos workers que compitan por el último saldo deben serializar reserva por credencial+dimensión+periodo, verificar reservado+confirmado, insertar con idempotency key y commitear antes del HTTP. Los consumos externos de la credencial compartida crean deriva; comparar `RateLimit-*`/usage y pausar si saldo remoto menor.

Para exportación simultánea, mantener exclusión distribuida por `credencial_ref` mientras haya export sin estado terminal. El lock DB dura solo la reserva; nunca durante HTTP. En `INCOMPLETE`, no suponer que se devuelve el límite mensual o se libera slot hasta reconciliar.

### 6.2 Parámetros frente a libro transaccional

`ops.parametro` podría guardar límites confirmados, margen, tabla de coste endpoint/bucket, concurrencia por tipo, polling, deadlines, backoff y feature flag; requiere auditoría, permisos y runtime que hoy no se halló. Reservas, request enviado, export ID, consumo confirmado, Retry-After y reconciliación pertenecen a ledger. Logs no son autoridad.

Las cuotas aprobadas se cargan como configuración inicial (30.000/mes, 50 exports/mes, 50 llamadas/día), no constantes. Si no se aprueba tabla, alternativa de ledger en payload de tarea es débil: no ofrece unicidad y ciclo de vida multi-request; no se recomienda y exige aprobación de solución externa si se rechaza DDL.

## 7. Concurrencia y convivencia con archivos

| Alternativa | Ventaja | Riesgo/coste | Evaluación |
|---|---|---|---|
| A. Aumentar `ThreadPoolExecutor` actual | Reutiliza runner; IO concurrente. | Límite por proceso; sleep ocupa hilo; varias réplicas multiplican slots; sin fairness hay starvation. | Insuficiente sola. |
| B. Dispatcher fair + procesadores separados + cuotas por tipo | Cambio acotado, compatible con runner; conserva processor archivo. | Límite global requiere coordinación DB; no mantener hilos durante polling. | **Base recomendada.** |
| C. Cliente async/asyncio | Alto rendimiento IO sin hilo bloqueado. | Runner y drivers actuales son síncronos; cambio amplio y más riesgo. | Considerar si medición demuestra límite de B. |
| D. Procesos/servicios separados por tipo | Aislamiento y escalado independiente. | Más despliegue; global concurrency/cuotas aún requieren DB. | Solo si capacidad/aislamiento lo justifica. |

**Propuesta técnica.** Mantener workers actuales; procesadores distintos para `carga_archivo` y `carga_meltwater`; dispatcher justo con cuotas por tipo y scheduler durable para próxima fase. Las etapas remotas son trabajos breves: submit, poll vencido, download, transform/persist. El polling se guarda en `disponible_en`; sin transacción ni hilo dormido. CPU pesada puede tener pool separado tras medición.

- **Global:** límite entre procesos/réplicas mediante slots/leases compartidos; config por proceso no basta.
- **Por tipo:** reservar capacidad mínima para archivos si hay tareas; cuotas separadas para Meltwater y límite de export sin resolver por credencial.
- **Por proceso:** `SYNTRA_WORKER_CONCURRENCY` 1–32 limita runner local; con R réplicas el nominal puede ser R×C.
- **Fairness:** round-robin/ponderado con progreso garantizado; si una exportación esperando mantiene ocupado todo el pool, es fallo de diseño.
- No aprobar `C_global=3`, 2 archivos + 1 Meltwater ni margen 80% sin medir recursos, IP/NAT de salida, número de réplicas y cuota real.

## 8. Programación y recuperación

**Comprobado:** `med.programacion_meltwater` guarda una programación por medición (`medicion_id` PK), activa, inicio/fin, frecuencia mínima 15 min y `proxima_ejecucion`. El código persiste, no evalúa. El PK limita a una configuración vigente por medición.

**Propuesta técnica:** scheduler worker con claim transaccional/`SKIP LOCKED` o advisory lock breve; varias réplicas no encolan dos veces. Crear tarea y avanzar próxima ocurrencia en la misma transacción. Clave determinista sugerida: `meltwater:{medicion_id}:{inicio_ventana_utc}:{fin_ventana_utc}:v1`. Ejecución inmediata usa idempotencia basada en medición+rango+solicitud, permitiendo repetición explícita controlada.

| Estrategia de ventanas omitidas | Ventaja | Riesgo |
|---|---|---|
| Solo última ventana vencida | Reduce backlog. | Pierde ventanas y datos sin visibilidad especial. |
| Encolar todas | Conserva cada ventana. | Tormenta de cuota al volver. |
| Consolidar rango atrasado | Menos requests. | Cambia semántica y rango aprobado. |

**Decisión pendiente:** misfire/backfill, límite de backlog y si se preserva cada ventana. Recomendación: recuperar secuencialmente hasta tope configurable, dejando backlog explícito; no consolidar rango silenciosamente.

Pausar impide nuevas tareas, no cancela export aceptada. Al reiniciar, rescatar lease y consultar estado remoto por ID antes de repetir POST. Ventanas duplicadas se bloquean con clave idempotente/transacción. Se requiere acción operativa para limpiar/omitir backlog con auditoría.
## 9. Flujo, contratos, persistencia y aislamiento

### 9.1 Flujo propuesto

1. API valida permiso; resuelve cliente/cuenta por contexto confiable y medición; verifica fuente activa y rango configurado; crea proceso/tarea idempotentes.
2. Dispatcher reclama `carga_meltwater`, reserva cuota y export slot en transacción corta, y commitea.
3. Adapter hace `POST /v3/exports/one-time` fuera de la transacción. Persiste ID externo y fase mínima, sin raw JSON/secreto.
4. Polling ocurre solo cuando `disponible_en` vence; estados/429/deadline quedan durables; no hilo/conexión dormida.
5. Descarga a storage temporal privado; no conserva JSON original. Transforma por lotes/checkpoints con reglas de Syntra.
6. Persiste registros, rechazos y contadores; completa proceso y libera slot al terminal/reconciliado.
7. UI consulta progreso persistido por contrato; no porcentaje inventado. Notificaciones solo si contrato existente lo define.

### 9.2 Mapping

| Dato | Destino propuesto | Validación |
|---|---|---|
| URL | identidad/campos canónicos según esquema | Requerida y válida; mantener hash compatible aprobado. No usar `external_id`. |
| Fecha de publicación | campo temporal canónico correspondiente | Semántica, formato y zona horaria del proveedor por validar; convertir UTC solo con fuente inequívoca. Fecha ambigua/inválida se rechaza. |
| Texto/título | campos canónicos existentes | Texto no vacío según decisión; respetar límites y no sobrescribir histórico/manual. |
| Fuente/origen | `cat.origen`/red existentes | Código reconocido; no crear catálogo automáticamente. |
| ID externo | Solo `extra` si aporta trazabilidad y privacidad lo permite | Nunca identidad ni clave de dedupe. |
| Otros campos | `dat.registro.extra` con allowlist | Excluir token, JSON raw y datos personales no necesarios; limitar bytes/profundidad/longitud. |
| Rechazos/contadores | `dat.ejecucion` y detalle de `dat.registro_evento` | Leer/aceptar/nuevo/duplicado/rechazado y razón codificada; no payload completo. |

**Comprobado:** nombres observados en muestra incluyen `published_date`, `content.body/title`, `source.*`, `url`; esto no confirma semántica ni equivalencia canónica. El mapping debe confirmarse con contrato/datos de prueba del tenant.

### 9.3 Duplicados, histórico, tenant

Conservar las reglas aprobadas de Syntra: huella por cuenta+medición y reglas de hash compatibles; URL no cruza tenant. En una transacción corta insertar/upsert/preservar histórico según estado real. No inferir histórico del proveedor ni actualizar registros históricos. Toda tarea vincula inequívocamente proceso, cuenta y medición. Consultas de origen, resultado, descarga y checkpoints filtran cuenta+medición autorizadas. La API deriva contexto de autorización, no de un campo de body sin validar. Probar URL idéntica en dos clientes, tareas concurrentes y retries. La credencial compartida autentica ante Meltwater, no otorga acceso entre clientes.

## 10. Reintentos, deadlines y SLA

| Fase/error | Tratamiento propuesto |
|---|---|
| Error de red antes de envío demostrado | Retry conforme política; liberar reserva si no salió solicitud. |
| Timeout POST después de posible envío | `uncertain`; reconciliar antes de cualquier nuevo POST. |
| 429 | Respetar Retry-After, guardar `disponible_en`, liberar slot de ejecución; no ocupar hilo. |
| 5xx/GET status/download | Backoff durable con jitter, deadline y máximo. |
| 4xx definitivo | Terminal, salvo rate-limit u otra clase explícita transitoria. |
| `INCOMPLETE` | Estado remoto incompleto y recuperación controlada; no es fallo local equivalente. |
| Expiración URL temporal | Consultar estado si posible; nunca crear export nuevo sin comprobación. |
| Transformación/persistencia | Checkpoints e idempotencia por lote/registro. |

La configuración efectiva de `ops.politica_reintento` no se consultó; el seed no prueba valores desplegados. El helper del script usa timeout HTTP 120s, 4 intentos y esperas 2/30, que no son política Syntra confirmada. Deben separarse aceptación API, espera de cola, creación remota, poll, descarga, transformación/persistencia y E2E. El `time.sleep` del ejemplo bloquea su proceso; el patrón productivo debería programar la siguiente fase durable.

### 10.1 SLA

Los RF/RNF incluyen objetivos de carga de archivos; Entrega 5 aprobó aparte 100k en 180s y 1M en menos de 1.799s. No mezclar objetivos ni sustituirlos. Ninguno incluye automáticamente el tiempo remoto.

**Propuesta:** medir p50/p95/p99 para aceptación+enqueue, espera cola, POST, preparación externa, download, transformación/persistencia, y E2E con/sin latencia externa. **Pendiente:** SLA numérico inicial Meltwater, timeout por fase y máximo total; proponer después de prueba autorizada con tamaño/ventana representativos. Documentación oficial de export indica aproximadamente 1 min a 1 hora; es referencia publicada, no promesa contractual ni límite fijo.

## 11. Seguridad, configuración y operación

- Usar mecanismo privado existente para credential mount/lectura runtime; confirmar en implementación. Nunca en payload, ledger, evento o logs; redactar Authorization, URL firmada, bodies y excepciones sensibles.
- Ledger solo usa `credencial_ref` opaca. Una credencial compartida no se expone al usuario.
- Roles separados API/worker/configuración; mínimos privilegios para tareas, datos y ledger. No usar superusuario.
- Métricas: cuotas y remaining por bucket, reservas/uncertain, exports pendientes/edad, espera de cola por tipo, requests/429, retries, documentos estimados/descargados/persistidos, drift de reconciliación. Alertas: cuota baja, uncertain envejecido, export atascado, backlog y fallas repetidas.
- Runbook con pausa global/por credential, consulta de export por ID, reconciliación y recuperación manual. No ofrecer retry que repita POST ambiguo.
- Despliegue gradual: feature flag apagado, migración/permisos aprobados, worker limitado, prueba pequeña autorizada, revisión de métricas y tenant, habilitación por medición.
- Rollback: deshabilitar enqueue/scheduler, preservar tareas/exports remotos, no borrar ledger/consumo real, conservar compatibilidad de procesos existentes; revertir DDL solo si no elimina evidencia y tras respaldo.

## 12. Cambios previstos (no ejecutados)

| Área | Cambio probable | Estado/impacto |
|---|---|---|
| API/casos de uso | Inmediata, estado/detalle/cancelación según OpenAPI y permisos. | Contrato/runtime desalineados; no implementado. |
| PostgreSQL | Ledger de cuotas; confirmar si proceso/tarea pueden cubrir vínculo de export. | Cambio de esquema probable; bloqueado hasta aprobación. |
| Worker | Processor separado, dispatcher fair, polling durable, scheduler, reconciliación y adapter HTTP. | No implementado; regresión de archivos debe probarse. |
| Configuración | Límites, costes por endpoint, concurrencia, deadlines/backoff, secret ref, flag. | `ops.parametro` runtime no localizado; discrepancy a resolver. |
| Datos | Mapping canónico, allowlist `extra`, rechazos y contadores. | Validar constraints/triggers/grants en DB descartable. |
| Frontend | Ejecutar ahora, programar, consultar estado/resultado, estados visibles. | Mockup no demuestra soporte; alinear OpenAPI antes. |
| Permisos | Grants mínimos diferenciados API/worker/admin. | Requiere ensayo con roles limitados. |
| Operación | Métricas, runbook de uncertain y reconciliación. | No existente para Meltwater. |

## 13. Matriz de decisiones y aprobaciones

| Decisión | Estado | Acción |
|---|---|---|
| URL como identidad; rechazo por URL/texto; credencial compartida; rango de medición; inmediato+programado; no raw JSON; extra controlado | **Aprobado** | Preservar al implementar. |
| Cuotas 30k/mes, 50 exports/mes, 50 llamadas/día | **Aprobado** | Configurar y reconciliar; no solicitar aprobación de nuevo. |
| Coordinador PostgreSQL + ledger | **Recomendado; cambio estructural pendiente** | Aprobar diseño detallado y migración/retención/roles. |
| Concurrencia global/por tipo | **Aprobado conceptualmente; valores pendientes** | Medir recursos, réplicas e IP de salida. |
| Un export procesado a la vez | **Publicado; tenant por confirmar** | Límite conservador en QA mientras se confirma. |
| Mapping, zona/semántica fecha, allowlist | **Pendiente técnico** | Validar con contrato/muestra autorizada. |
| Misfire/backfill y tope de backlog | **Pendiente** | Definir política; recomendar ventanas secuenciales con tope. |
| POST incierto/idempotencia externa | **Bloqueador** | Confirmar API idempotency o reconciliación segura. |
| Rutas/códigos/permisos | **Pendiente contractual** | Resolver OpenAPI/runtime. |
| SLA y deadlines Meltwater | **Pendiente** | Proponer tras prueba autorizada. |
| Retención del ledger | **Pendiente** | Alinear auditoría y ciclo de facturación. |
| Implementación | **No autorizada ahora** | Esperar aprobación expresa posterior. |

## 14. Plan de pruebas y aceptación

No se ejecutaron pruebas funcionales de integración; lo siguiente es plan.

- **Unitarias/contrato:** mapping, URL/fecha/texto inválidos, allowlist/limites `extra`, estados/error, Retry-After, deadlines, redacción y validación íntegra OpenAPI vs routers.
- **DB/privilegios:** migración forward/rollback en DB descartable, unicidad/idempotencia, transiciones ledger, rollback transaccional, API/worker/admin con roles limitados sin superuser.
- **Cuotas/concurrencia:** dos workers compiten por último saldo y solo uno gana; cuota compartida entre mediciones/tenants; múltiples réplicas y SKIP LOCKED sin doble ejecución; consumo externo reduce remaining; un export activo; 429 y reinicios.
- **Coexistencia:** export Meltwater esperando mientras una carga se procesa y termina; varias tareas mixtas, fallo aislado y ausencia de starvation; ningún hilo duerme durante espera remota.
- **Recuperación:** timeout de POST antes/después de envío, estado uncertain sin POST duplicado; export pending/finished/incomplete/cancelled; crash en cada etapa; reconcile de `/usage/me/metrics` y `/requests`.
- **Programación:** dos schedulers, ventana idéntica, inmediato idempotente, pausa, reinicio, backlog/misfire y tope.
- **Tenant/API/UI:** usuario autorizado/no autorizado, medición ajena, datos segregados con URL común, filtros, estados sin porcentaje falso; revisión visual contra mockup.
- **QA/performance:** prueba pequeña autorizada con cuota observada; registrar ventanas, número de docs, fases, red, CPU/memoria, percentiles y errores. No usar carga productiva sin aprobación.

Criterio: ninguna tarea duplicada; cuotas globales respetadas; archivos continúan progresando con export pendiente; aislamiento íntegro; incertidumbre de POST recuperable sin crear export accidental; secretos ausentes de datos/logs; SLA por etapa medido; contrato coincide con runtime.

## 15. Riesgos y bloqueos

1. **Crítico:** POST pudo llegar aunque hubo timeout; repetir puede gastar otro export mensual.
2. **Alto:** consumo externo de credencial o carreras multi-réplica exceden cuota si se usan límites locales.
3. **Alto:** OpenAPI describe rutas ausentes en backend.
4. **Alto:** scheduler no aparece en runtime pese a requisito y tabla de programación.
5. **Alto:** `q.ingesta` hoy filtra `carga_archivo`; Meltwater requiere processor/dispatcher separado.
6. **Medio:** `ThreadPoolExecutor` es por proceso; espera bloqueante retiene capacidad.
7. **Medio:** nombres de campos de muestra no confirman mapping semántico, especialmente fecha/origen.
8. **Medio:** no se consultó estado instalado de DB/permisos; seeds no garantizan despliegue.
9. **Medio:** API de exportación pública reporta duración aprox. de 1 min a 1 hora; SLA interno no debe absorberla sin definirlo.
10. **Privacidad:** prohibido guardar JSON original; evitar temporales persistentes y logs de cuerpos/URL firmada.

## 16. Referencias del repositorio

- [Antecedente técnico y anexos](../../../Propuesta_integracion_API_Meltwater.md)
- [Script de ejemplo](meltwater_export.py)
- [OpenAPI](../../Syntra_openapi.yaml) · [Arquitectura](../../Syntra_Arquitectura.html) · [Mockup](../../Syntra_mockup_v0.4.html)
- [Modelo SQL oficial](../../Modelo%20de%20Persistencia/v1_Syntra_schema.sql) · [RF/RNF](../../Actores_RF_RNF.xlsx)
- `backend/app/api/routers/mediciones.py`, `measurement_files.py`, `ops.py`, `backend/app/main.py`
- `backend/app/modules/mediciones/infrastructure/postgres.py`
- `worker/app/main.py`, `worker/app/application/runner.py`, `worker/app/config.py`, `worker/app/infrastructure/ingest_queue.py`

## 17. Resultado de esta fase

**Comprobado:** Meltwater no está implementado en runtime revisado; ejemplos y mockup no prueban operación real. **Comprobado:** no se modificó código, frontend, backend, worker, OpenAPI, SQL/esquema, configuración funcional, base de datos ni se llamó al proveedor. Solo se crea este documento.

**Siguiente paso:** revisar ledger, dispatcher global/fair, recovery POST incierto, misfire, mapping y SLA. Implementación requiere aprobación expresa posterior. Las cuotas confirmadas de la cuenta no necesitan volver a aprobarse.