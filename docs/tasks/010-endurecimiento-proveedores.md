# Tarea 010 — Endurecimiento de proveedores

## Contexto

Leer `docs/tasks/auditoria-003-008.md` y el código `autosolid.providers`. La tarea 009 se encarga de persistencia; esta tarea solo corrige proveedores y sus pruebas. No integrar proveedores con el dominio ni llamar servicios externos.

## Alcance obligatorio

1. **Parseo seguro:** `parse_json_object` y el sobre HTTP deben convertir `ValueError` de enteros patológicos y `RecursionError` de anidación en `ProviderError` con códigos estables. No capturar `BaseException`, `KeyboardInterrupt`, `SystemExit` ni errores de memoria. Aplicar rechazo de `NaN`/`Infinity` también al sobre.
2. **Simulador coherente:** mappings y `SimulatedReply` deben usar JSON estándar (`allow_nan=False`) y la misma validación que el adaptador real. Rechazar contenido contradictorio cuando se solicita JSON. No aceptar `NaN` ni `parsed_json` incoherente con `content`.
3. **Concurrencia del simulador:** proteger registro, índice y cola con un lock para evitar IDs duplicados, asociación incorrecta e `IndexError`. Añadir prueba concurrente real.
4. **Inmutabilidad real:** impedir que `request.messages`, `response.parsed_json` y el historial `provider.requests` cambien retroactivamente. Usar tuplas/copias defensivas u otra representación compatible con Pydantic y el código actual.
5. **Configuración:** rechazar `?` y `#` aunque estén vacíos en `base_url`; normalizar `timeout_seconds` a `float` para que `to_public_dict()` sea JSON serializable también con `Fraction`.
6. Mantener bloqueo de redirects, proxy explícito, límites y redacción de credenciales. No añadir reintentos, streaming, visión ni integración con MCP/API/CadSpec.
7. Añadir regresiones para cada caso y documentar en `docs/tasks/010-informe.md`, sin declarar auditoría independiente.

## Fuera de alcance

- Llamadas a proveedores externos, API keys reales y benchmarks.
- Persistencia, aprobaciones, UI y tareas de otras iteraciones.
- Commits, pushes y publicación.

## Verificación

- Demostrar que las nuevas regresiones fallan antes de corregir.
- Ejecutar `pytest` completo y `compileall`.
- Comprobar que los errores esperados siguen siendo `ProviderError` y no filtran secretos.
- No modificar pruebas existentes para ocultar fallos.
