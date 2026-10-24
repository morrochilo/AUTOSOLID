# ADR-001: Servicio local con MCP como fachada

- Estado: aceptado
- Fecha: 2026-10-24
- Iteración: 0

## Contexto

La interfaz, OpenCode y futuros clientes deben compartir proyectos, revisiones y validaciones. Si MCP contuviera el dominio, la interfaz dependería de un protocolo pensado para agentes y se duplicarían reglas.

## Decisión

Implementar un servicio de aplicación local como núcleo. MCP, REST y CLI serán adaptadores sobre los mismos casos de uso. El agente SolidWorks será un proceso Windows separado y no llamará a modelos.

## Alternativas consideradas

- MCP como núcleo completo: rechazado por acoplamiento y duplicación.
- Macro/add-in con toda la lógica: rechazado porque dificulta proveedores, pruebas e interfaz independiente.
- Servicio remoto obligatorio: rechazado por privacidad y dependencia de red.

## Consecuencias

Se necesita una API de aplicación estable y contratos compartidos. OpenCode puede aportar su propio modelo, pero los modelos gratuitos de OpenCode no se presuponen disponibles como API para la interfaz.

## Evidencia / pruebas

Decisión arquitectónica documentada. La comunicación de extremo a extremo se probará en iteraciones 1 y 5; todavía no está implementada.
