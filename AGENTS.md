# AUTOSOLID — instrucciones para agentes

## Fuente de verdad

Leer `README.md` y los documentos de `docs/` antes de cambiar código. La arquitectura y los contratos aprobados no se sustituyen por decisiones implícitas de un modelo.

## Reglas de dominio

- `CadSpec` separa interpretación de construcción. No llamar a SolidWorks desde proveedores, parsers o MCP.
- Las cotas impresas y los datos humanos tienen prioridad sobre píxeles o inferencias.
- No inventar dimensiones. Las preguntas críticas abiertas bloquean construcción.
- Usar valores decimales en el contrato, unidades canónicas mm/deg y procedencia de evidencias.
- Los cambios de revisión invalidan aprobaciones anteriores.
- No sobrescribir archivos CAD originales.

## Forma de trabajo

- Mantener cambios acotados a la tarea asignada.
- No inicializar Git, hacer commits ni modificar configuración global.
- No instalar dependencias globalmente ni agregar paquetes sin justificar su necesidad.
- No leer ni copiar secretos. Los ejemplos usan placeholders.
- Añadir pruebas positivas y negativas junto al código; el proyecto usa `pytest`.
- No afirmar que SolidWorks, AutoCAD, PDF o proveedores fueron verificados si no se ejecutaron realmente.
- Actualizar documentación que quede desactualizada, sin cambiar el estado de una iteración salvo evidencia completa.

## Alcance por tarea

Cada tarea delegada debe tener un archivo numerado en `docs/tasks/` con alcance, exclusiones y verificación. El núcleo aceptado cubre perfiles de líneas, extrusión y revolución. No ampliar ese alcance ni modificar su contrato sin una tarea explícita y casos de compatibilidad.

Los agentes no hacen commits ni publican cambios. La integración y publicación requieren revisión y pruebas independientes.
