# Arquitectura propuesta

## 1. Visión

AUTOSOLID será una aplicación local para Windows con cuatro puntos de entrada: interfaz de revisión, API local, MCP y automatización por lotes. Todos ejecutan el mismo caso de uso y comparten proyectos, artefactos y validaciones.

```mermaid
flowchart LR
    UI[Interfaz local React] --> APP[Servicio de aplicación FastAPI]
    OC[OpenCode / otro cliente MCP] --> MCP[Adaptador MCP]
    API[CLI / lotes] --> APP
    MCP --> APP

    PDF[PDF] --> INGEST[Ingesta y evidencias]
    IMG[Imágenes] --> INGEST
    TXT[Texto] --> APP
    INGEST --> APP

    APP --> ROUTER[Enrutador de modelos]
    ROUTER --> LOCAL[Pesos locales / LoRA]
    ROUTER --> OAI[Servidores OpenAI-compatibles]
    ROUTER --> CLOUD[Proveedores con API key]
    ROUTER --> VLM[Modelos multimodales]

    APP --> SPEC[CadSpec + validadores]
    SPEC --> REVIEW[Revisión y aprobación]
    REVIEW --> AGENT[Agente local SolidWorks]
    AGENT --> SW[SolidWorks: SLDPRT nativo]

    INGEST --> ACAD[Adaptador opcional AutoCAD]
    ACAD --> DXF[DXF normalizado]
    DXF --> SPEC

    APP --> STORE[(SQLite + artefactos)]
    SW --> VERIFY[Verificación y reporte]
    VERIFY --> STORE
```

## 2. Límites de responsabilidad

### Interfaz local

React + TypeScript, empaquetada inicialmente como aplicación web local servida por el backend. No se añade Electron/Tauri hasta que exista una necesidad demostrada.

La vista principal tendrá cuatro zonas:

1. **Fuente:** PDF/imagen con zoom, páginas, vistas y resaltado de evidencias.
2. **Interpretación:** vistas detectadas, escala, cotas, supuestos e incógnitas.
3. **Diseño:** árbol de operaciones y editor de parámetros/croquis.
4. **Resultado:** previsualización 3D, comparación con las vistas y reporte de validación.

La acción `Construir en SolidWorks` permanece deshabilitada si existen errores o ambigüedades críticas. Toda corrección humana se guarda como un nuevo evento, sin sobrescribir la evidencia original.

### Servicio de aplicación

Python y FastAPI, con modelos Pydantic para los contratos. Orquesta trabajos, versiones, proveedores, validación y aprobaciones. El dominio CAD no depende de FastAPI ni del SDK de MCP para poder probarlo de forma aislada.

SQLite conserva proyectos, estados, configuraciones no secretas y metadatos. Los PDF, imágenes, JSON, DXF, STEP, reportes y SLDPRT se guardan como artefactos content-addressed o con identificadores inmutables.

### Adaptador MCP

Servidor MCP local, preferiblemente `stdio` para OpenCode. Expone herramientas pequeñas y con esquemas estrictos; no duplica reglas del dominio.

MCP se elige porque es una interfaz estándar para clientes compatibles y OpenCode admite servidores locales y remotos. No sustituye la interfaz gráfica ni el servicio de aplicación.

### Agente SolidWorks

Proceso Windows aislado en C#, usando la API COM oficial de SolidWorks/Interop. Se comunica con el backend mediante un canal local autenticado y una cola de trabajos.

- Serializa las operaciones sobre una sesión de SolidWorks.
- Crea documentos nuevos por defecto; nunca sobrescribe el original sin autorización.
- Construye croquis, referencias y operaciones nativas editables.
- Captura errores de API, advertencias de reconstrucción y estado del árbol.
- Exporta reportes y artefactos de comprobación.
- Usa una versión de .NET y de Interop fijada tras probar la versión real de SolidWorks en la iteración 0.

El agente no contiene prompts ni llama a modelos. Recibe un `CadSpec` validado y una aprobación.

### Enrutador de modelos

