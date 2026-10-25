# Informe de tarea 006 — Fuentes inmutables y almacén de artefactos

## Resultado

La tarea 006 quedó implementada y verificada localmente. Un proyecto puede recibir PDF, imágenes PNG/JPEG/WebP y texto UTF-8; el contenido se guarda una sola vez por hash SHA-256 en `AUTOSOLID_DATA_DIR/artifacts/`, se indexa en SQLite y se sirve de nuevo con verificación de integridad. La interfaz local permite cargar, listar, descargar y referenciar esas fuentes en el editor `CadSpec`.

La ingesta se limita a almacenar bytes y metadatos. No se extrae texto, geometría, páginas, cotas ni escala, y no se valida la estructura interna de PDF o imágenes. Una fuente cargada no crea, modifica ni aprueba una revisión `CadSpec`: la referencia solo se inserta en el editor cuando el usuario pulsa «Añadir al CadSpec», y todavía debe validar y guardar.

## Archivos

- `src/autosolid/artifacts/store.py`: almacén content-addressed con escritura atómica, deduplicación por SHA-256 y lectura verificada.
- `src/autosolid/artifacts/__init__.py`: exportación del almacén y su error.
- `src/autosolid/projects/sources.py`: normalización de nombres, clasificación por extensión, comprobación de firmas y UTF-8, y límite de tamaño.
- `src/autosolid/projects/exceptions.py`: errores de fuente ausente, fuente inválida y fuente demasiado grande.
- `src/autosolid/projects/store.py`: esquema SQLite v2, migración v1→v2, tablas `artifacts` y `sources`, triggers de inmutabilidad y consultas de fuentes.
- `src/autosolid/projects/service.py`: casos de uso `add_source`, `list_sources`, `get_source` y `read_source`.
- `src/autosolid/projects/__init__.py`: exportaciones públicas nuevas.
- `src/autosolid/api/routes.py`: subida binaria, listado, metadatos, descarga y cabeceras seguras.
- `src/autosolid/api/errors.py`: traducción de errores de fuente a códigos HTTP estables.
- `src/autosolid/api/static/index.html`: panel «Fuentes del proyecto» y selector de archivo.
- `src/autosolid/api/static/app.css`: estilos del panel y de la lista de fuentes.
- `src/autosolid/api/static/app.js`: carga, listado, descarga, estados y referencia explícita al editor.
- `tests/test_sources.py`: pruebas de almacén, validación, deduplicación, corrupción y migración.
- `tests/test_api_sources.py`: pruebas HTTP positivas y negativas, descarga y persistencia.
- `tests/test_projects_store.py`: versión de esquema actualizada y migraciones 1 y 2.
- `tests/test_ui.py`: controles de fuentes, endpoints usados y ausencia de recursos externos.
- `.gitignore`: `artifacts/` pasó a `/artifacts/` para excluir solo el directorio de datos de la raíz y no el paquete `src/autosolid/artifacts/`.
- `docs/tasks/006-fuentes-y-artefactos.md`: alcance, exclusiones y verificación previstos.

## Decisiones de implementación

