# Tarea 006 — Fuentes inmutables y almacén de artefactos

## Contexto

Las tareas 001–005 están implementadas. Existen `CadSpec`, proyectos y
revisiones SQLite, la API FastAPI, la fachada MCP y una interfaz local que
revisa y guarda especificaciones. La iteración 1 del plan maestro todavía pide
almacenamiento de artefactos y una interfaz con carga de fuente; la iteración 2
necesitará esas fuentes como entrada, pero aún no hay parser PDF/DXF ni corpus.

Leer `AGENTS.md`, `docs/01-plan-maestro.md`, `docs/02-arquitectura.md`,
`docs/03-contrato-cad-y-apis.md`, `docs/05-guia-de-colaboracion.md` y los
informes 003–005 antes de modificar código.

## Objetivo

Guardar de forma inmutable y content-addressed las fuentes que el usuario carga
en un proyecto (PDF, imágenes y texto UTF-8), exponerlas por la API y mostrarlas
en la interfaz local. Una fuente cargada podrá referenciarse en el `CadSpec`,
pero no se interpretará, rasterizará ni convertirá en geometría en esta tarea.

El almacén debe compartirse entre API, interfaz y futuro MCP a través del mismo
`ProjectService`. No se duplican reglas en los adaptadores.

## Alcance obligatorio

1. Almacén de artefactos en `AUTOSOLID_DATA_DIR/artifacts/`, identificado por
   SHA-256, con escritura atómica, deduplicación por contenido y lectura con
   verificación de integridad.
2. Migración SQLite de la versión 1 a la 2 con tablas de artefactos y fuentes,
   asociación por proyecto, claves foráneas e inmutabilidad de metadatos.
3. Validación de fuentes en el servicio:
   - tipos admitidos: `pdf`, `image` y `text`;
   - extensiones `.pdf`; `.png`, `.jpg`, `.jpeg`, `.webp`; `.txt`, `.md`,
     `.csv`, `.json`;
   - comprobación de firma PDF (`%PDF-`), firma PNG/JPEG/WebP y UTF-8 válido
     para texto, sin caracteres nulos;
   - límite de 20 MiB por fuente, configurable en el servicio para pruebas;
   - nombre base saneado, sin rutas, controles ni nombres vacíos;
   - deduplicación por `(proyecto, sha256)`.
4. API bajo `/api/v1`:
   - `POST /projects/{project_id}/sources?filename=...` con cuerpo binario;
   - `GET /projects/{project_id}/sources`;
   - `GET /projects/{project_id}/sources/{source_id}`;
   - `GET /projects/{project_id}/sources/{source_id}/content`.
5. Descarga segura: `Content-Disposition: attachment`, nombre codificado,
   `ETag`/hash, `nosniff`, sin rutas internas en respuestas ni errores.
6. Interfaz local:
   - selector de archivo y carga por proyecto;
   - lista de fuentes con tipo, tamaño, hash y enlace de descarga;
   - acción explícita para insertar la referencia en el editor JSON, sin
     guardar ni validar automáticamente;
   - estados de carga, error y vacío accesibles.
7. Pruebas positivas y negativas de almacén, migración, servicio, API, UI,
   descarga, límites, nombres y corrupción.
8. Verificación real en navegador con carga, descarga, referencia en el editor
   y recarga del proyecto.
9. Actualizar README, plan maestro, arquitectura, contrato y el informe de la
   tarea.

## Fuera de alcance

- Extraer texto, vectores, páginas, cotas, vistas o renders de PDF.
- OCR, visión, clasificación de páginas o cálculo de escala.
- Parsear DXF/DWG o validar estructura interna de PDF/imágenes.
- Antivirus, cuarentena, cifrado en reposo o control de acceso multiusuario.
- Trabajos asíncronos, cancelación, aprobaciones, proveedores y CAD.
- Modificar el contrato `CadSpec`, las herramientas MCP o las reglas de
  validación geométrica.
- Borrar, reemplazar o editar fuentes ya cargadas.
- Recolectar blobs huérfanos o implementar retención.
- Añadir dependencias, Node, bundlers, CDN o recursos externos.

## Restricciones

- No hacer commits ni publicar.
- No modificar pruebas existentes para ocultar fallos.
- No afirmar extracción, previsualización o validación de PDF si solo se
  comprobó la cabecera.
- Mantener el estilo del proyecto: español en documentación/interfaz, Python
  3.11+, Pydantic/FastAPI existentes.
- La API sigue siendo local; no se añade autenticación remota ni CORS abierto.
- La adición de una fuente no cambia la revisión `CadSpec` ni la aprueba.

## Riesgos y decisiones

- La firma de archivo solo descarta errores evidentes; no sustituye un parser.
- El límite se aplica al cuerpo recibido y al servicio; no hay análisis de
  malware.
- Si el archivo se escribe pero falla la transacción SQLite, puede quedar un
  blob huérfano. Es inocuo y se documenta; no se borra automáticamente.
- El mismo contenido en dos proyectos comparte blob pero tiene IDs de fuente
  distintos. El mismo contenido en un proyecto es idempotente.
- La referencia al `CadSpec` se inserta solo por acción del usuario; la UI no
  altera la revisión guardada.
- No se puede afirmar que una fuente sea legible por el futuro extractor solo
  porque haya pasado la validación de tipo.

## Verificación

- `pytest` completo.
- Pruebas nuevas de migración v1→v2, hash, deduplicación, aislamiento entre
  proyectos, validación de tipo/firma/UTF-8, límite, rutas, descarga,
  cabeceras, corrupción y persistencia tras reabrir.
- Pruebas de UI para el selector, los endpoints usados y la ausencia de
  recursos externos.
- Arranque real en `127.0.0.1` con datos temporales: cargar PDF y texto, listar,
  descargar, insertar referencia, validar/guardar y recargar.
- Comprobar que no se añadieron dependencias ni archivos externos.
- Informe con comandos, resultados y limitaciones.

Resultado: [`006-informe.md`](006-informe.md).
