# Revisión de la tarea 002

## Alcance revisado

- Persistencia SQLite con esquema versionado, WAL y conexiones por operación.
- Proyectos y revisiones `CadSpec` inmutables con SHA-256.
- Bloqueo optimista con doble comprobación de revisión.
- API FastAPI `/api/v1`, errores estables y escucha loopback por defecto.
- Sin MCP, modelos, PDF ni integración CAD.

## Verificación independiente

- `pytest`: **86 pruebas superadas** en Python 3.12 con el entorno de auditoría.
- Dos escritores con la misma revisión: uno gana y el otro recibe `REVISION_CONFLICT`.
- Persistencia comprobada al recrear store/app.
- Decimales, hash e inmutabilidad comprobados.
- Servidor real iniciado en `127.0.0.1:8765` con datos temporales aislados.
- Llamadas HTTP reales superadas: `health`, crear proyecto, validar, guardar, leer y conflicto de revisión.
- Servidor temporal detenido al finalizar.

## Observaciones

La suite muestra una advertencia de depreciación de Starlette relacionada con el backend HTTPX de TestClient. No afecta al resultado actual; se revisará al actualizar el toolchain, sin añadir otro cliente HTTP a esta iteración.

La creación de la aplicación global puede crear el directorio de datos al importar `autosolid.api`. Está excluido de Git y es comportamiento a simplificar cuando se incorporen otros adaptadores, no una fuga de datos.

## Resultado

**Iteración 002 aceptada dentro de su alcance.** No constituye verificación de MCP, PDF, SolidWorks ni AutoCAD.
