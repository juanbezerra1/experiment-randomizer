"""The protocol of a study, and the pure function that turns it into an allocation.

A :class:`Protocol` holds everything that decides what a session gets: the arms and their ratio,
the sizes of the permuted blocks, the conditions, the number of rounds, the design of the orders
and the master seed. ``draw(protocol, k)`` is a *pure function* of the protocol and the session
number ``k``: it reads no file and no clock, so any allocation can be regenerated and compared
with what the log says.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .designs import DESIGNS, block_orders, permuted_blocks
from .rng import Stream

__all__ = ["FORMAT", "Allocation", "Protocol", "arm_sequence", "draw", "round_orders"]

FORMAT = 1
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+]*$")


def _check_labels(kind: str, labels: Sequence[str]) -> tuple[str, ...]:
    out = tuple(labels)
    for label in out:
        if not isinstance(label, str) or not _LABEL.match(label):
            raise ValueError(
                f"invalid {kind} label {label!r}: start with a letter or digit, then use only "
                "letters, digits, '_', '.' and '+' (no spaces, '-', ';' or quotes, so the log "
                "stays unambiguous and safe to open in a spreadsheet)"
            )
    if len(set(out)) != len(out):
        raise ValueError(f"duplicate {kind} labels in {list(out)}")
    return out


@dataclass(frozen=True)
class Protocol:
    """Everything that determines the allocations of a study."""

    arms: tuple[str, ...] = ()
    arm_weights: tuple[int, ...] = ()
    arm_block_sizes: tuple[int, ...] = ()
    conditions: tuple[str, ...] = ()
    n_rounds: int = 0
    design: str = "shuffle"
    seed: int = field(default_factory=lambda: secrets.randbits(64))

    def __post_init__(self) -> None:
        arms = _check_labels("arm", self.arms)
        conditions = _check_labels("condition", self.conditions)
        if not arms and not conditions:
            raise ValueError("give arms, conditions, or both")
        object.__setattr__(self, "arms", arms)
        object.__setattr__(self, "conditions", conditions)

        if arms:
            if len(arms) < 2:
                raise ValueError("need at least two arms (or none)")
            weights = tuple(self.arm_weights) or (1,) * len(arms)
            if len(weights) != len(arms) or any(
                isinstance(w, bool) or not isinstance(w, int) or w < 1 for w in weights
            ):
                raise ValueError("arm_weights must be one positive integer per arm")
            unit = sum(weights)
            sizes = tuple(self.arm_block_sizes) or (2 * unit, 3 * unit)
            if any(isinstance(s, bool) or not isinstance(s, int) for s in sizes) or any(
                s < unit or s % unit for s in sizes
            ):
                raise ValueError(f"arm_block_sizes must be multiples of {unit}, the sum of weights")
            object.__setattr__(self, "arm_weights", weights)
            object.__setattr__(self, "arm_block_sizes", sizes)
        elif self.arm_weights or self.arm_block_sizes:
            raise ValueError("arm_weights and arm_block_sizes need arms")

        if conditions:
            if len(conditions) < 2:
                raise ValueError("need at least two conditions (or none)")
            if isinstance(self.n_rounds, bool) or not isinstance(self.n_rounds, int):
                raise ValueError("n_rounds must be an integer")
            if self.n_rounds < 1:
                raise ValueError("n_rounds must be at least 1 when there are conditions")
            if self.design not in DESIGNS:
                raise ValueError(
                    f"unknown design {self.design!r}; choose one of {', '.join(DESIGNS)}"
                )
        elif self.n_rounds:
            raise ValueError("n_rounds needs conditions")

        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")

    # -- serialisation ------------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "arms": list(self.arms),
            "arm_weights": list(self.arm_weights),
            "arm_block_sizes": list(self.arm_block_sizes),
            "conditions": list(self.conditions),
            "n_rounds": self.n_rounds,
            "design": self.design,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Protocol:
        if data.get("format") != FORMAT:
            raise ValueError(f"unsupported protocol format {data.get('format')!r}")
        try:
            return cls(
                arms=tuple(data["arms"]),
                arm_weights=tuple(data["arm_weights"]),
                arm_block_sizes=tuple(data["arm_block_sizes"]),
                conditions=tuple(data["conditions"]),
                n_rounds=data["n_rounds"],
                design=data["design"],
                seed=data["seed"],
            )
        except KeyError as exc:
            raise ValueError(f"protocol is missing the field {exc.args[0]!r}") from exc

    def canonical_json(self) -> str:
        """The form that is hashed: sorted keys, no spaces, so formatting never matters."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def hash(self) -> str:
        """SHA-256 of the canonical JSON; the log chain starts from it."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> Protocol:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"protocol file is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("protocol file must hold a JSON object")
        return cls.from_dict(data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


@dataclass(frozen=True)
class Allocation:
    """What one session gets."""

    session: int
    arm: str  # "" when the protocol has no arms
    rounds: tuple[tuple[str, ...], ...]  # the order of the conditions in each round

    def round_strings(self) -> tuple[str, ...]:
        """Each round as it is written in the log: ``"c2-c4-c1-c3"``."""
        return tuple("-".join(r) for r in self.rounds)


def arm_sequence(protocol: Protocol, n: int) -> list[str]:
    """The arms of sessions 1..n; the sequence of ``n`` is always a prefix of that of ``n + 1``."""
    if not protocol.arms:
        return [""] * n
    return permuted_blocks(
        protocol.arms,
        protocol.arm_weights,
        protocol.arm_block_sizes,
        n,
        Stream(protocol.seed, "arms"),
    )


def round_orders(protocol: Protocol, session: int) -> tuple[tuple[str, ...], ...]:
    """The order of the conditions in each round of one session (independent of the others)."""
    if not protocol.conditions:
        return ()
    return tuple(
        block_orders(
            protocol.conditions,
            protocol.n_rounds,
            protocol.design,
            Stream(protocol.seed, "orders", session),
        )
    )


def draw(protocol: Protocol, session: int) -> Allocation:
    """The allocation of session number ``session`` (1, 2, 3, ...), a pure function."""
    if isinstance(session, bool) or not isinstance(session, int) or session < 1:
        raise ValueError("session numbers start at 1")
    return Allocation(
        session=session,
        arm=arm_sequence(protocol, session)[session - 1],
        rounds=round_orders(protocol, session),
    )
