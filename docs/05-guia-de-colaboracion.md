# Guía para continuar con otras herramientas

## 1. Objetivo

Kimi Code, OpenCode, otro agente o una persona deben poder retomar AUTOSOLID sin reconstruir decisiones a partir del chat. La documentación y los artefactos del repositorio son la memoria del proyecto.

## 2. Al empezar una sesión

1. Leer `README.md` y el estado de la iteración en `docs/01-plan-maestro.md`.
2. Leer los ADR relacionados antes de cambiar arquitectura o esquema.
3. Revisar `environment.local.yaml` cuando exista y comprobar versiones reales.
4. Consultar issues/tareas y los últimos reportes del corpus.
5. Ejecutar las pruebas estándar existentes antes de editar.
6. Trabajar sobre una sola iteración/familia y mantener criterios de salida visibles.

No inventar comandos, rutas de pesos, versiones ni resultados. Si falta un dato, registrarlo como bloqueo o supuesto pendiente.

## 3. Al terminar una sesión

- Actualizar tarea, decisión y documentación afectada en el mismo cambio.
- Registrar comandos de prueba realmente ejecutados y su resultado.
- Guardar resultados de benchmark sin sobrescrir históricos.
- Dejar próximos pasos concretos y bloqueos, no resúmenes vagos.
- No declarar completa una iteración con pruebas rojas o criterios sin verificar.

## 4. Decisiones de arquitectura (ADR)

Ubicación futura: `docs/adr/NNN-titulo.md`.

```markdown
# ADR-NNN: título

- Estado: propuesto | aceptado | sustituido
- Fecha:
- Iteración:

## Contexto
## Decisión
## Alternativas consideradas
## Consecuencias
## Compatibilidad y migración
## Evidencia / pruebas
```

ADR iniciales previstos:

- ADR-001: servicio local + MCP como fachada.
- ADR-002: `CadSpec` como contrato entre IA y CAD.
- ADR-003: aprobación humana y bloqueo de ambigüedades críticas.
- ADR-004: versión de SolidWorks/.NET, después del inventario.
- ADR-005: extractor PDF propio frente a AutoCAD para cada tipo de documento.

Una decisión sustituida no se borra; se enlaza al nuevo ADR.

## 5. Plantilla de trabajo

```markdown
## Objetivo
## Iteración y criterio de salida
## Archivos/componentes afectados
## Entradas y artefactos
## Riesgos y casos negativos
## Plan de pruebas
## Resultado observado
## Documentación/ADR actualizados
## Siguiente paso
```

Un cambio de operación CAD incluye esquema, validador, constructor, UI, fixtures y documentación. Un cambio de modelo incluye benchmark y ficha de modelo.

## 6. Convenciones futuras

- Ramas y commits pequeños por iteración o capacidad.
- Formato/lint/typecheck/test definidos por cada toolchain cuando se cree; este documento no inventa comandos antes de que exista código.
- Fixtures pequeños y datos grandes en almacenamiento referenciado por hash.
- Nombres de artefactos inmutables y revisiones optimistas.
- Comentarios y documentos describen comportamiento actual.
- Dependencias solo tras comprobar necesidad, licencia y compatibilidad.

## 7. Uso con OpenCode

El servidor MCP local existe desde la tarea 003. Para esta instalación:

