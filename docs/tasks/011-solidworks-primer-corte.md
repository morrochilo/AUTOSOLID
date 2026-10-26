# Tarea 011 — Primer SLDPRT nativo desde CadSpec

## Contexto verificado

- SolidWorks 2024 SP0.1 instalado; ProgID COM funciona y devuelve `32.0.1`.
- Interop en `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist`.
- `src/solidworks-agent` ya contiene un smoke `version` compilado y ejecutado correctamente con .NET 8.
- CadSpec actual cubre líneas, extrusión y revolución con longitudes mm y ángulos grados.

## Objetivo

Implementar un agente C# fuera de proceso que construya y verifique una pieza nueva desde un `CadSpec` válido, sin integrar todavía API/MCP ni PDF.

## Alcance

1. CLI `version`, `build <spec.json> <output.sldprt>` y `verify <output.sldprt>`.
2. Leer JSON con `System.Text.Json`, validar campos mínimos, unidades mm/deg, una operación `extrude` o `revolve`, croquis de líneas cerrado y valores finitos. Rechazar archivos existentes, rutas de salida no `.sldprt`, preguntas críticas abiertas y entradas fuera de alcance. No sobrescribir.
3. Convertir mm a metros y grados a radianes en el borde Interop.
4. Usar plantilla de parte de `GetUserPreferenceStringValue(swDefaultTemplatePart)` y `NewDocument(template, 0, 0, 0)`.
5. Seleccionar plano frontal con fallback explícito para nombres localizados; documentar plantilla soportada. Crear líneas con `SketchManager.CreateLine` en el croquis.
6. Extrusión con `FeatureExtrusion2`, usando profundidad D1, T1=0 (`swEndCondBlind`), `Merge=false`, `UseFeatScope=false`, `UseAutoSelect=true` y valores coherentes de la firma real.
7. Revolución con `FeatureRevolve2`, `SingleDir=true`, `IsSolid=true`, `IsThin=false`, `IsCut=false`, `Dir1Type=0`, ángulo en radianes, `Merge=false`, `UseFeatScope=false`, `UseAutoSelect=true`. Eje ya validado en CadSpec y contenido en el plano.
8. Reconstruir con `EditRebuild3`, comprobar operación/feature nula y guardar con `SaveAs4` capturando errores/warnings. No cerrar la aplicación ni documentos del usuario; cerrar solo el documento creado por el agente si procede.
9. `verify` debe abrir el SLDPRT, reconstruir, obtener volumen con `GetMassProperties` y devolver JSON con estado, ruta, volumen, errores/warnings y versión. `build` debe incluir volumen esperado/medido y diferencia.
10. Pruebas deterministas de parsing/conversión sin COM cuando sea posible y smoke real de extrusión 40×20×10 mm y revolución del cilindro Ø50×80 mm. Volumen esperado extrusión: 0.000008 m³; revolución: π·0.025²·0.080 m³.
11. Guardar salidas solo bajo `.opencode-runtime/solidworks/` o ruta temporal indicada, nunca en el código público. Documentar todo en `docs/tasks/011-informe.md`.

## Fuera de alcance

- API/MCP/UI, aprobación de construcción, PDF/OCR/DXF, proveedores, cortes, arcos, agujeros, patrones, ensamblajes y STEP.
- No cambiar el contrato `CadSpec` ni las implementaciones anteriores.
- No hacer commits ni publicar.
- No cerrar SolidWorks ni modificar piezas existentes del usuario.

## Firmas Interop verificadas

- `FeatureExtrusion2(Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2, Dang1, Dang2, OffsetReverse1, OffsetReverse2, TranslateSurface1, TranslateSurface2, Merge, UseFeatScope, UseAutoSelect, T0, StartOffset, FlipStartOffset)`.
- `FeatureRevolve2(SingleDir, IsSolid, IsThin, IsCut, ReverseDir, BothDirectionUpToSameEntity, Dir1Type, Dir2Type, Dir1Angle, Dir2Angle, OffsetReverse1, OffsetReverse2, OffsetDistance1, OffsetDistance2, ThinType, ThinThickness1, ThinThickness2, Merge, UseFeatScope, UseAutoSelect)`.
- `SaveAs4(Name, Version, Options, out Errors, out Warnings)`.

## Verificación

- `dotnet build` sin errores.
- `version` real.
- Construcción real de ambas piezas y reapertura para verificar volumen y reconstrucción.
- Comprobar diferencia de volumen dentro de 1e-9 m³ o tolerancia relativa documentada más estricta que el error de interpretación.
- Probar rechazo de salida existente y entrada inválida sin crear archivos.
