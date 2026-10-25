# Tarea 002 — Proyectos, revisiones y API local

## Contexto

La tarea 001 ya fue auditada y aceptada: `CadSpec` tiene modelos Pydantic, validación y 56 pruebas. Leer `AGENTS.md`, ADR-001/002/003, `docs/03-contrato-cad-y-apis.md` y `docs/tasks/001-revision.md`. No cambiar el contrato CAD existente salvo que sea indispensable para compatibilidad y esté justificado en el resumen.

## Objetivo

Implementar el servicio local mínimo de proyectos con persistencia SQLite, revisiones inmutables de `CadSpec`, validación mediante la función existente y una API FastAPI bajo `/api/v1`.

## Alcance obligatorio

1. Actualizar `pyproject.toml` con FastAPI y Uvicorn en runtime y HTTPX en desarrollo, usando rangos compatibles; no añadir ORM ni otras dependencias.
2. Implementar una capa de dominio/aplicación separada de FastAPI, por ejemplo `autosolid.projects` y `autosolid.api`.
3. Persistencia con `sqlite3` de la biblioteca estándar:
   - directorio de datos configurable con `AUTOSOLID_DATA_DIR`, por defecto `.autosolid/` sin aceptar rutas desde requests;
   - esquema versionado/migración inicial;
   - proyectos con ID generado por servidor, nombre y revisión actual;
   - historial de revisiones `CadSpec` inmutables con JSON y hash SHA-256;
   - transacciones y bloqueo optimista para no perder actualizaciones concurrentes;
   - conexiones seguras para TestClient/hilos y cierre correcto.
4. Operaciones de aplicación y endpoints:
   - `GET /api/v1/health` sin información del equipo;
   - `POST /api/v1/projects` con nombre validado, respuesta 201;
   - `GET /api/v1/projects` y `GET /api/v1/projects/{project_id}`;
   - `GET /api/v1/projects/{project_id}/cadspec`, con 404 si proyecto o especificación no existe;
   - `POST /api/v1/projects/{project_id}/cadspec/validate`, sin persistir ni cambiar revisión, devolviendo diagnósticos del validador;
   - `PUT /api/v1/projects/{project_id}/cadspec` con `expected_revision`, guardando solo si no hay diagnósticos de error y creando revisión `expected_revision + 1`;
   - respuesta 409 para conflicto de revisión, 422 para especificación inválida y 404 para proyecto ausente, con formato de error estable y sin stack traces.
5. `CadSpec.project_id` debe coincidir con el proyecto de la ruta. La revisión almacenada y el campo `revision` deben quedar coherentes sin mutar una revisión anterior.
6. Añadir `python -m autosolid.api` o script equivalente que escuche por defecto solo en `127.0.0.1`; host configurable de forma explícita.
7. Pruebas unitarias y de API con `tmp_path`:
   - crear/listar/obtener proyectos y persistir al recrear el store/app;
   - obtener/validar/guardar `CadSpec` válido;
   - no persistir especificaciones inválidas ni preguntas críticas abiertas;
   - conflicto `expected_revision`, proyecto inexistente y `project_id` incoherente;
   - inmutabilidad del historial y decimales preservados;
   - esquema JSON/diagnósticos y errores sin filtrar rutas internas;
   - prueba de dos actualizaciones con la misma revisión: solo una puede ganar.

## Fuera de alcance

- MCP, interfaz web, trabajos asíncronos, aprobaciones y construcción.
- PDF/OCR/DXF/imágenes y proveedores de modelos.
- SolidWorks/AutoCAD.
- Autenticación remota, CORS abierto, despliegue público o servicio fuera de loopback por defecto.
- Nuevas operaciones geométricas o cambios del plan maestro.

## Restricciones

- No hacer commits ni publicar.
- No modificar configuración global ni archivos fuera del workspace.
- No instalar paquetes globalmente.
- No guardar credenciales ni información del inventario local.
- No usar `eval`, `exec`, SQL construido con valores interpolados ni suprimir excepciones silenciosamente.
- No modificar pruebas existentes para ocultar fallos.

## Verificación

Ejecutar `pytest` completo. Probar también el arranque/importación de la app y una llamada real con TestClient. Informar archivos, API creada, pruebas y limitaciones; no afirmar integración MCP/CAD.
