# Política de seguridad

## Estado del proyecto

AUTOSOLID está en desarrollo inicial. Todavía no existe una versión estable ni una integración CAD verificada. No debe utilizarse como única validación para piezas de fabricación o seguridad funcional.

## Reportar una vulnerabilidad

Usar **GitHub Security Advisories / Report a vulnerability** en el repositorio para un reporte privado. No abrir un issue público con detalles explotables, secretos, planos privados o datos personales.

Incluir el impacto, versiones afectadas, pasos de reproducción y una mitigación propuesta, usando siempre datos sintéticos. No enviar claves reales ni documentos CAD confidenciales.

## Datos que nunca deben publicarse

- API keys, tokens, contraseñas, cookies, certificados o claves privadas.
- Sesiones y bases de datos de OpenCode u otros agentes.
- Rutas locales, inventario real del equipo o configuración con información sensible.
- Planos, imágenes, piezas, DXF/DWG o pesos de modelos sin autorización explícita de publicación.
- Datos personales, correos privados o credenciales de proveedores.

Los archivos `*.local.yaml`, `.env`, `.opencode-runtime/`, pesos y artefactos CAD están excluidos por defecto. Antes de publicar un ejemplo, revisar también sus metadatos.

## Uso seguro

- Mantener servicios en loopback y no exponerlos directamente a Internet.
- No ejecutar macros o código generado por un modelo sin revisión.
- Exigir aprobación humana para construir o sobrescribir archivos.
- Usar documentos nuevos y copias de seguridad.
- Revisar dependencias y mantener GitHub secret scanning/push protection activados.

## Divulgación

Las actualizaciones y el estado de una corrección se coordinarán mediante la advisory privada de GitHub. No se promete un plazo de corrección mientras el proyecto esté en fase inicial.
