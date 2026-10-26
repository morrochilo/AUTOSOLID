# Tarea 013 — Endurecimiento de publicación y cola build

## Contexto

La tarea 012 tiene 321 pruebas verdes, pero la auditoría independiente encontró fallos de recuperación, concurrencia y persistencia. No ampliar funcionalidad. Leer `docs/tasks/012-informe.md` y los archivos afectados.

## Hallazgos obligatorios

1. **Recuperación/publicación:** archivo y base de datos no son atómicos. Si falla `_file_digest` o `finish_build_job` después de publicar, el trabajo puede quedar `running`/`failed` con SLDPRT válido sin metadatos y sin reintento posible.
2. **Borrado ajeno:** `except OSError: target.unlink()` puede borrar un archivo creado por otro proceso, incluso si el fallo fue al abrir el origen. Nunca borrar un destino que el proceso no creó.
3. **Parciales:** la copia fallback puede dejar archivo parcial en el destino final. Escribir staging temporal y publicar de forma exclusiva sin copiar directamente al destino.
4. **Cierre:** `SerialJobQueue.stop()` espera 5 s y la API cierra el store aunque el worker siga. El cierre ordenado debe esperar al trabajo activo antes de cerrar el store; no marcar completado mientras el hilo sigue vivo.
5. **Inmutabilidad:** `build_jobs` permite `INSERT OR REPLACE` con triggers recursivos desactivados. Añadir trigger BEFORE INSERT anti-duplicado como en las demás tablas, también en migraciones existentes.
6. **Windows:** alias de componentes terminados en punto/espacio deben normalizarse para destination_hash. Rechazar nombres reservados `CON, PRN, AUX, NUL, COM1–COM9, LPT1–LPT9` sin perder `.sldprt`.
7. **TOCTOU:** recheck de contención y symlinks/junctions justo antes de publicar. Documentar límite residual si no hay handles seguros.
8. **Timeout:** detener el árbol del proceso del agente, no solo el padre cuando la plataforma lo permita, sin matar SolidWorks ni procesos ajenos. Documentar que COM puede continuar y staging evita publicación.
9. **JSON:** `_finite_number` debe convertir `OverflowError` en `BuildExecutionError(RUNNER_OUTPUT_INVALID)`.
10. **Reconciliación:** retry/startup debe poder completar un artefacto ya publicado cuyo hash/destino/revisión coinciden, sin reconstruir ni duplicar. No reintentar si el archivo difiere o es parcial.

## Requisitos de implementación

- Calcular hash antes de publicar cuando sea posible; no publicar hasta tener validación y metadatos listos.
- Mantener destino exclusivo y no sobrescribir. Limpiar solo temporales propios, nunca archivos ajenos.
- Diseñar recuperación explícita de `running`/publicación incompleta: si existe artefacto final con hash esperado, registrar `completed`; si no, fallo recuperable. No ocultar errores de persistencia.
- Mantener cola serial, aprobación de un solo uso e idempotencia.
- No añadir UI, MCP, PDF, proveedores ni nuevas operaciones CAD.
- No hacer commits ni cambiar SolidWorksBuilder salvo corrección justificada.

## Regresiones obligatorias

- Fallo al calcular hash/publicar/finalizar trabajo y reconciliación posterior.
- Simular dos procesos y demostrar que la limpieza no borra archivos ajenos.
- Cierre con runner lento: `stop()` no retorna antes de terminar y store no se cierra prematuramente.
- `INSERT OR REPLACE` en `build_jobs` bloqueado.
- Alias Windows, nombres reservados y recheck de symlink.
- Entero JSON enorme produce error estable.
- Suite completa y `dotnet build`.

Documentar en `docs/tasks/013-informe.md` cambios, pruebas y limitaciones. No declarar auditoría independiente.
