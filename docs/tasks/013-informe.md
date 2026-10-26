# Informe de la tarea 013 — Endurecimiento de publicación y cola build

## Resultado

Se corrigieron los diez hallazgos de la auditoría de la tarea 012 sin ampliar el alcance funcional. No se modificó `CadSpec`, `SolidWorksBuilder`, el contrato del agente C# ni se añadieron operaciones CAD, UI, MCP, PDF o proveedores. No se hicieron commits.

La publicación del artefacto ahora prepara hash y metadatos antes de crear el archivo final, publica con creación exclusiva y deja recuperación explícita para trabajos `running` o parcialmente publicados. La cola espera al trabajo activo antes de permitir el cierre del almacén.

Este informe no declara una auditoría independiente. Los resultados son la verificación local ejecutada en esta tarea.

## Cambios

### Publicación y recuperación

- `ProjectService._execute_build_job` calcula SHA-256 y tamaño del archivo de staging **antes** de publicarlo y persiste esos metadatos en el trabajo `running` mediante `record_build_job_artifact`.
- El destino se vuelve a resolver justo antes del enlace/creación exclusiva. Se comparan hash canónico, ruta resuelta y ausencia del destino; un cambio produce `DESTINATION_CHANGED` sin publicar.
- Se eliminó el hash posterior a la publicación. Un fallo al calcular el hash ya no puede dejar un SLDPRT válido sin metadatos.
- `recover_incomplete_build_jobs` (invocado al iniciar la API) reconcilia trabajos `running` y `failed` con metadatos de artefacto:
  - si la revisión vigente y su SHA-256 siguen coincidiendo, el archivo final existe, es regular y su hash/tamaño coinciden, se marca `completed` con `finalize_recovered_build_job` sin reconstruir;
  - si falta, difiere, la revisión cambió o no se puede verificar, se marca `failed` con `OUTPUT_RECOVERY_FAILED` y queda recuperable;
  - nunca se borra un archivo no verificado.
- `retry_build_job` reconcilia primero un trabajo `running` inactivo. Si el artefacto ya coincide, devuelve `completed` y no vuelve a ejecutar el agente. Si el destino existe pero no coincide con el hash registrado, no se reconstruye y se mantiene el error de destino ocupado.
- Los errores de persistencia del `finish_build_job` no se convierten en un `completed` ficticio: el trabajo queda `running` para la reconciliación posterior.

### Publicación exclusiva y archivos ajenos

- `_move_without_overwrite` usa enlace duro exclusivo (`os.link`) como ruta normal.
- Si el enlace no está disponible, copia a un staging privado en el directorio de destino y vuelve a intentar el enlace. Solo como último recurso usa apertura exclusiva `xb`; en ese caso únicamente elimina el archivo que este proceso acaba de crear.
- Un fallo al abrir el origen, copiar o hacer `fsync` ya no borra un destino preexistente de otro proceso.
- Un fallo de copia del fallback deja staging temporal limpio y no deja un archivo parcial en el destino final.

### Cola y cierre ordenado

- `SerialJobQueue.stop()` bloquea por defecto hasta que termina el trabajo activo y el hilo sale. No inicia trabajos encolados después de solicitar el cierre; esos trabajos permanecen `queued` en SQLite para un `retry` explícito.
- `stop()` es idempotente y admite un timeout opcional para llamadores que puedan gestionar el hilo por su cuenta; la API usa el cierre bloqueante.
- El `lifespan` de FastAPI reconcilia al iniciar y ejecuta `service.shutdown()` antes de `store.close()`.

### Inmutabilidad de `build_jobs`

- Se añadió el trigger `BEFORE INSERT` que impide reutilizar un `id` existente de `build_jobs`, incluso con `INSERT OR REPLACE` y `PRAGMA recursive_triggers = OFF`.
- El trigger se incluye en el esquema v5 para instalaciones nuevas y en una sentencia de endurecimiento idempotente que se aplica a bases existentes compatibles al inicializarlas. No se cambió el número de versión del archivo SQLite.

### Destinos Windows

- En Windows se eliminan puntos y espacios finales de cada componente antes de resolver, almacenar y calcular el hash. `parts./Block.sldprt`, `parts/Block.sldprt`, `parts/Block.sldprt.` y `parts/Block.sldprt ` comparten destino y hash.
- Se rechazan los nombres reservados `CON, PRN, AUX, NUL, COM1–COM9, LPT1–LPT9`, también con extensión (`CON.sldprt`, `COM1.sldprt`, `PRN.part.sldprt`) y en cualquier componente de carpeta.

