"""Strict JSON-object decoding shared by provider implementations."""

from __future__ import annotations

import json
from typing import Any

from .errors import ProviderError


def _reject_non_finite(value: str) -> Any:
    raise ProviderError(
        "MODEL_OUTPUT_INVALID",
        "La respuesta JSON del modelo contiene un número no finito.",
        details={"reason": "non_finite_number"},
    )


MAX_JSON_NESTING = 100


def ensure_json_nesting(content: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in content:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_NESTING:
                raise ValueError("JSON supera la profundidad máxima")
        elif character in "]}":
            depth -= 1


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse one complete JSON object; never repair fences or extra text."""

    if not content.strip():
        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "La respuesta JSON del modelo está vacía.",
            details={"reason": "empty_content"},
        )
    try:
        ensure_json_nesting(content)
        parsed = json.loads(content, parse_constant=_reject_non_finite)
    except json.JSONDecodeError as error:
        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "La respuesta del modelo no es JSON válido.",
            details={"reason": "invalid_json", "position": error.pos},
        ) from error
    except (ValueError, RecursionError) as error:
        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "La respuesta JSON del modelo es demasiado compleja o inválida.",
            details={"reason": "invalid_json"},
        ) from error
    if not isinstance(parsed, dict):
        raise ProviderError(
            "MODEL_OUTPUT_INVALID",
            "La respuesta JSON del modelo debe ser un objeto.",
            details={"reason": "json_not_object"},
        )
    return parsed
