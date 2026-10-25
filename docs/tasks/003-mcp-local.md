# Tarea 003 — Servidor MCP local para proyectos y diseños

## Contexto

Las tareas 001 y 002 están aceptadas. Existe `ProjectService` con persistencia SQLite, revisiones inmutables y API FastAPI. Leer `AGENTS.md`, ADR-001/002/003, `docs/03-contrato-cad-y-apis.md`, `docs/tasks/002-proyectos-y-api.md` y `docs/tasks/002-revision.md`.

## Objetivo

Crear una fachada MCP local `stdio` sobre el mismo servicio de aplicación, para que OpenCode y otros clientes puedan gestionar proyectos y revisiones sin duplicar lógica de dominio.

## Alcance obligatorio

1. Añadir el SDK oficial Python `mcp` en runtime, con rango compatible. Comprobar su API real instalada antes de implementar; no inventar métodos.
2. Implementar `autosolid.mcp` con una factoría del servidor y un comando `autosolid-mcp` o `python -m autosolid.mcp` usando `stdio` y `AUTOSOLID_DATA_DIR`.
3. Reutilizar `ProjectStore`/`ProjectService`; no conectar por HTTP ni reimplementar validación, SQL o revisiones.
4. Exponer estas herramientas con esquemas de entrada estrictos y salida estructurada:
   - `autosolid_project_create`
   - `autosolid_project_list`
   - `autosolid_project_get`
   - `autosolid_design_get`
   - `autosolid_design_validate`
   - `autosolid_design_update`
5. `design_validate` no persiste. `design_update` exige `expected_revision` y usa exactamente las reglas del servicio. Los errores esperados devuelven código/mensaje/detalles sin stack traces ni rutas internas.
6. Cerrar correctamente store/recursos al terminar. No escribir logs en stdout porque corrompen MCP; stderr solo si es necesario y sin secretos.
7. Añadir pruebas unitarias de cada herramienta y al menos una prueba de protocolo real cliente↔servidor soportada por el SDK (sesión en memoria o subprocess stdio):
   - inicializar y listar herramientas;
   - crear proyecto, validar y guardar un `CadSpec`, volver a leerlo;
   - conflicto de revisión y especificación inválida;
   - salida estructurada y decimales preservados.
8. Incluir un ejemplo de configuración MCP para OpenCode con placeholders, sin credenciales ni rutas personales. No cambiar `opencode.json` en esta tarea.

## Fuera de alcance

- MCP remoto, OAuth, HTTP/SSE o exposición a red.
- Ingesta PDF/imágenes, proveedores, UI y trabajos asíncronos.
- Aprobaciones o herramienta `solidworks_build`.
- AutoCAD/SolidWorks.
- Cambios del contrato CAD o del servicio salvo corrección justificada por integración.

## Restricciones

- No hacer commits ni publicar.
- No instalar paquetes globalmente ni modificar configuración global.
- No leer secretos ni incluir tokens en configuración/ejemplos.
- No usar `eval`, `exec`, acceso arbitrario a archivos o herramienta genérica para ejecutar código.
- No eliminar/relajar pruebas existentes.

## Verificación

Ejecutar `pytest` completo y una prueba de protocolo real. Informar versión del SDK, herramientas disponibles, resultados y limitaciones. La conexión final con OpenCode será auditada por separado.

## Registro de implementación

El resultado local, los comandos y los límites observados se documentan en [003-informe.md](003-informe.md). La tarea sigue pendiente de auditoría independiente.
