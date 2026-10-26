# ADR-003: Aprobación humana y bloqueo de ambigüedades críticas

- Estado: aceptado
- Fecha: 2026-10-24
- Iteración: 0
- Implementación: parcial (tareas 008 y 012; API local sin UI/MCP de construcción)

## Contexto

Una escala, cota, eje o interpretación incorrecta puede producir una pieza plausible pero errónea. La confianza del modelo no es una medida suficiente de exactitud.

## Decisión

Las preguntas críticas abiertas bloquean la aprobación. Construir requiere una aprobación explícita ligada a proyecto, revisión, hash y destino, de un solo uso y con expiración. Cualquier cambio crea otra revisión e invalida la aprobación anterior. Los archivos nuevos son el comportamiento por defecto.

## Estado de implementación (tareas 008 y 009)

La tarea 008 implementó una **aprobación de diseño** de alcance `design`, explícita, inmutable y append-only, ligada a la revisión vigente y a su SHA-256. Se guarda en la tabla `approvals`, con unicidad por `(proyecto, revisión, alcance)` y triggers que impiden modificaciones y reescrituras. La migración SQLite v4 añadió protección anti-duplicados contra `INSERT OR REPLACE`. El estado se calcula como `valid` o `stale` en una instantánea coherente de proyecto, revisión e historial: guardar otra revisión invalida automáticamente la aprobación anterior sin borrarla ni modificarla. Aprobar exige que la revisión sea la actual, que el hash coincida y que el `CadSpec` guardado vuelva a pasar `validate_spec` sin diagnósticos de error.

La tarea 012 añadió la **aprobación de construcción** de alcance `build` en `build_approvals`, separada de `design`. Liga proyecto, revisión actual, SHA-256 del `CadSpec`, destino relativo dentro del directorio configurado y hash canónico del destino; incluye revisor, creación, expiración y notas. Es append-only y el consumo se registra en `build_consumptions` junto con un `build_jobs` en la misma transacción, sin `UPDATE` de la aprobación. Dos consumidores concurrentes no pueden usar el mismo token. El servicio revalida revisión, hash, destino y expiración, y una nueva revisión invalida el token. La cola es serial por proceso y el runner lanza el agente C# sin shell, valida el JSON y no sobrescribe archivos. Reintentar reutiliza el consumo y no crea un archivo duplicado.

La aprobación `design` sigue sin autorizar construcción. La aprobación `build` no exige una aprobación de diseño previa en esta iteración. No hay UI ni MCP de construcción, ni recuperación automática de trabajos `running` tras un fallo del proceso.

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

La tarea 012 verificó la aprobación de construcción y la cola:

- `tests/test_builds.py` y `tests/test_api_builds.py`: 65 pruebas superadas (migración v4→v5, destinos, expiración, obsolescencia, consumo único, concurrencia, idempotencia, reintento, runner simulado y API).
- Suite completa: 339 pruebas superadas y 1 aviso preexistente de Starlette/httpx.
- `dotnet build` del agente C#: 0 errores y 0 advertencias.
- Trabajo real con SolidWorks 2024 (`RevisionNumber = 32.0.1`): `completed`, SLDPRT nuevo de 54 884 bytes, volumen verificado `8.000000000000001e-06 m³`, caja 40×20×10 mm, errores 0 y 4 avisos visibles. No se cerró SolidWorks.
- Un primer intento real falló solo por la limpieza del archivo temporal bloqueado por SolidWorks; se corrigió y el segundo terminó `completed`.

Siguen pendientes la UI/MCP de construcción, la recuperación automática de trabajos `running` huérfanos, la cancelación y la verificación con otras versiones, plantillas y familias geométricas.
