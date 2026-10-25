# Tarea 005 — Interfaz local mínima de revisión

## Contexto

Las tareas 001–004 están implementadas. Existen `CadSpec`, el servicio de
proyectos/revisiones con API FastAPI y una fachada MCP. La iteración 1 del plan
maestro pide una interfaz con estado, preguntas y visor JSON que use el mismo
servicio que la API y que OpenCode. Todavía no existen ingesta PDF, trabajos ni
construcción CAD.

Leer `AGENTS.md`, `docs/01-plan-maestro.md`, `docs/02-arquitectura.md`,
`docs/03-contrato-cad-y-apis.md`, `docs/05-guia-de-colaboracion.md` y los
informes 003/004 antes de modificar código.

## Objetivo

Añadir una interfaz web local mínima, servida por la aplicación FastAPI
existente, para crear/listar proyectos y revisar, validar y guardar `CadSpec`
contra la API actual, mostrando estado, diagnósticos, preguntas abiertas y el
JSON resultante.

La interfaz no duplica reglas de negocio: usa `/api/v1` y el mismo
`ProjectService` que MCP. No requiere Node, bundler ni dependencias nuevas.

## Alcance obligatorio

1. Servir una página en `/` y recursos locales `/ui/app.css` y `/ui/app.js`
   desde `autosolid.api`, sin recursos externos ni CDN.
2. Cabeceras de seguridad razonables: CSP restrictiva, `nosniff`,
   `frame-ancestors 'none'`, `no-referrer` y `Cache-Control: no-store` para el
   documento.
3. Interfaz con:
   - estado del servicio local;
   - listado y creación de proyectos;
   - carga del proyecto y de su revisión actual (o plantilla vacía si no hay);
   - editor JSON de `CadSpec`;
   - validación sin persistir;
   - guardado con `expected_revision` y manejo visible de conflictos;
   - panel de diagnósticos por severidad, código, ruta y mensaje;
   - panel de preguntas abiertas del `CadSpec`;
   - visor JSON y hash/revisión de la última carga o guardado;
   - mensajes de estado accesibles y estados de carga.
4. No usar `innerHTML` con datos del servidor; insertar texto con
   `textContent`. No guardar secretos ni usar almacenamiento del navegador para
   credenciales.
5. Añadir pruebas con `TestClient` para rutas, tipos, cabeceras, ausencia de
   recursos externos, CSP y convivencia con `/api/v1`.
6. Verificación manual con navegador local: crear proyecto, cargar plantilla,
   validar un `CadSpec` de ejemplo y guardar una revisión; documentar el
   resultado real.

## Fuera de alcance

- Ingesta/carga de PDF, imágenes o texto y almacenamiento de artefactos.
- Llamadas a proveedores de modelos, prompts, interpretación o propuesta de
  diseños.
- Trabajos asíncronos, cancelación, aprobaciones y construcción SolidWorks.
- Autenticación remota, multiusuario, CORS abierto o exposición fuera de
  loopback.
- Frameworks frontend, bundlers, Node, CDN, fuentes externas o dependencias
  nuevas.
- Cambios al contrato `CadSpec`, a la API existente o a MCP.

## Restricciones

- No hacer commits ni publicar.
- No modificar pruebas existentes para ocultar fallos.
- No afirmar que la ingesta PDF o la construcción CAD existen.
- Mantener el estilo del proyecto: español en documentación/interfaz, Python
  3.11+, Pydantic/FastAPI existentes.
- La interfaz debe ser útil sin conexión a Internet.

## Verificación

- `pytest` completo.
- Pruebas nuevas de la interfaz y de sus recursos.
- Arranque real en `127.0.0.1` con un directorio de datos temporal, navegación,
  creación de proyecto, validación y guardado; captura/observación del estado y
  consola del navegador.
- Informe con comandos, resultados y limitaciones.

Resultado: [`005-informe.md`](005-informe.md).
