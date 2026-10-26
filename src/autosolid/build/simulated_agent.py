"""CLI used only by tests to exercise the subprocess runner without SolidWorks.

It is intentionally not imported by the service. Every successful result is
marked ``"simulated": true`` so it can never be mistaken for a real SolidWorks
verification.

Modes are selected with ``AUTOSOLID_SIMULATED_MODE``:

- ``ok`` (default): write a fake SLDPRT and a coherent JSON result.
- ``invalid_json``: print non-JSON output.
- ``timeout``: sleep for ``AUTOSOLID_SIMULATED_DELAY`` seconds.
- ``volume_mismatch``: report a volume difference above tolerance.
- ``rebuild_failed``: report a failed rebuild and exit 1.
- ``no_output``: print an ok result without creating the file.
- ``huge_output``: print more bytes than the runner capture limit.
- ``overflow_number``: report a JSON integer too large for a finite float.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 3 or arguments[0] != "build":
        print(
            "Uso: python -m autosolid.build.simulated_agent build "
            "<spec.json> <output.sldprt>",
            file=sys.stderr,
        )
        return 2

    mode = os.environ.get("AUTOSOLID_SIMULATED_MODE", "ok")
    output_path = Path(arguments[2])
    if output_path.exists():
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "OutputExists",
                    "message": "La salida ya existe; no se sobrescribe",
                }
            )
        )
        return 1

    if mode == "timeout":
        time.sleep(_number("AUTOSOLID_SIMULATED_DELAY", 30.0))
        return 1

    if mode == "invalid_json":
        print("this is not the JSON contract")
        return 0

    if mode == "huge_output":
        print("x" * 200_000)
        return 0

    if mode == "overflow_number":
        print(
            '{"status": "ok", "rebuildSucceeded": true, '
            '"volumeM3": ' + "1" + "0" * 400 + ", "
            '"volumeDifferenceM3": 0.0, "errors": 0, "warnings": 0}'
        )
        return 0

    if mode == "non_finite":
        print(
            json.dumps(
                {
                    "status": "ok",
                    "rebuildSucceeded": True,
                    "volumeM3": "NaN",
                    "volumeDifferenceM3": 0.0,
                    "errors": 0,
                    "warnings": 0,
                    "simulated": True,
                }
            )
        )
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if mode != "no_output":
        output_path.write_bytes(b"SIMULATED-SLDPRT-NOT-REAL\n")

    if mode == "rebuild_failed":
        print(
            json.dumps(
                {
                    "status": "rebuild_failed",
                    "rebuildSucceeded": False,
                    "volumeM3": 0.0,
                    "volumeDifferenceM3": 0.0,
                    "errors": 1,
                    "warnings": 0,
                    "simulated": True,
                }
            )
        )
        return 1

    difference = (
        _number("AUTOSOLID_SIMULATED_VOLUME_DIFFERENCE", 0.0)
        if mode == "volume_mismatch"
        else 0.0
    )
    volume = 0.000008
    print(
        json.dumps(
            {
                "status": "ok",
                "path": str(output_path),
                "revision": "simulated",
                "rebuildSucceeded": True,
                "volumeM3": volume,
                "expectedVolumeM3": volume,
                "volumeDifferenceM3": difference,
                "errors": 0,
                "warnings": 0,
                "units": "simulated",
                "boundingBox": [0.0, 0.0, 0.0, 0.04, 0.02, 0.01],
                "simulated": True,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())
