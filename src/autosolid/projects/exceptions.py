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


class StoreError(ProjectError):
    """Storage could not complete an operation."""


class StoreClosedError(StoreError):
    def __init__(self) -> None:
        super().__init__("El almacén de proyectos está cerrado.")
