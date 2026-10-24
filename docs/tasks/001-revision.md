# Revisión de la tarea 001

## Delegación

- Cliente: OpenCode CLI 1.19.4 mediante `npx`.
- Modelo: `opencode/deepseek-v4.1-flash-free`.
- Alcance: contrato `CadSpec`, validadores y pruebas para líneas/extrusión/revolución.
- Coste reportado por OpenCode en las llamadas iniciales: 0.
- La generación se realizó en el workspace; la aceptación depende de revisión independiente.

## Primera auditoría

Entorno independiente: Python 3.12, instalación editable sin dependencias y `pytest` desde `.audit-venv`.

Resultado inicial: **46 pruebas superadas**. Este resultado no fue suficiente para aceptar el código.

Se añadieron cuatro pruebas en `tests/test_audit_regressions.py` que fallaron y demostraron:

1. Una unión angular válida podía marcarse como `SKETCH_SELF_INTERSECTION` porque la comprobación colineal solo evaluaba un extremo del segundo segmento.
2. Una dimensión podía discrepar del parámetro referenciado sin emitir diagnóstico.
3. Un supuesto crítico no aceptado no bloqueaba la especificación.
4. Un plano con ejes no unitarios se aceptaba aunque la proyección 2D depende de una base ortonormal.

Resultado de las regresiones antes de corregir: **4 fallos de 4**.

## Segunda delegación

Se devolvieron los cuatro hallazgos a la misma sesión de DeepSeek, manteniendo las pruebas y exigiendo `pytest` completo. Las correcciones se revisarán antes del primer commit.

## Puerta de publicación

- Todas las pruebas deben pasar en el entorno independiente.
- Los archivos generados deben revisarse después de la última corrección.
- `git diff --cached --check` debe pasar.
- La lista staged debe excluir sesiones, entornos, inventario local, pesos y CAD.
- El escaneo textual de rutas personales y secretos debe quedar sin hallazgos.
- La creación pública en GitHub requiere autenticación de GitHub CLI sin exponer credenciales.

## Resultado final

**Núcleo aceptado dentro de su alcance limitado.**

- `pytest`: **56 pruebas superadas** en el entorno independiente.
- Comprobación adicional: **11.000 casos geométricos aleatorios superados**.
- Exportación de JSON Schema verificada.
- Wheel construido; contiene el paquete y `LICENSE` en `.dist-info/licenses/`.
- Las cuatro regresiones de auditoría pasan sin haber sido eliminadas ni relajadas.
- No se verificó PDF, MCP, interfaz, AutoCAD ni SolidWorks; sigue siendo núcleo de dominio, no una solución CAD de extremo a extremo.

La primera comprobación de la ruta de licencia en el wheel esperaba `.dist-info/LICENSE`; el paquete usa `.dist-info/licenses/LICENSE`. Se corrigió la comprobación, no el contenido del wheel.
