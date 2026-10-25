"""Validation and normalization of uploaded source files.

The checks in this module only reject obvious mismatches. They do not parse or
validate the internal structure of a PDF, image or JSON document.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
from dataclasses import dataclass

from .exceptions import InvalidSourceError, SourceTooLargeError

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_FILENAME_LENGTH = 200
SOURCE_KINDS = ("pdf", "image", "text")

_PDF_EXTENSIONS = {".pdf"}
_IMAGE_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}


@dataclass(frozen=True)
class ValidatedSource:
    filename: str
    kind: str
    media_type: str
    sha256: str
    byte_size: int


def validate_source(
    filename: object,
    data: object,
    *,
    kind_hint: object = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> ValidatedSource:
    """Return normalized metadata or raise a source-domain error."""

    normalized_name = normalize_source_filename(filename)
    if not isinstance(data, (bytes, bytearray)):
        raise InvalidSourceError("El contenido de la fuente debe ser binario.")

    payload = bytes(data)
    if not payload:
        raise InvalidSourceError(
            "La fuente está vacía.", reason="empty"
        )
    if len(payload) > max_bytes:
        raise SourceTooLargeError(max_bytes, len(payload))

    detected_kind, expected_media_type = _detect_kind(normalized_name)
    if kind_hint is not None:
        if not isinstance(kind_hint, str) or kind_hint not in SOURCE_KINDS:
            raise InvalidSourceError(
                "El tipo de fuente debe ser pdf, image o text.",
                reason="unsupported_kind",
            )
        if kind_hint != detected_kind:
            raise InvalidSourceError(
                "El tipo declarado no coincide con la extensión del archivo.",
                reason="kind_mismatch",
            )

    media_type = _validate_content(
        detected_kind,
        payload,
        expected_media_type,
    )
    return ValidatedSource(
        filename=normalized_name,
        kind=detected_kind,
        media_type=media_type,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )


def normalize_source_filename(filename: object) -> str:
    if not isinstance(filename, str):
        raise InvalidSourceError("El nombre del archivo debe ser texto.")

    normalized = unicodedata.normalize("NFC", filename.strip())
    if not normalized:
        raise InvalidSourceError(
            "El nombre del archivo no puede estar vacío.", reason="filename"
        )
    if len(normalized) > MAX_SOURCE_FILENAME_LENGTH:
        raise InvalidSourceError(
            "El nombre del archivo es demasiado largo.", reason="filename"
        )
    if "/" in normalized or "\\" in normalized:
        raise InvalidSourceError(
            "El nombre del archivo no puede contener rutas.", reason="filename"
        )
    if normalized in {".", ".."}:
        raise InvalidSourceError(
            "El nombre del archivo no es válido.", reason="filename"
        )
    if any(
        ord(character) < 32 or ord(character) == 127
        for character in normalized
    ):
        raise InvalidSourceError(
            "El nombre del archivo no puede contener caracteres de control.",
            reason="filename",
        )
    return normalized


def source_media_type(filename: str) -> str:
    return _detect_kind(filename)[1]


def _detect_kind(filename: str) -> tuple[str, str]:
    extension = os.path.splitext(filename)[1].lower()
    if extension in _PDF_EXTENSIONS:
        return "pdf", "application/pdf"
    if extension in _IMAGE_EXTENSIONS:
        return "image", _IMAGE_EXTENSIONS[extension]
    if extension in _TEXT_EXTENSIONS:
        return "text", "text/plain"
    raise InvalidSourceError(
        "La extensión no está admitida. Usa PDF, PNG/JPEG/WebP o texto UTF-8.",
        reason="unsupported_extension",
    )


def _validate_content(
    kind: str,
    data: bytes,
    expected_media_type: str,
) -> str:
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise InvalidSourceError(
                "El archivo no tiene una cabecera PDF reconocible.",
                reason="signature",
            )
        return expected_media_type

    if kind == "image":
        if expected_media_type == "image/png":
            valid = data.startswith(b"\x89PNG\r\n\x1a\n")
        elif expected_media_type == "image/jpeg":
            valid = data.startswith(b"\xff\xd8\xff")
        else:
            valid = (
                len(data) >= 12
                and data.startswith(b"RIFF")
                and data[8:12] == b"WEBP"
            )
        if not valid:
            raise InvalidSourceError(
                "La firma de la imagen no coincide con su extensión.",
                reason="signature",
            )
        return expected_media_type

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidSourceError(
            "El archivo de texto no está codificado en UTF-8.",
            reason="encoding",
        ) from error
    if "\x00" in text:
        raise InvalidSourceError(
            "El archivo de texto contiene caracteres nulos.",
            reason="encoding",
        )
    if not text.strip():
        raise InvalidSourceError(
            "El archivo de texto no contiene texto visible.",
            reason="empty_text",
        )
    return expected_media_type
