# Tarea 009 — Endurecimiento de aprobaciones, artefactos y subidas

## Contexto

Leer `docs/tasks/auditoria-003-008.md`. Las tareas 003–008 están implementadas localmente, pero la publicación está bloqueada por defectos confirmados. No añadir funcionalidad.

## Regresiones ya creadas por auditoría

`tests/test_audit_009_regressions.py` contiene cuatro casos que fallan antes de la corrección. No modificar ni relajar esas pruebas.

## Alcance obligatorio

1. **Instantánea de aprobaciones:** `list_approvals` y `get_approval` deben calcular estados con proyecto, hash e historial leídos en una única instantánea SQLite coherente. Evitar mezclar estados antes/después de otra revisión. Mantener aislamiento y rendimiento razonable. Añadir prueba equivalente para `get_approval` y aprobación recién creada.
2. **Inmutabilidad:** activar `PRAGMA recursive_triggers=ON` en toda conexión y verificar que `INSERT OR REPLACE` no puede reescribir ni borrar implícitamente filas en `revisions`, `approvals`, `sources` y `artifacts`. Añadir regresiones para todas esas tablas y para migraciones v1→v2→v3.
3. **MIME por fuente:** corregir la deduplicación content-addressed para que el MIME de una fuente no dependa de otro proyecto ni del primer nombre usado. Mantener un único blob por hash, tamaño íntegro y metadatos coherentes. Elegir separación de metadatos o clasificación por contenido sin romper la base existente ni la API. Los mismos bytes como `.pdf` y `.txt` deben funcionar en ambos órdenes.
4. **Event loop:** la subida en `src/autosolid/api/routes.py` debe ejecutar el trabajo síncrono `service.add_source` fuera del bucle con `anyio.to_thread.run_sync`. Añadir una prueba funcional en la que una subida bloqueada no impida responder `/health`.
5. Mantener los errores estables y no filtrar rutas. No cambiar el contrato `CadSpec` ni el alcance `design` de aprobaciones.
6. Documentar cambios y resultados en `docs/tasks/009-informe.md`, sin declarar auditoría independiente ni publicación.

## Fuera de alcance

- Proveedores y sus hallazgos (tarea 010).
- PDF/OCR/DXF, modelos reales, trabajos, construcción CAD y nuevas herramientas MCP.
- Commits, pushes o cambios en GitHub.
- Reescritura completa del almacén o nuevas dependencias.

## Verificación

- Las cuatro regresiones de auditoría deben pasar.
- Ejecutar `pytest` completo, `compileall` y `node --check` si se toca JS.
- Comprobar explícitamente migraciones, concurrencia e inmutabilidad.
- No eliminar pruebas existentes ni cambiar su intención.
