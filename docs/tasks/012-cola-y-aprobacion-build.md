# Tarea 012 — Cola y aprobación de construcción SolidWorks

## Contexto

La tarea 011 verificó `src/solidworks-agent` con bloque y cilindro reales. Leer `docs/tasks/011-informe.md`, ADR-003 y los modelos actuales de proyectos/aprobaciones. Usar DeepSeek Go, pero mantener la regla: un modelo nunca aprueba ni construye por sí mismo.

## Objetivo

Conectar el servicio Python con el agente C# mediante una cola serial y una aprobación `build` explícita, de un solo uso, con destino y expiración.

## Alcance obligatorio

1. **Aprobación build separada de design:**
   - Alcance `build`, ligada a `project_id`, revisión actual, SHA-256 del `CadSpec` y hash canónico del destino.
   - `approved_by`, `created_at`, `expires_at`, `destination_hash`; destino dentro de un directorio de salida configurado por el servidor.
   - No permitir rutas absolutas/relativas que escapen del directorio ni archivos existentes.
   - Migración SQLite compatible hacia adelante y registros append-only.
2. **Consumo atómico:** marcar uso una sola vez en la misma transacción que encola el trabajo. Rechazar aprobación expirada, obsoleta, destino distinto, ya usada o revisión/hash incoherente. Mantener historial de consumo sin UPDATE de la aprobación original; usar tabla de trabajos/consumos.
3. **Runner C#:** `SolidWorksRunner` en Python, usando `subprocess` sin shell, ruta de ejecutable configurable, timeout y captura acotada de stdout/stderr JSON. No aceptar comandos del modelo. Validar salida `.sldprt` nueva dentro del directorio autorizado y resultado JSON `status=ok`, `rebuildSucceeded=true`, volumen finito y `volumeDifferenceM3` dentro de tolerancia.
4. **Trabajos:** estados `queued/running/completed/failed`, timestamps, idempotency key, proyecto/revisión/aprobación, destino, error estable y artefacto resultante. Una cola serial por proceso; reintentos sin duplicar archivo ni consumir aprobación otra vez.
5. **API:** endpoints para crear aprobación build, solicitar construcción y consultar trabajo/estado. No exponer construcción por MCP en esta tarea. Añadir consulta MCP de trabajos solo si no amplía riesgo; es opcional.
6. **Pruebas sin SolidWorks:** runner simulado/CLI auxiliar para éxito, JSON inválido, timeout, diferencia de volumen, destino escapado, aprobación expirada/usada, revisión obsoleta, reintento y concurrencia de dos consumidores. No simular que SolidWorks fue verificado.
7. **Smoke real si es viable:** usar el agente 011 con un `CadSpec` conocido y directorio temporal para comprobar un trabajo real. No cerrar SolidWorks ni tocar documentos del usuario. Si no se ejecuta, declararlo.
8. Actualizar documentación e informe con evidencia. No hacer commits ni publicar.

## Fuera de alcance

- PDF/OCR/DXF, proveedores, cortes/arcos, AutoCAD, UI de construcción y MCP build.
- Cambios en `CadSpec`, `SolidWorksBuilder` salvo corrección necesaria documentada.
- Aprobaciones automáticas por modelo, rutas arbitrarias, shell, servicios remotos o sobrescritura.

## Verificación

- Suite completa y pruebas de concurrencia/consumo.
- `dotnet build` sigue pasando.
- Un trabajo real si se ejecuta: estado `completed`, SLDPRT nuevo y JSON válido.
- Privacidad: no secretos, rutas personales ni binarios en cambios.