- **Content-addressed:** el nombre del blob es su SHA-256. La escritura usa un archivo temporal en el mismo directorio, `fsync` y `os.replace`; una lectura vuelve a calcular el hash y rechaza contenido corrupto.
- **Deduplicación por proyecto:** `(project_id, sha256)` es único. Subir otra vez el mismo contenido al mismo proyecto devuelve la fuente existente y HTTP 200; el mismo contenido en otro proyecto comparte blob pero recibe otro `source_id`.
- **SQLite v2:** `artifacts` guarda tamaño y tipo MIME; `sources` guarda proyecto, hash, tipo, nombre y fecha. Los triggers impiden `UPDATE` y `DELETE` sobre ambas tablas. La migración desde v1 crea las tablas sin tocar proyectos ni revisiones.
- **Validación de cabecera, no de estructura:** se acepta `.pdf` con firma `%PDF-`; `.png`, `.jpg`/`.jpeg` y `.webp` con su firma; `.txt`, `.md`, `.csv` y `.json` como UTF-8 sin NUL ni contenido vacío. No se comprueba que un PDF tenga objetos, páginas o xref válidos.
- **Límite de 20 MiB:** se comprueba primero `Content-Length` y después cada chunk del cuerpo; el servicio repite la comprobación para cualquier cliente que no pase por HTTP. El límite es configurable en `ProjectService` para pruebas.
- **Sin `python-multipart`:** la subida usa cuerpo binario y `?filename=` en la query, de modo que no se añadió ninguna dependencia.
- **Descarga segura:** `Content-Disposition: attachment` con nombre ASCII de respaldo y `filename*=UTF-8''`; `ETag`, `X-Content-SHA256`, `nosniff` y caché inmutable. Las respuestas y los errores no exponen rutas internas.
- **Inmutabilidad:** no hay endpoints para editar, reemplazar o borrar fuentes. Tampoco hay recolector de blobs huérfanos.
- **Referencia manual:** la interfaz inserta `{id, kind, sha256}` en `sources` del editor solo tras una acción explícita. No guarda, no valida y no altera la revisión vigente.
- **Sin cambios en `CadSpec`:** el modelo y las reglas de validación geométrica no se modificaron; una referencia a una fuente sigue siendo un dato declarado por el usuario.

## Pruebas automatizadas

Comprobación de sintaxis y compilación:

```powershell
.venv\Scripts\python -m compileall -q src
node --check src/autosolid/api/static/app.js
```

Ambos comandos terminaron sin errores.

Pruebas focalizadas:

```powershell
.venv\Scripts\python -m pytest -q tests/test_projects_store.py tests/test_api_projects.py
.venv\Scripts\python -m pytest -q tests/test_sources.py tests/test_api_sources.py tests/test_projects_store.py
.venv\Scripts\python -m pytest -q tests/test_ui.py tests/test_sources.py tests/test_api_sources.py
```

Resultados: `49 passed`, `49 passed` y `39 passed` respectivamente, con el aviso preexistente de Starlette/httpx.

Suite completa:

```powershell
.venv\Scripts\python -m pytest -q
```

Resultado final: **192 passed, 1 warning**. El aviso es el preexistente `StarletteDeprecationWarning` sobre `TestClient` y `httpx`; no se introdujo un fallo nuevo.

Las pruebas nuevas cubren, entre otros casos:

- escritura, lectura y persistencia de una fuente tras reabrir el almacén;
- deduplicación en el mismo proyecto y aislamiento entre proyectos;
- extensión no admitida, firma incorrecta, tipo declarado incoherente, UTF-8 inválido, NUL, archivo vacío y nombre con rutas o controles;
- límite de tamaño antes de escribir el blob;
- corrupción del blob detectada y reparación mediante una nueva subida;
- inmutabilidad de metadatos en SQLite;
- migración de una base v1 real a v2;
- respuestas HTTP 201/200/422/413/404 y descarga con cabeceras;
- ausencia de rutas internas en errores;
- controles de fuentes en la interfaz y ausencia de `innerHTML`, `eval` o URLs externas.

## Verificación real en navegador

Se arrancó el servidor con datos temporales:

```powershell
$env:AUTOSOLID_DATA_DIR = "$env:TEMP\opencode\autosolid-src-smoke"
.venv\Scripts\python -m autosolid.api --host 127.0.0.1 --port 8765
```

Se usó el navegador del entorno OpenCode y el `input` real de archivo, sin el diálogo nativo del sistema operativo.

Flujo positivo:

