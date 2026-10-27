# Syntra

Syntra es una aplicación web para configurar mediciones de conversación pública y gestionar la información que las alimenta. El proyecto organiza clientes, cuentas y usuarios; permite definir mediciones y cargar archivos; conserva el seguimiento de procesos y cambios mediante auditoría.

## Objetivos

Syntra busca que los equipos puedan:

- Organizar clientes, cuentas y grupos de usuarios con acceso según sus permisos.
- Configurar mediciones y las fuentes que las alimentan.
- Ingerir publicaciones desde archivos con controles de formato, normalización, deduplicación y separación por cuenta y medición.
- Consultar procesos, resultados de carga, notificaciones y cambios registrados.
- Mantener las operaciones de larga duración fuera de las solicitudes web, mediante tareas persistidas en PostgreSQL y workers independientes.

El alcance funcional se describe en los [requisitos oficiales](docs/especificaciones/Actores_RF_RNF.xlsx) y el [mockup aprobado](docs/especificaciones/Syntra_mockup_v0.4.html).

## Funcionalidades actuales

La siguiente lista refleja lo que está conectado en el código del repositorio. La disponibilidad de cada operación también depende de que la base tenga sus catálogos, permisos y datos configurados.

| Área | Estado actual |
| --- | --- |
| Inicio de sesión y autorización | Implementados con JWT, renovación de sesión mediante cookie segura y permisos por módulo y acción. |
| Clientes | Consulta, creación, edición, eliminación lógica, restauración, estado, historial y consulta de cuentas asociadas. |
| Cuentas y configuración | Rutas y pantallas para Cuentas, Roles y accesos, Usuarios, Grupos, Países, Prompts y Regex. Regex se prueba con el motor RE2. |
| Auditoría | Consulta y detalle de eventos; exportación XLSX asíncrona mediante el worker de reportes. |
| Mediciones | Creación y edición de configuración, resumen, historial de archivos, descarga, lotes y consulta del estado persistido. |
| Carga e ingesta | Carga local de archivos y procesamiento asíncrono para el formato `talkwalker_simple` (`DBFormatoSimple`), cuando su mapeo está habilitado y validado. Se aceptan `url` y `published` como encabezados obligatorios; las fechas se interpretan con las reglas del formato y se rechazan las inválidas o ambiguas. |
| Procesos y workers | Seguimiento de colas y latidos de workers, además de tareas, reintentos e historial persistidos. El worker no se inicia automáticamente al cerrar la terminal o reiniciar el equipo. |
| Correo y notificaciones | El worker puede enviar mensajes de acceso por SMTP y procesar notificaciones de tareas. SMTP debe configurarse fuera del repositorio. |

### Funcionalidades parciales o pendientes

- En la carga, la incorporación automática se controla por la opción `incorporar`. Las opciones de relevancia, sentimiento, clusters y bots se pueden configurar, pero no debe interpretarse su selección como prueba de que cada análisis esté ejecutándose.
- En el flujo de archivo, el formato habilitado depende de que el catálogo confirme un mapeo válido. Plantilla Syntra, Brandwatch y Talkwalker no deben presentarse como habilitados si su mapeo no está configurado.
- Scraping y extracción mediante proveedores externos, análisis LLM, procesamiento completo de sentimiento/clusters/bots, fiscalización, consulta general de registros e informes analíticos no están implementados como flujos operativos completos en el backend y frontend actuales.
- Algunas gráficas e indicadores de Procesos y del Inicio muestran estados vacíos o marcadores cuando todavía no existe una fuente funcional conectada.
- El [contrato OpenAPI](docs/especificaciones/Syntra_openapi.yaml) describe también capacidades objetivo que no necesariamente tienen una ruta operativa correspondiente en esta versión. La existencia de una operación en el contrato no significa por sí sola que esté implementada.

## Arquitectura

Syntra se ejecuta como un monolito modular con un proceso de worker independiente. No utiliza microservicios ni Redis.

