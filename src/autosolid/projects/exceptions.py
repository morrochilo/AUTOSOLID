"""Domain and application errors for the local project service."""

from __future__ import annotations

from collections.abc import Sequence

from autosolid.cad.models import Diagnostic


class ProjectError(Exception):
    """Base class for expected project-service failures."""


class InvalidProjectNameError(ProjectError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProjectNotFoundError(ProjectError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"El proyecto '{project_id}' no existe.")
        self.project_id = project_id


class CadspecNotFoundError(ProjectError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"El proyecto '{project_id}' no tiene una especificación guardada.")
        self.project_id = project_id


class RevisionConflictError(ProjectError):
    def __init__(self, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            "La revisión esperada no coincide con la revisión actual del proyecto."
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class InvalidRevisionError(ProjectError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidSpecError(ProjectError):
    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        super().__init__("La especificación contiene diagnósticos de error.")
        self.diagnostics = list(diagnostics)


class SourceNotFoundError(ProjectError):
    def __init__(self, project_id: str, source_id: str) -> None:
        super().__init__(
            f"El proyecto '{project_id}' no tiene la fuente '{source_id}'."
        )
        self.project_id = project_id
        self.source_id = source_id


class SourceNotTextError(ProjectError):
    def __init__(self, project_id: str, source_id: str, kind: str) -> None:
        super().__init__(
            "La fuente solicitada no es de tipo texto."
        )
        self.project_id = project_id
        self.source_id = source_id
        self.kind = kind


class InvalidSourceError(ProjectError):
    def __init__(self, message: str, *, reason: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class SourceTooLargeError(ProjectError):
    def __init__(self, limit_bytes: int, actual_bytes: int | None = None) -> None:
        super().__init__(
            f"La fuente supera el límite de {limit_bytes} bytes."
        )
        self.limit_bytes = limit_bytes
        self.actual_bytes = actual_bytes


class InvalidApprovalError(ProjectError):
    def __init__(self, message: str, *, reason: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ApprovalNotFoundError(ProjectError):
    def __init__(self, project_id: str, approval_id: str) -> None:
        super().__init__(
            f"El proyecto '{project_id}' no tiene la aprobación '{approval_id}'."
        )
        self.project_id = project_id
        self.approval_id = approval_id


class ApprovalHashMismatchError(ProjectError):
    def __init__(
        self,
        project_id: str,
        revision: int,
        provided_sha256: str,
        current_sha256: str,
    ) -> None:
        super().__init__(
            "El hash indicado no coincide con el de la revisión actual."
        )
        self.project_id = project_id
        self.revision = revision
        self.provided_sha256 = provided_sha256
        self.current_sha256 = current_sha256


class ApprovalBlockedError(ProjectError):
    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        super().__init__(
            "La revisión no cumple las condiciones para aprobarse."
        )
        self.diagnostics = list(diagnostics)


class InvalidBuildApprovalError(ProjectError):
    def __init__(self, message: str, *, reason: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class InvalidBuildRequestError(ProjectError):
    def __init__(self, message: str, *, reason: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class BuildApprovalNotFoundError(ProjectError):
    def __init__(self, project_id: str, approval_id: str) -> None:
        super().__init__(
            f"El proyecto '{project_id}' no tiene la aprobación de construcción "
            f"'{approval_id}'."
        )
        self.project_id = project_id
        self.approval_id = approval_id


class BuildApprovalExpiredError(ProjectError):
    def __init__(self, project_id: str, approval_id: str) -> None:
        super().__init__(
            "La aprobación de construcción ha expirado y no puede consumirse."
        )
        self.project_id = project_id
        self.approval_id = approval_id


class BuildApprovalConsumedError(ProjectError):
    def __init__(self, project_id: str, approval_id: str) -> None:
        super().__init__(
            "La aprobación de construcción ya fue consumida por otro trabajo."
        )
        self.project_id = project_id
        self.approval_id = approval_id


class BuildApprovalStaleError(ProjectError):
    def __init__(
        self,
        project_id: str,
        revision: int,
        *,
        current_revision: int,
    ) -> None:
        super().__init__(
            "La aprobación de construcción no corresponde a la revisión vigente."
        )
        self.project_id = project_id
        self.revision = revision
        self.current_revision = current_revision


class BuildDestinationError(ProjectError):
    def __init__(self, message: str, *, reason: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class BuildDestinationMismatchError(ProjectError):
    def __init__(self, project_id: str, approval_id: str) -> None:
        super().__init__(
            "El destino solicitado no coincide con el autorizado por la aprobación."
        )
        self.project_id = project_id
        self.approval_id = approval_id


class BuildJobNotFoundError(ProjectError):
    def __init__(self, project_id: str, job_id: str) -> None:
        super().__init__(
            f"El proyecto '{project_id}' no tiene el trabajo de construcción "
            f"'{job_id}'."
        )
        self.project_id = project_id
        self.job_id = job_id


class BuildJobConflictError(ProjectError):
    def __init__(self, message: str, *, reason: str = "conflict") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class StoreError(ProjectError):
    """Storage could not complete an operation."""


class StoreClosedError(StoreError):
    def __init__(self) -> None:
        super().__init__("El almacén de proyectos está cerrado.")
