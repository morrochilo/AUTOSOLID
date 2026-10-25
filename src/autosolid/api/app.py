"""FastAPI application factory for the local AUTOSOLID service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from autosolid.projects import ProjectService, ProjectStore

from .errors import register_error_handlers
from .routes import router
from .ui import router as ui_router


def create_app(store: ProjectStore | None = None) -> FastAPI:
    project_store = ProjectStore.from_env() if store is None else store
    service = ProjectService(project_store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            project_store.close()

    app = FastAPI(
        title="AUTOSOLID local API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.store = project_store
    app.state.service = service
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(ui_router)
    return app


app = create_app()
