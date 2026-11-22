"""How lopsided can a small study get? Coin tossing against permuted blocks.

    python examples/imbalance.py                      # 20 participants, 20 000 simulated studies
    python examples/imbalance.py --n 30 --studies 5000

For coin tossing the table also shows the exact binomial probability, which the simulation
should match; for permuted blocks (sizes 4 and 6) the imbalance is bounded by construction.
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Sequence
from math import comb

import exprand as ex

THRESHOLDS = (4, 6, 8)


def exact_coin(n: int, threshold: int) -> float:
    """P(|nA - nB| >= threshold) when each of ``n`` participants is a fair coin toss."""
    return sum(comb(n, k) for k in range(n + 1) if abs(2 * k - n) >= threshold) / 2**n


def main(argv: Sequence[str] | None = None) -> dict[str, list[int]]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=20, help="participants per study")
    parser.add_argument("--studies", type=int, default=20000, help="simulated studies")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    coin, blocks = [], []
    for i in range(args.studies):
        a = sum(rng.random() < 0.5 for _ in range(args.n))
        coin.append(abs(2 * a - args.n))
        seq = ex.permuted_blocks(["A", "B"], [1, 1], [4, 6], args.n, ex.Stream(args.seed, "s", i))
        blocks.append(abs(seq.count("A") - seq.count("B")))

    print(f"{args.n} participants, two arms, {args.studies} simulated studies")
    print("share of studies that end with a difference of at least ... between the arms:\n")
    print(
        f"{'':>26}"
        + "".join(
            f"{f'{t} (e.g. {(args.n + t) // 2}-{(args.n - t) // 2})':>14}" for t in THRESHOLDS
        )
    )
    simulated = "".join(f"{sum(d >= t for d in coin) / args.studies:>14.1%}" for t in THRESHOLDS)
    print(f"{'coin tossing (simulated)':>26}{simulated}")
    exact = "".join(f"{exact_coin(args.n, t):>14.1%}" for t in THRESHOLDS)
    print(f"{'coin tossing (exact)':>26}{exact}")
    permuted = "".join(f"{sum(d >= t for d in blocks) / args.studies:>14.1%}" for t in THRESHOLDS)
    print(f"{'permuted blocks 4 and 6':>26}{permuted}")
    print(f"\nlargest difference seen: coin tossing {max(coin)}, permuted blocks {max(blocks)}")
    return {"coin": coin, "blocks": blocks}


if __name__ == "__main__":
    main()
