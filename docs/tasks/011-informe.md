# Informe de la tarea 011 — Primer corte SolidWorks

## Resultado

Primer corte real verificado en SolidWorks 2024 (`RevisionNumber = 32.0.1`). El agente C# fuera de proceso compila y ejecuta `version`, `build` y `verify`.

La integración usa `CadSpec` directo, sin API/MCP/UI ni aprobación de construcción. No hay PDF, modelo de lenguaje ni automatización de interpretación.

## Implementación

- `src/solidworks-agent/CadSpecDocument.cs`: parsing y validación de alcance, conversión mm→m y grados→radianes, croquis ordenado, volumen esperado y rechazo de sobrescritura.
- `src/solidworks-agent/SolidWorksBuilder.cs`: conexión COM, plantilla, croquis, selección por tipo de plano/feature, extrusión, revolución, guardado y verificación.
- `src/solidworks-agent/Program.cs`: CLI y errores JSON.
- Plano seleccionado por `RefPlane`; croquis por `ProfileFeature`, evitando nombres localizados.
- Revolución con croquis seleccionado, eje de tipo `ConstructionGeometry` y `FeatureRevolve`.
- Verificación con `EditRebuild3`, `SaveAs4`, `GetPartBox` y `GetMassProperties` (índice 3: volumen, según el orden documentado CoM X/Y/Z, volumen, área, masa).

## Evidencia real

| Pieza | Resultado | Volumen medido | Esperado | Diferencia |
|---|---|---:|---:|---:|
| Bloque 40×20×10 mm | SLDPRT abierto y reconstruido | 0.000008 m³ | 0.000008 m³ | 0 |
| Cilindro Ø50×80 mm | SLDPRT abierto y reconstruido | 0.00015707963267948965 m³ | igual | 0 |

- `dotnet build`: sin errores ni advertencias en el equipo con Interop instalado. El job .NET de GitHub se retiró porque los runners alojados no tienen las DLL propietarias; no se incluyen binarios ni stubs.
- `version`: conexión real y revisión `32.0.1`.
- `build`: errores 0 y warnings 0 para ambas piezas.
- `verify`: reapertura y reconstrucción correctas; `OpenDoc6` reportó warning 128, que queda visible en el resultado y no se oculta.
- Segunda construcción sobre el mismo destino: rechazada con `La salida ya existe; no se sobrescribe` y código 1.
- Los SLDPRT se guardaron solo en `.opencode-runtime/solidworks/`, excluido de Git.

## Incidencias resueltas

- Plano/croquis con nombres localizados: se cambió a selección por tipo.
- `GetMassProperties` devuelve `double[]`; se usa `Array`, no `object[]`.
- El volumen está en el índice 3, no en los índices de masa o centro de masa.
- Revolución requería seleccionar croquis y eje; el eje usa `ConstructionGeometry`.
- El cálculo esperado de Pappus se corrigió para centroide y conversión mm³→m³.

## Limitaciones

- Solo una operación `extrude` o `revolve` de `new_body`, perfiles de líneas y una plantilla configurada.
- No hay cortes, arcos, agujeros, patrones, STEP, ensamblajes ni integración con API/MCP/UI.
- No existe aprobación de construcción, cola, idempotencia completa ni manejo de sesiones paralelas.
- No se verificó compatibilidad con otras versiones de SolidWorks ni otra plantilla.
- La delegación DeepSeek no se ejecutó por `Free usage limit reached`; la implementación fue directa. Después se verificó `opencode-go/deepseek-v4-pro` para las siguientes tareas.
- Las piezas de prueba son sintéticas y no certifican fabricabilidad ni precisión de documentos reales.

## Siguiente paso

Integrar el agente con el servicio de aplicación mediante una operación de construcción aprobada y en cola, sin permitir llamadas directas desde modelos. Después se ampliarán verificación y familias geométricas.
