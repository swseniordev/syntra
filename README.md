# Syntra

El módulo Clientes sirve como referencia de separación entre HTTP, casos de uso, dominio y PostgreSQL. La [guía para los próximos CRUD](docs/guia_crud_onion.md) describe el patrón y sus límites.

Aplicación local en desarrollo: React + TypeScript, API FastAPI modular, worker independiente y PostgreSQL 18. La segunda entrega incorporó autenticación y Clientes con persistencia real. La [entrega 3](docs/plan_entrega_3.md) está en validación: Roles, Cuentas, Prompts, Regex, Países, Grupos, Usuarios y Auditoría ya tienen rutas y pantallas conectadas a PostgreSQL. El correo real se verificó con un usuario descartable y un buzón autorizado; aún faltan verificaciones manuales de reenvío, permisos y rendimiento antes de cerrar la entrega.

## Requisitos locales

- Windows 10/11, PostgreSQL 18 en `127.0.0.1:5432`, base `syntra_dev`.
- Node.js 22.12 o posterior y npm; Python 3.11 o posterior.
- Modelo y catálogos inicializados según [el procedimiento de base de datos](docs/inicializacion_syntra_dev.md). No volver a ejecutar el DDL sobre la base ya inicializada.

Comprobación de PostgreSQL y metadatos de la base, usando `%APPDATA%\postgresql\pgpass.conf` existente o el prompt interactivo `-W`:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_isready.exe' -h 127.0.0.1 -p 5432
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -X -W -h 127.0.0.1 -p 5432 -U postgres -d syntra_dev -c 'SELECT current_database(), current_user, current_setting(''server_version'');'
```

El procedimiento de inicialización explica cómo verificar el hash del modelo, qué sentencias se separaron de los datos de demostración y cómo actuar ante un error. La instalación actual ya se inicializó; la secuencia de DDL se reserva para una base nueva y vacía.

## Dependencias y configuración local

Si se prepara otro equipo, crear los entornos e instalar las dependencias declaradas:

```powershell
Set-Location C:\Proyectos\syntra\backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Set-Location C:\Proyectos\syntra\frontend
npm ci
```

Los comandos de instalación son instrucciones de preparación para otro equipo; no se volvieron a ejecutar durante esta verificación final. La configuración de la API lee `SYNTRA_DB_HOST`, `SYNTRA_DB_PORT`, `SYNTRA_DB_NAME`, `SYNTRA_DB_USER`, `SYNTRA_DB_PASSFILE`, `SYNTRA_JWT_PRIVATE_KEY` y `SYNTRA_PUBLIC_ORIGIN`. En esta instalación se usaron los valores predeterminados de `backend/app/core/config.py`; solo se generaron los archivos privados del passfile y la clave JWT. No se usa una variable de contraseña en el proceso.

En un entorno nuevo, `backend/scripts/setup_local_credentials.py` crea una sola vez el passfile privado y el par RS256 después de aplicar los SQL de rol y RBAC. `backend/scripts/setup_local_https.py` crea una sola vez el certificado local. Ambos scripts se detienen si sus archivos ya existen. No volver a ejecutarlos sobre esta instalación.

## Primer administrador

El primer administrador ya fue creado en esta instalación mediante el siguiente comando, ejecutado por el usuario. **No volver a ejecutarlo en `syntra_dev`.** Para preparar una base nueva y vacía, el procedimiento sería:

```cmd
cd /d C:\Proyectos\syntra\backend
.venv\Scripts\python.exe scripts\bootstrap_admin.py
```

El comando pide nombre y correo, y solicita la contraseña en un prompt oculto. Solo funciona si `seg.usuario` está vacío. No poner la contraseña en argumentos, archivos del repositorio ni en el chat.

## Ejecutar la API

Las credenciales de `syntra_api_login` y la clave RS256 ya están en archivos privados del perfil Windows. La API no usa el usuario `postgres`.

```powershell
Set-Location C:\Proyectos\syntra\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/salud` comprueba solo que el proceso responde. Los endpoints de `/api/v1/clientes` exigen Bearer JWT y permisos en PostgreSQL. El acceso directo al puerto 8000 queda limitado a loopback en desarrollo; el frontend proxifica `/api/v1` bajo su propio origen.

## Ejecutar el frontend

```powershell
Set-Location C:\Proyectos\syntra\frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Abrir `https://127.0.0.1:5173/`. Vite usa el certificado local autofirmado ubicado en `%LOCALAPPDATA%\Syntra\certs`. El 20 de octubre de 2026, con aprobación del usuario, se agregó únicamente el certificado público de esta instalación al almacén `CurrentUser\Root` de Windows y se comprobó que el navegador confía en HTTPS. Su SHA-256 es `214C7B54B74ACA2F2F7F43311FA81EAA255AD61B4490989C48F5B94050F55E46`; vence el 20 de octubre de 2027. En otro equipo se debe comprobar la identidad del certificado antes de confiar en él. No omitir la comprobación TLS para usar el login: la cookie de renovación requiere `Secure` y `SameSite=Strict`.

