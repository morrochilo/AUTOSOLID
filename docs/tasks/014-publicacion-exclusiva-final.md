# Tarea 014 — Eliminar fallback de publicación directa

## Contexto

La revisión de 013 confirmó que el último fallback `open(target, "xb")` sigue permitiendo:
- borrar un archivo sustituido por otro proceso durante la limpieza;
- dejar un SLDPRT parcial tras RuntimeError, KeyboardInterrupt o corte de proceso.

## Corrección obligatoria

- Eliminar completamente la copia directa al destino final con `xb`.
- Publicar únicamente mediante enlace duro exclusivo desde staging preparado. Si `os.link` no está disponible, fallar con `OUTPUT_WRITE_FAILED` sin crear el destino final.
- No sustituirla por `os.replace`, renombrado ni otra forma que pueda sobrescribir.
- Limpiar solo staging propio. Nunca ejecutar `unlink` sobre el destino final en ningún flujo.
- Mantener hash/metadatos antes de publicar y reconciliación posterior.

## Regresiones obligatorias

1. `os.link` falla siempre: el trabajo falla, no existe destino y un archivo creado por otro proceso permanece intacto.
2. `RuntimeError` durante el intento de publicación: no aparece archivo parcial ni se borra un archivo ajeno.
3. Flujo normal por enlace sigue funcionando y la suite completa pasa.
4. Revisar todos los caminos de `_move_without_overwrite` para demostrar que ninguno elimina o escribe directamente el destino.

No ampliar alcance, no hacer commits. Documentar en `docs/tasks/014-informe.md`. Ejecutar `pytest` y `dotnet build`.
