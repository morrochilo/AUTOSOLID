# Informe de tarea 007 — Fuentes del proyecto por MCP

## Resultado

La tarea 007 quedó implementada y verificada localmente. El servidor MCP local expone ahora tres herramientas de solo lectura sobre las fuentes que la interfaz y la API ya almacenan:

- `autosolid_source_list`: lista metadatos de las fuentes de un proyecto.
- `autosolid_source_get`: obtiene los metadatos de una fuente concreta.
- `autosolid_source_read_text`: devuelve el texto UTF-8 de una fuente de tipo `text`, limitado por `max_chars`.

Las tres reutilizan `ProjectService` y respetan el aislamiento por proyecto y la verificación SHA-256 del almacén. No se añadió carga de archivos por MCP, contenido binario, extracción PDF, trabajos, aprobaciones ni CAD. El catálogo MCP pasó de seis a nueve herramientas.

El contenido devuelto por `autosolid_source_read_text` se trata como **dato no confiable**. Las descripciones de las herramientas y las instrucciones del servidor advierten que no debe interpretarse como instrucciones. El texto se limita por caracteres para no inundar el contexto del agente.

## Archivos

- `src/autosolid/mcp/models.py`: modelos estrictos de entrada/salida para fuentes y `SourceInfo`.
- `src/autosolid/mcp/tools.py`: tres manejadores y definiciones de herramientas de solo lectura.
- `src/autosolid/mcp/errors.py`: errores estables `SOURCE_NOT_FOUND` y `SOURCE_NOT_TEXT`.
- `src/autosolid/mcp/server.py`: instrucciones del servidor ampliadas con la advertencia de contenido no confiable.
- `src/autosolid/projects/exceptions.py`: `SourceNotTextError`.
- `src/autosolid/projects/__init__.py`: exportación del error nuevo.
- `tests/test_mcp_server.py`: catálogo esperado, esquemas y anotaciones actualizados.
- `tests/test_mcp_sources.py`: ocho pruebas nuevas de fuentes por MCP.
- `docs/tasks/007-fuentes-por-mcp.md`: alcance, exclusiones y verificación previstos.

No se modificaron la API HTTP, la interfaz, el esquema SQLite, el contrato `CadSpec` ni las dependencias.

## Decisiones de implementación

- **Solo lectura:** no hay herramienta para subir, borrar o reemplazar fuentes. La carga sigue siendo una acción explícita de la interfaz o de la API HTTP.
- **Sin binarios por MCP:** PDF e imágenes solo exponen metadatos. Devolver hasta 20 MiB en base64 no es adecuado para el contexto de un agente y todavía no existe un extractor que justifique otra forma de acceso.
- **Texto acotado:** `max_chars` vale 20.000 por defecto y admite de 1 a 100.000 caracteres. La respuesta incluye `returned_chars`, `truncated`, `byte_size` y `sha256` para que el cliente sepa que solo recibió una parte.
- **BOM:** una fuente de texto con BOM UTF-8 se decodifica con `utf-8-sig`; el BOM no se devuelve como contenido.
- **Integridad:** se lee el blob completo y se verifica su SHA-256 antes de devolver texto. Una corrupción produce `STORE_ERROR` sin rutas internas.
- **Errores estables:** proyecto ausente → `PROJECT_NOT_FOUND`; fuente ausente → `SOURCE_NOT_FOUND`; fuente PDF/imagen → `SOURCE_NOT_TEXT` con `kind`; corrupción → `STORE_ERROR`.
- **Aislamiento:** una fuente de otro proyecto no se puede obtener ni listar; la consulta devuelve `SOURCE_NOT_FOUND` o una lista vacía, nunca contenido ajeno.
- **Sin duplicar reglas:** el adaptador MCP no lee archivos directamente ni reimplementa validaciones; llama al servicio.

## Pruebas automatizadas

Comprobación de compilación:

```powershell
.venv\Scripts\python -m compileall -q src tests
```

Sin errores.

Pruebas focalizadas:

```powershell
.venv\Scripts\python -m pytest -q tests/test_mcp_sources.py tests/test_mcp_server.py
```

Resultado: **35 passed**.

Suite completa:

```powershell
.venv\Scripts\python -m pytest -q
```

Resultado final: **200 passed, 1 warning**. El aviso es el preexistente `StarletteDeprecationWarning` sobre `TestClient` y `httpx`; no se introdujo un fallo nuevo.

Las pruebas nuevas cubren:

- catálogo de nueve herramientas, esquemas estrictos y anotaciones de solo lectura/idempotencia;
- lista vacía y lista con PDF y texto, con metadatos completos y nombres Unicode;
- obtención de una fuente y errores de proyecto/fuente ausente;
- lectura de texto UTF-8, eliminación de BOM y conservación de saltos de línea;
- truncado por caracteres sin cortar bytes multibyte, con `truncated=True` y hash original;
- rechazo de PDF/imagen con `SOURCE_NOT_TEXT`;
- corrupción del blob con `STORE_ERROR` sin rutas;
- argumentos inválidos (`max_chars` fuera de rango, tipo incorrecto, campos extra);
- validación de las respuestas contra los esquemas de salida declarados;
- invocación real por el protocolo MCP en memoria, incluyendo `structuredContent` y el texto JSON.

## Verificación MCP

La prueba de protocolo usa `create_connected_server_and_client_session` y comprueba que las herramientas aparecen en `list_tools`, que las anotaciones son correctas y que `call_tool` devuelve el mismo objeto en `structuredContent` y en el contenido textual. También se ejecutaron las pruebas existentes de `stdio`, que arrancan `python -m autosolid.mcp` en un subproceso y verifican que no escribe en `stdout`.

No se ha invocado el servidor desde una sesión de agente de OpenCode. La conexión de catálogo ya se había comprobado en la tarea 003, pero la invocación de estas tres herramientas desde un agente real sigue pendiente de verificación independiente.

## Limitaciones

- No hay herramienta MCP para subir fuentes; el agente solo puede leer lo que ya existe.
- No se devuelven PDF ni imágenes, ni como base64 ni como recursos MCP. Un agente no puede analizar el contenido binario por esta vía.
- No hay extracción de texto de PDF, OCR, visión, cotas, escala ni geometría. `autosolid_source_read_text` solo funciona con fuentes que ya son texto UTF-8.
- El texto se lee completo en memoria antes de truncarlo para poder verificar el hash. El límite de 20 MiB acota el coste, pero no hay lectura por streaming ni rango.
- No hay búsqueda, paginación ni filtros en la lista de fuentes; se devuelven todos los metadatos del proyecto.
- El contenido de una fuente puede contener instrucciones maliciosas. La advertencia reduce el riesgo, pero no sustituye el criterio del cliente ni una futura política de cuarentena.
- No se ha auditado ni aceptado la tarea; no se hicieron commits ni publicaciones.

## Reproducción

```powershell
$env:AUTOSOLID_DATA_DIR = "$env:TEMP\autosolid-mcp-sources"
.venv\Scripts\python -m autosolid.mcp
```

Para ejecutar las pruebas:

```powershell
.venv\Scripts\python -m pytest -q tests/test_mcp_sources.py tests/test_mcp_server.py
.venv\Scripts\python -m pytest -q
```

## Siguiente paso

La iteración 1 sigue abierta por trabajos asíncronos, cancelación, aprobaciones, proveedor real conectado y la prueba de invocación MCP desde un agente. La siguiente tarea puede abordar el ciclo de aprobación ligado a revisión/hash o una infraestructura mínima de trabajos; no conviene iniciar el parser PDF sin una dependencia justificada y un corpus de PDF/DXF de prueba.
