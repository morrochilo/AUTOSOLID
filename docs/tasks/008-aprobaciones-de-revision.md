# Tarea 008 — Aprobaciones de diseño ligadas a revisión y hash

## Contexto

Las tareas 001–007 están implementadas: núcleo `CadSpec`, proyectos y revisiones SQLite, API FastAPI, interfaz local, almacén de fuentes y lectura de fuentes por MCP. La iteración 1 sigue abierta porque no existen trabajos asíncronos, cancelación, aprobaciones, proveedor real conectado ni construcción CAD.

El ADR-003 exige que una aprobación quede ligada a proyecto, revisión, hash y destino, sea explícita, de un solo uso y con expiración, y que cualquier cambio de revisión invalide la anterior. La construcción y el consumo de un token todavía no existen. Esta tarea implementa la parte que ya puede verificarse sin simular CAD: **una aprobación de diseño, explícita y ligada a la revisión y su SHA-256**, con invalidación automática al cambiar de revisión.

La aprobación de esta tarea **no autoriza construir**. El alcance `design` es distinto de una futura aprobación de construcción con destino, expiración y consumo único. No se debe presentar como permiso de construcción ni como verificación de SolidWorks.

Leer `AGENTS.md`, `docs/01-plan-maestro.md`, `docs/02-arquitectura.md`, `docs/03-contrato-cad-y-apis.md`, `docs/05-guia-de-colaboracion.md`, el ADR-003 y los informes 005–007 antes de modificar código.

## Objetivo

Registrar una aprobación humana explícita de la revisión vigente de un proyecto, vinculada a su SHA-256, y consultar su estado. La aprobación se invalida automáticamente cuando el proyecto pasa a otra revisión, sin borrar ni mutar el registro histórico.

## Alcance obligatorio

1. Esquema SQLite v3 con tabla `approvals` inmutable y migración v2→v3:
   - campos: `id`, `project_id`, `revision`, `revision_sha256`, `scope`, `approved_by`, `note`, `created_at`;
   - única por `(project_id, revision, scope)`;
   - claves foráneas a proyecto y revisión;
   - triggers que impiden `UPDATE` y `DELETE`.
2. Casos de uso en `ProjectService`:
   - crear una aprobación de alcance `design` para la revisión actual;
   - exigir que `revision` sea la actual y que `sha256` coincida con el hash almacenado;
   - revalidar la revisión almacenada y bloquear la aprobación si produce diagnósticos de error;
   - listar aprobaciones con estado calculado `valid` o `stale`;
   - obtener una aprobación concreta;
   - deduplicar por `(proyecto, revisión, alcance)` devolviendo la existente.
3. API HTTP bajo `/api/v1`:
   - `POST /projects/{project_id}/approvals` (201 nueva, 200 existente);
   - `GET /projects/{project_id}/approvals`;
   - `GET /projects/{project_id}/approvals/{approval_id}`.
4. Errores estables y sin rutas internas: `INVALID_APPROVAL`, `APPROVAL_HASH_MISMATCH`, `APPROVAL_BLOCKED`, `APPROVAL_NOT_FOUND`, además de los existentes `REVISION_CONFLICT`, `CADSPEC_NOT_FOUND` y `PROJECT_NOT_FOUND`.
5. MCP de solo lectura:
   - `autosolid_approval_list`;
   - `autosolid_approval_get`.
   - No se expone ninguna herramienta MCP para crear, revocar o consumir aprobaciones.
6. Interfaz local:
   - panel de aprobación de diseño con nombre del revisor y nota opcional;
   - estado vigente/obsoleto e historial;
   - acción explícita, con confirmación, solo para la revisión y el hash cargados;
   - botón deshabilitado si hay cambios sin guardar, la revisión cargada no es la actual o no existe hash;
   - refresco del estado al guardar otra revisión.
7. Pruebas positivas y negativas: migración v2→v3, inmutabilidad, validación de entradas, conflicto de revisión, hash incorrecto, bloqueo por diagnósticos, deduplicación, concurrencia, aislamiento por proyecto, invalidación al cambiar de revisión, API y MCP.
8. Actualizar README, plan maestro, arquitectura, contrato, guía de colaboración, ADR-003 (evidencia) e informe de la tarea.

## Fuera de alcance

- Construir en SolidWorks/AutoCAD, generar SLDPRT/DXF/STEP o simular una construcción.
- Consumir la aprobación, hacerla de un solo uso, asignarle destino o expiración. Eso pertenece a una futura aprobación de construcción.
- Trabajos asíncronos, cancelación, colas, reintentos y progreso.
- Revocar o borrar aprobaciones. El historial es inmutable.
- Aprobar desde MCP. La aprobación exige una acción humana explícita en la interfaz o en la API.
- Cambiar el esquema `CadSpec`, el formato de las revisiones o el contrato geométrico.
- Interpretar fuentes, extraer PDF, cotas, escala o evidencia.
- Añadir dependencias.

## Restricciones

- No hacer commits ni publicar.
- No duplicar reglas de validación en la API, la interfaz o MCP: el servicio reutiliza `validate_spec`.
- No confundir una aprobación de diseño con una verificación CAD ni con permiso de construcción.
- No mutar ni borrar registros de aprobación para invalidarlos: el estado se calcula contra la revisión vigente.
- Mantener el estilo, los mensajes en español y el uso de valores decimales del contrato.
- No exponer rutas internas, hashes de otros proyectos ni contenido ajeno.
- La UI no debe usar `innerHTML`, `eval`, recursos externos ni dependencias nuevas.

## Riesgos y decisiones

- **Append-only:** no hay borrado ni revocación. Una aprobación equivocada permanece en el historial y solo es válida mientras no cambie la revisión. La interfaz pide confirmación y muestra el número de revisión y el hash antes de aprobar.
- **Sin expiración:** una aprobación de diseño no es un token de construcción. La expiración y el consumo único se implementarán cuando exista una operación real de construcción.
- **Alcance `design`:** evita que una aprobación de revisión se interprete como autorización de construcción. El alcance de construcción queda reservado.
- **Doble comprobación de revisión/hash:** el servicio valida antes de llamar al almacén y el almacén repite la comprobación dentro de `BEGIN IMMEDIATE`, para que una carrera entre guardar y aprobar no deje una aprobación incoherente.
- **Revalidación al aprobar:** una revisión guardada con reglas anteriores podría no cumplir las reglas actuales. Aprobar vuelve a ejecutar `validate_spec` y bloquea si hay errores.
- **Deduplicación:** dos solicitudes para la misma revisión y alcance devuelven la misma aprobación; no se crean duplicados ni se reescribe autor/nota.
- **MCP de solo lectura:** un agente puede consultar si la revisión está aprobada, pero no puede aprobarse a sí mismo ni consumir la aprobación.

## Verificación

- `pytest` completo.
- Pruebas focalizadas de aprobaciones, API, MCP y migraciones.
- `node --check` sobre el JavaScript de la interfaz.
- `compileall` sobre `src` y `tests`.
- Prueba real en navegador: crear proyecto, guardar revisión, aprobar, recargar, guardar otra revisión y comprobar que la aprobación anterior queda obsoleta.
- Comprobar que no se añadieron dependencias ni se modificó el contrato geométrico.
- Informe con comandos, resultados y limitaciones.

Resultado: [`008-informe.md`](008-informe.md).