- **Frontend:** aplicación web en React y TypeScript.
- **Backend:** API HTTP en FastAPI. Los routers gestionan la frontera HTTP y los módulos separan responsabilidades de aplicación, dominio e infraestructura según corresponda.
- **Workers:** procesos separados que reclaman tareas durables de PostgreSQL. El código actual registra consumidores para `q.notificaciones`, `q.reportes`, `q.mantenimiento` y `q.ingesta`.
- **Persistencia:** PostgreSQL. La aplicación se conecta con identidades técnicas de privilegio limitado; API y workers usan passfiles separados por función.
- **Almacenamiento local:** las cargas y exportaciones privadas usan directorios configurables fuera del repositorio. En un despliegue, los directorios deben persistir y tener permisos limitados.

El navegador accede al frontend y este dirige `/api/v1` al backend mediante el proxy de desarrollo de Vite. En un despliegue se requiere un proxy inverso que sirva el frontend y enrute la API bajo el mismo origen.

## Tecnologías

Versiones y rangos declarados por los archivos de dependencias del proyecto:

- Python 3.11 o posterior.
- FastAPI `>=0.115,<1.0` y Uvicorn `>=0.34,<1.0`.
- Psycopg 3 `>=3.2,<4.0`.
- PostgreSQL 18 para el entorno local documentado.
- React 19, TypeScript 5.9 y Vite 7.
- Vitest 5 para pruebas de frontend.
- Google RE2 para validar expresiones regulares.
- PostgreSQL como almacenamiento de datos y cola; no se requiere Redis.

Los rangos concretos de dependencias están en [backend/pyproject.toml](backend/pyproject.toml), [worker/pyproject.toml](worker/pyproject.toml) y [frontend/package.json](frontend/package.json).

## Estructura del repositorio

```text
syntra/
├── backend/
│   ├── app/api/             # Routers y dependencias HTTP
│   ├── app/core/            # Configuración, seguridad y conexión
│   ├── app/modules/         # Módulos de negocio y sus capas
│   ├── scripts/             # Herramientas locales, incluido bootstrap inicial
│   └── tests/               # Pruebas API, dominio e integración optativa
├── frontend/
│   └── src/
│       ├── app/             # Pantallas y componentes de módulos
│       ├── shared/          # API y componentes compartidos
│       └── styles/          # Estilos y tokens visuales
├── worker/
│   ├── app/                 # Consumidores, casos de uso e infraestructura
│   └── tests/               # Pruebas del worker
├── docs/especificaciones/   # Requisitos y artefactos oficiales
└── .env.example             # Variables locales no secretas de referencia
```

## Requisitos para desarrollo local

Entorno descrito: Windows 10/11, PowerShell, PostgreSQL 18, Python 3.11 o posterior y Node.js compatible con Vite 7 (se recomienda Node.js 22.12 o posterior).

Los comandos siguientes usan `C:\Proyectos\syntra` como ejemplo; sustituye esa ruta por la ubicación de tu clon. Son para una instalación local nueva. No los ejecutes sobre una base existente sin revisar el estado y el procedimiento aprobado.

### 1. Preparar PostgreSQL

La configuración predeterminada de la API apunta a `127.0.0.1:5432`, base `syntra_dev`, usuario técnico `syntra_api_login`. Los workers utilizan usuarios y passfiles distintos según la cola.

Comprueba que el servidor esté disponible:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_isready.exe' -h 127.0.0.1 -p 5432
```

**Importante:** el esquema oficial es un modelo de referencia, no un script de migración para ejecutarse a ciegas sobre una base existente. Los scripts de inicialización, roles, permisos y catálogos de desarrollo no están incluidos en este repositorio Git porque `database/` y otros artefactos locales están excluidos por `.gitignore`. Para una instalación nueva, se deben obtener del paquete de inicialización aprobado y seguir su orden documentado. Si no se cuenta con ese paquete, no es posible reconstruir la base desde un clon limpio solo con este repositorio.

No uses el rol PostgreSQL `postgres` desde la API o el worker. No ejecutes el modelo oficial directamente sobre una base con datos.

### 2. Instalar las dependencias

En una ventana de PowerShell para la API:

```powershell
Set-Location C:\Proyectos\syntra\backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

