# Informe de la tarea 012 — Cola y aprobación de construcción

## Resultado

La aprobación de construcción de un solo uso, el consumo atómico, la cola serial por proceso y el runner del agente C# existente están implementados en el servicio Python. La API local expone creación de aprobaciones `build`, solicitud de construcción, consulta de trabajos y reintento.

No se añadió construcción por MCP ni botón/UI de construcción. No se modificó `CadSpec`, `SolidWorksBuilder` ni el contrato del agente C#. El runner ejecuta el ejecutable configurado con una lista de argumentos y `shell=False`; ningún modelo elige comandos, destinos ni aprobaciones.

Un trabajo real terminó en `completed` con el agente de la tarea 011 y SolidWorks 2024 (`RevisionNumber = 32.0.1`). No se cerró SolidWorks ni se tocaron documentos del usuario.

## Implementación

### Persistencia y migración

- Esquema SQLite v5, migración hacia delante desde v4, v3, v2 y v1 sin recrear tablas existentes.
- `build_approvals`: alcance `build`, proyecto, revisión, SHA-256 del `CadSpec`, destino relativo canónico, hash del destino, revisor, `created_at` y `expires_at`. Es append-only: triggers impiden `UPDATE`, `DELETE` y reutilización del identificador.
- `build_jobs`: estados `queued/running/completed/failed`, intento, timestamps, proyecto/revisión/aprobación, clave de idempotencia, destino, error estable y metadatos del artefacto (nombre relativo, SHA-256 y tamaño).
- `build_consumptions`: una fila por aprobación y trabajo. El trabajo y el consumo se insertan en la misma transacción `BEGIN IMMEDIATE`, de modo que dos consumidores no pueden usar la misma aprobación.
- La aprobación original nunca se actualiza. El estado `used/expired/stale/valid` se calcula desde la revisión vigente, la expiración y la tabla de consumos.
- Triggers adicionales protegen la identidad del trabajo y el historial de consumos.

### Destino

