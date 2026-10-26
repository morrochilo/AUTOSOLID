# Informe de la tarea 014 — Publicación exclusiva final

## Resultado

Se eliminó el último fallback de publicación directa al destino final. `ProjectService._move_without_overwrite` publica únicamente mediante enlace duro exclusivo (`os.link`) desde el staging preparado. Si el enlace no está disponible o falla, el trabajo falla con `OUTPUT_WRITE_FAILED` sin crear el destino. Ningún camino abre para escritura, copia, renombra, sustituye ni elimina el destino final.

No se modificaron `CadSpec`, el contrato del agente C# ni el flujo feliz de construcción. No se añadieron operaciones CAD, UI, MCP, PDF o proveedores. No se hicieron commits.

Este informe documenta la verificación local de la tarea. No declara una auditoría independiente.

## Cambio en la publicación

Antes, tras fallar el enlace duro, se copiaba a un staging privado en el directorio de destino, se reintentaba el enlace y, como último recurso, se abría el destino con `xb` y se copiaba directamente. Ese último camino permitía:

- dejar un `.sldprt` parcial en el destino si la copia se interrumpía;
- eliminar con `unlink` un destino que otro proceso hubiera sustituido durante la limpieza.

Ahora `_move_without_overwrite` solo tiene estos pasos:

1. Crear los directorios padre del destino. No crea ni abre el archivo final.
2. Ejecutar `os.link(source, target)`.
   - Éxito: el destino queda publicado de forma atómica y exclusiva; se elimina únicamente el staging propio de origen.
   - `FileExistsError`: se informa `DESTINATION_EXISTS` sin tocar el archivo existente.
   - `OSError` o `NotImplementedError`: se informa `OUTPUT_WRITE_FAILED` sin crear el destino.
   - Cualquier otra excepción (por ejemplo `RuntimeError` o `KeyboardInterrupt`) se propaga sin crear ni borrar el destino; el staging queda dentro del `TemporaryDirectory` del trabajo.
3. No se usa `os.replace`, renombrado, apertura `xb`, `shutil`, copia directa ni `unlink` sobre el destino.

El hash y el tamaño se siguen calculando y persistiendo en el trabajo **antes** de publicar, y la reconciliación posterior no cambió.

## Revisión de todos los caminos de `_move_without_overwrite`

| Camino | Efecto sobre el destino final |
|---|---|
| `mkdir` del padre falla | No se crea ni modifica el destino. |
| `os.link` tiene éxito | Enlace duro atómico y exclusivo; el contenido ya estaba completo en staging. |
| `os.link` lanza `FileExistsError` | No se escribe ni se elimina; se conserva el archivo ajeno. |
| `os.link` lanza `OSError`/`NotImplementedError` | No se crea el destino; falla con `OUTPUT_WRITE_FAILED`. |
| Excepción inesperada durante `os.link` | Se propaga sin abrir, escribir ni eliminar el destino. |
| Limpieza del staging (`_unlink_quiet`) | Solo recibe la ruta de staging propia, nunca el destino. |

La búsqueda en `src/autosolid` no encontró aperturas `xb`, `os.replace`, renombrados ni copias sobre el destino de construcción fuera del almacén de artefactos de fuentes, que no forma parte de este flujo.

## Regresiones añadidas

Archivo `tests/test_build_hardening.py`:

- **Enlace duro no disponible en un trabajo completo:** el trabajo falla con `OUTPUT_WRITE_FAILED`, no existe el destino y no se intenta ninguna copia de respaldo.
- **Archivo ajeno creado justo en el intento de publicación:** el trabajo falla y el archivo de otro proceso permanece byte a byte intacto.
- **`RuntimeError` durante la publicación:** el trabajo falla con `INTERNAL_ERROR`, no aparece archivo parcial y no se toca un archivo ajeno.
- **Todos los fallos de publicación:** prueba parametrizada con `OSError`, `NotImplementedError`, `FileExistsError` y `RuntimeError` que registra las llamadas a `_unlink_quiet` y demuestra que el destino nunca se elimina.
- **Flujo normal:** prueba directa que verifica que se usa un único `os.link(source, target)`, que el contenido y el enlace son correctos y que solo se elimina el staging de origen.
- **Sin fallback de copia:** si `os.link` falla, ninguna copia directa se ejecuta y el destino sigue ausente.

También se ajustó la prueba anterior de fallback para reflejar que ya no existe copia directa; su cobertura de «no dejar parciales» se conserva en las pruebas nuevas.

## Verificación ejecutada

| Comprobación | Resultado |
|---|---|
| `pytest` completo con `.venv` | 373 pruebas superadas, 1 aviso preexistente de Starlette/httpx |
| `tests/test_build_hardening.py` | 34 pruebas superadas |
| `dotnet build src/solidworks-agent/AutoSolid.SolidWorksAgent.csproj` | 0 errores, 0 advertencias |

Comandos usados:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
dotnet build src\solidworks-agent\AutoSolid.SolidWorksAgent.csproj --nologo
```

## Limitaciones residuales

- **Requisito de enlaces duros:** en un sistema de archivos que no soporte `os.link`, la construcción falla con `OUTPUT_WRITE_FAILED` por diseño. No hay ruta alternativa de publicación.
- **TOCTOU de rutas:** la comprobación y la publicación siguen separadas por una ventana en la que un actor con permisos de escritura podría cambiar un componente de ruta. El enlace final es exclusivo y no sobrescribe, pero la contención se comprueba por ruta, no con un handle de directorio abierto.
- **Atomicidad archivo/DB:** SQLite y el sistema de archivos no comparten transacción; la recuperación sigue reconciliando por hash.
- **Sin SolidWorks real:** esta tarea no ejecutó SolidWorks. Las pruebas usan archivos temporales y el agente simulado.
- **Sin auditoría independiente:** solo se documenta la verificación local.
