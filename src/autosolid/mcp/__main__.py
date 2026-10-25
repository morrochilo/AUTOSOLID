"""Allow ``python -m autosolid.mcp`` to start the stdio server."""

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
