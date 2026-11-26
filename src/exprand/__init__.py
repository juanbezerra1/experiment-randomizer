"""Reproducible, auditable randomisation for small experiments."""

from .designs import DESIGNS, block_orders, latin_rows, permuted_blocks, williams_rows
from .lock import FileLock, LockTimeout
from .log import Entry, LogError, check
from .placement import Finding, folder_warnings
from .protocol import Allocation, Protocol, arm_sequence, draw, round_orders
from .rng import Stream
from .study import Study, VerifyReport

__version__ = "0.1.0"

__all__ = [
    "DESIGNS",
    "Allocation",
    "Entry",
    "FileLock",
    "Finding",
    "LockTimeout",
    "LogError",
    "Protocol",
    "Stream",
    "Study",
    "VerifyReport",
    "__version__",
    "arm_sequence",
    "block_orders",
    "check",
    "draw",
    "folder_warnings",
    "latin_rows",
    "permuted_blocks",
    "round_orders",
    "williams_rows",
]
