# Informe de implementación de la tarea 003

## Alcance ejecutado

Fachada MCP local `stdio` sobre `ProjectService`/`ProjectStore`, sin HTTP y sin
duplicar validación, SQL ni revisiones. La tarea 003 sigue pendiente de auditoría
independiente; este documento registra lo implementado y lo realmente probado.

## SDK y entorno

- Python: **3.12.10** (venv del repositorio).
- SDK oficial `mcp`: **1.30.0**, declarado como `mcp>=1.30,<2`.
- Pydantic: **2.14.1**.
- OpenCode CLI: **1.19.4** mediante `npx opencode-ai`.
- Sistema: Windows 11.

## Herramientas expuestas

| Herramienta | Efecto | Anotación MCP |
|---|---|---|
| `autosolid_project_create` | Crea proyecto | escritura, no destructiva |
| `autosolid_project_list` | Lista proyectos | solo lectura, idempotente |
| `autosolid_project_get` | Lee un proyecto | solo lectura, idempotente |
| `autosolid_design_get` | Lee la última revisión | solo lectura, idempotente |
| `autosolid_design_validate` | Valida sin persistir | solo lectura, idempotente |
| `autosolid_design_update` | Guarda revisión con `expected_revision` | escritura, no destructiva |

Todas tienen `inputSchema` estricto (`additionalProperties: false`),
`outputSchema` estructurado, título, descripción y resultado JSON también en
`content[0].text`. Los errores esperados devuelven `ok: false` y
`error: {code, message, details}` sin trazas ni rutas internas.

## Decisiones de implementación

- El servidor se construye con `create_server()` y comparte la misma capa de
  aplicación que la API; no hay lógica de dominio en el adaptador MCP.
- `design_validate` es de solo lectura; `design_update` usa el bloqueo optimista
  del servicio y exige `expected_revision`.
- Las llamadas síncronas a SQLite se ejecutan fuera del bucle de eventos con
  `anyio.to_thread.run_sync`, para no bloquear el servidor MCP.
- El servidor toma propiedad del `ProjectStore` que utiliza y lo cierra al
  terminar su ciclo de vida.
- No se escribe nada en `stdout` fuera del protocolo. Si el transporte se
  cierra, el proceso termina sin ruido.
- `python -m autosolid.mcp --version` y el comando `autosolid-mcp` están
  disponibles.

## Verificación ejecutada

Comandos reales, desde la raíz del repositorio:

```text
.venv\Scripts\python -m pytest -q tests/test_mcp_server.py
27 passed

.venv\Scripts\python -m pytest -q
113 passed, 1 warning
```

La advertencia es la depreciación conocida de Starlette/httpx en la API; no
afecta a MCP.

Pruebas MCP relevantes:

- catálogo, esquemas de entrada/salida estrictos, títulos y anotaciones;
- metadatos de inicialización y versión;
- creación, lista y lectura de proyectos;
- validación sin persistencia y actualización con decimales preservados;
- conflicto de revisión e informe de especificación inválida;
- argumentos inválidos y herramienta desconocida con errores estructurados;
- errores inesperados sin rutas, trazas ni secretos;
- protocolo en memoria con SDK real;
- dos actualizaciones concurrentes: una gana y la otra recibe
  `REVISION_CONFLICT`;
- protocolo real por subproceso `stdio` con `AUTOSOLID_DATA_DIR`;
- arranque y cierre por EOF sin escritura en `stdout`;
- correspondencia de las respuestas con los `outputSchema` declarados.

## Comprobación con OpenCode

En un directorio temporal aislado, con `XDG_*` propios y sin tocar la
configuración global, se usó la forma de configuración de OpenCode 1.19.4
(`mcp.<nombre>`, `enabled: true`) y se ejecutó:

```text
npx opencode-ai mcp list
```

Resultado observado:

```text
● ✓ autosolid connected
```

Esto verifica que OpenCode inicia el proceso, habla el transporte `stdio` y
enumera el servidor. **No** se ejecutó una conversación de OpenCode que invoque
las herramientas; esa prueba queda para la auditoría de integración.

## Ejemplo de configuración

`examples/opencode-mcp.example.json` contiene la forma verificada para OpenCode
1.19.4, con placeholders y sin credenciales. Para OpenCode V2, los servidores se
declaran bajo `mcp.servers` y se usa `disabled` en lugar de `enabled`; ver
`examples/opencode-mcp-v2.example.json`.

## Límites y pendientes

- No hay MCP remoto, OAuth, HTTP/SSE ni exposición a red.
- No hay ingesta PDF, proveedores, interfaz, aprobaciones ni construcción CAD.
- No se ha probado una versión de OpenCode distinta de 1.19.4 ni el flujo de
  invocación de herramientas desde una sesión de agente.
- La compatibilidad con futuras versiones 1.x de `mcp` no está garantizada por
  pruebas; el rango declarado es una intención, no una verificación.
- El servidor es local y de un solo usuario; no debe exponerse a Internet.
- El cierre del `ProjectStore` inyectado forma parte del ciclo de vida del
  servidor. Un consumidor que comparta la misma instancia debe respetar esa
  propiedad o pasar una instancia distinta.
