"""FastAPI application factory for the local AUTOSOLID service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from autosolid.projects import ProjectService, ProjectStore

from .errors import register_error_handlers
from .routes import router
from .ui import router as ui_router


def create_app(
    store: ProjectStore | None = None,
    *,
    service: ProjectService | None = None,
) -> FastAPI:
    if store is None and service is not None:
        project_store = service.store
    else:
        project_store = ProjectStore.from_env() if store is None else store
    project_service = (
        ProjectService(project_store) if service is None else service
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        project_service.recover_incomplete_build_jobs()
        try:
            yield
        finally:
            project_service.shutdown()
            project_store.close()

    app = FastAPI(
        title="AUTOSOLID local API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.store = project_store
    app.state.service = project_service
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(ui_router)
    return app


app = create_app()
