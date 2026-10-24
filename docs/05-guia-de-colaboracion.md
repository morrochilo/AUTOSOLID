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

Cuando el servidor exista:

1. Configurar AUTOSOLID como MCP local `stdio` según la documentación vigente de OpenCode.
2. Seleccionar en OpenCode el modelo permitido, incluido uno gratuito si está disponible en esa instalación.
3. Usar herramientas de análisis/lectura para proponer y revisar.
4. Aprobar explícitamente antes de `autosolid_solidworks_build`.
5. Consultar el reporte; una respuesta textual del modelo no sustituye verificación.

Los modelos gratuitos de OpenCode no se presuponen accesibles mediante una API separada. Para la interfaz propia se configura un proveedor local/directo.

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
