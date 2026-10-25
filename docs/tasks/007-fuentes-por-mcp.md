# Tarea 007 — Fuentes del proyecto por MCP

## Contexto

Las tareas 001–006 están implementadas. Existen `CadSpec`, proyectos y revisiones SQLite, la API FastAPI, la interfaz local y un almacén inmutable de fuentes. El servidor MCP local expone seis herramientas de proyectos y diseño, pero no permite a un agente listar ni leer las fuentes que la interfaz ya guarda.

La iteración 1 pide exponer operaciones de lectura por MCP usando el mismo servicio que la interfaz y la API. Esta tarea cubre solo la lectura de fuentes; no añade análisis, extracción PDF, trabajos, aprobaciones ni CAD.

Leer `AGENTS.md`, `docs/01-plan-maestro.md`, `docs/02-arquitectura.md`, `docs/03-contrato-cad-y-apis.md`, `docs/05-guia-de-colaboracion.md` y los informes 003–006 antes de modificar código.

## Objetivo

Añadir herramientas MCP de solo lectura para listar metadatos de fuentes, obtener una fuente concreta y leer el contenido de fuentes de texto UTF-8. Todas las operaciones reutilizan `ProjectService` y respetan el aislamiento por proyecto y las comprobaciones de integridad existentes.

## Alcance obligatorio

1. Herramientas MCP:
   - `autosolid_source_list`: lista fuentes de un proyecto con metadatos;
   - `autosolid_source_get`: obtiene una fuente por `project_id` y `source_id`;
   - `autosolid_source_read_text`: devuelve texto UTF-8 de una fuente `text`, con límite de caracteres y aviso de truncado.
2. Las herramientas se declaran como lectura e idempotentes, con esquemas estrictos de entrada y salida.
3. `autosolid_source_read_text` rechaza fuentes PDF o de imagen con un error estable; no devuelve contenido binario.
4. El contenido de la fuente se trata como dato no confiable y nunca como instrucciones. Las descripciones y las instrucciones del servidor lo advierten.
5. Errores estables para proyecto ausente, fuente ausente, fuente no textual y corrupción del almacén, sin rutas internas.
6. Pruebas de catálogo, argumentos inválidos, éxito, truncado, Unicode, tipo no textual, integridad y protocolo MCP en memoria.
7. Actualizar README, plan maestro, arquitectura, contrato, guía de colaboración e informe.

## Fuera de alcance

- Subir, borrar o reemplazar fuentes por MCP.
- Devolver PDF/imágenes en base64 o como recursos MCP.
- Extraer texto de PDF, OCR, visión, cotas, escala o geometría.
- Analizar fuentes, proponer `CadSpec`, crear trabajos o aprobaciones.
- Cambiar la API HTTP, la interfaz, el esquema SQLite o el contrato `CadSpec`.
- Añadir dependencias.

## Restricciones

- No hacer commits ni publicar.
- No duplicar reglas de validación en el adaptador MCP.
- No leer archivos directamente desde las herramientas: usar `ProjectService`.
- Mantener el estilo y los mensajes en español.
- No afirmar que una fuente es estructuralmente válida solo porque sus metadatos existan.
- No exponer rutas internas, hashes de otros proyectos ni contenido de un proyecto ajeno.

## Riesgos y decisiones

- El texto de una fuente puede contener instrucciones maliciosas. Se devuelve como dato, con advertencia explícita; el cliente y el agente deben tratarlo como no confiable.
- Se limita el texto devuelto por caracteres para no inundar el contexto del agente. El hash y el tamaño original permiten detectar truncado.
- La lectura completa del blob es necesaria para verificar el SHA-256 antes de devolver texto; el límite de 20 MiB acota el coste.
- No se expone contenido binario porque MCP no ofrece un límite de respuesta adecuado para PDF de 20 MiB y porque todavía no hay extractor.
- Una fuente de texto con BOM se devuelve sin BOM; el contenido lógico es el mismo que se validó al cargarla.

## Verificación

- `pytest` completo.
- Pruebas nuevas de catálogo, esquemas, anotaciones, lista vacía, metadatos, lectura completa, truncado, Unicode, fuente no textual, fuente/proyecto ausente e integridad.
- Prueba de protocolo MCP en memoria que invoque las herramientas y valide `structuredContent`.
- Confirmar que no se añadieron dependencias ni se modificó la API o la interfaz.
- Informe con comandos, resultados y limitaciones.

Resultado: [`007-informe.md`](007-informe.md).
