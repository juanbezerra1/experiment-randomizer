from collections import Counter
from itertools import pairwise

import pytest

from exprand import Stream, block_orders, latin_rows, permuted_blocks, williams_rows


def running_imbalance(sequence, a="A", b="B"):
    diff, worst = 0, 0
    for item in sequence:
        diff += (item == a) - (item == b)
        worst = max(worst, abs(diff))
    return worst


# ------------------------------------------------------------------ permuted blocks
def test_every_complete_block_has_the_planned_proportions():
    sequence = permuted_blocks(["A", "B"], [1, 1], [4], 20, Stream(1, "t"))
    assert len(sequence) == 20
    for start in range(0, 20, 4):
        assert Counter(sequence[start : start + 4]) == {"A": 2, "B": 2}


def test_unequal_ratios_hold_in_every_block():
    sequence = permuted_blocks(["A", "B"], [2, 1], [6], 30, Stream(2, "t"))
    for start in range(0, 30, 6):
        assert Counter(sequence[start : start + 6]) == {"A": 4, "B": 2}
    assert Counter(sequence) == {"A": 20, "B": 10}


def test_three_arms():
    sequence = permuted_blocks(["A", "B", "C"], [1, 1, 1], [3, 6], 60, Stream(3, "t"))
    assert max(Counter(sequence).values()) - min(Counter(sequence).values()) <= 3


@pytest.mark.parametrize("seed", range(150))
def test_imbalance_never_exceeds_half_the_largest_block(seed):
    sequence = permuted_blocks(["A", "B"], [1, 1], [4, 6], 50, Stream(seed, "t"))
    assert running_imbalance(sequence) <= 3


def test_a_longer_sequence_extends_a_shorter_one():
    short = permuted_blocks(["A", "B"], [1, 1], [4, 6], 9, Stream(5, "t"))
    long = permuted_blocks(["A", "B"], [1, 1], [4, 6], 40, Stream(5, "t"))
    assert long[:9] == short
    assert permuted_blocks(["A", "B"], [1, 1], [4], 0, Stream(5, "t")) == []


def test_the_first_assignment_is_fair():
    firsts = Counter(
        permuted_blocks(["A", "B"], [1, 1], [4, 6], 1, Stream(s, "t"))[0] for s in range(2000)
    )
    assert 900 < firsts["A"] < 1100  # about 4.5 standard deviations


@pytest.mark.parametrize(
    "labels, weights, sizes",
    [
        (["A", "B"], [1, 1], [3]),  # not a multiple of 2
        (["A", "B"], [2, 1], [4]),  # not a multiple of 3
        (["A", "B"], [1, 1], []),
        (["A", "B"], [1, 1], [0]),
        (["A", "B"], [1, 0], [2]),
        (["A", "B"], [1], [2]),
        ([], [], [2]),
    ],
)
def test_bad_block_plans_are_rejected(labels, weights, sizes):
    with pytest.raises(ValueError):
        permuted_blocks(labels, weights, sizes, 4, Stream(1))


# ------------------------------------------------------------------ squares
@pytest.mark.parametrize("n", range(2, 9))
def test_latin_rows_are_a_latin_square(n):
    rows = latin_rows(n)
    assert len(rows) == n
    assert all(sorted(row) == list(range(n)) for row in rows)
    assert all(sorted(col) == list(range(n)) for col in zip(*rows, strict=True))


def pair_counts(rows):
    return Counter(pair for row in rows for pair in pairwise(row))


@pytest.mark.parametrize("n", [2, 4, 6, 8, 10])
def test_williams_even_balances_position_and_carryover(n):
    rows = williams_rows(n)
    assert len(rows) == n
    assert all(sorted(row) == list(range(n)) for row in rows)
    assert all(sorted(col) == list(range(n)) for col in zip(*rows, strict=True))
    counts = pair_counts(rows)
    assert len(counts) == n * (n - 1) and set(counts.values()) == {1}


@pytest.mark.parametrize("n", [3, 5, 7])
def test_williams_odd_needs_twice_the_rows(n):
    rows = williams_rows(n)
    assert len(rows) == 2 * n
    assert all(sorted(row) == list(range(n)) for row in rows)
    for col in zip(*rows, strict=True):
        assert set(Counter(col).values()) == {2}
    counts = pair_counts(rows)
    assert len(counts) == n * (n - 1) and set(counts.values()) == {2}


@pytest.mark.parametrize("make", [latin_rows, williams_rows])
def test_squares_need_two_conditions(make):
    with pytest.raises(ValueError):
        make(1)


# ------------------------------------------------------------------ orders within a session
CONDITIONS = ["c1", "c2", "c3", "c4"]


def test_shuffle_rounds_are_permutations_and_not_all_alike():
    rounds = block_orders(CONDITIONS, 8, "shuffle", Stream(1, "o"))
    assert all(sorted(r) == CONDITIONS for r in rounds)
    assert len(set(rounds)) > 1


def test_latin_orders_put_every_condition_in_every_position_once():
    rounds = block_orders(CONDITIONS, 4, "latin", Stream(2, "o"))
    for position in zip(*rounds, strict=True):
        assert sorted(position) == CONDITIONS


def test_williams_orders_balance_carryover_over_a_full_cycle():
    rounds = block_orders(CONDITIONS, 4, "williams", Stream(3, "o"))
    for position in zip(*rounds, strict=True):
        assert sorted(position) == CONDITIONS
    counts = pair_counts(rounds)
    assert len(counts) == 12 and set(counts.values()) == {1}


def test_williams_with_three_conditions_balances_over_six_rounds():
    rounds = block_orders(["x", "y", "z"], 6, "williams", Stream(4, "o"))
    counts = pair_counts(rounds)
    assert len(counts) == 6 and set(counts.values()) == {2}


@pytest.mark.parametrize("design", ["shuffle", "latin", "williams"])
def test_the_first_condition_of_a_session_is_uniform_across_sessions(design):
    firsts = Counter(block_orders(CONDITIONS, 4, design, Stream(s, "o"))[0][0] for s in range(2000))
    assert all(400 < c < 600 for c in firsts.values()) and len(firsts) == 4


@pytest.mark.parametrize("design", ["shuffle", "latin", "williams"])
def test_orders_are_deterministic(design):
    assert block_orders(CONDITIONS, 5, design, Stream(9, "o")) == block_orders(
        CONDITIONS, 5, design, Stream(9, "o")
    )


def test_bad_orders_are_rejected():
    with pytest.raises(ValueError, match="unknown design"):
        block_orders(CONDITIONS, 3, "random", Stream(1))
    with pytest.raises(ValueError):
        block_orders(["only"], 3, "shuffle", Stream(1))
    with pytest.raises(ValueError):
        block_orders(CONDITIONS, 0, "shuffle", Stream(1))