1. Se creó el proyecto `Bancada con fuentes`.
2. Se cargó `plano-prueba.pdf` (589 B). La interfaz mostró `Fuente añadida: plano-prueba.pdf.` y el SHA-256 `2cd4b394f782cb10cc54d9a374e23abe08136bf18fae7379e0c242db9f98da0b`.
3. Se cargó `nota-tecnica.txt` (29 B, texto `Cota 40 mm; longitud 80 mm.`). El SHA-256 mostrado fue `b3bccbf...` y el contador pasó a 2.
4. «Añadir al CadSpec» insertó la referencia del PDF en el editor y mostró `Sin guardar`; no se guardó nada automáticamente.
5. Se completó un `CadSpec` de rectángulo 40 × 20 mm con extrusión de 10 mm, se validó y se guardó la revisión 1 con hash `c3d18f1254b64ee369b7931d137c25a65065b915a86851f6cf4b845eb595a0bc`.
6. Se añadió también la referencia del texto, se validó y se guardó la revisión 2 con hash `8c272241ba792db6cca31b912b6e84ba7f861fcc82b2c6f72a8561a5284211df`.
7. Tras recargar la página se conservaron la revisión 2, las dos fuentes y las dos referencias en el `CadSpec`.

Flujos negativos y de borde:

- La descarga del PDF desde la interfaz devolvió 589 B con el mismo SHA-256 que el archivo original.
- `falso.pdf` (12 B, sin cabecera PDF) fue rechazado con HTTP 422 `INVALID_SOURCE` y `reason: signature`; el contador de fuentes no cambió.
- Volver a subir el mismo PDF devolvió 200 y el mensaje `La fuente ya existía: plano-prueba.pdf.`, sin duplicar la fuente.
- La consola del navegador solo registró el 422 esperado del archivo inválido; no aparecieron errores JavaScript adicionales.

Los procesos temporales se detuvieron, la pestaña se cerró y los directorios de datos y de archivos de prueba se eliminaron.

## Limitaciones

- No hay parser PDF/DXF, OCR, visión, clasificación de páginas, extracción de cotas, cálculo de escala ni generación de `DrawingSpec`.
- La validación de firmas y UTF-8 no demuestra que un PDF o una imagen sean estructuralmente válidos ni legibles por un futuro extractor.
- No hay antivirus, cuarentena, cifrado en reposo, control de acceso multiusuario, cuotas por proyecto ni retención.
- No se pueden editar, reemplazar ni borrar fuentes; tampoco existe recolector de blobs huérfanos. Si falla la transacción SQLite después de escribir el blob, el archivo puede quedar sin metadatos.
- La descarga no admite `Range`, previsualización inline ni conversión; siempre es una descarga completa.
- La referencia insertada en el editor no comprueba que la fuente exista en el proyecto; la validación real del `CadSpec` sigue siendo la del contrato existente.
- MCP no expone todavía herramientas de fuentes; la API y la interfaz son los únicos consumidores.
- La prueba de navegador es manual, no una prueba E2E automatizada en CI.
- No se ha llamado a ningún proveedor externo ni se ha verificado SolidWorks o AutoCAD.
- No se ha auditado ni aceptado la tarea; no se hicieron commits ni publicaciones.

## Reproducción

```powershell
$env:AUTOSOLID_DATA_DIR = "$env:TEMP\autosolid-sources"
.venv\Scripts\python -m autosolid.api --host 127.0.0.1 --port 8000
# abrir http://127.0.0.1:8000/
```

Para ejecutar las pruebas:

```powershell
.venv\Scripts\python -m pytest -q
```

## Siguiente paso

La siguiente tarea debe elegir entre completar la iteración 1 (trabajos asíncronos, cancelación, aprobaciones, proveedor real y prueba MCP de extremo a extremo) o exponer las fuentes por MCP. No conviene iniciar el parser PDF de la iteración 2 sin una dependencia justificada y un corpus de PDF/DXF de prueba.

La opción de exponer las fuentes por MCP se abordó en la [tarea 007](007-informe.md), limitada a metadatos y texto UTF-8.
