"""The two building blocks: who goes to which arm, and in which order conditions are run.

**Arm allocation: permuted blocks.** Tossing a coin for every participant leaves small studies
lopsided: with 20 participants, a split of 14-6 or worse happens in about a quarter of the
studies. Permuted blocks fix that: the sequence is cut into blocks (here of random size, so the
last assignment of a block cannot be guessed), and every block holds each arm in exactly its
planned proportion, in random order. The imbalance can then never exceed half the largest block.

**Condition orders within a session.** A *round* is one pass through every condition. Three ways
to order the conditions of each round:

``shuffle``
    an independent random order every round;
``latin``
    the rows of a cyclic Latin square: over ``n`` rounds each condition appears once in every
    position, which balances position (fatigue, learning) effects;
``williams``
    the rows of a Williams square: additionally every condition follows every other equally
    often, which balances first-order carry-over. It needs ``n`` rows when ``n`` is even and
    ``2 n`` when ``n`` is odd.

For ``latin`` and ``williams`` a session starts at a random row and uses a random relabelling of
the conditions, then walks down the rows round by round. The balance is exact within a session
when the number of rounds is a multiple of the number of rows, and in expectation across sessions
otherwise.
"""

from __future__ import annotations

from collections.abc import Sequence

from .rng import Stream

__all__ = ["DESIGNS", "block_orders", "latin_rows", "permuted_blocks", "williams_rows"]

DESIGNS = ("shuffle", "latin", "williams")


def permuted_blocks(
    labels: Sequence[str],
    weights: Sequence[int],
    block_sizes: Sequence[int],
    n: int,
    stream: Stream,
) -> list[str]:
    """``n`` assignments in permuted blocks of randomly chosen size.

    ``weights`` is the allocation ratio (``[1, 1]`` for equal arms, ``[2, 1]`` for two to one);
    every size in ``block_sizes`` must be a multiple of ``sum(weights)``.
    """
    if len(labels) != len(weights) or not labels:
        raise ValueError("labels and weights must be non-empty and of the same length")
    if any(w < 1 for w in weights):
        raise ValueError("weights must be positive integers")
    unit = sum(weights)
    if not block_sizes or any(s < unit or s % unit for s in block_sizes):
        raise ValueError(f"block sizes must be multiples of {unit} (the sum of the weights)")
    out: list[str] = []
    while len(out) < n:
        size = block_sizes[stream.below(len(block_sizes))]
        block = [
            label for label, w in zip(labels, weights, strict=True) for _ in range(w * size // unit)
        ]
        stream.shuffle(block)
        out.extend(block)
    return out[:n]


def latin_rows(n: int) -> list[tuple[int, ...]]:
    """The ``n`` rows of the cyclic Latin square: row ``i`` is ``i, i+1, ... (mod n)``."""
    if n < 2:
        raise ValueError("need at least two conditions")
    return [tuple((i + j) % n for j in range(n)) for i in range(n)]


def williams_rows(n: int) -> list[tuple[int, ...]]:
    """Rows of a Williams design: every ordered pair of conditions is adjacent equally often.

    The first row is ``0, 1, n-1, 2, n-2, ...``, whose successive differences are all distinct
    modulo ``n`` when ``n`` is even; the other rows are its cyclic shifts. For odd ``n`` the
    reversed rows are added, giving ``2 n`` rows.
    """
    if n < 2:
        raise ValueError("need at least two conditions")
    first = [0]
    low, high = 1, n - 1
    while len(first) < n:
        first.append(low)
        low += 1
        if len(first) < n:
            first.append(high)
            high -= 1
    rows = [tuple((x + i) % n for x in first) for i in range(n)]
    if n % 2:
        rows += [tuple(reversed(row)) for row in rows]
    return rows


def block_orders(
    conditions: Sequence[str], n_rounds: int, design: str, stream: Stream
) -> list[tuple[str, ...]]:
    """The order of the conditions in each of ``n_rounds`` rounds of one session."""
    if design not in DESIGNS:
        raise ValueError(f"unknown design {design!r}; choose one of {', '.join(DESIGNS)}")
    n = len(conditions)
    if n < 2:
        raise ValueError("need at least two conditions")
    if n_rounds < 1:
        raise ValueError("n_rounds must be at least 1")
    if design == "shuffle":
        orders = []
        for _ in range(n_rounds):
            order = list(conditions)
            stream.shuffle(order)
            orders.append(tuple(order))
        return orders
    rows = latin_rows(n) if design == "latin" else williams_rows(n)
    relabel = list(range(n))
    stream.shuffle(relabel)
    start = stream.below(len(rows))
    return [
        tuple(conditions[relabel[s]] for s in rows[(start + r) % len(rows)])
        for r in range(n_rounds)
    ]
