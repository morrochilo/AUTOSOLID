# Contrato CAD, herramientas y trazabilidad

## 1. Principio

`CadSpec` es el límite estable entre interpretación y construcción. Modelos, PDF, texto e imágenes pueden cambiar; el constructor SolidWorks solo consume esta estructura validada.

El esquema se implementará con JSON Schema/Pydantic, tendrá versionado semántico y migraciones explícitas. Los ejemplos siguientes definen intención de diseño; no son todavía un esquema ejecutable.

## 2. Reglas obligatorias

- Unidades canónicas internas: longitudes en milímetros y ángulos en grados, con conversión explícita en los bordes.
- Sistema de coordenadas y planos con orientación documentada.
- Toda dimensión conserva valor nominal, unidad original, tolerancia y evidencia.
- Toda operación referencia croquis/referencias por ID estable.
- Ninguna dimensión desconocida se reemplaza silenciosamente por cero o un valor “típico”.
- Los supuestos son datos visibles y requieren aceptación si afectan a geometría.
- La procedencia distingue `extracted`, `inferred`, `user_supplied` y `default`.
- Los estados de confianza no sustituyen reglas duras ni aprobación.
- El constructor no modifica el `CadSpec`; devuelve observaciones y errores.

## 3. Ejemplo conceptual

Pieza axisimétrica sencilla. Los IDs de evidencia apuntan al documento original.

```json
{
  "schema_version": "0.1.0",
  "project_id": "prj_01...",
  "revision": 3,
  "units": { "length": "mm", "angle": "deg" },
  "sources": [
    {
      "id": "src_pdf",
      "kind": "pdf",
      "sha256": "...",
      "page": 1
    }
  ],
  "parameters": {
    "outer_diameter": {
      "value": "50.000",
      "unit": "mm",
      "origin": "extracted",
      "evidence_ids": ["ev_dim_01"]
    },
    "length": {
      "value": "80.000",
      "unit": "mm",
      "origin": "extracted",
      "evidence_ids": ["ev_dim_02"]
    }
  },
  "references": [
    { "id": "front_plane", "kind": "plane", "name": "Front" },
    { "id": "main_axis", "kind": "axis", "origin": [0, 0, 0], "direction": [1, 0, 0] }
  ],
  "sketches": [
    {
      "id": "profile",
      "plane_id": "front_plane",
      "entities": [
        { "id": "l1", "kind": "line", "start": [0, 0], "end": [0, 25] },
        { "id": "l2", "kind": "line", "start": [0, 25], "end": [80, 25] },
        { "id": "l3", "kind": "line", "start": [80, 25], "end": [80, 0] },
        { "id": "axis_segment", "kind": "line", "start": [80, 0], "end": [0, 0] }
      ],
      "constraints": [
        { "kind": "closed_loop", "entity_ids": ["l1", "l2", "l3", "axis_segment"] },
        { "kind": "coincident_axis", "entity_id": "axis_segment", "reference_id": "main_axis" }
      ],
      "dimensions": [
        { "kind": "distance", "from": [0, 0], "to": [80, 0], "parameter": "length" },
        { "kind": "distance", "from": [0, 0], "to": [0, 25], "expression": "outer_diameter / 2" }
      ]
    }
  ],
  "features": [
    {
      "id": "body",
      "kind": "revolve",
      "sketch_id": "profile",
      "axis_id": "main_axis",
      "angle": "360",
      "operation": "new_body"
    }
  ],
  "open_questions": [],
  "assumptions": [],
  "approval": null
}
```

El ejemplo no pretende definir todavía el formato completo de restricciones. Las pruebas de iteración 3 fijarán esa representación antes de conectar inferencia automática.

## 4. Evidencia y ambigüedad

Cada evidencia debe permitir volver a la fuente:

```json
{
  "id": "ev_dim_01",
  "source_id": "src_pdf",
  "page": 1,
  "view_id": "view_front",
  "bbox": [100.0, 220.0, 180.0, 260.0],
  "kind": "linear_dimension",
  "raw_text": "⌀50 h7",
  "normalized_value": "50.000",
  "unit": "mm",
  "tolerance": { "kind": "iso_fit", "designation": "h7" },
  "extractor": "pdf-vector@...",
  "confidence": 0.98
}
```

Las incógnitas se clasifican:

- `critical`: impiden definir forma, escala, eje, unidades o cotas requeridas; bloquean aprobación.
- `major`: permiten una hipótesis, pero exigen confirmación humana.
- `minor`: documentación o presentación sin cambio geométrico conocido.

Una confianza numérica alta nunca convierte una `critical` en válida.

## 5. Validaciones por capas

