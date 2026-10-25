# Informe de tarea 005 — Interfaz local mínima de revisión

## Resultado

La tarea 005 quedó implementada y verificada localmente. La aplicación FastAPI sirve una interfaz web mínima en `/` que reutiliza `/api/v1` y el mismo `ProjectService` que MCP. Para esta tarea no se añadieron dependencias, framework frontend, bundler, Node ni recursos externos.

La interfaz permite:

- comprobar el estado del servicio local;
- crear, listar y seleccionar proyectos;
- cargar la revisión actual o una plantilla vacía;
- editar el `CadSpec` como JSON;
- validar sin persistir;
- guardar con `expected_revision`;
- mostrar conflictos de revisión y recargar la revisión vigente;
- listar diagnósticos con severidad, código, ruta y mensaje;
- listar preguntas abiertas;
- mostrar revisión, hash SHA-256 y visor JSON;
- anunciar estados y errores mediante regiones accesibles.

## Archivos

- `src/autosolid/api/ui.py`: rutas `/`, `/ui/app.css` y `/ui/app.js`, cabeceras de seguridad y carga de recursos empaquetados.
- `src/autosolid/api/static/index.html`: estructura y controles accesibles.
- `src/autosolid/api/static/app.css`: presentación adaptable, modo claro/oscuro y estados.
- `src/autosolid/api/static/app.js`: llamadas a la API, validación, guardado, conflictos, diagnósticos y preguntas.
- `src/autosolid/api/app.py`: inclusión del router de interfaz.
- `pyproject.toml`: inclusión de `static/*` en el paquete `autosolid.api`.
- `tests/test_ui.py`: cinco pruebas de interfaz, recursos, cabeceras, esquema y almacén compartido.
- `docs/tasks/005-interfaz-local.md`: alcance, exclusiones y verificación previstos.

## Decisiones de implementación

- La interfaz es HTML, CSS y JavaScript del navegador, sin paso de compilación. React se pospone hasta que la vista de fuentes y la previsualización 3D justifiquen el toolchain.
- Todos los datos del servidor se insertan con `textContent`; no se usa `innerHTML` para contenido dinámico.
- El documento se sirve con CSP restrictiva, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, `Permissions-Policy` y `Cache-Control: no-store`. Los recursos usan `Cache-Control: no-cache` y las mismas cabeceras base.
- El editor no guarda automáticamente. Validar no persiste; guardar exige la revisión actual y el servidor sigue siendo la autoridad.
- Las rutas de interfaz no aparecen en OpenAPI.

## Pruebas automatizadas

Comando ejecutado:

```powershell
.venv\Scripts\python -m pytest -q tests/test_ui.py
```

Resultado: `5 passed, 1 warning`.

Comando ejecutado después de todos los cambios:

```powershell
.venv\Scripts\python -m pytest -q
```

Resultado final: `158 passed, 1 warning`. Las 153 pruebas anteriores más las 5 nuevas pasan. El aviso es el preexistente de Starlette/httpx sobre `TestClient`; no se introdujo un fallo nuevo.

Las pruebas cubren:

- respuesta de `/` con HTML y cabeceras de seguridad;
- CSP sin `unsafe-inline` ni `unsafe-eval`, sin scripts inline y sin URLs externas;
- entrega de CSS/JS locales, sin `innerHTML`, `eval` ni recursos externos;
- exclusión de las rutas de interfaz del esquema OpenAPI;
- uso del mismo almacén por API e interfaz;
- error 404 estable para un recurso desconocido.

## Verificación real en navegador

Se arrancó el servidor con un directorio de datos temporal:

```powershell
$env:AUTOSOLID_DATA_DIR = "$env:TEMP\opencode\autosolid-ui-smoke"
.venv\Scripts\python -m autosolid.api --host 127.0.0.1 --port 8765
```

Flujo positivo observado en el navegador del entorno OpenCode:

1. `/` mostró `Servicio local activo`.
2. Se creó el proyecto `Bancada de prueba` y apareció en la lista con revisión 0.
3. Se cargó la plantilla vacía y se reemplazó por un `CadSpec` de rectángulo 40 × 20 mm con extrusión de 10 mm.
4. `Validar` mostró `Especificación válida. Todavía no se ha guardado.`, sin diagnósticos.
5. `Guardar revisión` mostró `Revisión 1 guardada.` y el hash `a28fe887bb8cbd06…`.
6. Tras recargar la página, el proyecto siguió seleccionado, la revisión era 1 y el hash coincidía; el estado fue `Revisión 1 cargada.`.
7. La consola del navegador no registró mensajes en este flujo.

