"""Safe resolution of build destinations below a server-owned directory."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_DESTINATION_CHARS = 512
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_INVALID_PATTERN = re.compile(r'[<>:"|?*]')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_WINDOWS_RESERVED_CASEFOLD = frozenset(
    name.casefold() for name in _WINDOWS_RESERVED_NAMES
)
_WINDOWS = os.name == "nt"


class DestinationError(Exception):
    """A destination is unsafe, out of scope or already occupied."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


@dataclass(frozen=True)
class ResolvedDestination:
    """Canonical destination bound to one configured output root."""

    root: Path
    path: Path
    relative: str
    destination_hash: str


def _canonical_components(relative: str) -> tuple[str, ...]:
    """Split a relative path into its platform-canonical components.

    On Windows, trailing dots and spaces are aliases for the same file name.
    They are removed from every component except ``.`` and ``..`` before the
    destination is hashed or resolved. Empty components are ignored, matching
    the behaviour of :class:`pathlib.Path`.
    """

    components: list[str] = []
    for raw in relative.replace("\\", "/").split("/"):
        if raw in ("", "."):
            continue
        if raw == "..":
            components.append(raw)
            continue
        if _WINDOWS:
            raw = raw.rstrip(" .")
            if not raw:
                raise DestinationError(
                    "El destino contiene un nombre de archivo no válido.",
                    reason="destination",
                )
        components.append(raw)
    if not components:
        raise DestinationError(
            "El destino debe nombrar un archivo dentro del directorio de salida.",
            reason="destination",
        )
    return tuple(components)


def _reject_reserved_names(components: tuple[str, ...]) -> None:
    """Reject Windows device names even when they carry an extension."""

    for component in components:
        bare = component.rstrip(" .")
        if not bare:
            raise DestinationError(
                "El destino contiene un nombre de archivo no válido.",
                reason="destination",
            )
        # Windows reserves CON, CON.sldprt, CON.any.extension, etc. The device
        # name is the part before the first dot, ignoring trailing separators.
        device = bare.split(".", 1)[0].rstrip(" .").casefold()
        if device in _WINDOWS_RESERVED_CASEFOLD:
            raise DestinationError(
                "El destino usa un nombre reservado de Windows.",
                reason="reserved",
            )


def _canonical_relative(relative: str) -> str:
    return "/".join(_canonical_components(relative))


def canonical_destination_hash(root: Path, relative: str) -> str:
    """Return the stable hash used to bind an approval to a destination.

    The hash covers only the canonical relative path below the configured
    output root, not a machine-specific absolute path. On Windows the path is
    case-folded with :func:`os.path.normcase` and every component is stripped
    of trailing dots/spaces so aliases of the same file share one hash.
    """

    resolved_root = Path(root).expanduser().resolve()
    components = _canonical_components(relative)
    _reject_reserved_names(components)
    resolved = resolved_root.joinpath(*components).resolve()
    try:
        canonical_relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as error:  # pragma: no cover - defensive
        raise DestinationError(
            "El destino debe estar dentro del directorio de salida.",
            reason="escape",
        ) from error
    normalized = os.path.normcase(_canonical_relative(canonical_relative))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_destination(
    root: str | os.PathLike[str],
    raw_destination: object,
    *,
    require_absent: bool = True,
) -> ResolvedDestination:
    """Validate ``raw_destination`` and resolve it below ``root``.

    Absolute paths, drive-qualified paths, parent escapes, control characters,
    Windows device names and non-``.sldprt`` files are rejected. Existing files
    are rejected by default so constructing can never overwrite a prior
    document.
    """

    if (
        not isinstance(raw_destination, str)
        or not raw_destination.strip()
        or len(raw_destination) > MAX_DESTINATION_CHARS
    ):
        raise DestinationError(
            "El destino debe ser una ruta relativa no vacía.",
            reason="destination",
        )

    candidate_text = raw_destination.strip()
    if _CONTROL_PATTERN.search(candidate_text):
        raise DestinationError(
            "El destino contiene caracteres de control.",
            reason="destination",
        )

    # Both separators are accepted on input; the canonical form is POSIX.
    normalized_text = candidate_text.replace("\\", "/")
    if (
        normalized_text.startswith("/")
        or normalized_text.startswith("//")
        or _DRIVE_PATTERN.match(normalized_text) is not None
    ):
        raise DestinationError(
            "El destino debe ser relativo al directorio de salida.",
            reason="absolute",
        )
    if _WINDOWS_INVALID_PATTERN.search(candidate_text):
        raise DestinationError(
            "El destino contiene caracteres no admitidos.",
            reason="destination",
        )

    components = _canonical_components(normalized_text)
    if components[0].casefold() == ".work":
        raise DestinationError(
            "El destino usa una carpeta reservada por el servidor.",
            reason="destination",
        )
    if any(part == ".." for part in components):
        raise DestinationError(
            "El destino no puede salir del directorio de salida.",
            reason="escape",
        )
    _reject_reserved_names(components)

    candidate = Path(*components)
    if candidate.is_absolute():
        raise DestinationError(
            "El destino debe ser relativo al directorio de salida.",
            reason="absolute",
        )

    resolved_root = Path(root).expanduser().resolve()
    raw_path = resolved_root / candidate
    if raw_path.is_symlink():
        raise DestinationError(
            "El destino no puede ser un enlace simbólico.",
            reason="destination",
        )
    resolved = raw_path.resolve()
    if resolved == resolved_root:
        raise DestinationError(
            "El destino debe nombrar un archivo dentro del directorio de salida.",
            reason="destination",
        )
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise DestinationError(
            "El destino no puede salir del directorio de salida.",
            reason="escape",
        ) from error
    relative = _canonical_relative(relative)
    if _WINDOWS:
        # Resolve again through the canonical spelling so a trailing dot or
        # space never reaches the agent as a distinct file name.
        resolved = resolved_root.joinpath(*relative.split("/"))

    if not relative.lower().endswith(".sldprt"):
        raise DestinationError(
            "El destino debe ser un archivo .sldprt.",
            reason="extension",
        )

    if resolved.parent.exists() and not resolved.parent.is_dir():
        raise DestinationError(
            "La carpeta del destino no es un directorio.",
            reason="parent",
        )

    if require_absent and (resolved.exists() or resolved.is_symlink()):
        raise DestinationError(
            "El destino ya existe; no se sobrescribe.",
            reason="exists",
        )

    return ResolvedDestination(
        root=resolved_root,
        path=resolved,
        relative=relative,
        destination_hash=canonical_destination_hash(resolved_root, relative),
    )
