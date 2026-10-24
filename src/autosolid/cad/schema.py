"""JSON Schema export for ``CadSpec`` without writing repository artefacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .models import CadSpec, Diagnostic


def cad_spec_json_schema() -> dict[str, Any]:
    return CadSpec.model_json_schema()


def diagnostic_json_schema() -> dict[str, Any]:
    return Diagnostic.model_json_schema()


def main(argv: Sequence[str] | None = None) -> int:
    """Print the CadSpec JSON Schema or write it to an explicit path."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) > 1:
        sys.stderr.write("Uso: autosolid-schema [ruta_salida.json]\n")
        return 2

    schema = cad_spec_json_schema()
    if arguments:
        destination = Path(arguments[0])
        destination.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        sys.stdout.write(f"{destination}\n")
    else:
        json.dump(schema, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI tests
    raise SystemExit(main())
