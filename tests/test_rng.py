from collections import Counter

import pytest

from exprand import Stream


def numbers(stream, n=40, high=10**9):
    return [stream.below(high) for _ in range(n)]


def test_the_same_seed_and_path_give_the_same_numbers():
    assert numbers(Stream(1, "x", 2)) == numbers(Stream(1, "x", 2))


def test_a_different_seed_or_path_gives_a_different_stream():
    streams = [Stream(1, "x"), Stream(2, "x"), Stream(1, "y"), Stream(1, "x", 0), Stream(1)]
    assert len({tuple(numbers(s)) for s in streams}) == len(streams)


def test_path_elements_cannot_run_into_each_other():
    assert numbers(Stream(1, "a", "b")) != numbers(Stream(1, "a|b"))
    assert numbers(Stream(1, 2)) != numbers(Stream(1, "2"))


def test_known_answers_never_change():
    """These numbers are the promise that an old log can be regenerated on any Python."""
    stream = Stream(12345, "demo")
    assert [stream.below(100) for _ in range(10)] == [6, 84, 34, 15, 82, 69, 62, 42, 75, 18]
    items = list(range(8))
    Stream(12345, "shuffle").shuffle(items)
    assert items == [2, 1, 7, 5, 6, 0, 4, 3]


def test_below_is_uniform():
    stream = Stream(7, "uniform")
    counts = Counter(stream.below(6) for _ in range(60000))
    assert set(counts) == set(range(6))
    assert all(abs(c - 10000) < 600 for c in counts.values())  # about 6 standard deviations


def test_shuffle_reaches_every_permutation_equally_often():
    stream = Stream(8, "perm")
    counts: Counter[tuple[int, ...]] = Counter()
    for _ in range(60000):
        items = [0, 1, 2]
        stream.shuffle(items)
        counts[tuple(items)] += 1
    assert len(counts) == 6
    assert all(abs(c - 10000) < 600 for c in counts.values())


def test_shuffle_handles_tiny_inputs():
    for items in ([], [1]):
        Stream(1).shuffle(items)
    assert Stream(1).below(1) == 0


@pytest.mark.parametrize("seed", [-1, 1.5, "1", True, None])
def test_the_seed_must_be_a_non_negative_integer(seed):
    with pytest.raises(ValueError, match="seed"):
        Stream(seed)


def test_below_needs_a_positive_bound():
    with pytest.raises(ValueError):
        Stream(1).below(0)
