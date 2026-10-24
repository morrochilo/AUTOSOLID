# Contribuir a AUTOSOLID

## Antes de empezar

Leer `README.md`, `AGENTS.md`, el plan maestro y los ADR relacionados. Elegir una capacidad acotada y documentar el criterio de aceptación. No mezclar en un mismo cambio esquema CAD, interfaz, proveedores y entrenamiento.

## Entorno

Copiar `environment.example.yaml` como `environment.local.yaml` y completar solo la copia local. No publicar inventario, rutas, claves, sesiones, planos ni archivos CAD privados.

Requisitos del núcleo actual: Python 3.11–3.14. Las integraciones SolidWorks/AutoCAD requieren Windows y sus licencias correspondientes, pero todavía no están implementadas.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows Git Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
pytest
```

## Reglas de contribución

- Mantener `CadSpec` independiente de proveedores y constructores.
- No inventar cotas ni ocultar preguntas críticas.
- Añadir pruebas positivas y negativas para cada regla.
- Usar fixtures sintéticos o con permiso explícito y documentar su procedencia/licencia.
- No agregar dependencias sin justificar necesidad, licencia y compatibilidad.
- No afirmar verificación de SolidWorks, AutoCAD o proveedores sin ejecutarla.
- Actualizar documentación y ADR cuando cambie una decisión.
- Revisar `git diff --cached` antes de cada commit.

## Definición de hecho

Un cambio está listo cuando sus pruebas pasan, los casos negativos están cubiertos, no contiene datos privados y la documentación describe el comportamiento actual. Las integraciones externas deben probarse de extremo a extremo o declarar claramente qué no se pudo verificar.

## Reportes

Usar issues públicos solo con datos sintéticos. Las vulnerabilidades se reportan privadamente siguiendo `SECURITY.md`.
