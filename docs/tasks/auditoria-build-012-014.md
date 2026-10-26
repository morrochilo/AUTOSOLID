# Auditoría independiente de la cola build 012–014

## Veredicto

El conjunto queda aceptado para PR: aprobación de construcción de un solo uso, cola serial, runner C#, publicación exclusiva y recuperación. Las revisiones encontraron defectos adicionales que fueron corregidos antes de la validación final.

## Evidencia

- **373 pruebas superadas** en el entorno independiente, una advertencia conocida de Starlette/TestClient.
- `compileall` y `git diff --check` correctos.
- `dotnet build` del agente sin errores ni advertencias.
- Trabajo real mediante `ProjectService` y aprobación `build`:
  - proyecto `prj_7bf79349384f4388aea7c8a7ee0aa802`;
  - trabajo `job_cb452624e3904bedbc1d26e7d4ba60b7`;
  - estado `completed`;
  - SLDPRT de 55 352 bytes, abierto y reconstruido;
  - volumen `8.000000000000001e-06 m³`, caja 40×20×10 mm, errores 0, avisos 4 visibles;
  - segunda solicitud con la misma aprobación rechazada.
- Revisión focalizada de consumo, destinos, runner y publicación completada.

## Hallazgos corregidos

- `build_jobs` sin trigger antiinserción duplicada: añadido y probado con `INSERT OR REPLACE`.
- Cierre de API con trabajo activo: `shutdown()` espera antes de cerrar el store.
- Hash/finalización después de publicar: metadatos preparados antes y reconciliación por hash.
- Reintento de trabajos `running` ya publicados sin reconstrucción.
- Posible borrado de archivos ajenos y archivos parciales: se eliminó completamente el fallback de copia/`xb`.
- Publicación solo mediante enlace duro exclusivo; si no está disponible, falla sin crear el destino.
- Alias/reservados Windows y recheck de destino.
- Timeout de árbol del agente y `OverflowError` convertido en error estable.

## Límites conocidos

- La cola es serial por proceso, no coordinación entre procesos vivos.
- La contención por ruta tiene una ventana TOCTOU residual documentada; no hay handles de directorio portables.
- Archivo y SQLite no comparten transacción distribuida; se reconcilia por hash.
- COM puede seguir activo tras matar al agente; el staging evita publicación incompleta.
- Sin UI/MCP de construcción, cancelación ni recuperación entre procesos de trabajos `running` heredados sin metadatos.
- Solo se probó una extrusión conocida con SolidWorks 2024 y la plantilla configurada; no se afirma cobertura de otras versiones, PDF o fabricabilidad.

## Publicación

Se permite crear el PR solo después de repetir la auditoría de privacidad y comprobar que no hay binarios CAD, DLL ni datos locales en el índice.
