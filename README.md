# AUTOSOLID

[![CI](https://github.com/morrochilo/AUTOSOLID/actions/workflows/ci.yml/badge.svg)](https://github.com/morrochilo/AUTOSOLID/actions/workflows/ci.yml)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green.svg)](LICENSE)

Sistema local asistido por IA para convertir planos PDF, texto e imágenes en piezas mecánicas paramétricas de SolidWorks, con revisión humana y trazabilidad geométrica.

## Estado

**Fase actual: desarrollo inicial.** El núcleo `CadSpec` y el servicio local de proyectos/API están auditados. La fachada MCP local `stdio`, la capa de proveedores (simulado y OpenAI-compatible), una interfaz local mínima de revisión, un almacén inmutable de fuentes (PDF, imágenes y texto) y un registro inmutable de aprobaciones de diseño ligadas a revisión y SHA-256 están implementados y probados localmente, pendientes de auditoría independiente. La extracción de PDF/imágenes, la integración de proveedores con el dominio y la construcción en SolidWorks/AutoCAD todavía no están implementadas ni verificadas. No se afirma precisión mecánica de extremo a extremo.

El objetivo no es que un modelo “adivine” una pieza y la escriba directamente en SolidWorks. El sistema debe extraer evidencia, construir una especificación CAD explícita, validarla, permitir corregirla y recién entonces crear el archivo nativo.

## Capacidades objetivo

- PDF vectorial: extraer geometría, textos, cotas, vistas y escala sin rasterizar el contenido innecesariamente.
- PDF escaneado e imágenes: usar visión y OCR como apoyo, marcando la menor confianza y exigiendo validación dimensional.
- Texto: crear piezas paramétricas a partir de requisitos, preguntas pendientes y valores por defecto explícitos.
- SolidWorks: generar piezas nativas con croquis y operaciones editables, no únicamente sólidos importados.
- AutoCAD: ofrecer una ruta alternativa que automatice el flujo `PDFATTACH` → `PDFIMPORT` sobre el objeto/subrayado → `PDFDETACH` → escalado controlado → intercambio DXF/DWG.
- Modelos: conectar pesos locales, servidores compatibles con API de OpenAI y proveedores mediante API key.
- OpenCode: utilizar AUTOSOLID como servidor MCP; los modelos gratuitos disponibles dentro de OpenCode se usarán cuando OpenCode sea el cliente.
- Interfaz: revisar evidencias, cotas, operaciones y resultado 3D antes de aprobar la construcción.

## Decisiones principales

1. **MCP es una fachada, no el núcleo.** La interfaz web local, OpenCode y otros clientes reutilizan el mismo servicio de aplicación.
2. **La fuente de verdad es `CadSpec`.** Es un documento JSON versionado con unidades, cotas, croquis, operaciones, incógnitas y referencias a la evidencia.
3. **La geometría se valida de forma determinista.** Un LLM propone; validadores, reglas geométricas y el usuario deciden.
4. **Las cotas mandan.** La longitud dibujada y la escala gráfica sirven para comprobar, no para sustituir una cota impresa.
5. **Sin datos suficientes no hay construcción automática.** Las ambigüedades críticas quedan bloqueantes.
6. **Primero un flujo completo pequeño.** Extrusión y revolución antes de agregar más familias de piezas o entrenar modelos.
7. **Entrenar solo contra una línea base medida.** Los pesos y LoRA existentes se integran como proveedores reemplazables y compiten en el mismo banco de pruebas.

## Documentación

| Documento | Contenido |
|---|---|
| [Plan maestro](docs/01-plan-maestro.md) | Alcance, fases, iteraciones, entregables, criterios de salida y próximos pasos |
| [Arquitectura](docs/02-arquitectura.md) | Componentes, stack propuesto, PDF/AutoCAD, MCP, SolidWorks, proveedores y seguridad |
| [Contrato CAD y APIs](docs/03-contrato-cad-y-apis.md) | `CadSpec`, invariantes, herramientas MCP, estados, errores y trazabilidad |
| [Calidad y evaluación](docs/04-calidad-y-evaluacion.md) | Dataset dorado, comprobación dimensional, pruebas, métricas y promoción de modelos |
| [Guía de colaboración](docs/05-guia-de-colaboracion.md) | Cómo continuar desde otras herramientas, ADR, incidencias, inventario y convenciones |

## Orden recomendado de lectura

1. Plan maestro para decidir el alcance de la iteración actual.
2. Arquitectura para entender los límites entre módulos.
3. Contrato CAD antes de modificar modelos, prompts o conectores.
4. Calidad antes de aceptar una pieza o promover un modelo.
5. Guía de colaboración al retomar el proyecto desde Kimi Code, OpenCode u otra herramienta.

## Inventario inicial aportado

La captura suministrada menciona estos activos; su existencia, licencia, formato y rendimiento deben comprobarse en la iteración 0:

| Línea | Configuración/artefacto indicado | Estado indicado en la captura |
|---|---|---|
| `MiMo-V2.6-Distill-Qwen-9B` | `configs/soup_mimo9b.yaml`, `output/lumocad_mimo9b` | Entrenado; pérdida final indicada: 0.0266 |
| `Qwen2.5-Coder-3B-Instruct` | `configs/soup_qwen3b.yaml`, `output/lumocad_qwen3b` | Base listo para entrenar |

Estas líneas parecen orientadas a lenguaje/código. **No se presupone que resuelvan visión.** La lectura de planos e imágenes requerirá un modelo multimodal o una combinación de extracción determinista, OCR y visión.

## Primera iteración

La iteración 0 no construye piezas: registra versiones y licencias reales, selecciona un corpus representativo, define las familias iniciales y captura el proceso manual actual como referencia. Los criterios concretos están en el [plan maestro](docs/01-plan-maestro.md).

## Desarrollo del núcleo

```bash
python -m venv .venv
# Windows Git Bash: source .venv/Scripts/activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
autosolid-schema > cadspec.schema.json
```

El esquema generado es un artefacto local; no debe confundirse con una pieza CAD ni con una validación de SolidWorks.

## API local de proyectos

```bash
autosolid-api
# http://127.0.0.1:8000/api/v1/health
# Documentación interactiva: http://127.0.0.1:8000/docs
```

La API crea proyectos, valida especificaciones, guarda revisiones inmutables, almacena fuentes content-addressed y registra aprobaciones de diseño en `.autosolid/`. Usar `AUTOSOLID_DATA_DIR` para otro directorio local. No exponer el servicio a Internet; todavía no incorpora autenticación remota ni construcción CAD.

Endpoints de fuentes bajo `/api/v1`:

- `POST /projects/{project_id}/sources?filename=...` con el archivo como cuerpo binario.
- `GET /projects/{project_id}/sources`.
- `GET /projects/{project_id}/sources/{source_id}`.
- `GET /projects/{project_id}/sources/{source_id}/content` como descarga verificada.

Endpoints de aprobaciones de diseño bajo `/api/v1`:

- `POST /projects/{project_id}/approvals` con `revision`, `sha256`, `scope: "design"`, `approved_by` y `note` opcional.
- `GET /projects/{project_id}/approvals`.
- `GET /projects/{project_id}/approvals/{approval_id}`.

## Interfaz local de revisión

El mismo proceso de la API sirve una interfaz web mínima en `http://127.0.0.1:8000/`:

```bash
autosolid-api
```

La interfaz usa únicamente `/api/v1` y el mismo `ProjectService` que MCP; no requiere Node, bundler, CDN ni conexión a Internet. Permite crear/listar/seleccionar proyectos, cargar la revisión actual o una plantilla, editar el `CadSpec` como JSON, validarlo sin persistir, guardarlo con `expected_revision`, ver conflictos de revisión, consultar diagnósticos y preguntas abiertas, y revisar el JSON, la revisión y el hash SHA-256. También permite cargar fuentes del proyecto, listarlas, descargarlas y añadir su referencia al editor mediante una acción explícita. El panel de aprobación exige revisor, confirmación y la revisión y hash cargados; se deshabilita si hay cambios sin guardar o si la revisión no es la actual, y muestra el historial con estado vigente u obsoleto.

Los recursos estáticos se sirven desde `src/autosolid/api/static/` con CSP restrictiva, `nosniff`, `frame-ancestors 'none'`, `no-referrer` y `Cache-Control: no-store` para el documento. El servidor escucha en loopback por defecto. La interfaz no interpreta las fuentes, no ejecuta proveedores, trabajos ni CAD. Una aprobación de diseño no construye ni verifica SolidWorks. Informe de verificación local: [`docs/tasks/008-informe.md`](docs/tasks/008-informe.md).

## Fuentes y artefactos

La tarea 006 añadió un almacén inmutable y content-addressed para las fuentes del proyecto:

- Se aceptan PDF, PNG/JPEG/WebP y texto UTF-8 (`.txt`, `.md`, `.csv`, `.json`) hasta 20 MiB.
- Se comprueban extensión, firma de archivo, codificación y nombre; no se valida la estructura interna del documento.
- El contenido se guarda una sola vez por SHA-256 en `AUTOSOLID_DATA_DIR/artifacts/`; la base SQLite v4 conserva los metadatos y la asociación al proyecto.
- Subir el mismo contenido al mismo proyecto es idempotente; en otro proyecto comparte blob pero recibe otro identificador de fuente.
- Las fuentes no se pueden editar ni borrar desde la API. Añadir una fuente no modifica ni aprueba la revisión `CadSpec`.
- La descarga se sirve como adjunto, con `ETag`, hash y `nosniff`, sin exponer rutas internas.

Esto es almacenamiento, no ingesta interpretada: no hay extracción de texto, vectores, páginas, cotas, escala ni geometría. Informe local: [`docs/tasks/006-informe.md`](docs/tasks/006-informe.md).

## Aprobaciones de diseño

La tarea 008 añadió una aprobación humana explícita, inmutable y append-only, vinculada al proyecto, la revisión vigente y su SHA-256:

- Aprobar exige que la revisión indicada sea la actual y que el hash coincida con el almacenado; el servicio revalida el `CadSpec` guardado y bloquea la aprobación si produce diagnósticos de error.
- La creación es idempotente por `(proyecto, revisión, alcance)`: repetir la solicitud devuelve el registro existente sin reescribir autor ni nota.
- El estado se calcula como `valid` o `stale` contra la revisión vigente. Cambiar de revisión invalida automáticamente la aprobación anterior sin borrar ni mutar el historial.
- Los registros no se pueden editar ni borrar; no hay revocación, expiración, destino ni consumo único en esta tarea.
- La aprobación es de alcance `design` y **no autoriza construir**. La aprobación de construcción del ADR-003 sigue pendiente.
- MCP solo expone `autosolid_approval_list` y `autosolid_approval_get`; no existe herramienta para aprobar, revocar o consumir.

Informe local: [`docs/tasks/008-informe.md`](docs/tasks/008-informe.md).

## Servidor MCP local

```bash
autosolid-mcp
# equivalente: python -m autosolid.mcp
# usa AUTOSOLID_DATA_DIR o .autosolid/ por defecto
```

El servidor habla MCP `stdio`, reutiliza el mismo `ProjectService` y expone once herramientas: crear/listar/leer proyectos, leer/validar/guardar revisiones `CadSpec`, listar/leer metadatos o texto de fuentes y listar/leer aprobaciones de diseño. `autosolid_design_validate` no persiste; `autosolid_design_update` exige `expected_revision`. `autosolid_source_read_text` solo devuelve fuentes de tipo texto, truncadas a `max_chars`, y trata su contenido como dato no confiable. `autosolid_approval_list` y `autosolid_approval_get` son de solo lectura. No escribe logs en `stdout`.

- Ejemplo para OpenCode 1.19.4: [`examples/opencode-mcp.example.json`](examples/opencode-mcp.example.json).
- Ejemplo para OpenCode V2 (`mcp.servers`): [`examples/opencode-mcp-v2.example.json`](examples/opencode-mcp-v2.example.json).
- Informe de verificación local: [`docs/tasks/003-informe.md`](docs/tasks/003-informe.md).

La conexión se comprobó con `opencode mcp list` en OpenCode 1.19.4; no se ha auditado todavía una sesión de agente que invoque las herramientas.

## Proveedores de modelos

`autosolid.providers` define un contrato síncrono de completion independiente del dominio CAD:

- `SimulatedProvider`: cola determinista de respuestas y errores para pruebas, sin red ni reloj.
- `OpenAICompatibleProvider`: `POST` a `{base_url}/chat/completions` mediante `urllib.request`, sin dependencias HTTP adicionales.

```python
from autosolid.providers import (
    ChatMessage,
    CompletionRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)

config = OpenAICompatibleConfig.from_env()
provider = OpenAICompatibleProvider(config)
response = provider.complete(
    CompletionRequest(
        messages=[ChatMessage(role="user", content="Devuelve un objeto JSON.")],
        response_format="json_object",
    )
)
print(response.parsed_json)
```

Variables de entorno en [`examples/provider.env.example`](examples/provider.env.example). Límites de seguridad:

- HTTPS obligatorio; HTTP sin TLS solo en loopback salvo `AUTOSOLID_OPENAI_ALLOW_INSECURE_HTTP=true`.
- Redirecciones bloqueadas, proxies del sistema desactivados por defecto y límite de bytes de respuesta.
- `json_object` exige un objeto JSON completo; no se reparan cercas Markdown ni texto adicional.
- Errores con códigos estables que no incluyen claves, cuerpos crudos ni trazas.

La capa no está integrada todavía con MCP, la API, proyectos ni `CadSpec`, y no se ha probado contra un proveedor externo real. Informe local: [`docs/tasks/004-informe.md`](docs/tasks/004-informe.md).

## Privacidad y seguridad

Los archivos `.env`, `*.local.yaml`, sesiones de agentes, entornos virtuales, pesos, planos y artefactos CAD están excluidos de Git. Copiar `environment.example.yaml` como `environment.local.yaml` para la configuración real. Revisar [SECURITY.md](SECURITY.md) antes de publicar ejemplos o reportar una vulnerabilidad.

## Contribuir y licencia

Las instrucciones están en [CONTRIBUTING.md](CONTRIBUTING.md). El código se distribuye bajo la [licencia MIT](LICENSE), con atribución a `AUTOSOLID contributors`. SolidWorks y AutoCAD son productos de sus respectivos propietarios; este proyecto no está afiliado ni certificado por ellos.
