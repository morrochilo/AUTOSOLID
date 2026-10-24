# ADR-002: `CadSpec` como frontera entre IA y CAD

- Estado: aceptado
- Fecha: 2026-10-24
- Iteración: 0

## Contexto

Los modelos pueden cambiar y sus respuestas no son suficientemente confiables para controlar CAD directamente. Se necesita comprobar geometría y procedencia antes de construir.

## Decisión

Usar un documento JSON versionado con unidades canónicas, parámetros decimales, referencias, croquis, operaciones, evidencias, supuestos y preguntas. El constructor solo acepta una revisión válida y aprobada. Los cambios incompatibles requieren migración.

## Alternativas consideradas

- Generar macros C# directamente con LLM: rechazado por seguridad, validación y mantenibilidad.
- STEP/malla como representación principal: rechazado porque pierde intención paramétrica.
- CadQuery/OpenCASCADE como única fuente: aplazado; pueden apoyar validación, pero no sustituyen el contrato neutral.

## Consecuencias

Cada nueva operación exige esquema, validador, constructor, interfaz y pruebas. La primera implementación se limita a líneas, extrusión y revolución; otras geometrías quedan explícitamente fuera hasta ampliar el contrato.

## Evidencia / pruebas

La tarea `docs/tasks/001-nucleo-cadspec.md` define la primera implementación y sus casos negativos. La construcción nativa se verificará por separado en iteración 3.