1. **Sintaxis:** esquema, tipos, IDs únicos y referencias existentes.
2. **Unidades:** conversiones, magnitudes finitas, ángulos y signos.
3. **Croquis:** bucles, auto-intersecciones, coincidencias, arcos y restricciones.
4. **Operación:** perfil/eje compatibles, dirección, profundidad, ámbito y cuerpos resultantes.
5. **Mecánica:** espesores, radios, diámetros y relaciones imposibles según reglas declaradas.
6. **Construcción:** llamadas SolidWorks y reconstrucción sin errores.
7. **Resultado:** dimensiones, volumen, bounding box, caras y vistas comparados con expectativas.

Los errores incluyen ruta JSON, código, explicación y sugerencia. No se repara en bucle indefinidamente: como máximo un número configurado de intentos y luego vuelve al usuario.

## 6. API de aplicación

Casos de uso compartidos por REST, MCP y CLI:

| Operación | Entrada principal | Resultado |
|---|---|---|
| Crear proyecto | nombre, configuración | proyecto y revisión inicial |
| Ingerir fuente | PDF/imagen/texto y opciones | fuente, hash y artefactos |
| Analizar documento | fuente, perfil de análisis | `DrawingSpec`, evidencias, preguntas |
| Proponer diseño | fuentes, instrucciones, modelo | revisión `CadSpec` candidata |
| Validar diseño | revisión `CadSpec` | diagnósticos y reporte |
| Actualizar diseño | parche y revisión base | nueva revisión o conflicto |
| Aprobar construcción | revisión, hash y alcance | aprobación de un solo uso |
| Construir | revisión aprobada, destino nuevo | trabajo y artefactos |
| Consultar trabajo | ID y cursor | estado, progreso, diagnósticos |
| Obtener comparación | construcción | métricas, imágenes y reporte |

Toda mutación exige `expected_revision` para evitar que un modelo sobrescriba cambios humanos. Las operaciones costosas devuelven un `job_id`.

## 7. Herramientas MCP iniciales

| Herramienta | Efecto | Observación |
|---|---|---|
| `autosolid_project_create` | escritura local | Crea proyecto |
| `autosolid_document_ingest` | escritura local | Ingiere ruta permitida |
| `autosolid_document_analyze` | trabajo de análisis | Puede consumir modelo |
| `autosolid_design_propose` | trabajo de análisis | Devuelve candidato, no construye |
| `autosolid_design_get` | lectura | Revisión y diagnósticos |
| `autosolid_design_validate` | lectura/computación | Validación determinista |
| `autosolid_job_status` | lectura | Estado y progreso |
| `autosolid_artifact_get` | lectura | Metadatos o recurso autorizado |
| `autosolid_solidworks_build` | efecto externo local | Requiere aprobación válida y ruta nueva |

La aprobación se obtiene en la interfaz o mediante una acción humana explícita del cliente. El token queda ligado a proyecto, revisión, hash y destino, expira y solo se usa una vez.

No se expondrá una herramienta genérica `run_code` ni acceso arbitrario al sistema de archivos.

## 8. Resultado de construcción

```json
{
  "job_id": "job_...",
  "spec_revision": 3,
  "spec_sha256": "...",
  "status": "completed",
  "solidworks_version": "...",
  "artifacts": {
    "part": "artifact:...",
    "step": "artifact:...",
    "preview": "artifact:...",
    "report": "artifact:..."
  },
  "verification": {
    "rebuild_errors": 0,
    "rebuild_warnings": [],
    "dimensions_checked": 12,
    "dimensions_failed": 0,
    "open_critical_questions": 0
  }
}
```

`completed` significa que pasó las validaciones configuradas; no certifica fabricabilidad ni seguridad funcional por sí solo.

## 9. Errores y observabilidad

Códigos estables, por ejemplo:

- `SOURCE_UNSUPPORTED`
- `SCALE_UNRESOLVED`
- `DIMENSION_CONFLICT`
- `QUESTION_CRITICAL_OPEN`
- `SCHEMA_INVALID`
- `SKETCH_NOT_CLOSED`
- `FEATURE_UNSUPPORTED`
- `MODEL_OUTPUT_INVALID`
- `PROVIDER_UNAVAILABLE`
- `APPROVAL_REQUIRED`
- `REVISION_CONFLICT`
- `SOLIDWORKS_UNAVAILABLE`
- `SOLIDWORKS_REBUILD_FAILED`
- `VERIFICATION_FAILED`

Los logs usan IDs de proyecto/trabajo y redacción de secretos. Las respuestas del modelo se guardan como artefactos de depuración solo si la política de privacidad lo permite.

## 10. Versionado y compatibilidad

- `schema_version` obligatorio en cada especificación.
- Prompts y constructores declaran versiones compatibles.
- Una revisión aprobada queda inmutable; corregir crea otra.
- Los resultados guardan versiones de extractor, validador, proveedor y SolidWorks.
- Cambios incompatibles requieren ADR, migración y prueba del corpus dorado.
