# ADR-003: Aprobación humana y bloqueo de ambigüedades críticas

- Estado: aceptado
- Fecha: 2026-10-24
- Iteración: 0

## Contexto

Una escala, cota, eje o interpretación incorrecta puede producir una pieza plausible pero errónea. La confianza del modelo no es una medida suficiente de exactitud.

## Decisión

Las preguntas críticas abiertas bloquean la aprobación. Construir requiere una aprobación explícita ligada a proyecto, revisión, hash y destino, de un solo uso y con expiración. Cualquier cambio crea otra revisión e invalida la aprobación anterior. Los archivos nuevos son el comportamiento por defecto.

## Alternativas consideradas

- Construcción automática por umbral de confianza: rechazada.
- Revisión posterior únicamente: rechazada porque ya se habría creado el archivo incorrecto.
- Aprobación global por sesión: rechazada porque no protege una revisión concreta.

## Consecuencias

El sistema puede rechazar casos ambiguos y debe medir cobertura además de precisión. La revisión humana forma parte del flujo, no es un fallo excepcional.

## Evidencia / pruebas

Los criterios exigen cero construcciones con preguntas críticas abiertas, invalidación al editar y reintentos sin duplicados. Estas pruebas se implementarán con el flujo de construcción.
