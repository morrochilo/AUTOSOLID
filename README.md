# AUTOSOLID

Sistema local asistido por IA para convertir planos PDF, texto e imágenes en piezas mecánicas paramétricas de SolidWorks, con revisión humana y trazabilidad geométrica.

## Estado

**Fase actual: desarrollo inicial.** Existe un núcleo `CadSpec` en auditoría con perfiles de líneas, extrusión, revolución y pruebas. PDF, MCP, interfaz y construcción en SolidWorks/AutoCAD todavía no están implementados ni verificados. No se afirma precisión mecánica de extremo a extremo.

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

## Privacidad y seguridad

Los archivos `.env`, `*.local.yaml`, sesiones de agentes, entornos virtuales, pesos, planos y artefactos CAD están excluidos de Git. Copiar `environment.example.yaml` como `environment.local.yaml` para la configuración real. Revisar [SECURITY.md](SECURITY.md) antes de publicar ejemplos o reportar una vulnerabilidad.

## Contribuir y licencia

Las instrucciones están en [CONTRIBUTING.md](CONTRIBUTING.md). El código se distribuye bajo la [licencia MIT](LICENSE), con atribución a `AUTOSOLID contributors`. SolidWorks y AutoCAD son productos de sus respectivos propietarios; este proyecto no está afiliado ni certificado por ellos.
