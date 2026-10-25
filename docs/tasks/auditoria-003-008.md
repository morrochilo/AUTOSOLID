# Auditoría independiente de las tareas 003–008

Fecha: 2026-10-25

## Veredicto actualizado

Las correcciones 009/010 resolvieron los hallazgos con regresiones. La suite actual tiene **274 pruebas superadas**, incluida concurrencia de aprobaciones, inmutabilidad de todas las tablas, event loop y proveedores con límite portable de anidación JSON. El conjunto es candidato a PR después de la validación de empaquetado y privacidad.

Las tareas 001–002 ya integradas no se reabrieron. Los hallazgos de la tabla siguiente se conservan como registro de la auditoría original; su resolución está documentada en `009-informe.md` y `010-informe.md`.

## Evidencia positiva

- `pytest`: **254 pruebas superadas**, una advertencia conocida de Starlette/TestClient.
- `compileall` sobre `src` y `tests`: correcto.
- `node --check src/autosolid/api/static/app.js`: correcto.
- OpenCode 1.19.4 conectó con el servidor MCP local.
- DeepSeek invocó realmente `autosolid_project_create` y `autosolid_project_list`; el proyecto quedó persistido y el agente observó **11 herramientas MCP**.
- Navegador real: crear proyecto, editar `CadSpec`, validar, guardar revisión 1 y aprobar diseño; la interfaz mostró la aprobación vigente.
- No se ejecutó ninguna construcción CAD ni se afirmó extracción PDF.

## Hallazgos

| Severidad | Hallazgo | Ubicación principal | Corrección requerida |
|---|---|---|---|
| Alta | `list_approvals`/`get_approval` combinan lecturas de distintos instantes y pueden devolver estados invertidos. Reproducido: `(1 valid, 2 stale)` cuando el estado real era `(1 stale, 2 valid)`. | `src/autosolid/projects/service.py:260-280` | Leer proyecto, hash e historial en una instantánea SQLite común o consulta coherente. Añadir prueba de carrera. |
| Media | `INSERT OR REPLACE` evita los triggers de inmutabilidad con `recursive_triggers=0`. Afecta a aprobaciones, revisiones, fuentes y artefactos mediante acceso SQLite directo. | `src/autosolid/projects/store.py` | Activar `PRAGMA recursive_triggers=ON` en todas las conexiones y probar `INSERT OR REPLACE` en cada tabla append-only. |
| Media | El MIME global por hash hace que el mismo contenido sea aceptado o rechazado según qué proyecto/extensión lo cargó primero. | `src/autosolid/projects/store.py:541-558`, `projects/sources.py` | Separar metadatos por fuente del blob o clasificar por contenido; probar el mismo bytes como `.pdf` y `.txt` en distinto orden. |
| Media | La subida `async` ejecuta filesystem, `fsync` y SQLite bloqueante en el event loop. | `src/autosolid/api/routes.py:231-246` | Ejecutar `service.add_source` con `anyio.to_thread.run_sync`; probar `/health` durante un bloqueo. |
| Media | JSON patológico puede lanzar `ValueError`/`RecursionError` en vez de `ProviderError`, tanto en contenido como en el sobre HTTP. | `src/autosolid/providers/json_output.py`, `openai_compatible.py` | Normalizar errores de parseo y profundidad como `MODEL_OUTPUT_INVALID`/`PROVIDER_RESPONSE_INVALID`, sin capturar errores del proceso. |
| Media | El simulador acepta `NaN` y respuestas `SimulatedReply` contradictorias que el proveedor real rechazaría. | `src/autosolid/providers/simulated.py` | Serialización estricta `allow_nan=False`, validación común y coherencia contenido/JSON. |
| Baja-media | `SimulatedProvider` no es seguro entre hilos: IDs duplicados, respuestas mal asociadas y posible `IndexError`. | `src/autosolid/providers/simulated.py:40-62` | Proteger petición/índice/cola con un lock o declarar y exigir uso de un solo hilo. |
| Baja | El sobre HTTP acepta `NaN`/`Infinity` y los convierte en metadatos `None`. | `src/autosolid/providers/openai_compatible.py` | Usar rechazo de constantes no finitas también en el sobre. |
| Baja | `frozen=True` no impide mutar listas/diccionarios; el registro del simulador cambia retroactivamente. | `src/autosolid/providers/models.py`, `simulated.py` | Usar contenedores inmutables/copias defensivas y probar el historial. |
| Baja | `base_url` con `?` o `#` vacíos se acepta y forma un endpoint incorrecto. | `src/autosolid/providers/config.py:182-186,266-268` | Rechazar los delimitadores aunque query/fragmento sean vacíos. |
| Baja | `timeout_seconds` admite `Fraction` y la vista pública deja de ser JSON serializable. | `src/autosolid/providers/config.py` | Normalizar a `float` después de validar. |

Los cinco primeros defectos funcionales seleccionados —carrera, `INSERT OR REPLACE`, MIME, JSON patológico y `NaN` del simulador— se reprodujeron también desde el entorno de auditoría principal. Los demás se confirmaron en la revisión focalizada de proveedores.

## Áreas sin defectos nuevos confirmados

- MCP comparte `ProjectService`, usa salida estructurada y no expone aprobación por escritura ni acceso arbitrario a archivos.
- La creación de aprobaciones comprueba revisión/hash y no autoriza CAD.
- No se confirmó traversal por nombre de fuente, XSS en la interfaz revisada ni fuga directa de API keys.
- Redirecciones de proveedores están bloqueadas; proxies del sistema están desactivados por defecto.

## Limitaciones que siguen abiertas

- No se llamó a un proveedor externo real ni a un runtime local de inferencia.
- No hay extracción PDF/OCR/DXF, cotas, escala ni `DrawingSpec`.
- No hay trabajos asíncronos/cancelación, aprobación de construcción ni SolidWorks/AutoCAD.
- La aprobación `design` no tiene destino, expiración, consumo único ni revocación; no es un permiso de construcción.
- La prueba de navegador es una pasada real, no una suite E2E automatizada en CI.
- Persiste la advertencia de depreciación de Starlette/TestClient.

## Puerta para el próximo PR

1. Corregir la carrera y todos los hallazgos medios con pruebas que fallen antes de la corrección.
2. Resolver o planificar explícitamente los hallazgos bajos de proveedores.
3. Ejecutar toda la suite, protocolo MCP real y flujo de navegador otra vez.
4. Revisar migraciones v1→v2→v3 y compatibilidad de datos existentes.
5. Repetir auditoría de privacidad y `git diff --check` antes de commit.

Hasta entonces, el código permanece local en la rama `feat/003-mcp-local`, sin aceptación ni publicación como conjunto 003–008.