La ruta `/?preview=1` mantiene la previsualización de desarrollo sin autenticación ni datos de negocio. Para una revisión visual HTTP, `SYNTRA_HTTP_PREVIEW=1` deshabilita TLS en Vite; ese modo no sirve para comprobar el login real.

La pantalla de acceso usa el contrato `/auth/login`. El access token vive solo en memoria del navegador; la renovación usa una cookie `HttpOnly; Secure`. Clientes y los módulos de la entrega 3 consultan datos reales; Cuentas, Prompts, Regex, Países y Grupos pueden mostrar listados vacíos mientras no existan registros funcionales. El sector del filtro de Clientes no precarga valores ficticios.

## Worker independiente

```powershell
Set-Location C:\Proyectos\syntra\worker
$env:SYNTRA_WORKER_CONCURRENCY = "1"
$env:SYNTRA_WORKER_QUEUE = 'q.reportes'
..\backend\.venv\Scripts\python.exe -m app.main
```

El worker consume `q.reportes` para exportaciones XLSX de Auditoría y, tras configurar SMTP y activar su rol limitado, `q.notificaciones` para contraseñas temporales. Cada cola usa una identidad PostgreSQL distinta; la concurrencia se configura externamente. Ver [credenciales y ejecución local](docs/inicializacion_syntra_dev.md) antes de iniciar cualquiera de las colas en `syntra_dev`.

**El worker debe permanecer en ejecución además de la API y Vite.** Iniciar solo los servidores web registra la exportación pero la deja en `en_cola`; la API no genera el XLSX de forma síncrona. En la comprobación local del 21/10/2026 había dos tareas `auditoria_exportar` disponibles y ningún worker `q.reportes` vivo. Al iniciar el proceso anterior con `syntra_report_worker_login`, ambas terminaron y produjeron XLSX legibles. Tras reiniciar Windows o cerrar ese proceso, volver a iniciar el worker. Para comprobar el estado sin leer filas de Auditoría:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -X -W -h 127.0.0.1 -p 5432 -U postgres -d syntra_dev -c "SELECT cola,tipo,estado,count(*) FROM prc.proceso_tarea WHERE cola='q.reportes' GROUP BY 1,2,3; SELECT count(*) AS workers_vivos FROM ops.worker WHERE 'q.reportes'=ANY(colas) AND latido>now()-interval '2 minutes';"
```

La evaluación de [arquitectura, concurrencia y límites del worker](docs/auditoria_worker_entrega3.md) distingue la protección implementada del límite físico de ejecución y de la operación supervisada todavía pendientes.

## Verificaciones

```powershell
Set-Location C:\Proyectos\syntra\frontend
npm test
npm run build

