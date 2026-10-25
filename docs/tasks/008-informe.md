# Informe de tarea 008 — Aprobaciones de diseño ligadas a revisión y hash

## Resultado

La tarea 008 quedó implementada y verificada localmente. El sistema registra ahora una aprobación humana explícita de alcance `design`, ligada al proyecto, a la revisión vigente y a su SHA-256:

- La aprobación se guarda en SQLite v3 en una tabla append-only con triggers que impiden `UPDATE` y `DELETE`.
- Solo se puede aprobar la revisión actual y con el hash almacenado.
- El servicio revalida el `CadSpec` guardado y bloquea la aprobación si produce diagnósticos de error.
- La creación es idempotente por `(proyecto, revisión, alcance)`.
- El estado se calcula como `valid` o `stale` contra la revisión vigente; guardar otra revisión invalida la anterior sin borrarla ni mutarla.
- La API, la interfaz local y MCP reutilizan el mismo `ProjectService`; MCP solo permite consultar.

La aprobación es de alcance `design` y **no autoriza construir**, no verifica SolidWorks/AutoCAD y no implementa destino, expiración, consumo único ni revocación. Todo el trabajo sigue sin commit ni publicación, pendiente de auditoría independiente.

## Archivos

- `src/autosolid/projects/store.py`: `SCHEMA_VERSION = 3`, tabla `approvals`, triggers de inmutabilidad, migración v2→v3 y métodos `save_approval`, `list_approvals`, `get_approval`.
- `src/autosolid/projects/service.py`: `approve_revision`, `list_approvals`, `get_approval`, validación de campos, revalidación de la revisión y cálculo de estado.
- `src/autosolid/projects/exceptions.py`: errores de validación, hash, bloqueo y aprobación ausente.
- `src/autosolid/projects/__init__.py`: exportaciones nuevas.
- `src/autosolid/api/routes.py`: endpoints de creación, lista y obtención.
- `src/autosolid/api/errors.py`: traducción a códigos HTTP estables.
- `src/autosolid/api/schemas.py`: modelo de la solicitud de aprobación.
- `src/autosolid/mcp/tools.py`: `autosolid_approval_list` y `autosolid_approval_get`.
- `src/autosolid/mcp/models.py`: modelos estrictos de entrada/salida.
- `src/autosolid/mcp/errors.py`: traducción de errores de aprobación.
- `src/autosolid/mcp/server.py`: instrucciones del servidor actualizadas.
- `src/autosolid/mcp/__init__.py`: exportación de `TOOLS_BY_NAME` usada por las pruebas.
- `src/autosolid/api/static/index.html`: panel de aprobación e historial.
- `src/autosolid/api/static/app.js`: estado, validaciones de interfaz, confirmación y refresco.
- `src/autosolid/api/static/app.css`: estilos del panel y de los estados.
- `tests/test_approvals.py`: 32 pruebas de dominio, almacén, migración, inmutabilidad, concurrencia y aislamiento.
- `tests/test_api_approvals.py`: pruebas de API, errores y transición a obsoleto.
- `tests/test_mcp_approvals.py`: pruebas MCP de solo lectura y errores estables.
- `tests/test_ui.py`: comprobaciones de los elementos y estilos nuevos.
- `docs/tasks/008-aprobaciones-de-revision.md`: alcance y decisiones de la tarea.

No se añadieron dependencias ni se modificó el contrato geométrico de `CadSpec`.

## Decisiones de implementación

- **Registro separado:** la aprobación no es un campo de `CadSpec`. Cambiar de revisión no reescribe la especificación anterior ni elimina la aprobación.
- **Vinculación estricta:** la solicitud incluye `revision` y `sha256`; ambos deben coincidir con la revisión actual. Un desajuste devuelve `REVISION_CONFLICT` o `APPROVAL_HASH_MISMATCH`.
- **Revalidación:** antes de insertar, el servicio ejecuta `validate_spec` sobre la revisión almacenada. Cualquier diagnóstico de error, incluido `QUESTION_CRITICAL_OPEN`, produce `APPROVAL_BLOCKED`.
- **Idempotencia:** la tabla tiene unicidad por `(project_id, revision, scope)`. Repetir la solicitud devuelve el registro existente sin reescribir autor ni nota; la API responde 200 en lugar de 201.
- **Append-only:** no hay actualización ni borrado. El estado `valid`/`stale` se calcula en cada consulta comparando la revisión y el hash con los vigentes.
- **Doble comprobación:** el servicio valida antes de llamar al almacén y `save_approval` repite la comprobación de revisión y hash dentro de la transacción de escritura SQLite para reducir carreras entre guardar y aprobar.
- **Alcance `design`:** el único alcance admitido en esta tarea. El alcance de construcción queda reservado para una aprobación futura.
- **MCP de solo lectura:** no existe herramienta para crear, revocar o consumir aprobaciones. Un agente puede consultar el estado, pero la decisión sigue siendo humana.
- **Interfaz:** exige revisor, confirmación explícita y la revisión y hash cargados. El botón se deshabilita con cambios sin guardar, sin hash, con una revisión no actual o con una aprobación vigente existente.
- **Migración:** una base v2 se actualiza a v3 conservando proyectos, revisiones y fuentes; las pruebas comprueban la versión registrada y la nueva tabla.

