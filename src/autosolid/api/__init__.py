"""Local FastAPI adapter for AUTOSOLID projects."""

from .app import app, create_app
from .cli import main

__all__ = ["app", "create_app", "main"]