- El servidor configura el directorio de salida con `AUTOSOLID_BUILD_DIR` o el constructor de `ProjectService`; por defecto usa `AUTOSOLID_DATA_DIR/builds`.
- Solo se aceptan rutas relativas terminadas en `.sldprt`, con `/` o `\`, sin unidad, sin `/` inicial, sin `..`, sin caracteres de control, sin caracteres inválidos de Windows y sin archivos existentes.
- El hash canónico usa la ruta relativa resuelta y, en Windows, `normcase`; no se guarda ni se expone la ruta absoluta del servidor.
- Se comprueba la ausencia del destino al aprobar, al consumir y antes de ejecutar. La escritura final se hace con enlace/creación exclusiva, nunca con sobrescritura.

### Runner y trabajos

- `SubprocessSolidWorksRunner` usa `subprocess.Popen` con lista de argumentos, `shell=False`, timeout, límite de stdout/stderr y entorno opcional.
- Valida un único JSON de stdout con `status=ok`, `rebuildSucceeded=true`, `errors=0`, `volumeM3` finito no negativo y `volumeDifferenceM3` finito dentro de `1e-9 m³`.
- Comprueba que la salida sea un `.sldprt` nuevo, no vacío y dentro del directorio autorizado.
- La cola es serial por proceso (con un bloqueo de proceso adicional) y en memoria; SQLite conserva el estado durable.
- El agente escribe en un archivo temporal dentro de `.work`; solo al validar el contrato se publica en el destino final. Los errores se convierten en códigos estables sin rutas.
- Reintentar un trabajo fallido incrementa `attempt` y reutiliza la aprobación ya consumida. Reintentar uno completado es idempotente. Un trabajo `queued` puede reencolarse explícitamente tras reiniciar el proceso.
- Si la revisión cambia antes de ejecutar, el trabajo falla con `APPROVAL_STALE` y no crea archivo.

### API

- `POST /api/v1/projects/{project_id}/build-approvals` (201).
- `GET /api/v1/projects/{project_id}/build-approvals`.
- `GET /api/v1/projects/{project_id}/build-approvals/{approval_id}`.
- `POST /api/v1/projects/{project_id}/builds` (202 nuevo, 200 si la clave de idempotencia ya existía).
- `GET /api/v1/projects/{project_id}/builds`.
- `GET /api/v1/projects/{project_id}/builds/{job_id}`.
- `POST /api/v1/projects/{project_id}/builds/{job_id}/retry` (202 si se reencola, 200 si no cambia).

La solicitud de construcción exige `approval_id`, `destination` e `idempotency_key`. La aprobación exige `revision`, `sha256`, `approved_by`, `destination`, `expires_in_seconds` opcional (30–3600) y `note` opcional.

## Evidencia verificada

| Comprobación | Resultado |
|---|---|
| Suite completa `pytest` | 339 pruebas superadas, 1 aviso preexistente de Starlette/httpx |
| Pruebas nuevas de construcción | 65 superadas (dominio, almacén, migración, API, concurrencia, runner simulado) |
| `dotnet build` del agente C# | 0 errores y 0 advertencias |
| `compileall` de `src` y `tests` | sin errores |
| Trabajo real | `completed`, aprobación `used`, SLDPRT nuevo de 54 884 bytes |
| Verificación real del SLDPRT | `status=ok`, `rebuildSucceeded=true`, volumen `8.000000000000001e-06 m³`, caja `40×20×10 mm`, errores 0, avisos 4 |
| SolidWorks | `RevisionNumber = 32.0.1` (2024) |

La prueba real usó una extrusión conocida de 40 × 20 × 10 mm, un directorio temporal fuera del repositorio y la aprobación de construcción del flujo normal. El trabajo real fue `job_40ed03ca081241b1b0be9d89205edc9b`; el artefacto declarado fue `task012/block-40x20x10.sldprt` con SHA-256 `f84756f0dd4796c31a02cf990d066d80e25fd39322b6f60b0024d29105435c19`. No se cerró SolidWorks.

La verificación posterior con el comando `verify` del agente abrió y reconstruyó el archivo sin guardarlo; reportó los 4 avisos, que no se ocultan. El runner del trabajo ya había validado `status=ok`, reconstrucción, volumen finito y diferencia de volumen antes de publicar el archivo.

## Incidencias resueltas

- El primer trabajo real terminó `OUTPUT_WRITE_FAILED` aunque el SLDPRT era válido: SolidWorks mantenía abierto el archivo temporal y la limpieza del directorio temporal fallaba. Se cambió la limpieza a best-effort (`ignore_cleanup_errors=True`) y se separó el fallo de `unlink` del resultado del trabajo. El segundo trabajo terminó `completed`.
- Una carrera entre dos solicitudes con la misma clave de idempotencia podía devolver `BUILD_APPROVAL_CONSUMED` en vez del trabajo existente. La ruta no válida ahora delega en la transacción atómica, que devuelve el trabajo de la misma clave antes de rechazar el consumo.
- Los dos consumidores concurrentes y las dos solicitudes concurrentes con la misma clave están cubiertos por pruebas con barrera.
- Reintentar mientras el procesador anterior aún no había retirado la entrada de la cola podía dejar el trabajo `queued` sin procesar. La cola ya no deduplica por una lista en memoria; las ejecuciones duplicadas son no-ops porque el paso a `running` es transaccional.

## Pendiente y limitaciones

- No hay MCP de construcción ni consulta MCP de trabajos; se dejó fuera para no ampliar superficie en esta tarea.
- No hay botón ni panel de UI para aprobar construcción, solicitar trabajo o reintentar. La UI existente sigue siendo de diseño/fuentes.
- La cola es por proceso. Si el proceso muere con trabajos `running`, no hay recuperación automática; un trabajo `queued` puede reencolarse con `retry`, pero un `running` huérfano requiere intervención y no se marca automáticamente como fallido.
- No se añadió cancelación, prioridad, límite de trabajos pendientes ni recolección de `.work` bloqueado por SolidWorks.
- El runner valida el contrato JSON del agente, pero no persiste el volumen ni los avisos en el trabajo; solo guarda estado, error y metadatos del artefacto.
- El artefacto se registra por nombre/hash/tamaño en el trabajo; no se copia al almacén content-addressed.
- La aprobación de construcción no exige una aprobación de diseño previa. Son alcances independientes y ambas son explícitas.
- Solo se probó la familia aceptada por el agente de la tarea 011: un croquis de líneas con una extrusión o revolución. No se probaron otras versiones de SolidWorks, otras plantillas, cortes, arcos ni ensamblajes.
- No se afirma fabricabilidad, precisión mecánica ni cobertura de documentos reales.

## Privacidad

No se añadieron secretos, rutas personales, binarios CAD ni documentos del usuario a los cambios. Las pruebas usan directorios temporales y el agente simulado marca sus resultados con `simulated: true`; ninguna prueba automatizada afirma haber verificado SolidWorks real.
