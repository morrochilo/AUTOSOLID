# Informe de la tarea 009 — Persistencia y concurrencia

## Resultado

Correcciones implementadas y verificadas para aprobaciones, artefactos y subidas. La tarea fue completada directamente porque OpenCode/DeepSeek devolvió `Free usage limit reached`; no se cambió de modelo ni se compró cuota.

## Cambios

- `ProjectStore.approval_snapshot` lee proyecto, revisión actual e historial en una transacción SQLite común. `ProjectService` calcula estados con esa instantánea y conserva la verificación SHA-256 del `CadSpec`.
- `PRAGMA recursive_triggers=ON` en conexiones del store.
- Migración SQLite v4 con triggers `BEFORE INSERT` anti-duplicados para `revisions`, `approvals`, `sources` y `artifacts`. Esto también bloquea reescrituras mediante `INSERT OR REPLACE` desde conexiones con triggers recursivos desactivados.
- MIME calculado por fuente/nombre, sin rechazar un blob idéntico cargado con otra extensión en otro proyecto. Se mantiene un único blob por hash y la comprobación de tamaño.
- `upload_source` ejecuta `service.add_source` mediante `anyio.to_thread.run_sync` con una llamada compatible con AnyIO instalado.
- Migraciones existentes actualizadas a v4 sin cambiar el contrato `CadSpec` ni el alcance `design`.

## Evidencia

- Las cuatro regresiones iniciales de `tests/test_audit_009_regressions.py` fallaban antes y ahora pasan.
- Se añadió cobertura para `INSERT OR REPLACE` en todas las tablas append-only.
- Se añadió `tests/test_api_source_event_loop.py`: `/health` responde mientras una subida está bloqueada.
- Suite completa: **260 pruebas superadas**, una advertencia conocida de Starlette/TestClient.
- `compileall` y `node --check` correctos.

## Incidencias de delegación

El primer intento DeepSeek quedó sin actividad y el reintento mostró el límite gratuito en el log. Los procesos huérfanos fueron detenidos. La implementación directa se usó para no bloquear el proyecto; la reanudación de delegación para 010 quedó pendiente de disponibilidad.

## Pendientes

- Auditoría final conjunta con las correcciones 010 de proveedores.
- No se creó commit ni PR para este cambio aislado.
