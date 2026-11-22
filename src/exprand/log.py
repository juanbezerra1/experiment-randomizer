"""The session log: an append-only CSV in which every row is chained to the one before it.

Each row carries ``hash = SHA-256(previous hash + "\\n" + the row's own fields)``, and the first
row chains to the hash of the protocol. Editing a cell, deleting, inserting or reordering a row,
or changing the protocol after the first session, breaks every hash from that point on, so
:func:`check` finds it. Because the arms and orders are also *regenerated* from the protocol and
compared with what the log says, a row that was edited together with its hash is caught as well,
unless the protocol was edited too and every hash recomputed. Writing the latest hash somewhere
else (a lab notebook, an e-mail to a colleague) closes that last gap: ``check(..., expect_head=)``.

The file is ``;``-separated, UTF-8 with a byte-order mark and CRLF line ends, which is what
spreadsheet programs in many locales open directly.

Columns: ``kind;session;timestamp;arm;round_1;...;round_n;note;hash``. ``kind`` is ``draw`` for a
session and ``note`` for a remark about an earlier session; rows are never changed or removed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .protocol import Allocation, Protocol, arm_sequence, round_orders

__all__ = [
    "Entry",
    "LogError",
    "check",
    "clean_note",
    "format_row",
    "head_hash",
    "header",
    "read_entries",
    "row_hash",
]

DRAW, NOTE = "draw", "note"
MAX_NOTE = 300


class LogError(Exception):
    """The log file is unreadable or fails verification."""


@dataclass(frozen=True)
class Entry:
    kind: str
    session: int
    timestamp: str
    arm: str
    rounds: tuple[str, ...]
    note: str
    hash: str

    def fields(self) -> list[str]:
        """The fields the hash covers: everything but the hash itself."""
        return [self.kind, str(self.session), self.timestamp, self.arm, *self.rounds, self.note]


def header(n_rounds: int) -> list[str]:
    return [
        "kind",
        "session",
        "timestamp",
        "arm",
        *(f"round_{i}" for i in range(1, n_rounds + 1)),
        "note",
        "hash",
    ]


def clean_note(text: str) -> str:
    """One short line of plain text that a spreadsheet will not mistake for a formula."""
    text = " ".join(text.split())
    if any(ord(ch) < 32 for ch in text):
        raise ValueError("notes cannot contain control characters")
    if len(text) > MAX_NOTE:
        raise ValueError(f"notes are limited to {MAX_NOTE} characters")
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return text


def row_hash(previous: str, fields: Sequence[str]) -> str:
    body = json.dumps(list(fields), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{previous}\n{body}".encode()).hexdigest()


def head_hash(protocol: Protocol, entries: Sequence[Entry]) -> str:
    """The hash of the last row, or of the protocol when nothing has been drawn yet."""
    return entries[-1].hash if entries else protocol.hash


def make_entry(
    protocol: Protocol,
    entries: Sequence[Entry],
    *,
    kind: str,
    session: int,
    timestamp: str,
    allocation: Allocation | None = None,
    note: str = "",
) -> Entry:
    arm = allocation.arm if allocation else ""
    rounds = allocation.round_strings() if allocation else ("",) * protocol.n_rounds
    fields = [kind, str(session), timestamp, arm, *rounds, note]
    return Entry(
        kind=kind,
        session=session,
        timestamp=timestamp,
        arm=arm,
        rounds=tuple(rounds),
        note=note,
        hash=row_hash(head_hash(protocol, entries), fields),
    )


def format_row(entry: Entry) -> str:
    """The CSV text of one entry, with its line end."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerow([*entry.fields(), entry.hash])
    return buffer.getvalue()


def format_header(n_rounds: int) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerow(header(n_rounds))
    return buffer.getvalue()


def read_entries(path: Path, n_rounds: int) -> list[Entry]:
    """Parse the log; raises :class:`LogError` if it is not a log of this protocol's shape."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=";"))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise LogError(f"cannot read {path.name}: {exc}") from exc
    if not rows:
        return []
    if rows[0] != header(n_rounds):
        raise LogError(f"{path.name}: the header does not match the protocol")
    entries = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(rows[0]):
            raise LogError(f"{path.name} line {number}: expected {len(rows[0])} fields")
        kind, session_text, timestamp, arm = row[:4]
        try:
            session = int(session_text)
        except ValueError as exc:
            raise LogError(f"{path.name} line {number}: bad session number") from exc
        entries.append(
            Entry(kind, session, timestamp, arm, tuple(row[4 : 4 + n_rounds]), row[-2], row[-1])
        )
    return entries


def check(
    protocol: Protocol, entries: Sequence[Entry], expect_head: str | None = None
) -> list[str]:
    """Every problem found, as readable sentences; an empty list means the log is intact."""
    problems: list[str] = []
    previous = protocol.hash
    last_session = 0
    arms = arm_sequence(protocol, sum(e.kind == DRAW for e in entries))
    for index, entry in enumerate(entries):
        line = index + 2  # the header is line 1
        if entry.kind not in (DRAW, NOTE):
            problems.append(f"line {line}: unknown kind {entry.kind!r}")
        if row_hash(previous, entry.fields()) != entry.hash:
            problems.append(
                f"line {line}: the row does not match its hash "
                "(edited, or something before it was removed, added or reordered)"
                if index
                else f"line {line}: the first row does not chain to this protocol "
                "(the row or the protocol file was changed)"
            )
        previous = entry.hash
        if entry.kind == DRAW:
            if entry.session != last_session + 1:
                problems.append(
                    f"line {line}: session {entry.session} follows {last_session}; "
                    "sessions must be consecutive"
                )
            elif entry.session <= len(arms):  # after a gap there may be sessions beyond the file
                rounds = tuple("-".join(r) for r in round_orders(protocol, entry.session))
                if entry.arm != arms[entry.session - 1] or entry.rounds != rounds:
                    problems.append(
                        f"line {line}: session {entry.session} is not what the protocol and "
                        "seed produce for it"
                    )
            last_session = max(last_session, entry.session)
        elif entry.kind == NOTE and not 1 <= entry.session <= last_session:
            problems.append(f"line {line}: a note refers to session {entry.session}, not drawn yet")
    if expect_head is not None and head_hash(protocol, entries) != expect_head:
        problems.append("the latest hash is not the one you expected")
    return problems