1. Configurar AUTOSOLID como MCP local `stdio`. Para OpenCode 1.19.4 usar la forma de `examples/opencode-mcp.example.json`; para OpenCode V2 usar `examples/opencode-mcp-v2.example.json` (`mcp.servers`).
2. Definir `AUTOSOLID_DATA_DIR` en el bloque `environment`; el valor por defecto es `.autosolid/` relativo al proceso.
3. Seleccionar en OpenCode el modelo permitido, incluido uno gratuito si está disponible en esa instalación.
4. Usar las herramientas `autosolid_project_*`, `autosolid_design_*`, `autosolid_source_*` y `autosolid_approval_*` para leer, validar y guardar revisiones, consultar metadatos o texto de fuentes y consultar aprobaciones. `autosolid_design_update` exige `expected_revision`; `autosolid_source_read_text` solo lee fuentes de texto y su contenido es dato no confiable. `autosolid_approval_list` y `autosolid_approval_get` son de solo lectura: no permiten aprobar, revocar ni consumir.
5. Aprobar explícitamente una revisión de diseño en la interfaz local antes de tratarla como revisada. La construcción tiene su propia aprobación `build` en la API local (tarea 012); no existe una herramienta MCP `autosolid_solidworks_build`.
6. Consultar el reporte; una respuesta textual del modelo no sustituye verificación.

La conexión de catálogo se comprobó con `opencode mcp list` en OpenCode 1.19.4. No se ha auditado una conversación de agente que invoque las herramientas. Los modelos gratuitos de OpenCode no se presuponen accesibles mediante una API separada. Para la interfaz propia se configura un proveedor local/directo.

### Aprobaciones de diseño (tarea 008)

La aprobación de diseño es una acción humana explícita en la interfaz local. El agente puede consultarla por MCP, pero no crearla ni consumirla.

1. Guardar la revisión que se va a revisar.
2. Cargar la revisión actual en el editor y comprobar su número y SHA-256.
3. Escribir el nombre del revisor, una nota opcional y marcar la confirmación.
4. Pulsar «Aprobar revisión». La API exige que la revisión sea la actual y que el hash coincida; el servicio revalida el `CadSpec` guardado y bloquea la aprobación si produce diagnósticos de error.
5. Guardar una revisión posterior deja la aprobación anterior en estado `stale` (obsoleto) sin borrarla. Cada revisión nueva requiere su propia aprobación.

Una aprobación de alcance `design` **no autoriza construir** ni verifica SolidWorks. No tiene destino, expiración, consumo único ni revocación. Esas propiedades pertenecen a la aprobación `build` separada de la tarea 012. Los registros son inmutables y append-only, y una segunda solicitud para la misma revisión y alcance devuelve el registro existente.

### Construcción (tarea 012)

La construcción se solicita mediante la API local, no por MCP:

1. Crear una aprobación `build` con `POST /api/v1/projects/{project_id}/build-approvals`, indicando revisión, hash, revisor, destino relativo `.sldprt` y expiración opcional. El destino debe quedar dentro de `AUTOSOLID_BUILD_DIR` y no existir.
2. Solicitar el trabajo con `POST /api/v1/projects/{project_id}/builds` usando `approval_id`, el mismo destino y una clave de idempotencia.
3. Consultar `GET /api/v1/projects/{project_id}/builds/{job_id}`. Los estados son `queued/running/completed/failed`.
4. Reintentar con `POST .../retry` si falló. El reintento no consume otra vez la aprobación ni sobrescribe archivos.

Configurar `AUTOSOLID_SOLIDWORKS_AGENT` con la ruta del ejecutable C#. El runner usa `subprocess` sin shell, timeout, captura acotada y validación de `status=ok`, reconstrucción, volumen finito y diferencia de volumen. Sin ejecutable configurado, el trabajo falla con `SOLIDWORKS_NOT_CONFIGURED`. La cola es serial por proceso y en memoria; SQLite conserva el estado de los trabajos.

### Conexión verificada para este proyecto

- CLI: `opencode-ai 1.19.4` mediante `npx`.
- Modelo configurado en `opencode.json`: `opencode/deepseek-v4.1-flash-free`.
- Una llamada mínima respondió correctamente con coste reportado `0`; esto no constituye un benchmark de programación.
- El estado usa `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME` y `XDG_CONFIG_HOME` bajo `.opencode-runtime/xdg/` para no tocar la base global de OpenCode.
- Las tareas delegadas se documentan en `docs/tasks/`; la integración exige auditoría y pruebas independientes.

