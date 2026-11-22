import json
from collections import Counter

import pytest

from exprand import LogError, Protocol, Study, draw
from exprand.log import Entry, format_header, format_row, make_entry, read_entries

# ------------------------------------------------------------------ helpers


def read_raw(path):
    """A file's text with its line ends untouched (``Path.read_text`` only learnt that in 3.13)."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def lines(study):
    return read_raw(study.log_path).split("\r\n")[:-1]


def write_lines(study, rows):
    study.log_path.write_text("\r\n".join(rows) + "\r\n", encoding="utf-8-sig", newline="")


def fill(study, n=6):
    return [study.next() for _ in range(n)]


def rebuild_chain(study, entries):
    """What a forger would do: edit rows, then recompute every hash from the protocol onwards."""
    fixed: list[Entry] = []
    for e in entries:
        alloc = None
        if e.kind == "draw":
            alloc = type("A", (), {"arm": e.arm, "round_strings": lambda self, e=e: e.rounds})()
        fixed.append(
            make_entry(
                study.protocol, fixed, kind=e.kind, session=e.session,
                timestamp=e.timestamp, allocation=alloc, note=e.note,
            )
        )  # fmt: skip
    text = format_header(study.protocol.n_rounds) + "".join(format_row(e) for e in fixed)
    study.log_path.write_text(text, encoding="utf-8-sig", newline="")


# ------------------------------------------------------------------ creating a study
def test_init_writes_the_protocol_and_refuses_to_overwrite_it(tmp_path, protocol):
    study = Study.init(tmp_path / "new" / "deeper", protocol)
    assert study.protocol == protocol
    assert json.loads(study.protocol_path.read_text())["seed"] == 123
    with pytest.raises(FileExistsError, match="cannot change"):
        Study.init(tmp_path / "new" / "deeper", Protocol(arms=("A", "B"), seed=1))
    assert Study(tmp_path / "new" / "deeper").protocol == protocol


def test_opening_a_folder_without_a_study_says_how_to_create_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="exprand init"):
        Study(tmp_path)


# ------------------------------------------------------------------ drawing
def test_next_numbers_sessions_consecutively_and_matches_the_pure_draw(study):
    drawn = fill(study, 5)
    assert [a.session for a in drawn] == [1, 2, 3, 4, 5]
    assert drawn == [draw(study.protocol, k) for k in range(1, 6)]


def test_numbering_continues_after_reopening(study):
    fill(study, 3)
    again = Study(study.directory)
    assert again.next().session == 4


def test_the_log_is_semicolon_utf8_bom_crlf_with_the_header_once(study):
    fill(study, 3)
    raw = study.log_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbfkind;session;timestamp;arm;round_1;")
    assert raw.count(b"\xef\xbb\xbf") == 1 and raw.count(b"\r\n") == 4
    assert raw.count(b"kind;session") == 1


def test_a_draw_is_on_disk_before_it_is_returned(study, monkeypatch):
    seen = {}
    real = study._append

    def spy(entry):
        real(entry)
        seen["rows"] = len(lines(study))

    monkeypatch.setattr(study, "_append", spy)
    study.next()
    assert seen["rows"] == 2  # header + the new row, written inside next()


def test_arms_stay_balanced_in_every_prefix(study):
    arms = [a.arm for a in fill(study, 40)]
    diff = 0
    for arm in arms:
        diff += 1 if arm == "A" else -1
        assert abs(diff) <= 3
    assert abs(Counter(arms)["A"] - Counter(arms)["B"]) <= 2


def test_notes_and_timestamps_are_stored_and_sanitised(study):
    study.next(note="=cmd|' /C calc'!A0", now="2026-03-04T05:06:07-03:00")
    study.next(note="não compareceu")
    first, second = study.entries()
    assert first.timestamp == "2026-03-04T05:06:07-03:00"
    assert first.note.startswith("'=cmd")
    assert second.note == "não compareceu" and "T" in second.timestamp
    assert study.verify().ok


def test_a_study_without_arms_or_without_conditions_works(tmp_path):
    arms_only = Study.init(tmp_path / "a", Protocol(arms=("A", "B"), seed=1))
    fill(arms_only, 5)
    assert lines(arms_only)[0].lstrip("﻿") == "kind;session;timestamp;arm;note;hash"
    report = arms_only.verify()
    assert report.ok and sum(report.arm_counts.values()) == 5
    orders_only = Study.init(
        tmp_path / "o", Protocol(conditions=("x", "y", "z"), n_rounds=2, design="latin", seed=1)
    )
    fill(orders_only, 5)
    report = orders_only.verify()
    assert report.ok and report.arm_counts == {} and report.imbalance == 0
    assert all(e.arm == "" for e in orders_only.entries())


def test_a_log_file_that_is_empty_or_only_a_header_still_works(study):
    study.log_path.write_bytes(b"")
    assert study.next().session == 1
    assert study.log_path.read_bytes().count(b"kind;session") == 1
    study.log_path.write_text(
        format_header(5), encoding="utf-8-sig", newline=""
    )  # a header and no rows
    assert study.next().session == 1
    assert study.log_path.read_bytes().count(b"kind;session") == 1


# ------------------------------------------------------------------ notes about sessions
def test_annotate_adds_a_note_row_without_touching_the_rest(study):
    fill(study, 3)
    before = lines(study)
    study.annotate(2, "participant did not attend")
    after = lines(study)
    assert after[:-1] == before and len(after) == len(before) + 1
    note = study.entries()[-1]
    assert (note.kind, note.session, note.note) == ("note", 2, "participant did not attend")
    assert study.verify().n_notes == 1 and study.verify().ok
    assert study.next().session == 4  # notes do not use up session numbers


def test_annotate_validates_its_input(study):
    fill(study, 2)
    for session in (0, 3, -1):
        with pytest.raises(ValueError, match="has not been drawn"):
            study.annotate(session, "x")
    with pytest.raises(ValueError, match="empty"):
        study.annotate(1, "   ")


# ------------------------------------------------------------------ verification
def test_verify_reports_counts_and_the_chain_head(study):
    fill(study, 8)
    report = study.verify()
    assert report.ok and report.problems == [] and report.n_sessions == 8
    assert sum(report.arm_counts.values()) == 8 and report.imbalance <= 3
    assert report.head == study.head() == study.entries()[-1].hash
    assert Study.init(study.directory.parent / "fresh", study.protocol).verify().head == (
        study.protocol.hash
    )


def edit_cell(index, column, value):
    def apply(rows):
        cells = rows[index].split(";")
        cells[column] = value
        rows[index] = ";".join(cells)

    return apply


def delete_row(index):
    return lambda rows: rows.pop(index)


def swap_rows(i, j):
    def apply(rows):
        rows[i], rows[j] = rows[j], rows[i]

    return apply


def duplicate_row(index):
    return lambda rows: rows.insert(index + 1, rows[index])


def forged_row(rows):
    rows.append("draw;7;2026-01-01T00:00:00+00:00;A;c1-c2-c3-c4;c1-c2-c3-c4;c1-c2-c3-c4;"
                "c1-c2-c3-c4;c1-c2-c3-c4;;" + "0" * 64)  # fmt: skip


@pytest.mark.parametrize(
    "tamper, line",
    [
        pytest.param(edit_cell(2, 4, "c4-c3-c2-c1"), 3, id="edit a round"),
        pytest.param(edit_cell(2, 2, "2020-01-01T00:00:00+00:00"), 3, id="edit a timestamp"),
        pytest.param(edit_cell(5, 1, "9"), 6, id="edit a session number"),
        pytest.param(delete_row(3), 4, id="delete a row"),
        pytest.param(swap_rows(2, 4), 3, id="swap two rows"),
        pytest.param(duplicate_row(2), 4, id="duplicate a row"),
        pytest.param(forged_row, 9, id="append a forged row"),
    ],
)
def test_any_edit_of_the_log_is_found(study, tamper, line):
    """Rows are numbered from the header (line 1): six sessions and a note fill lines 2-8."""
    fill(study, 6)
    study.annotate(3, "kept")
    rows = lines(study)
    tamper(rows)
    write_lines(study, rows)
    report = study.verify()
    assert not report.ok
    assert any(f"line {line}:" in p for p in report.problems), report.problems


def test_editing_the_arm_is_always_found(study):
    fill(study, 6)
    rows = lines(study)
    original_arm = rows[3].split(";")[3]
    edit_cell(3, 3, "B" if original_arm == "A" else "A")(rows)
    write_lines(study, rows)
    assert not study.verify().ok


def test_editing_the_note_is_found(study):
    fill(study, 3)
    study.annotate(1, "original remark")
    rows = lines(study)
    rows[-1] = rows[-1].replace("original remark", "changed remark")
    write_lines(study, rows)
    assert not study.verify().ok


def test_a_truncated_last_line_is_found(study):
    fill(study, 3)
    raw = study.log_path.read_bytes()
    study.log_path.write_bytes(raw[:-40])
    report = study.verify()
    assert not report.ok


def test_changing_the_protocol_after_the_first_session_is_found(study):
    fill(study, 3)
    data = json.loads(study.protocol_path.read_text())
    data["seed"] += 1
    study.protocol_path.write_text(json.dumps(data))
    report = Study(study.directory).verify()
    assert not report.ok
    assert any("does not chain to this protocol" in p for p in report.problems)


def test_a_forger_who_recomputes_every_hash_is_caught_by_regeneration(study):
    fill(study, 6)
    entries = study.entries()
    other_arm = "B" if entries[2].arm == "A" else "A"
    entries[2] = Entry(**{**entries[2].__dict__, "arm": other_arm})
    rebuild_chain(study, entries)
    report = study.verify()
    assert not report.ok
    assert any("not what the protocol and seed produce" in p for p in report.problems)
    assert not any("matches its hash" in p for p in report.problems)  # the chain itself is fine


def test_a_forger_who_also_rewrites_the_protocol_is_caught_by_the_written_down_head(study):
    fill(study, 4)
    honest_head = study.head()
    data = json.loads(study.protocol_path.read_text())
    data["seed"] = 999
    study.protocol_path.write_text(json.dumps(data))
    forged = Study(study.directory)
    new_entries = [
        make_entry(forged.protocol, [], kind="draw", session=1, timestamp="t",
                   allocation=draw(forged.protocol, 1))
    ]  # fmt: skip
    for k in range(2, 5):
        new_entries.append(
            make_entry(forged.protocol, new_entries, kind="draw", session=k, timestamp="t",
                       allocation=draw(forged.protocol, k))
        )  # fmt: skip
    text = format_header(5) + "".join(format_row(e) for e in new_entries)
    forged.log_path.write_text(text, encoding="utf-8-sig", newline="")
    assert forged.verify().ok  # internally consistent...
    report = forged.verify(expect_head=honest_head)
    assert not report.ok and "not the one you expected" in report.problems[-1]


def test_next_refuses_to_add_to_a_log_that_fails_verification(study):
    fill(study, 3)
    rows = lines(study)
    edit_cell(2, 4, "c4-c3-c2-c1")(rows)
    write_lines(study, rows)
    before = study.log_path.read_bytes()
    with pytest.raises(LogError, match="Refusing to add"):
        study.next()
    with pytest.raises(LogError, match="Refusing to add"):
        study.annotate(1, "x")
    assert study.log_path.read_bytes() == before


def test_a_log_opened_and_saved_by_a_spreadsheet_with_lf_endings_still_verifies(study):
    fill(study, 4)
    text = read_raw(study.log_path)
    study.log_path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="")
    assert study.verify().ok
    assert study.next().session == 5


def test_an_unreadable_log_is_reported_not_raised_by_verify(study):
    study.log_path.write_text("this is not a log\n", encoding="utf-8")
    report = study.verify()
    assert not report.ok and "header" in report.problems[0]
    assert read_entries(study.log_path.with_name("absent.csv"), 5) == []


def test_cutting_off_the_latest_sessions_is_invisible_without_a_written_down_head(study):
    """The honest limit of a hash chain: a shorter log is still a valid log."""
    fill(study, 5)
    head_after_five = study.head()
    write_lines(study, lines(study)[:-2])  # remove sessions 4 and 5
    assert study.verify().ok  # nothing inside the file betrays it...
    report = study.verify(expect_head=head_after_five)  # ...but the head noted earlier does
    assert not report.ok and "not the one you expected" in report.problems[-1]
    assert study.next().session == 4  # and the numbers 4 and 5 would be reused


def test_entry_for_finds_the_row_of_a_drawn_session(study):
    fill(study, 3)
    study.annotate(2, "a note about 2")
    assert study.entry_for(2).kind == "draw" and study.entry_for(2).note == ""
    with pytest.raises(ValueError, match="has not been drawn"):
        study.entry_for(4)
