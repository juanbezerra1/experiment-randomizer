import pytest

from exprand import Protocol, draw
from exprand.log import (
    Entry,
    LogError,
    check,
    clean_note,
    format_header,
    format_row,
    head_hash,
    header,
    make_entry,
    read_entries,
    row_hash,
)

P = Protocol(arms=("A", "B"), conditions=("c1", "c2", "c3"), n_rounds=2, seed=5)


def build(n, protocol=P):
    entries: list[Entry] = []
    for k in range(1, n + 1):
        entries.append(
            make_entry(
                protocol, entries, kind="draw", session=k,
                timestamp=f"2026-01-01T10:00:0{k}+00:00", allocation=draw(protocol, k),
            )
        )  # fmt: skip
    return entries


def test_header_has_one_column_per_round():
    assert header(2) == [
        "kind",
        "session",
        "timestamp",
        "arm",
        "round_1",
        "round_2",
        "note",
        "hash",
    ]
    assert header(0) == ["kind", "session", "timestamp", "arm", "note", "hash"]


def test_a_clean_chain_passes_and_starts_from_the_protocol():
    entries = build(5)
    assert check(P, entries) == []
    assert entries[0].hash == row_hash(P.hash, entries[0].fields())
    assert head_hash(P, entries) == entries[-1].hash
    assert head_hash(P, []) == P.hash


def test_the_hash_depends_on_the_previous_hash_and_on_every_field():
    fields = ["draw", "1", "t", "A", "c1-c2", "c2-c1", ""]
    base = row_hash("x", fields)
    assert row_hash("y", fields) != base
    for i in range(len(fields)):
        changed = list(fields)
        changed[i] += "z"
        assert row_hash("x", changed) != base


def test_notes_are_one_short_line_that_cannot_be_a_formula():
    assert clean_note("  did   not\tattend \n today ") == "did not attend today"
    assert clean_note("não compareceu") == "não compareceu"
    for risky in ("=1+1", "+1", "-1", "@SUM(A1)"):
        assert clean_note(risky) == "'" + risky
    assert clean_note("") == ""
    with pytest.raises(ValueError, match="control"):
        clean_note("bell\x07")
    with pytest.raises(ValueError, match="limited"):
        clean_note("x" * 301)


def test_read_entries_round_trips_what_format_row_writes(tmp_path):
    entries = build(3)
    path = tmp_path / "log.csv"
    text = format_header(2) + "".join(format_row(e) for e in entries)
    path.write_text(text, encoding="utf-8-sig", newline="")
    assert read_entries(path, 2) == entries
    assert read_entries(tmp_path / "missing.csv", 2) == []
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    assert read_entries(empty, 2) == []


@pytest.mark.parametrize(
    "text, message",
    [
        ("wrong;header\r\n", "header does not match"),
        (format_header(2) + "draw;1;t;A\r\n", "expected 8 fields"),
        (format_header(2) + "draw;x;t;A;c1-c2;c2-c1;;h\r\n", "bad session number"),
    ],
)
def test_unreadable_logs_raise_log_error(tmp_path, text, message):
    path = tmp_path / "log.csv"
    # newline="" keeps the \r\n above as written; in text mode Windows would make it \r\r\n
    path.write_text(text, encoding="utf-8", newline="")
    with pytest.raises(LogError, match=message):
        read_entries(path, 2)


def test_a_file_that_is_not_text_raises_log_error(tmp_path):
    path = tmp_path / "log.csv"
    path.write_bytes(b"\xff\xfe\x00\x00 not utf-8 \x80\x81")
    with pytest.raises(LogError, match="cannot read"):
        read_entries(path, 2)


def test_check_reports_unknown_kinds_and_notes_about_the_future():
    entries = build(2)
    bad = make_entry(P, entries, kind="oops", session=3, timestamp="t")
    problems = check(P, [*entries, bad])
    assert any("unknown kind" in p for p in problems)
    early = make_entry(P, entries, kind="note", session=9, timestamp="t", note="x")
    assert any("not drawn yet" in p for p in check(P, [*entries, early]))


def test_a_huge_forged_session_number_does_not_hang_the_check():
    entries = build(2)
    forged = make_entry(
        P, entries, kind="draw", session=10**9, timestamp="t",
        allocation=draw(P, 3),
    )  # fmt: skip
    problems = check(P, [*entries, forged])
    assert any("must be consecutive" in p for p in problems)
