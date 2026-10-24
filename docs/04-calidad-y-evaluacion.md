# Calidad, precisión y evaluación

## 1. Principio de aceptación

Una pieza no se considera correcta porque “se ve bien”, porque el modelo devuelve JSON válido ni porque SolidWorks la abre. Debe superar validaciones geométricas independientes y conservar trazabilidad a las cotas de entrada.

El sistema distingue:

- **exactitud de especificación:** si `CadSpec` representa la intención;
- **éxito de construcción:** si SolidWorks genera el árbol esperado;
- **exactitud geométrica:** si el sólido cumple las referencias;
- **utilidad:** si reduce trabajo manual sin aumentar correcciones riesgosas.

## 2. Corpus dorado

Cada caso contiene:

```text
cases/<family>/<case_id>/
  source.pdf | source.png | prompt.txt
  expected.cadspec.json
  expected.measurements.json
  reference.sldprt | reference.step    # cuando exista
  review.yaml
  LICENSE / provenance.yaml
```

`review.yaml` declara familia, operaciones, dificultad, unidades, tolerancias, preguntas esperadas, datos ausentes y si el caso pertenece a train, validación o test.

### Cobertura mínima

- Extrusión rectangular y con arcos.
- Revolución de 360° con diámetros y longitudes.
- Cortes simples cuando se habiliten.
- Unidades mm/pulgadas y conversiones.
- Vistas con escala uniforme, escalas diferentes y dibujo no a escala.
- PDF vectorial, mixto y escaneado clasificado correctamente.
- Símbolos de diámetro/radio, líneas ocultas y secciones según alcance.
- Entradas incompletas, contradictorias y fuera de alcance.
- Texto con sinónimos, orden distinto y requisitos redundantes.
- Imágenes con perspectiva que no deben tratarse como vistas acotadas exactas.

### Separación de datos

El test se divide por pieza/familia, no por página o variante, para impedir que casi duplicados aparezcan en entrenamiento y prueba. El test ciego no se usa para elegir prompts, umbrales ni recetas soup.

## 3. Referencias independientes

Según el caso, usar al menos una referencia que no comparta el mismo error de inferencia:

- cálculo analítico de volumen/área/bounding box;
- `CadSpec` y medidas revisadas por una persona;
- SLDPRT de referencia construido manualmente;
- mediciones de SolidWorks sobre el resultado;
- segundo kernel para comparación puntual, sin asumir que sea infalible.

Una superposición de imágenes ayuda a localizar errores, pero no prueba por sí sola profundidad, tolerancias o geometría oculta.

## 4. Pruebas por capa

### Ingesta

- Hash y página correctos.
- Clasificación vectorial/raster/mixta.
- Superposición de vectores y textos con coordenadas originales.
- OCR comparado con texto conocido cuando aplique.
- Escala por cota y consistencia entre cotas.

### `CadSpec`

- Validación de esquema y referencias.
- Round-trip JSON sin pérdida de valores/procedencia.
- Croquis cerrados, no auto-intersectados y restricciones consistentes.
- Dimensiones nominales, tolerancias y unidades preservadas.
- Casos negativos que deben fallar con código específico.

### SolidWorks

- Documento nuevo y ruta esperada.
- Reconstrucción sin errores; advertencias revisadas.
- Tipos, orden y nombres del árbol esperados.
- Croquis totalmente definidos cuando el perfil P0 lo exija.
- Medidas de control dentro de tolerancia de modelado.
- Volumen, área, centro de masa y bounding box cuando haya referencia.
- Reapertura del archivo en un proceso limpio.

### Extremo a extremo

- PDF/texto/imagen → propuesta → preguntas → corrección → aprobación → construcción → reporte.
- Rechazo de falta de cotas, conflicto de escala y operación no soportada.
- Cambio de revisión después de aprobar invalida el permiso.
- Timeout/cancelación/reintento sin duplicados.
- Proveedor caído y SolidWorks ocupado con recuperación documentada.

## 5. Tolerancias

Hay tres conceptos diferentes que no deben mezclarse:

