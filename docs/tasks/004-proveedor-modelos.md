# Tarea 004 — Proveedor de modelos simulado y adaptador OpenAI-compatible

## Contexto

Las tareas 001–003 están implementadas; la 003 sigue pendiente de auditoría
independiente. El plan maestro (iteración 1) exige un proveedor simulado para
pruebas y un adaptador OpenAI-compatible con salida JSON estructurada. Hoy no
existe ninguna capa de proveedores y el dominio CAD no debe depender de ella.

## Objetivo

Crear `autosolid.providers` con:

1. Un contrato estricto de petición/respuesta de completion.
2. Un proveedor simulado determinista para pruebas y desarrollo local.
3. Un adaptador OpenAI-compatible basado en la biblioteca estándar, sin añadir
   otra dependencia HTTP.
4. Errores estables que nunca incluyan API keys, cuerpos de respuesta crudos,
   rutas locales ni trazas.
5. Validación JSON estricta: si se solicita `json_object`, la respuesta debe ser
   un objeto JSON parseable. No se reparan cercas Markdown ni texto adicional.
6. Configuración por variables de entorno con placeholders documentados.

## Alcance obligatorio

- Modelos Pydantic inmutables para mensajes, petición, uso y respuesta.
- `CompletionResponse.parsed_json` solo para respuestas JSON válidas.
- `SimulatedProvider` con cola de respuestas, registro de peticiones y errores
  inyectables.
- `OpenAICompatibleProvider` con `POST` al endpoint configurado, timeout, límite
  de bytes, cabeceras de autenticación opcionales y bloqueo de redirecciones.
- Códigos como `PROVIDER_CONFIG_INVALID`, `PROVIDER_AUTH_FAILED`,
  `PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_RESPONSE_INVALID`,
  `PROVIDER_RESPONSE_TOO_LARGE`, `PROVIDER_REDIRECT_BLOCKED` y
  `MODEL_OUTPUT_INVALID`.
- Pruebas con un servidor HTTP local efímero; ninguna llamada a Internet.
- Ejemplo de configuración con placeholders y documentación de límites.

## Fuera de alcance

- Integración con MCP, API, proyectos o `CadSpec`.
- Prompts, propuesta de diseños, función de herramienta, streaming, visión,
  embeddings, reintentos automáticos o selección de modelos.
- Proveedores reales, claves reales, OAuth o facturación.
- PDF, interfaz, aprobaciones, SolidWorks o AutoCAD.

## Restricciones

- No hacer commits ni publicar.
- No añadir dependencias de runtime sin justificar; este adaptador usa
  `urllib.request`.
- No leer ni registrar secretos. La API key solo viaja en la cabecera
  `Authorization` y no aparece en `repr`, errores, logs ni ejemplos.
- No aceptar `http://` fuera de loopback salvo autorización explícita.
- No seguir redirecciones con credenciales.
- No relajar pruebas existentes.

## Verificación

- `pytest` completo.
- Pruebas positivas y negativas del adaptador contra un servidor local:
  petición, autenticación, JSON válido, JSON inválido, error HTTP, timeout,
  respuesta demasiado grande, redirección y configuración inválida.
- Pruebas del proveedor simulado y de la redacción de secretos.
- Informe con comandos, resultados y limitaciones.

## Implementación

- Informe local: [`004-informe.md`](004-informe.md).