En otra ventana para el frontend:

```powershell
Set-Location C:\Proyectos\syntra\frontend
npm.cmd ci
```

Para preparar el worker con su propio entorno:

```powershell
Set-Location C:\Proyectos\syntra\worker
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

En PowerShell se utiliza `npm.cmd` para evitar el bloqueo de `npm.ps1` cuando la política local no permite ejecutar scripts.

### 3. Configurar secretos y credenciales locales

[\.env.example](.env.example) contiene solamente valores locales no secretos para el entorno, el nivel de registro y la concurrencia del worker. El backend y el worker leen la configuración del entorno del proceso; no debe suponerse que cargan automáticamente un archivo `.env`.

Tras instalar una base de desarrollo vacía con los scripts aprobados, se puede preparar el passfile de la API y su clave JWT local con:

```powershell
Set-Location C:\Proyectos\syntra\backend
.\.venv\Scripts\python.exe scripts\setup_local_credentials.py
```

Este procedimiento requiere que el passfile administrativo local de PostgreSQL ya esté configurado y que el rol API se encuentre en el estado esperado por el script. Genera archivos privados fuera del repositorio; no imprime las credenciales. No lo ejecutes si esos archivos ya existen ni sobre una instalación ya configurada.

Para HTTPS de desarrollo, el certificado local se crea una sola vez:

```powershell
.\.venv\Scripts\python.exe scripts\setup_local_https.py
```

El certificado es local y autofirmado. El sistema operativo o el navegador pueden pedir que se verifique y confíe en el certificado público; no desactives la validación TLS. El script no sobrescribe archivos de certificado existentes.

El bootstrap del primer administrador solo se ejecuta después de inicializar roles y permisos, cuando la tabla de usuarios funcionales está vacía:

```cmd
cd /d C:\Proyectos\syntra\backend
.venv\Scripts\python.exe scripts\bootstrap_admin.py
```

Solicita la contraseña en un prompt oculto. No la incluyas en comandos, archivos versionados ni mensajes. No vuelvas a ejecutar el bootstrap en una base que ya tiene usuarios.

### 4. Iniciar los servicios

Mantén una ventana de PowerShell abierta por proceso.

**API**, desde `backend/`:

```powershell
Set-Location C:\Proyectos\syntra\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Frontend**, desde `frontend/`:

```powershell
Set-Location C:\Proyectos\syntra\frontend
npm.cmd run dev
```

Vite publica el frontend en `127.0.0.1:5173` y utiliza HTTPS si encuentra el certificado local. Su proxy reenvía las solicitudes `/api/v1` al backend local en `127.0.0.1:8000`. La configuración permite cambiar el destino mediante `SYNTRA_API_TARGET`, pero solo acepta una URL HTTP de loopback.

**Worker**, desde `worker/`, en otra ventana. Define explícitamente la cola y la concurrencia para cada proceso:

```powershell
Set-Location C:\Proyectos\syntra\worker
$env:SYNTRA_WORKER_QUEUE = 'q.ingesta'
$env:SYNTRA_WORKER_CONCURRENCY = '1'
.\.venv\Scripts\python.exe -m app.main
```

Los valores admitidos de `SYNTRA_WORKER_QUEUE` en el código actual son `q.ingesta`, `q.mantenimiento`, `q.reportes` y `q.notificaciones`. Ejecuta un proceso por cola que necesites y configura el passfile de la identidad correspondiente. El worker de notificaciones requiere, además, la configuración del proveedor SMTP y un archivo privado con la contraseña de aplicación. El proceso del worker debe mantenerse activo para que atienda las tareas; cerrar la ventana lo detiene.

Una vez iniciados API y frontend, abre:

