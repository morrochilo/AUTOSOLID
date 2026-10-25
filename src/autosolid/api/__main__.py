"""Allow ``python -m autosolid.api`` to start the loopback service."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