## 8. Uso con proveedores y pesos locales

Configuración conceptual, sin secretos:

```yaml
models:
  planner:
    adapter: openai_compatible
    base_url: http://127.0.0.1:PORT/v1
    model: MODEL_ID
    credential_ref: windows://autosolid/planner
  vision:
    adapter: PROVIDER_ADAPTER
    model: MULTIMODAL_MODEL_ID
    credential_ref: windows://autosolid/vision
```

El adaptador, puerto y modelo reales se documentan en configuración local no versionada. Los archivos de ejemplo solo usan placeholders. Nunca pegar API keys en issues, ADR, logs o prompts.

Para cada peso/LoRA registrar:

- ruta y hash;
- modelo base y arquitectura;
- formato y cuantización;
- runtime compatible;
- licencia y uso permitido;
- contexto máximo y modalidades reales;
- VRAM/RAM observada, no solo estimada;
- comando/configuración de inferencia;
- benchmark y rollback.

## 9. Inventario inicial de entorno

Copiar `environment.example.yaml` como `environment.local.yaml` en iteración 0 y completarla con datos comprobados. El archivo local está excluido de Git para no publicar inventario, rutas ni configuración del equipo:

```yaml
schema_version: 1
machine:
  windows_version: PENDING
  cpu: PENDING
  ram_gb: PENDING
  gpu: PENDING
  vram_gb: PENDING
cad:
  solidworks_version: PENDING
  solidworks_api_version: PENDING
  autocad_version: OPTIONAL_PENDING
models:
  - id: MiMo-V2.6-Distill-Qwen-9B
    base_path: PENDING
    adapter_path: output/lumocad_mimo9b
    soup_config: configs/soup_mimo9b.yaml
    status: REPORTED_TRAINED_UNVERIFIED
  - id: Qwen2.5-Coder-3B-Instruct
    base_path: PENDING
    adapter_path: output/lumocad_qwen3b
    soup_config: configs/soup_qwen3b.yaml
    status: REPORTED_BASE_UNVERIFIED
privacy:
  external_providers_allowed: PENDING
```

Este bloque es una plantilla, no evidencia de que esos archivos existan en el directorio actual.

## 10. Herramientas que pueden apoyar

| Necesidad | Candidato | Función y límite |
|---|---|---|
| PDF vectorial | PyMuPDF | Vectores/texto/render; validar licencia y fidelidad con corpus |
| OCR | Tesseract o PaddleOCR | Texto en raster; no entiende por sí solo intención mecánica |
| Imagen | OpenCV | Limpieza/segmentación; no sustituye cotas |
| DXF | ezdxf | Intercambio y normalización; no conserva toda la intención CAD |
| Geometría/preview | OpenCASCADE, CadQuery o build123d | Comprobación/preview puntual; no duplicar la fuente de verdad |
| CAD principal | SolidWorks API/Interop | SLDPRT paramétrico nativo |
| Flujo heredado | AutoCAD .NET/COM | PDFATTACH/PDFIMPORT/PDFDETACH/SCALE/DXF según versión |
| Cliente agente | OpenCode | Consume MCP y aporta su propio modelo |
| Cliente alternativo | Cualquier cliente MCP compatible | Reutiliza herramientas sin cambiar dominio |
| Modelos locales | Runtime compatible con el formato real | Servicio reemplazable; se decide tras inventario |

No se instalan todos por defecto. Cada herramienta entra cuando una iteración la necesita y una prueba demuestra compatibilidad.

## 11. Definición de hecho para cada cambio

- Criterio de la iteración enlazado.
- Contrato y migraciones actualizados.
- Casos positivos/negativos superados.
- Flujo real ejecutado cuando afecta a SolidWorks/AutoCAD/proveedor.
- Sin secretos ni archivos originales alterados.
- Reporte con límites y fallos conocidos.
- Documentación y ADR coherentes.
- Rollback posible para modelos y cambios de esquema.