Set-Location C:\Proyectos\syntra\backend
.\.venv\Scripts\python.exe -m pytest
$env:SYNTRA_RUN_DB_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q tests\test_clients_integration.py
Remove-Item Env:SYNTRA_RUN_DB_INTEGRATION

Set-Location C:\Proyectos\syntra\worker
..\backend\.venv\Scripts\python.exe -m pytest -q --basetemp .test-tmp
```

Las pruebas de integración de backend levantan un clúster PostgreSQL descartable, crean solo usuarios de prueba y lo eliminan al terminar. No insertan clientes ni usuarios en `syntra_dev`.

En Clientes, `nombre` se recorta en ambos extremos, reduce espacios en blanco interiores consecutivos a uno solo y debe quedar no vacío; `sector` aplica la misma normalización, pasa a mayúsculas y queda nulo si está vacío. `rfc` y `contacto` solo se recortan en ambos extremos y quedan nulos si se envían vacíos; los espacios interiores de `rfc` se conservan y el correo `contacto` sigue rechazando espacios interiores. No se alteran acentos ni registros anteriores. La misma validación se aplica en POST y PATCH del backend; son las únicas rutas de escritura de los campos de Clientes. El modelo oficial usa columnas `text` sin longitud máxima definida; el correo se valida y la unicidad del nombre vigente se comprueba tras normalizar. El filtro obtiene sectores distintos de todos los estados mediante `GET /api/v1/clientes/sectores`, protegido por `clientes:ver`; los clientes sin sector aparecen al usar «Sector: todos», pero no generan una opción vacía. El detalle muestra los nombres vigentes de los usuarios vinculados por `creado_por` y `actualizado_por`, y presenta las fechas `timestamptz` en hora de Bogotá. Si un ID histórico no tiene usuario disponible, muestra esa ausencia sin inventar un nombre.

El 20 de octubre de 2026 se ejecutó el recorrido manual en el navegador por HTTPS: inicio de sesión con el administrador, creación de `PRB CLIENTE` con sector `POLITICA`, recarga del listado, edición temporal del sector, recarga del detalle y restauración de `POLITICA`. Una consulta de solo lectura a PostgreSQL confirmó el estado final y los tres eventos de auditoría (creación y dos ediciones). Los fallos de conexión se muestran como error; no se reemplazan por datos de demostración.

Si falla la conexión, comprobar `pg_isready`, el puerto y el passfile privado. Si la API devuelve 401, verificar que exista el primer administrador y que la sesión esté vigente; si devuelve 403, comprobar los permisos oficiales del rol. Si el navegador muestra un error de certificado, resolver la confianza del certificado local antes de probar cookies seguras. El servidor Vite HTTP de previsualización no es sustituto de la prueba de acceso HTTPS.

## Límites y pendientes

- Clientes incluye eliminación lógica, restauración a inactivo, cambio de estado, historial y lectura de cuentas asociadas. La administración de Cuentas y los demás módulos enumerados en el plan de la entrega 3 ya tienen implementación y pruebas automatizadas; faltan verificaciones manuales de escritura sin usar datos funcionales de `syntra_dev`.
- El límite de intentos de login por IP se mantiene en memoria del proceso API local. Un despliegue con varios procesos requerirá un punto de entrada o almacén compartido antes de considerarlo efectivo a escala.
- El worker no ejecuta mediciones ni reaplicación de Regex. Los objetivos de rendimiento para 50.000 y 1.000.000 de registros permanecen sin medir; las colas aprobadas de correo y exportación funcionan con PostgreSQL descartable en las pruebas.

Para una entrega posterior, la columna «Cuentas» podría obtenerse con una agregación `cfg.cuenta GROUP BY cliente_id` para la página de clientes visible, excluyendo cuentas eliminadas, y un campo de conteo documentado en OpenAPI. Requiere aprobación del contrato antes de mostrar cifras; la entrega actual conserva «—» y evita una consulta por cada cliente.