1. **Tolerancia de fabricación:** pertenece a la pieza y se conserva en el diseño.
2. **Tolerancia de modelado CAD:** pequeña diferencia numérica permitida por kernel/API.
3. **Tolerancia de lectura:** incertidumbre de OCR/vectorización/escala; nunca se oculta convirtiéndola en tolerancia de fabricación.

Los umbrales concretos se fijan en iteración 0/3 según unidades, tamaño de pieza y versión de SolidWorks. Las cotas nominales extraídas deben coincidir exactamente como valores decimales normalizados; las mediciones del kernel usan la tolerancia de modelado aprobada.

No se usará una tolerancia geométrica amplia para hacer pasar una interpretación incorrecta.

## 6. Métricas

### Por caso

- `schema_valid`: salida válida sin reparación manual.
- `feature_exact`: operaciones y referencias equivalentes a lo esperado.
- `dimension_exact`: cotas nominales correctas.
- `critical_questions_recall`: ambigüedades críticas detectadas.
- `unsupported_rejection`: fuera de alcance correctamente rechazado.
- `build_success`: construcción y reapertura correctas.
- `geometry_pass`: verificación independiente superada.
- `human_edit_distance`: cantidad y tipo de correcciones.
- `review_time_seconds` y `total_time_seconds`.
- `latency`, `tokens`, `cost` y memoria cuando sea medible.

### Por conjunto

Reportar numerador/denominador y intervalos cuando el tamaño lo justifique. Separar resultados de:

- extracción determinista;
- modelo de lenguaje;
- visión/OCR;
- constructor;
- sistema completo.

No ocultar rechazos del denominador: informar cobertura automática y precisión por separado. Un sistema que rechaza casos difíciles puede ser seguro, pero no se presenta como si los hubiera resuelto.

## 7. Puertas de calidad del piloto

Para el conjunto P0 acordado:

- 100% de los casos aceptados automáticamente tienen `open_critical_questions = 0`.
- 100% de los SLDPRT entregados abren y reconstruyen sin errores.
- 100% de las cotas de control entregadas pasan la tolerancia aprobada.
- 0 archivos originales sobrescritos y 0 construcciones duplicadas en pruebas de reintento.
- Todos los fallos del banco tienen diagnóstico y clasificación.
- Cobertura, tasa de aceptación y correcciones humanas se publican junto con precisión.

No se fija de antemano un porcentaje de automatización que incentive aceptar piezas dudosas. La meta de eficiencia se decide tras la línea base.

## 8. Evaluación de modelos y soup

Todos los modelos reciben exactamente:

- mismas entradas y evidencias;
- mismo esquema y validadores;
- mismo presupuesto de reparación;
- temperatura/semillas documentadas cuando aplique;
- mismo test y umbrales de aceptación.

Comparar como mínimo:

1. modelo base local;
2. LoRA entrenado;
3. receta soup/merge si existe;
4. modelo de API elegido;
5. alternativa pequeña de menor coste.

La pérdida de entrenamiento es diagnóstica, no métrica de aceptación. La promoción exige mejorar exactitud/construcción o reducir coste manteniendo calidad, sin regresiones críticas. Guardar ficha con hash, licencia, datos, receta, hardware y resultados.

## 9. Datos de aprendizaje

Solo se usan ejemplos con derecho de uso. Una corrección humana se convierte en candidato de entrenamiento después de que la pieza pasa verificación; una respuesta del modelo no se convierte automáticamente en verdad.

Guardar:

- fuente y hash;
- propuesta original;
- ediciones humanas;
- `CadSpec` final;
- resultado de construcción/verificación;
- consentimiento/política de uso;
- división de dataset.

## 10. Reporte por entrega

Cada construcción genera un reporte legible con:

- archivo fuente, revisión y hashes;
- modelo(s), extractor y versiones;
- supuestos y preguntas resueltas por el usuario;
- cotas verificadas y tolerancias usadas;
- medidas del sólido y diferencias;
- advertencias y límites de la comprobación;
- aprobación y artefactos generados.

El reporte no certifica resistencia, fabricabilidad, normativa ni seguridad funcional salvo validaciones de ingeniería adicionales.
