# Plan maestro por iteraciones

## Estado de ejecución

- Iteración 0 en curso: hardware y versiones principales registrados en `environment.local.yaml`; ADR-001/002/003 creados.
- El corpus, las rutas/licencias de pesos y la comprobación runtime de CAD siguen pendientes.
- Tarea 001 aceptada: núcleo `CadSpec` revisado, 56 pruebas y 11.000 casos geométricos adicionales superados; alcance limitado a líneas/extrusión/revolución.
- Tarea 002 aceptada: proyectos SQLite, revisiones inmutables y API FastAPI; 86 pruebas y flujo HTTP real superados.
- Ninguna iteración se considera completada todavía.

## 1. Resultado buscado

Construir un sistema que produzca piezas SolidWorks editables desde PDF, texto e imágenes, con dimensiones trazables, preguntas ante ambigüedad y verificación posterior. El primer objetivo es un flujo completo confiable para piezas sencillas; no cobertura universal ni entrenamiento de un modelo nuevo.

## 2. Alcance y prioridades

### P0: piloto útil

- Windows, una versión concreta de SolidWorks y una sesión local.
- PDF vectorial de una página con vistas ortogonales.
- Texto estructurado o libre con dimensiones completas.
- Extrusión y revolución de base; cortes sencillos cuando el contrato inicial esté estable.
- `CadSpec`, validación, revisión humana, SLDPRT nativo y reporte.
- Interfaz local, API y MCP para OpenCode.
- Un proveedor OpenAI-compatible y un runtime local.
- Corpus dorado y comparación de modelos sin entrenamiento.

### P1: ampliación

- PDF escaneado e imágenes con OCR/visión.
- AutoCAD como extractor alternativo y DXF común.
- Agujeros, chaflanes, redondeos, simetría y patrones.
- Procesamiento por lotes y comparación de variantes.
- Ajuste/LoRA/soup basado en correcciones aceptadas.

### P2: posterior

- Ensamblajes, chapa, superficies complejas, tolerancias GD&T completas y planos multipágina complejos.
- Segundo kernel CAD, despliegue multiusuario y cola distribuida.

### Fuera del compromiso inicial

- “Cualquier PDF a cualquier pieza” sin revisión.
- Precisión de fabricación certificada solo por IA.
- Inferir dimensiones ausentes a partir de píxeles.
- Automatizar SolidWorks mediante clics de pantalla.
- Reemplazar criterio de ingeniería, tolerancias o validación funcional.

## 3. Estrategia

La secuencia reduce el riesgo principal primero: **obtener una pieza correcta y verificable**, no generar texto plausible.

1. Capturar el proceso manual y construir referencias.
2. Probar el contrato `CadSpec` directamente contra SolidWorks con ejemplos ya correctos.
3. Añadir extracción e inferencia delante de ese contrato.
4. Medir errores y correcciones humanas.
5. Entrenar solamente si un cambio supera a la línea base sin degradar seguridad ni precisión.

Duración orientativa del piloto P0: **8–12 semanas** para una persona con experiencia, incluyendo revisión mecánica y pruebas en el equipo real. Es una estimación, no un compromiso; las versiones instaladas y la variedad del corpus pueden cambiarla.

## 4. Iteración 0 — Descubrimiento y contrato de prueba

**Duración orientativa:** 2–4 días.

### Trabajo

- Registrar Windows, CPU, GPU/VRAM/RAM, SolidWorks y versión de API; AutoCAD si se usará.
- Comprobar rutas, formato, licencias y capacidades de los dos pesos y LoRA indicados en el inventario.
- Localizar el repositorio `soup`, sus configuraciones y cómo reproduce entrenamiento/inferencia.
- Reunir 20–30 ejemplos representativos y permisos de uso: PDF vectoriales, escaneos, imágenes y piezas descritas por texto.
- Seleccionar 8–12 casos P0 sencillos con resultado SLDPRT o especificación manual comprobable.
- Grabar/documentar el flujo manual PDFATTACH/importar objeto/detach/escalar, incluyendo decisiones y fallos.
- Definir unidades, tipo de proyección, familias iniciales y convención de referencias.
- Crear ADR-001 (arquitectura), ADR-002 (contrato CAD) y ADR-003 (política de revisión).
- Clasificar datos por confidencialidad antes de permitir proveedores externos.

