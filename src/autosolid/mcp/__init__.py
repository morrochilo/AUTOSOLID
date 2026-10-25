"""Local MCP stdio facade for AUTOSOLID projects."""

from .server import create_server, main, run_stdio
from .tools import TOOL_DEFINITIONS, TOOL_NAMES, TOOLS_BY_NAME, dispatch

__all__ = [
    "TOOL_DEFINITIONS",
    "TOOL_NAMES",
    "TOOLS_BY_NAME",
    "create_server",
    "dispatch",
    "main",
    "run_stdio",
]