- Aplicación: [https://127.0.0.1:5173/acceso](https://127.0.0.1:5173/acceso)
- Salud de API: [http://127.0.0.1:8000/salud](http://127.0.0.1:8000/salud)
- Documentación Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

La ruta de salud confirma que la API responde, no que PostgreSQL, los permisos o todos los workers funcionen. Swagger documenta el contrato expuesto; algunas operaciones objetivo del OpenAPI no tienen implementación funcional en esta versión.

## Pruebas

Los siguientes comandos están definidos por las configuraciones del proyecto. Deben ejecutarse desde las carpetas indicadas.

**Frontend** — Vitest y React Testing Library:

```powershell
Set-Location C:\Proyectos\syntra\frontend
npm.cmd test
npm.cmd run build
```

**Backend** — pruebas unitarias, de dominio y de API:

```powershell
Set-Location C:\Proyectos\syntra\backend
.\.venv\Scripts\python.exe -m pytest
```

**Worker** — pruebas de casos de uso, configuración e infraestructura:

```powershell
Set-Location C:\Proyectos\syntra\worker
.\.venv\Scripts\python.exe -m pytest
```

Algunas pruebas de integración del backend se omiten salvo activación explícita. La prueba de integración de Clientes crea un clúster PostgreSQL temporal y requiere ejecutables de PostgreSQL 18 y artefactos SQL de inicialización disponibles localmente:

```powershell
Set-Location C:\Proyectos\syntra\backend
$env:SYNTRA_RUN_DB_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q tests\test_clients_integration.py
Remove-Item Env:SYNTRA_RUN_DB_INTEGRATION
```

Usa únicamente pruebas que creen su propia base descartable. No dirijas pruebas de integración destructivas a `syntra_dev` ni a QA. Los comandos de esta sección no implican que las pruebas se hayan ejecutado en la revisión de este README.

## Estado y límites conocidos

- La Entrega 5 fue declarada cerrada por la responsable del proyecto. El código incluye configuración de mediciones, carga local del formato habilitado, lotes persistidos y consumidor de ingesta; el cierre de una entrega no sustituye una validación de cada entorno.
- En una prueba sintética local reportada anteriormente, el worker procesó 100.000 registros en 71,865 s y 1.000.000 en 816,207 s. Estos resultados usan datos sintéticos y una base descartable; no son una medición de QA ni de datos reales.
- Los objetivos de rendimiento aprobados para la Entrega 5 fueron 180 s para 100.000 registros y 1.799 s para 1.000.000. Sin embargo, los requisitos formales RNF-ESC-01 y RNF-PRF-05 mantienen objetivos distintos: staging en menos de 30 s y carga completa en menos de 10 min, además de 1 min/10 min por tamaño en RNF-PRF-05. La discrepancia documental sigue pendiente de resolución; no se deben tratar los objetivos como equivalentes.
- El estado real de una instalación depende de su base, catálogos, roles, permisos, archivos privados, variables del proceso y workers activos. Este README no afirma que QA esté actualizado con el último código.
- El arranque documentado es manual. Los workers deben ejecutarse como procesos separados y mantenerse activos mientras se necesiten sus colas.

## Documentación oficial

- [Requisitos funcionales y no funcionales](docs/especificaciones/Actores_RF_RNF.xlsx)
- [Arquitectura](docs/especificaciones/Syntra_Arquitectura.html)
- [Contrato OpenAPI](docs/especificaciones/Syntra_openapi.yaml)
- [Mockup aprobado, versión 0.4](docs/especificaciones/Syntra_mockup_v0.4.html)
- [Modelo oficial de persistencia operativa](docs/especificaciones/Modelo%20de%20Persistencia/v1_Syntra_schema.sql)
- [Modelo de persistencia histórica](docs/especificaciones/Modelo%20de%20Persistencia/v1_Syntra_schema_historico.sql), separado del esquema operativo.
- [Formato de carga DBFormatoSimple](docs/especificaciones/Formatos/DBFormatoSimple.csv)