### Entregables

`environment.local.yaml`, inventario de modelos, corpus inicial, matriz de casos, ADR y backlog priorizado.

### Criterio de salida

- Los ejemplos P0 tienen cotas y resultados esperados independientes.
- Se sabe qué ruta de PDF es viable en el equipo y qué requiere AutoCAD.
- Las versiones/licencias relevantes están documentadas.
- No hay documentos confidenciales destinados a nube sin autorización.

## 5. Iteración 1 — Esqueleto, interfaz mínima y MCP

**Duración orientativa:** 3–5 días.

### Trabajo

- Crear monorepo y configuración reproducible.
- Implementar almacenamiento de proyectos, artefactos, revisiones y trabajos.
- Definir esquemas iniciales y errores; añadir un proveedor simulado para pruebas.
- Conectar un proveedor OpenAI-compatible real y verificar salida JSON estructurada.
- Crear interfaz con carga de fuente, estado, preguntas y visor JSON.
- Exponer operaciones de lectura/análisis por MCP `stdio`.
- Configurar OpenCode como cliente y usar el mismo servicio que la interfaz.
- Añadir logs redactados, cancelación y límites básicos.

### Entregables

Aplicación local vacía pero operativa, adaptador MCP y primer adaptador de modelo.

### Criterio de salida

- Un proyecto creado desde la interfaz se consulta desde OpenCode sin duplicar lógica.
- Entrada inválida del modelo es rechazada por esquema, no construida.
- Una caída del proveedor deja el proyecto recuperable.
- Ninguna credencial aparece en repositorio o logs.

## 6. Iteración 2 — PDF a evidencia y escala

**Duración orientativa:** 5–8 días, más 3–5 si AutoCAD entra en P0.

### Trabajo

- Extraer vectores/texto y generar renders alineados con las coordenadas de origen.
- Clasificar vectorial, escaneado o mixto por página.
- Detectar cajetín, vistas, cotas y textos; guardar bounding boxes.
- Asociar cotas a entidades y calcular escalas por vista.
- Implementar conflictos de escala, unidades y dibujo no a escala como bloqueos.
- Crear `DrawingSpec` y superposición visual para revisar la extracción.
- Añadir parser DXF común.
- Si se habilita AutoCAD: crear agente temporal para attach/import/detach/scale/export, con comandos reales probados y recuperación de sesión.

### Entregables

Extractor propio, DXF normalizado, evidencias navegables y, opcionalmente, conector AutoCAD.

### Criterio de salida

- Toda geometría extraída se superpone a su PDF sin desplazamientos en los casos P0.
- Las cotas de prueba se asocian correctamente y su escala independiente es consistente.
- Un PDF con escalas incompatibles queda bloqueado con evidencias comprensibles.
- Un escaneo nunca se etiqueta como vectorial de alta confianza.
- AutoCAD, si existe, produce el mismo `DrawingSpec` que el extractor propio.

## 7. Iteración 3 — Constructor SolidWorks y verificación

**Duración orientativa:** 5–8 días.

Esta fase usa `CadSpec` escritos manualmente y ya validados; todavía no depende de LLM.

### Trabajo

- Implementar agente C#, cola serializada y adaptador de la versión instalada.
- Construir planos, ejes, croquis y operaciones de extrusión/revolución.
- Mantener nombres/IDs estables para referencias y árbol de operaciones.
- Implementar cortes sencillos si las pruebas de base están verdes.
- Crear archivos nuevos, guardar SLDPRT y exportar STEP/previsualización.
- Leer estado de reconstrucción y medir bounding box, volumen, área y cotas de control.
- Crear mecanismo de limpieza segura tras fallos sin borrar documentos del usuario.
- Probar cancelación, timeout, SolidWorks cerrado/ocupado y reinicio del agente.

