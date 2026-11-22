"""A small deterministic random stream.

The standard library promises that ``random.Random.random()`` gives the same numbers for the same
seed in every Python version. It makes no such promise for ``shuffle``, ``randrange`` or
``choice``, whose algorithms have changed between releases. Everything here is therefore built on
``random()`` alone, so an allocation recorded today can be regenerated, and checked, years from now
on another machine.

``Stream(seed, *path)`` hashes the seed and the path into the generator's own seed, so unrelated
parts of one study (the arm sequence, the condition orders of each session) get independent
streams from a single master seed, and changing one part never disturbs another.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import MutableSequence
from typing import Any

__all__ = ["Stream"]


class Stream:
    """Random numbers derived from ``(seed, *path)``: the same arguments give the same numbers."""

    def __init__(self, seed: int, *path: str | int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        key = json.dumps([seed, *path], separators=(",", ":")).encode("utf-8")
        self._random = random.Random(int.from_bytes(hashlib.sha256(key).digest(), "big"))

    def below(self, n: int) -> int:
        """A uniform integer ``k`` with ``0 <= k < n``.

        Built from one 53-bit float, so the bias is below ``n / 2**53``: irrelevant for the
        handful of values drawn here.
        """
        if n < 1:
            raise ValueError("n must be at least 1")
        return min(int(self._random.random() * n), n - 1)

    def shuffle(self, items: MutableSequence[Any]) -> None:
        """Fisher-Yates shuffle, in place."""
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
