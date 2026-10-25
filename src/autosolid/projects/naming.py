"""Small validation helpers shared by the store and the application layer."""

from __future__ import annotations

from .exceptions import InvalidProjectNameError

MAX_PROJECT_NAME_LENGTH = 200


def validate_project_name(name: object) -> str:
    """Return a trimmed project name or raise a domain error."""

    if not isinstance(name, str):
        raise InvalidProjectNameError("El nombre del proyecto debe ser texto.")
    normalized = name.strip()
    if not normalized:
        raise InvalidProjectNameError("El nombre del proyecto no puede estar vacío.")
    if len(normalized) > MAX_PROJECT_NAME_LENGTH:
        raise InvalidProjectNameError(
            f"El nombre del proyecto no puede superar {MAX_PROJECT_NAME_LENGTH} caracteres."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise InvalidProjectNameError(
            "El nombre del proyecto no puede contener caracteres de control."
        )
    return normalized