### Entregables

Constructor nativo, verificador y fixtures `CadSpec` para los casos base.

### Criterio de salida

- Los casos base generan SLDPRT que abre y reconstruye sin errores.
- El árbol contiene croquis y operaciones editables esperados.
- Todas las cotas de control están dentro de la tolerancia de modelado declarada.
- Volumen/bounding box coinciden con una referencia independiente cuando exista.
- Un fallo no sobrescribe archivos ni deja trabajos duplicados al reintentar.

## 8. Iteración 4 — Interpretación asistida por modelos

**Duración orientativa:** 5–8 días.

### Trabajo

- Diseñar prompts versionados con esquema estricto y salida mínima.
- Implementar propuesta de `CadSpec` desde texto y desde evidencias PDF.
- Añadir modelo multimodal para vistas/imágenes, separado de los LLM de código.
- Combinar reglas geométricas con hipótesis del modelo.
- Detectar candidatos de revolución/extrusión y explicar evidencias.
- Generar preguntas específicas para datos ausentes o contradicciones.
- Implementar reparación acotada de JSON y nunca reparación silenciosa de cotas.
- Registrar latencia/coste y ejecutar la primera comparación de modelos base/LoRA.

### Entregables

Orquestador de texto/PDF/imagen, enrutador de modelos y benchmark inicial.

### Criterio de salida

- Toda propuesta válida puede reconstruirse desde evidencias o entradas humanas.
- Ningún ejemplo con pregunta crítica se construye automáticamente.
- El modelo no puede introducir una operación fuera del esquema.
- Se publican resultados por caso y por modelo, incluidos fallos, sin afirmar precisión general.

## 9. Iteración 5 — Revisión visual y piloto de extremo a extremo

**Duración orientativa:** 5–8 días.

### Trabajo

- Completar interfaz de cuatro zonas: fuente, interpretación, diseño y resultado.
- Añadir edición de parámetros, supuestos y preguntas con historial.
- Resaltar en el PDF la evidencia de una cota/operación seleccionada.
- Mostrar previsualización 3D y comparación de siluetas/vistas.
- Implementar aprobación ligada al hash de revisión.
- Ejecutar el piloto con casos no usados durante desarrollo.
- Medir tiempo ahorrado frente al proceso manual y ediciones necesarias.
- Redactar guía de uso, límites y recuperación de errores.

### Entregables

Piloto P0, flujo aprobación → SLDPRT → verificación y guía de usuario.

### Criterio de salida

- PDF/texto → revisión → aprobación → SLDPRT → reporte funciona sin intervención del desarrollador en los casos P0.
- Toda salida aceptada pasa las reglas de [calidad](04-calidad-y-evaluacion.md).
- Una modificación humana invalida la aprobación anterior.
- El usuario puede identificar el origen de cada dimensión.
- Los casos fuera de alcance se rechazan de forma explícita y útil.

## 10. Iteración 6 — Más geometría y documentos difíciles

**Duración orientativa:** 1–2 semanas por familia, no todo a la vez.

Orden sugerido: agujeros/cortes → chaflanes/redondeos → simetría/patrones → escaneos → multipágina.

Para cada familia repetir un ciclo cerrado:

1. Ampliar contrato.
2. Añadir validador.
3. Añadir constructor.
4. Añadir interfaz.
5. Añadir casos dorados positivos y negativos.
6. Medir antes de habilitarla.

No se aumenta el alcance si las métricas P0 retroceden.

## 11. Iteración 7 — Entrenamiento, LoRA y soup

**Duración orientativa:** variable; cada experimento debe tener hipótesis y presupuesto.

### Trabajo

