# ADR-003: Aprobación humana y bloqueo de ambigüedades críticas

- Estado: aceptado
- Fecha: 2026-10-24
- Iteración: 0
- Implementación: parcial (tarea 008, iteración 1)

## Contexto

Una escala, cota, eje o interpretación incorrecta puede producir una pieza plausible pero errónea. La confianza del modelo no es una medida suficiente de exactitud.

## Decisión

Las preguntas críticas abiertas bloquean la aprobación. Construir requiere una aprobación explícita ligada a proyecto, revisión, hash y destino, de un solo uso y con expiración. Cualquier cambio crea otra revisión e invalida la aprobación anterior. Los archivos nuevos son el comportamiento por defecto.

## Estado de implementación (tareas 008 y 009)

La tarea 008 implementó una **aprobación de diseño** de alcance `design`, explícita, inmutable y append-only, ligada a la revisión vigente y a su SHA-256. Se guarda en la tabla `approvals`, con unicidad por `(proyecto, revisión, alcance)` y triggers que impiden modificaciones y reescrituras. La migración SQLite v4 añadió protección anti-duplicados contra `INSERT OR REPLACE`. El estado se calcula como `valid` o `stale` en una instantánea coherente de proyecto, revisión e historial: guardar otra revisión invalida automáticamente la aprobación anterior sin borrarla ni modificarla. Aprobar exige que la revisión sea la actual, que el hash coincida y que el `CadSpec` guardado vuelva a pasar `validate_spec` sin diagnósticos de error.

Esta implementación **no completa** el requisito de construcción del ADR: no hay destino, expiración, consumo único ni revocación. La aprobación `design` no provoca la transición a `BUILDING` ni autoriza SolidWorks/AutoCAD. La aprobación de construcción sigue pendiente.

## Alternativas consideradas

- Construcción automática por umbral de confianza: rechazada.
- Revisión posterior únicamente: rechazada porque ya se habría creado el archivo incorrecto.
- Aprobación global por sesión: rechazada porque no protege una revisión concreta.

## Consecuencias

El sistema puede rechazar casos ambiguos y debe medir cobertura además de precisión. La revisión humana forma parte del flujo, no es un fallo excepcional.

## Evidencia / pruebas

La tarea 008 verificó localmente la parte de aprobación de diseño:

- `tests/test_approvals.py`: 32 pruebas superadas (dominio, almacén, migración v2→v3, inmutabilidad, aislamiento, concurrencia y reapertura).
- `tests/test_api_approvals.py` y `tests/test_mcp_approvals.py`: 22 pruebas superadas (API, errores estables, transición a obsoleto y MCP de solo lectura).
- Suite completa: 254 pruebas superadas y 1 aviso preexistente de Starlette/httpx.
- `python -m compileall -q src tests`, `node --check` y `git diff --check` sin errores.
- Prueba real en navegador: revisión 1 aprobada como «Ana Revisora», persistencia tras recargar, y revisión 2 guardada después; la aprobación de la revisión 1 quedó obsoleta y la revisión 2 pendiente.

La invalidación por nueva revisión y la revalidación al aprobar están cubiertas para la aprobación de diseño. Los criterios específicos de construcción —cero construcciones con preguntas críticas abiertas, token de un solo uso con destino y expiración, y reintentos de construcción sin duplicados— siguen pendientes porque la operación de construcción no existe.
