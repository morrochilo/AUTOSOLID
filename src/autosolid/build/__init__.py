"""Build approval, destination and SolidWorks runner support.

Nothing in this package talks to SolidWorks on import. The runner only
executes the configured C# agent with an explicit argument list.
"""

from .destination import (
    DestinationError,
    ResolvedDestination,
    canonical_destination_hash,
    resolve_destination,
)
from .queue import SerialJobQueue
from .runner import (
    BuildExecutionError,
    BuildExecutionResult,
    SolidWorksRunner,
    SubprocessSolidWorksRunner,
    UnavailableSolidWorksRunner,
)

__all__ = [
    "BuildExecutionError",
    "BuildExecutionResult",
    "DestinationError",
    "ResolvedDestination",
    "SerialJobQueue",
    "SolidWorksRunner",
    "SubprocessSolidWorksRunner",
    "UnavailableSolidWorksRunner",
    "canonical_destination_hash",
    "resolve_destination",
]