- Convertir correcciones aceptadas en ejemplos con entrada, evidencias, `CadSpec` y resultado verificado.
- Separar train/validación/test por familia o pieza para evitar fugas de variantes casi idénticas.
- Mantener intacto un test ciego y casos adversariales.
- Reproducir las líneas `MiMo-V2.6-Distill-Qwen-9B` y `Qwen2.5-Coder-3B-Instruct`; confirmar qué pesos/LoRA existen.
- Evaluar base y adaptadores antes de entrenar otros.
- Si el repositorio soup resulta adecuado, comparar recetas/merges de forma aislada.
- Promover solo una mejora consistente en exactitud de cotas, validez estructural, construcción y edición humana.
- Conservar rollback al modelo anterior y ficha de modelo/licencia.

### Criterio de salida

- La mejora supera a la línea base en validación y test ciego, no solo en pérdida de entrenamiento.
- No aumenta aprobaciones inseguras, alucinación de cotas ni fallos críticos.
- La inferencia cabe en el hardware objetivo o el coste de ejecución está aceptado.
- El modelo se cambia por configuración sin modificar el constructor CAD.

**Importante:** una pérdida final de 0.0266, por sí sola, no demuestra precisión mecánica ni capacidad de generalización.

## 12. Iteración 8 — Empaquetado y operación

### Trabajo

- Instalador/arranque reproducible en Windows y comprobación de dependencias.
- Actualización de esquema/migraciones, copias de seguridad y recuperación.
- Diagnóstico descargable sin secretos ni datos no autorizados.
- Política de privacidad por proyecto, gestión de claves y permisos de rutas.
- Pruebas de estabilidad prolongada, documentos grandes y reinicios.
- Plantilla de ficha de modelo y procedimiento de rollback.

### Criterio de salida

Una máquina limpia equivalente puede instalar, importar un proyecto de prueba, construirlo y recuperar los artefactos siguiendo solo la documentación.

## 13. Próximas acciones concretas

La primera sesión de implementación debe ejecutar únicamente iteración 0:

1. Localizar rutas de pesos, LoRA y repositorio soup.
2. Confirmar versiones de SolidWorks/AutoCAD y hardware.
3. Seleccionar los primeros 8–12 casos P0.
4. Documentar el proceso manual de escalado con dos cotas de comprobación.
5. Fijar las operaciones P0 y crear los tres ADR.
6. Preparar iteración 1 solo cuando los criterios de salida estén cumplidos.

## 14. Riesgos y respuesta

| Riesgo | Señal | Respuesta |
|---|---|---|
| Escala incorrecta | Cotas independientes no coinciden | Bloqueo, revisión por vista y nunca promediar silenciosamente |
| PDF sin vectores | Importación vacía o solo imagen | OCR/visión, mayor revisión y cotas obligatorias |
| Modelo inventa geometría | Valores sin evidencia | Esquema de procedencia, preguntas y rechazo |
| Revolución/extrusión ambigua | Varias interpretaciones válidas | Variantes y elección humana |
| API cambia entre versiones | Fallos Interop/rebuild | Versión fijada, adaptador y pruebas en equipo real |
| Entrenamiento sobreajusta | Buen loss, mal test ciego | Separación por familia y benchmark geométrico |
| Modelos grandes no caben | Swap/latencia alta | Cuantización evaluada, modelo menor o proveedor externo autorizado |
| Filtración de planos | Proveedor externo activo | Modo local, consentimiento y redacción de logs |
| Archivos dañados | Sobrescritura o sesión bloqueada | Documentos nuevos, idempotencia, backup y cola |

## 15. Definición global de éxito del piloto

- Ahorro de tiempo medido frente al flujo manual en las familias P0.
- SLDPRT editable, no solo STEP/malla.
- Cotas críticas verificadas y trazables.
- Cero construcciones automáticas con ambigüedades críticas.
- Fallos visibles y recuperables.
- Cambio de modelo sin reescribir el sistema.
- OpenCode e interfaz ejecutan el mismo flujo.
- Entrenamiento futuro basado en datos aceptados y pruebas ciegas.
