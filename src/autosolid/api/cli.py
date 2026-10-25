"""Command-line entry point for the local API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m autosolid.api",
        description="Servicio HTTP local de AUTOSOLID.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Interfaz de escucha (por defecto {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Puerto de escucha (por defecto {DEFAULT_PORT}).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(), host=arguments.host, port=arguments.port)
    return 0
