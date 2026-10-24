# Tarea 001 — Núcleo `CadSpec` y validación

## Contexto

AUTOSOLID está en fase inicial. Leer `AGENTS.md`, `README.md`, `docs/02-arquitectura.md`, `docs/03-contrato-cad-y-apis.md` y `docs/04-calidad-y-evaluacion.md`. Esta tarea implementa una base de dominio, no una pieza completa ni integración externa.

## Objetivo

Crear un paquete Python con modelos Pydantic estrictos, validación determinista y pruebas para perfiles formados únicamente por líneas, extrusión de base y revolución de base.

## Alcance obligatorio

1. Crear `pyproject.toml` con proyecto `autosolid`, Python `>=3.11,<3.15`, Pydantic 2 y dependencia de desarrollo `pytest`. Usar distribución `src/` y configuración de pytest.
2. Implementar bajo `src/autosolid/cad/`:
   - modelos inmutables con `extra="forbid"` y versión de esquema;
   - fuentes, evidencias, parámetros con `Decimal`, procedencia y tolerancia básica;
   - preguntas/supuestos con severidad;
   - referencias de plano/eje;
   - croquis de líneas con puntos 2D, restricciones y dimensiones compatibles con el documento conceptual;
   - operaciones `extrude` y `revolve` de nueva base;
   - diagnósticos serializables con código, severidad, ruta y mensaje;
   - validación estructural de referencias y validación geométrica de líneas.
3. Validar al menos:
   - IDs únicos y referencias existentes;
   - números finitos, parámetros positivos cuando corresponda y unidades admitidas;
   - preguntas críticas abiertas como bloqueo;
   - segmentos de longitud no nula;
   - un único bucle cerrado, conectado, sin extremos sueltos;
   - auto-intersecciones de segmentos, ignorando la unión entre segmentos adyacentes;
   - distancia de extrusión positiva;
   - eje no nulo y ángulo de revolución en `(0, 360]`;
   - perfil que cruza el eje de revolución como error;
   - dimensiones que referencien parámetros existentes.
4. Exponer una API clara `validate_spec(spec) -> list[Diagnostic]`; no lanzar excepciones para errores geométricos esperados.
5. Añadir `tests/` con builders/fixtures propios y casos positivos/negativos para cada regla. Probar también serialización JSON con decimales preservados y rechazo de campos desconocidos.
6. Añadir exportación del JSON Schema mediante una función o comando pequeño, sin generar archivos grandes en el repositorio.

## Fuera de alcance

- Arcos, cortes, agujeros, tolerancias GD&T y operaciones de ensamblaje.
- PDF/OCR/DXF/visión.
- FastAPI, MCP, interfaz, SolidWorks, AutoCAD y llamadas a modelos.
- Resolución de expresiones matemáticas generales: si una expresión no se puede validar de forma segura, emitir diagnóstico explícito de no soportada, no usar `eval`.

## Restricciones

- No modificar los documentos de arquitectura/plan para declarar el trabajo completado.
- No instalar paquetes globalmente, no inicializar Git y no tocar archivos fuera del workspace.
- No introducir otras dependencias de runtime.
- No usar `eval`, `exec` ni suprimir errores con `except Exception: pass`.

## Verificación solicitada

Si existe `pyproject.toml`, usar un entorno virtual local si hace falta y ejecutar `pytest`. Informar archivos creados, pruebas ejecutadas y limitaciones reales. No afirmar integración CAD ni precisión mecánica.