Contrato único para completar texto, emitir JSON estructurado y analizar imágenes. Cada capacidad se configura por separado: `planner`, `vision`, `ocr_assist` y `repair`.

Adaptadores previstos:

- API OpenAI-compatible configurable (`base_url`, nombre de modelo y credencial).
- Proveedor nativo cuando sus funciones sean necesarias.
- Runtime local compatible con los pesos disponibles; la elección entre llama.cpp, vLLM, Transformers u otro depende del formato real y del hardware.
- Modelo multimodal independiente si las líneas de lenguaje no aceptan imágenes.

Cada respuesta registra proveedor, modelo, revisión/adaptador, parámetros, plantilla de prompt, tokens, latencia y hash de la entrada. No se guardan secretos en el historial.

**OpenCode:** cuando sea el cliente MCP, su propio modelo —incluido uno gratuito disponible allí— puede llamar a las herramientas AUTOSOLID. Esto no implica que esos modelos sean reutilizables como API dentro de la interfaz; para eso se necesita un proveedor directo o local.

## 3. Pipeline de PDF

### Ruta A: extracción propia, preferente para PDF vectorial

1. Calcular hash y conservar el original.
2. Detectar páginas, texto embebido, imágenes y operadores vectoriales.
3. Extraer líneas, curvas, arcos aproximables, textos y transformaciones con PyMuPDF u otra biblioteca validada.
4. Rasterizar una copia únicamente para visualización, OCR o contexto del modelo de visión.
5. Normalizar coordenadas, unidades de página y transformaciones.
6. Segmentar vistas, cotas, símbolos, cajetín y notas.
7. Asociar textos de cota con sus líneas de extensión y geometría.
8. Calcular escala por vista a partir de cotas conocidas.
9. Producir `DrawingSpec`, evidencias y una lista de ambigüedades.
10. Inferir operaciones candidatas y convertirlas a `CadSpec` mediante reglas + modelo.

La vectorización de un escaneo es una ruta distinta: segmentación/OCR/OpenCV y ajuste geométrico. No se presenta como equivalente al PDF vectorial y exige más revisión.

### Ruta B: AutoCAD como extractor opcional

Automatizar con .NET/COM o la API admitida por la versión instalada, evitando clics y coordenadas de pantalla.

1. Abrir un DWG temporal aislado.
2. Ejecutar `PDFATTACH` para la página indicada.
3. Ejecutar `PDFIMPORT` seleccionando el subrayado/objeto y opciones de importación documentadas.
4. Ejecutar `PDFDETACH` después de obtener geometría editable.
5. Explorar entidades, capas, textos y bloques; no confiar solo en una captura.
6. Escalar con `SCALE` por referencia o matriz calculada.
7. Validar al menos una segunda cota independiente.
8. Exportar DXF/DWG y convertir al `DrawingSpec` común.

El nombre exacto de comandos, opciones y automatización se comprobará contra la versión instalada. AutoCAD no será obligatorio si la ruta propia alcanza las mismas pruebas.

### Regla de escala

Para cada vista, con cotas `d_i` y longitudes geométricas `l_i`, calcular `s_i = d_i / l_i` después de transformar a una unidad común. Una sola cota produce una escala provisional. Dos o más cotas independientes deben ser consistentes dentro de una tolerancia establecida por el tipo de documento.

- Escalas incompatibles: bloquear y mostrar las evidencias.
- Escalas distintas por vista: permitirlas solo si están declaradas/verificadas por separado.
- Dibujo no a escala: usar cotas y reconstruir restricciones; no deformar el dibujo hasta que “parezca” correcto.
- Sin cotas suficientes: conservar dimensiones desconocidas; no inventarlas desde píxeles.

## 4. Interpretación mecánica

La intención se representa como operaciones, no como malla. El subconjunto inicial será:

- croquis cerrados con líneas y arcos;
- extrusión de base y corte;
- revolución de base y corte;
- eje, plano y referencias explícitos;
- agujeros simples y cotas básicas.

Después: roscas, chaflanes, redondeos, simetrías, patrones, piezas de chapa y ensamblajes, cada uno con dataset y validadores propios.