## Pruebas automatizadas

Compilación:

```powershell
.venv\Scripts\python -m compileall -q src tests
```

Sin errores.

Pruebas focalizadas de dominio y almacén:

```powershell
.venv\Scripts\python -m pytest -q tests/test_approvals.py
```

Resultado: **32 passed**.

Pruebas de API y MCP:

```powershell
.venv\Scripts\python -m pytest -q tests/test_api_approvals.py tests/test_mcp_approvals.py
```

Resultado: **22 passed**.

Suite completa:

```powershell
.venv\Scripts\python -m pytest -q
```

Resultado final: **254 passed, 1 warning**. El aviso es el preexistente `StarletteDeprecationWarning` sobre `TestClient` y `httpx`; no se introdujo un fallo nuevo.

Comprobación del JavaScript:

```powershell
node --check src/autosolid/api/static/app.js
```

Sin errores.

Comprobación de espacios y conflictos del diff:

```powershell
git diff --check
```

Sin errores.

Las pruebas nuevas cubren, entre otros casos:

- creación de una aprobación válida y persistencia tras reabrir el almacén;
- idempotencia y concurrencia de dos solicitudes idénticas;
- rechazo de una revisión no actual, un hash incorrecto o un proyecto sin revisión;
- validación de revisor, nota, alcance, hash y campos extra;
- revalidación de la revisión almacenada y bloqueo por `QUESTION_CRITICAL_OPEN`;
- corrupción de la revisión antes de aprobar;
- inmutabilidad mediante triggers de SQLite;
- aislamiento de aprobaciones entre proyectos;
- migración v2→v3;
- errores HTTP y MCP sin rutas internas;
- transición de una aprobación a `stale` al guardar otra revisión;
- catálogo MCP de once herramientas, sin ninguna herramienta de escritura de aprobaciones;
- ausencia de mutaciones en las revisiones al consultar aprobaciones por MCP.

## Verificación en navegador

Se ejecutó el servidor local con un directorio temporal (`%TEMP%\autosolid-ui-008`) y se recorrió el flujo real en el navegador:

1. Crear el proyecto «Bancada 008».
2. Guardar la revisión 1 con la plantilla.
3. Aprobar como «Ana Revisora» con la nota «Revisado contra el plano.».
4. Comprobar el estado «Vigente», el historial y el botón deshabilitado.
5. Recargar la página y comprobar que la aprobación persistía.
6. Modificar el editor sin guardar y comprobar que el botón se deshabilitaba con el aviso «Sin guardar».
7. Recargar la revisión actual y comprobar que volvía a estar «Pendiente» y habilitado.
8. Guardar la revisión 2 y comprobar que la aprobación de la revisión 1 pasaba a «Obsoleto» y la revisión 2 quedaba «Pendiente».

El servidor de prueba se detuvo y la pestaña se cerró. La captura de pantalla no estuvo disponible porque la herramienta exige una ventana visible; la verificación funcional se hizo mediante instantáneas de accesibilidad y consultas al DOM, no solo por inspección visual.

## Limitaciones

- La aprobación es solo de diseño. No construye, no genera SLDPRT/DXF/STEP y no verifica SolidWorks/AutoCAD.
- No hay destino, expiración, consumo único ni revocación. Esas propiedades pertenecen a una futura aprobación de construcción.
- No existen trabajos asíncronos, cancelación, colas, reintentos ni progreso.
- No se ha conectado un proveedor externo real ni se ha probado la integración de proveedores con el dominio.
- La invocación de las herramientas MCP desde una sesión de agente real sigue pendiente; las pruebas usan el protocolo MCP en memoria y el subproceso `stdio`.
- La prueba de navegador fue manual. No hay una prueba E2E automatizada del navegador ni captura de pantalla.
- No se ha auditado ni aceptado la tarea; no se hicieron commits ni publicaciones.

## Reproducción

```powershell
$env:AUTOSOLID_DATA_DIR = Join-Path $env:TEMP 'autosolid-ui-008'
.venv\Scripts\python -m uvicorn autosolid.api.app:create_app --factory --host 127.0.0.1 --port 8765
```

Abrir `http://127.0.0.1:8765/` y usar el panel «Aprobación de diseño».

Para ejecutar las pruebas:

```powershell
.venv\Scripts\python -m pytest -q tests/test_approvals.py
.venv\Scripts\python -m pytest -q tests/test_api_approvals.py tests/test_mcp_approvals.py
.venv\Scripts\python -m pytest -q
```

## Siguiente paso

La iteración 1 sigue abierta por trabajos asíncronos, cancelación, aprobación de construcción, integración real de proveedores y la prueba de invocación MCP desde un agente. La siguiente tarea puede abordar una infraestructura mínima de trabajos o la aprobación de construcción con destino, expiración y consumo único. No conviene iniciar el parser PDF sin una dependencia justificada y un corpus de PDF/DXF de prueba.
