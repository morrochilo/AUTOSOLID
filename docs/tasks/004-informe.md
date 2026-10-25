# Tarea 004 — Informe de implementación local

Fecha: 2026-10-24
Estado: implementada y probada localmente; sin auditoría independiente.

## Alcance ejecutado

Se creó `autosolid.providers` con un contrato propio, sin acoplarlo a MCP, a la
API de proyectos ni a `CadSpec`:

| Archivo | Contenido |
| --- | --- |
| `src/autosolid/providers/base.py` | Protocolo estructural `ModelProvider`. |
| `src/autosolid/providers/models.py` | Modelos Pydantic inmutables y estrictos para mensajes, petición, uso y respuesta. |
| `src/autosolid/providers/errors.py` | `ProviderError` con `code`, `message` y `details`; sin secretos. |
| `src/autosolid/providers/json_output.py` | Decodificación estricta de un objeto JSON completo. |
| `src/autosolid/providers/config.py` | `OpenAICompatibleConfig` y carga desde variables de entorno. |
| `src/autosolid/providers/simulated.py` | `SimulatedProvider` determinista con cola y registro de peticiones. |
| `src/autosolid/providers/openai_compatible.py` | Adaptador HTTP `POST /chat/completions` con `urllib.request`. |
| `tests/test_providers.py` | 40 pruebas con un servidor HTTP local efímero. |
| `examples/provider.env.example` | Variables de entorno con placeholders. |

## Decisiones relevantes

- **Sin dependencia HTTP nueva.** El adaptador usa `urllib.request`; no se añadió
  `httpx` ni otro cliente al runtime.
- **Redirecciones bloqueadas.** Un `HTTPRedirectHandler` propio devuelve `None`,
  de modo que el adaptador nunca reenvía credenciales a otro destino.
- **HTTP sin TLS restringido.** Solo se acepta en loopback; fuera de loopback se
  exige `https` o `allow_insecure_http=True` de forma explícita.
- **Credenciales fuera de logs.** `api_key` y `organization` usan `repr=False`.
  `to_public_dict()` expone únicamente `has_api_key` y `has_organization`.
  Los errores HTTP conservan solo el código de estado, nunca el cuerpo. Las
  cabeceras rechazan caracteres de control y valores fuera de Latin-1 para no
  provocar errores de codificación no controlados.
- **Sin proxies implícitos.** Se instala `ProxyHandler({})` salvo que
  `use_system_proxy=True`; así una variable de entorno del sistema no desvía la
  petición sin decisión explícita.
- **Tamaño acotado.** Se leen como máximo `max_response_bytes + 1` bytes y se
  falla con `PROVIDER_RESPONSE_TOO_LARGE` antes de parsear.
- **JSON estricto.** `response_format="json_object"` exige un objeto JSON
  completo. No se eliminan cercas Markdown ni texto adicional, y se rechazan
  `NaN`/`Infinity`, que Python acepta pero JSON no. Un fallo produce
  `MODEL_OUTPUT_INVALID` con un motivo estable.
- **Contrato síncrono.** `complete()` es bloqueante por diseño; la docstring del
  protocolo indica que un llamador asíncrono debe usar un hilo, por ejemplo
  `anyio.to_thread.run_sync`.

## Códigos de error implementados

`PROVIDER_CONFIG_INVALID`, `PROVIDER_AUTH_FAILED`, `PROVIDER_RATE_LIMITED`,
`PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_HTTP_ERROR`,
`PROVIDER_RESPONSE_INVALID`, `PROVIDER_RESPONSE_TOO_LARGE`,
`PROVIDER_REDIRECT_BLOCKED`, `MODEL_OUTPUT_INVALID` y
`SIMULATED_PROVIDER_EXHAUSTED`.

## Verificación ejecutada

Entorno: Windows, Python 3.12.10, pytest 9.1.1, Pydantic 2.14.1.

```text
.venv\Scripts\python -m pytest -q tests/test_providers.py
40 passed in 15.73s

.venv\Scripts\python -m pytest -q
153 passed, 1 warning in 21.38s
```

La advertencia es la existente de `starlette.testclient` sobre `httpx` y no
proviene de esta tarea.

Cobertura de las pruebas:

- Petición real contra un servidor local: ruta, método, JSON enviado, modelo,
  temperatura, `max_tokens`, `response_format`, `stream` y cabeceras.
- Respuesta de texto y respuesta JSON válida.
- Modelo por petición, funcionamiento sin API key, ruta de endpoint
  personalizada y cabecera de organización.
- Errores 401/403, 429, 500/503 y 400, comprobando que el cuerpo con la clave no
  se filtra.
- Redirección 302 sin seguimiento.
- Timeout con servidor local retardado, tanto desde la configuración como
  sobrescrito por la petición.
- JSON inválido, vacío, no-objeto, truncado y con números no finitos, sin
  reparación.
- Cuerpos de proveedor inválidos: texto, vacío, lista, sin opciones, opción
  inválida, sin mensaje, contenido no textual y respuesta no UTF-8.
- Límite de bytes de respuesta.
- Configuración inválida: HTTP remoto sin TLS, esquema no HTTP, credenciales en
  URL, consulta/fragmento, URL no ASCII, puerto inválido, inyección de cabeceras,
  caracteres no Latin-1 en cabeceras, `NaN`, ruta de endpoint inválida,
  variables obligatorias ausentes y valores de entorno no numéricos o no
  booleanos.
- Redacción de clave y organización en `repr` y en la vista pública.
- Proveedor simulado: cola, registro, JSON, errores inyectados y agotamiento.
- Conformidad estructural de ambos proveedores con `ModelProvider`.

## Límites y trabajo no realizado

- **No se llamó a ningún proveedor externo real.** Las pruebas de red usan un
  servidor efímero en `127.0.0.1`; no se verificaron OpenAI, servidores locales
  de inferencia ni pasarelas compatibles.
- **Sin integración.** No se conectó con MCP, API, proyectos, prompts ni
  `CadSpec`.
- **Sin streaming, reintentos, selección de modelo, visión, embeddings ni
  herramientas.** Quedan fuera del alcance de la tarea.
- **Sin proveedor asíncrono.** La interfaz es síncrona; el desacople de hilos
  queda a cargo del llamador.
- **Sin control de confianza TLS configurable.** Se usa la verificación por
  defecto de `urllib` y el almacén de certificados del sistema.
- **Timeout de socket, no plazo total.** `urllib` aplica el valor a operaciones
  de socket; una respuesta que progresa muy lentamente podría superar el tiempo
  nominal sin disparar el error.
- **`latency_ms` parcial.** Mide la petición HTTP y la lectura del cuerpo, no el
  parseo JSON ni la construcción del objeto de respuesta.
- **Sin límite de tamaño de petición propio.** Los mensajes están acotados por
  Pydantic, pero no se mide el cuerpo serializado antes de enviarlo.
- **Sin prueba de proxy real.** Solo se verifica que el valor de configuración
  se conserva; no se ejecutó un proxy.
- **Sin auditoría de seguridad independiente.** La revisión de redacción y
  bloqueo de redirecciones es local.