Para revolución se combinan evidencias: eje indicado, perfil y radios, vistas circulares, cotas de diámetro, secciones y contexto. El modelo puede proponer `revolve`, pero el validador exige eje y perfil válidos. Una pieza ambigua queda pendiente de elección humana.

## 5. Flujo y estados

```mermaid
stateDiagram-v2
    [*] --> INGESTED
    INGESTED --> ANALYZING
    ANALYZING --> NEEDS_INPUT: faltan datos críticos
    NEEDS_INPUT --> ANALYZING: usuario aporta correcciones
    ANALYZING --> SPEC_READY: especificación válida
    SPEC_READY --> APPROVED: aprobación explícita
    APPROVED --> BUILDING
    BUILDING --> VERIFYING
    VERIFYING --> COMPLETED: pruebas superadas
    VERIFYING --> FAILED_VALIDATION: diferencias o errores
    BUILDING --> FAILED_BUILD: error de SolidWorks
    FAILED_VALIDATION --> ANALYZING: nueva revisión
    FAILED_BUILD --> ANALYZING: nueva revisión
```

Las transiciones se registran. Reintentar un trabajo utiliza una clave de idempotencia para no duplicar archivos.

## 6. Estructura futura del repositorio

No se creará código hasta aprobar la iteración correspondiente.

```text
autosolid/
  apps/
    web/                  # React/TypeScript
  services/
    api/                  # FastAPI y casos de uso
    mcp/                  # fachada MCP
    solidworks-agent/     # C# / Interop
    autocad-agent/        # adaptador opcional
  packages/
    cad-schema/           # contratos versionados
    geometry/             # validadores deterministas
    document-ingest/      # PDF, imagen, OCR, DXF
    model-providers/      # adaptadores y enrutamiento
  tests/
    golden/               # corpus y resultados esperados
    fixtures/
  docs/
    adr/
```

Los límites de paquetes pueden simplificarse al inicio; lo importante es que el esquema y los validadores no dependan de un proveedor.

## 7. Seguridad, privacidad y robustez

- API keys en variables de entorno o Windows Credential Manager; nunca en JSON de proyecto, prompts, logs o Git.
- Servicios enlazados a loopback, con token local y lista de rutas permitidas.
- PDF e imágenes tratados como datos no confiables; su texto nunca se interpreta como instrucciones del sistema.
- Aprobación explícita para construir, exportar, sobrescribir o enviar documentos a un proveedor externo.
- Modo local para planos confidenciales y aviso visible antes de usar nube.
- Límites de tamaño/páginas, cancelación de trabajos, timeouts y cuarentena de documentos problemáticos.
- Backups y nombres únicos; SolidWorks y AutoCAD no operan sobre el único original.
- Licencias de modelos, pesos, LoRA, datos de entrenamiento y bibliotecas registradas antes de distribuir.

## 8. Extensibilidad

Una nueva pieza se habilita agregando: esquema de operación, constructor SolidWorks, validador, casos dorados y estrategia de interfaz. Un nuevo modelo solo agrega configuración/adaptador y supera el mismo benchmark.

Un segundo kernel —por ejemplo OpenCASCADE para previsualización/verificación o FreeCAD como salida— debe implementar el mismo contrato. No se añadirá al MVP salvo que acelere una validación concreta.

## 9. Referencias oficiales de partida

- SolidWorks API: https://help.solidworks.com/2024/english/api/sldworksapiprogguide/Welcome.htm
- Autodesk AutoCAD Help: https://help.autodesk.com/view/ACD/2024/ENU/
- Model Context Protocol: https://modelcontextprotocol.io/
- Seguridad MCP: https://modelcontextprotocol.io/specification/draft/basic/security_best_practices
- OpenCode MCP: https://opencode.ai/docs/mcp-servers/
- OpenCode proveedores: https://opencode.ai/docs/providers/

Las versiones concretas se fijarán durante la iteración 0; los enlaces no sustituyen una prueba de compatibilidad en el equipo objetivo.
