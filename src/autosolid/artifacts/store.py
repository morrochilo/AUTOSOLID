"""Content-addressed storage for immutable source files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ArtifactStoreError(Exception):
    """The artifact files could not be read or written safely."""


class ArtifactStore:
    """Store bytes by SHA-256 with atomic replacement and verified reads."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "artifacts"

    def path_for(self, sha256: str) -> Path:
        if not isinstance(sha256, str) or not _SHA256_PATTERN.fullmatch(sha256):
            raise ArtifactStoreError("El identificador del artefacto no es válido.")
        return self.root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: bytes) -> str:
        """Write bytes atomically and return their SHA-256 identifier."""

        if not isinstance(data, (bytes, bytearray)):
            raise ArtifactStoreError("El artefacto debe ser binario.")
        payload = bytes(data)
        sha256 = hashlib.sha256(payload).hexdigest()
        target = self.path_for(sha256)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and self._file_matches(target, sha256):
                return sha256
        except OSError as error:
            raise ArtifactStoreError(
                "No se pudo preparar el almacén de artefactos."
            ) from error

        temporary_path: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".source-",
                dir=target.parent,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        except OSError as error:
            raise ArtifactStoreError(
                "No se pudo escribir el artefacto."
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
        return sha256

    def read(self, sha256: str) -> bytes:
        """Read an artifact and reject missing or corrupted content."""

        target = self.path_for(sha256)
        try:
            data = target.read_bytes()
        except OSError as error:
            raise ArtifactStoreError("El artefacto no está disponible.") from error

        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise ArtifactStoreError(
                "El artefacto almacenado no supera la comprobación de integridad."
            )
        return data

    @staticmethod
    def _file_matches(path: Path, sha256: str) -> bool:
        try:
            data = path.read_bytes()
        except OSError:
            return False
        return hashlib.sha256(data).hexdigest() == sha256
