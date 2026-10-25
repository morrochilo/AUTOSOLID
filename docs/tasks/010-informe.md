# Informe de la tarea 010 — Endurecimiento de proveedores

## Resultado

Todos los hallazgos de proveedores de la auditoría 003–008 fueron corregidos sin llamadas externas ni cambios de alcance. La implementación fue directa porque DeepSeek continuaba devolviendo `Free usage limit reached`.

## Cambios

- `parse_json_object` normaliza enteros patológicos y anidación excesiva como `ProviderError`.
- El sobre HTTP rechaza `NaN`/`Infinity`, JSON patológico y errores de anidación con `PROVIDER_RESPONSE_INVALID`.
- El simulador serializa con `allow_nan=False`, valida coherencia entre contenido y `parsed_json` y usa el mismo parser estricto.
- Un `RLock` protege historial, índice y cola del simulador; las peticiones registradas usan copias profundas.
- `CompletionRequest.messages` usa tuplas y acepta listas en la entrada de Pydantic sin volver a ser mutable.
- `CompletionResponse.parsed_json` se congela recursivamente con `MappingProxyType`/tuplas.
- `base_url` rechaza `?` y `#` incluso vacíos; `timeout_seconds` se normaliza a `float`.
- Se conservan redacción de credenciales, bloqueo de redirects y política de proxies.

## Regresiones

`tests/test_audit_010_regressions.py` contiene 13 casos de auditoría para:

- enteros largos y anidación;
- `NaN` en simulador y sobre HTTP;
- respuestas contradictorias;
- inmutabilidad de mensajes, historial y respuestas;
- delimitadores vacíos y `Fraction`;
- concurrencia real con 50 llamadas e IDs únicos.

Las diez regresiones iniciales fallaban antes de corregir. Después se añadieron sobre HTTP y concurrencia.

## Verificación

- Proveedores y regresiones focalizadas: **53 pruebas superadas**.
- Suite completa: **273 pruebas superadas**, una advertencia conocida de Starlette/TestClient.
- `compileall`: correcto.
- No se llamó a proveedores externos ni se añadieron dependencias.

## Pendientes

Validación integral 009/010, auditoría de privacidad, empaquetado y PR. La delegación DeepSeek podrá reanudarse cuando el proveedor gratuito vuelva a estar disponible.