Sobre el código final, después de los ajustes de conflictos y estados de carga, se repitió una pasada positiva con una revisión existente: validar, guardar la revisión 2 (hash `01b550040eb56416…`) y recargar; la consola quedó vacía.

También se verificó el cambio entre un proyecto con revisión y otro vacío: el proyecto vacío mostró una plantilla con su propio `project_id`, revisión 0 y `Sin hash`; al volver al primero reaparecieron la revisión 1 y su hash. La consola registró el 404 esperado de `CADSPEC_NOT_FOUND` al abrir el proyecto sin revisión.

Flujos negativos:

- Con JSON sintácticamente inválido, la interfaz mostró `No se pudo validar. El editor no contiene JSON válido.` y mantuvo la revisión 1.
- Con `units.length = "in"`, la validación mostró un diagnóstico `SCHEMA_INVALID` en `units.length` (`Input should be 'mm'`) y no guardó.
- Para el conflicto se usó un segundo servidor temporal en el puerto 8766: la interfaz cargó la revisión 1, otro cliente guardó la revisión 2 y luego la interfaz intentó guardar con `expected_revision=1`. El servidor respondió 409 y la interfaz mostró `Conflicto de revisión: el servidor tiene la revisión 2. No se guardó nada. Se recargó la revisión 2.`, quedando visible la revisión 2 y el contenido nuevo. La consola registró únicamente el 409 de red esperado; no hubo excepción JavaScript.
- Se probó el caso de metadatos desactualizados: tras un cambio externo, `Actualizar` mostró la advertencia de que existía una revisión más reciente sin recargar el editor; `Guardar revisión` usó la revisión cargada (1), recibió 409 y recargó la revisión 2. La API confirmó `current_revision=2`; no se creó una revisión 3 con datos viejos.

Los directorios temporales, el archivo de especificación y los procesos de prueba se eliminaron al terminar.

## Verificación del paquete

Se construyó una wheel local sin modificar dependencias del proyecto:

```powershell
.venv\Scripts\python -m pip wheel . --no-deps --wheel-dir "$env:TEMP\opencode\autosolid-wheel"
```

La construcción terminó correctamente y la wheel incluyó:

- `autosolid/api/static/app.css`
- `autosolid/api/static/app.js`
- `autosolid/api/static/index.html`

La wheel y el directorio temporal se eliminaron después de comprobar el contenido.

## Limitaciones

- No hay carga de PDF, imágenes, texto ni artefactos; la pantalla solo revisa y guarda JSON existente. La ingesta corresponde a la iteración 2.
- No hay proveedores, propuesta automática, trabajos asíncronos, cancelación, aprobaciones, comparación 3D ni construcción SolidWorks/AutoCAD.
- No hay autenticación remota, multiusuario, TLS ni CORS abierto. El servicio está pensado para loopback.
- La interfaz usa un editor JSON, no formularios estructurados ni un árbol visual de operaciones.
- Cambiar de proyecto o recargar la página descarta cambios no guardados; no hay diálogo de confirmación ni recuperación local.
- Al resolver un conflicto, la interfaz recarga la revisión vigente y descarta el contenido local que no se pudo guardar; no hay fusión ni recuperación.
- La prueba de navegador es manual, no una prueba E2E automatizada en CI. La suite automatizada valida rutas, cabeceras, recursos y convivencia con la API, pero no ejecuta el flujo completo en un navegador.
- No se ejecutó un escáner de seguridad ni una auditoría externa. La CSP y las cabeceras se comprobaron con `TestClient`.
- La documentación interactiva de FastAPI (`/docs`) queda fuera de la interfaz y no se incluyó en las comprobaciones de CSP.
- La respuesta visual se revisó en el navegador del entorno, no en una matriz de navegadores ni en dispositivos móviles reales.
- No se ha auditado ni aceptado la tarea; no se hicieron commits ni publicaciones.

## Reproducción

```powershell
$env:AUTOSOLID_DATA_DIR = "$env:TEMP\autosolid-ui"
.venv\Scripts\python -m autosolid.api --host 127.0.0.1 --port 8000
# abrir http://127.0.0.1:8000/
```

Para ejecutar las pruebas:

```powershell
.venv\Scripts\python -m pytest -q
```
