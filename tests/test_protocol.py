import json

import pytest

from exprand import Protocol, arm_sequence, draw, round_orders


def make(**kwargs):
    base = {"arms": ("A", "B"), "conditions": ("c1", "c2", "c3", "c4"), "n_rounds": 2, "seed": 123}
    return Protocol(**{**base, **kwargs})


# ------------------------------------------------------------------ construction
def test_defaults_are_equal_arms_and_small_varying_blocks():
    p = make()
    assert p.arm_weights == (1, 1) and p.arm_block_sizes == (4, 6) and p.design == "shuffle"
    assert make(arms=("A", "B"), arm_weights=(2, 1)).arm_block_sizes == (6, 9)


def test_arms_only_and_conditions_only_studies_are_allowed():
    arms_only = Protocol(arms=("A", "B"), seed=1)
    assert arms_only.conditions == () and arms_only.n_rounds == 0
    orders_only = Protocol(conditions=("x", "y"), n_rounds=3, seed=1)
    assert orders_only.arms == () and orders_only.arm_block_sizes == ()


def test_the_seed_is_random_unless_given():
    seeds = {Protocol(arms=("A", "B")).seed for _ in range(5)}
    assert len(seeds) == 5 and all(0 <= s < 2**64 for s in seeds)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"arms": (), "conditions": ()}, "arms, conditions"),
        ({"arms": ("A",)}, "two arms"),
        ({"conditions": ("c1",)}, "two conditions"),
        ({"arms": ("A", "A")}, "duplicate"),
        ({"conditions": ("c1", "c1")}, "duplicate"),
        ({"arms": ("A B", "C")}, "invalid arm label"),
        ({"arms": ("A", "B;C")}, "invalid arm label"),
        ({"arms": ("=A", "B")}, "invalid arm label"),
        ({"conditions": ("c-1", "c2")}, "invalid condition label"),
        ({"conditions": ("", "c2")}, "invalid condition label"),
        ({"arm_weights": (1,)}, "one positive integer per arm"),
        ({"arm_weights": (1, 0)}, "one positive integer per arm"),
        ({"arm_block_sizes": (3,)}, "multiples of 2"),
        ({"arm_weights": (2, 1), "arm_block_sizes": (4,)}, "multiples of 3"),
        ({"n_rounds": 0}, "at least 1"),
        ({"n_rounds": 2.5}, "integer"),
        ({"design": "random"}, "unknown design"),
        ({"seed": -1}, "seed"),
        ({"seed": True}, "seed"),
    ],
)
def test_invalid_protocols_are_rejected_with_a_reason(kwargs, message):
    with pytest.raises(ValueError, match=message):
        make(**kwargs)


def test_options_that_need_arms_or_conditions_are_rejected_without_them():
    with pytest.raises(ValueError, match="need arms"):
        Protocol(conditions=("x", "y"), n_rounds=1, arm_weights=(1, 1))
    with pytest.raises(ValueError, match="needs conditions"):
        Protocol(arms=("A", "B"), n_rounds=3)


# ------------------------------------------------------------------ serialisation
def test_json_round_trip_and_hash_are_stable():
    p = make()
    assert Protocol.from_json(p.to_json()) == p
    assert Protocol.from_json(p.to_json()).hash == p.hash


def test_the_hash_ignores_formatting_but_not_content():
    p = make()
    data = p.to_dict()
    reordered = json.dumps(dict(reversed(list(data.items()))), indent=8)
    assert Protocol.from_json(reordered).hash == p.hash
    assert make(seed=124).hash != p.hash
    assert make(design="latin").hash != p.hash


def test_known_hash_never_changes():
    p = make()
    assert p.canonical_json() == (
        '{"arm_block_sizes":[4,6],"arm_weights":[1,1],"arms":["A","B"],'
        '"conditions":["c1","c2","c3","c4"],"design":"shuffle","format":1,"n_rounds":2,"seed":123}'
    )
    assert p.hash == "6e6b3f5a322de0bd12bbd41814fa134d113b6607a4e4ff38110af94308796717"


@pytest.mark.parametrize(
    "text, message",
    [
        ("{not json", "not valid JSON"),
        ("[1, 2]", "JSON object"),
        ('{"format": 2}', "unsupported protocol format"),
        ('{"format": 1, "arms": ["A", "B"]}', "missing the field"),
    ],
)
def test_broken_protocol_files_give_clear_errors(text, message):
    with pytest.raises(ValueError, match=message):
        Protocol.from_json(text)


# ------------------------------------------------------------------ drawing
def test_draw_is_a_pure_function_of_protocol_and_session():
    p = make()
    first = [draw(p, k) for k in range(1, 12)]
    again = [draw(p, k) for k in reversed(range(1, 12))][::-1]
    assert first == again
    assert draw(p, 7) == draw(make(), 7)


def test_known_allocations_never_change():
    p = make()
    assert arm_sequence(p, 12) == list("AABBBABABAAA")
    a1, a2, a3 = (draw(p, k) for k in (1, 2, 3))
    assert (a1.arm, a1.round_strings()) == ("A", ("c2-c4-c3-c1", "c2-c1-c3-c4"))
    assert (a2.arm, a2.round_strings()) == ("A", ("c3-c2-c1-c4", "c2-c3-c4-c1"))
    assert (a3.arm, a3.round_strings()) == ("B", ("c4-c3-c2-c1", "c1-c3-c4-c2"))
    q = make(n_rounds=4, design="williams")
    assert draw(q, 1).round_strings() == (
        "c1-c2-c3-c4",
        "c2-c4-c1-c3",
        "c4-c3-c2-c1",
        "c3-c1-c4-c2",
    )


def test_arms_follow_the_permuted_block_sequence_and_orders_are_independent_of_it():
    p = make()
    assert [draw(p, k).arm for k in range(1, 31)] == arm_sequence(p, 30)
    # changing the arm plan does not disturb any session's condition orders
    other = make(arm_block_sizes=(2,))
    assert [round_orders(p, k) for k in range(1, 6)] == [
        round_orders(other, k) for k in range(1, 6)
    ]


def test_sessions_get_different_orders():
    p = make(n_rounds=3)
    assert len({round_orders(p, k) for k in range(1, 40)}) > 30


def test_each_arm_gets_about_half_across_seeds():
    firsts = sum(draw(make(seed=s), 1).arm == "A" for s in range(1000))
    assert 440 < firsts < 560


def test_arms_only_and_conditions_only_allocations():
    a = draw(Protocol(arms=("A", "B"), seed=1), 3)
    assert a.arm in ("A", "B") and a.rounds == () and a.round_strings() == ()
    b = draw(Protocol(conditions=("x", "y", "z"), n_rounds=2, seed=1), 3)
    assert b.arm == "" and len(b.rounds) == 2


@pytest.mark.parametrize("session", [0, -1, 1.5, True, "1"])
def test_session_numbers_start_at_one(session):
    with pytest.raises(ValueError, match="start at 1"):
        draw(make(), session)