### Timeout y JSON

- En POSIX el agente se inicia en una sesión nueva y, al vencer el timeout, se mata el grupo del proceso.
- En Windows se usa `taskkill /F /T /PID`, que actúa sobre el árbol descendiente del agente y no sobre procesos no emparentados. Si falla, se mata al menos el hijo directo.
- `_finite_number` convierte `OverflowError` (por ejemplo, un entero JSON gigante) en `BuildExecutionError(RUNNER_OUTPUT_INVALID)`.

## Pruebas añadidas

Archivo nuevo `tests/test_build_hardening.py`, 26 pruebas:

- alias Windows con punto/espacio final y hash compartido;
- rechazo de nombres reservados con y sin `.sldprt`;
- rechazo de un enlace de directorio que sale del árbol de salida;
- recheck de destino antes de publicar;
- fallo de `_move_without_overwrite` sin borrar un archivo ajeno;
- fallo de copia fallback sin dejar parciales;
- fallo de `finish_build_job` después de publicar y recuperación al iniciar;
- retry de un trabajo `running` ya publicado sin reconstruir;
- fallo de hash antes de publicar y retry posterior;
- fallo de publicación y retry posterior;
- trabajo `running` sin artefacto convertido en fallo recuperable;
- artefacto parcial/ajeno que no se reconstruye ni se borra;
- `INSERT OR REPLACE` bloqueado en `build_jobs`;
- trigger añadido a una base existente que lo había perdido;
- `stop()` que espera al trabajo lento y no inicia trabajo encolado;
- `shutdown()` del servicio que espera al runner lento sin cerrar el store;
- entero JSON enorme mediante el agente simulado y llamada directa a `_finite_number`;
- timeout que termina el árbol del agente sin matar un proceso ajeno.

## Verificación ejecutada

| Comprobación | Resultado |
|---|---|
| `pytest` completo con `.venv` | 365 pruebas superadas, 1 aviso preexistente de Starlette/httpx |
| Pruebas nuevas de endurecimiento | 26 superadas |
| `compileall` de `src` y `tests` | sin errores |
| `dotnet build src/solidworks-agent/AutoSolid.SolidWorksAgent.csproj` | 0 errores, 0 advertencias, destino `bin/Debug/net8.0-windows` |

Comandos usados:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests
dotnet build src\solidworks-agent\AutoSolid.SolidWorksAgent.csproj --nologo
```

## Limitaciones residuales

- **TOCTOU:** el recheck reduce la ventana, pero no hay handles de directorio seguros portables entre la comprobación y el enlace. Un actor con permisos de escritura en el árbol de salida podría cambiar un componente en esa ventana. El enlace final sigue siendo exclusivo y no sobrescribe, pero la contención se comprueba por ruta, no con un handle abierto.
- **Atomicidad archivo/DB:** SQLite y el sistema de archivos no comparten transacción. La recuperación reconcilia por hash, pero no existe un commit distribuido.
- **Procesos:** en Windows `taskkill /T` actúa sobre descendientes. Una instancia de SolidWorks independiente no es descendiente y no se toca; si el agente lanzara SolidWorks como hijo, podría verse afectada. COM puede seguir vivo tras matar al agente; el staging privado impide que un resultado incompleto se publique.
- **Concurrencia entre procesos:** la cola es serial por proceso. La reconciliación al iniciar asume que el proceso anterior ya no está ejecutando el trabajo. No se añadió coordinación entre dos procesos vivos sobre el mismo store.
- **Sin SolidWorks real:** esta tarea no ejecutó SolidWorks ni verificó un SLDPRT real. Las pruebas usan el agente simulado y archivos temporales; no se afirma precisión mecánica ni comportamiento de todas las versiones de SolidWorks.
- **Sin auditoría independiente:** no se declara superada una auditoría externa; solo se documentan los cambios y las pruebas locales.
- **Cobertura de estados antiguos:** un trabajo `running` heredado sin metadatos de artefacto no se puede validar por hash y se marca como fallo recuperable, sin asumir que un archivo existente le pertenece.
