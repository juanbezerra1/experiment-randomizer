"""A study on disk: a protocol file, a log, and the rule that nothing is drawn without being logged.

``Study.next()`` takes the lock, reads and verifies the log, draws the next session from the
protocol, **writes it to disk (and syncs) before returning it**, and only then releases the lock.
A crash can therefore leave a session that was logged but never looked at, never one that was
looked at but not logged. Sessions are never reused or deleted; a session that was not run gets a
note instead (:meth:`Study.annotate`), so nobody can quietly re-draw until the arm suits them.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .lock import FileLock
from .log import (
    DRAW,
    NOTE,
    Entry,
    LogError,
    check,
    clean_note,
    format_header,
    format_row,
    head_hash,
    make_entry,
    read_entries,
)
from .protocol import Allocation, Protocol, draw

__all__ = ["Study", "VerifyReport"]

PROTOCOL_FILE = "study.json"
LOG_FILE = "log.csv"
LOCK_FILE = ".lock"


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    problems: list[str]
    n_sessions: int
    n_notes: int
    head: str
    arm_counts: dict[str, int]

    @property
    def imbalance(self) -> int:
        """Largest minus smallest number of sessions in an arm (0 without arms)."""
        counts = list(self.arm_counts.values())
        return max(counts) - min(counts) if counts else 0


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Study:
    """The files of one study in one directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.protocol_path = self.directory / PROTOCOL_FILE
        self.log_path = self.directory / LOG_FILE
        self.lock_path = self.directory / LOCK_FILE
        if not self.protocol_path.is_file():
            raise FileNotFoundError(
                f"no {PROTOCOL_FILE} in {self.directory}; create the study with `exprand init`"
            )
        self.protocol = Protocol.from_json(self.protocol_path.read_text(encoding="utf-8"))

    # -- creation -----------------------------------------------------------------------------
    @classmethod
    def init(cls, directory: str | Path, protocol: Protocol) -> Study:
        """Write the protocol; refuses to touch a directory that already holds a study."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / PROTOCOL_FILE
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(protocol.to_json())
        except FileExistsError:
            raise FileExistsError(
                f"{target} already exists; a protocol cannot change once sessions are drawn"
            ) from None
        return cls(directory)

    # -- reading ------------------------------------------------------------------------------
    def entries(self) -> list[Entry]:
        return read_entries(self.log_path, self.protocol.n_rounds)

    def entry_for(self, session: int) -> Entry:
        """The log row of a drawn session (not of a note about it)."""
        for entry in self.entries():
            if entry.kind == DRAW and entry.session == session:
                return entry
        raise ValueError(f"session {session} has not been drawn")

    def head(self) -> str:
        """The hash to write down somewhere else, to prove later that nothing was changed."""
        return head_hash(self.protocol, self.entries())

    def verify(self, expect_head: str | None = None) -> VerifyReport:
        try:
            entries = self.entries()
        except LogError as exc:
            return VerifyReport(False, [str(exc)], 0, 0, self.protocol.hash, {})
        problems = check(self.protocol, entries, expect_head)
        draws = [e for e in entries if e.kind == DRAW]
        counts = Counter(e.arm for e in draws)
        arm_counts = {arm: counts.get(arm, 0) for arm in self.protocol.arms}
        return VerifyReport(
            ok=not problems,
            problems=problems,
            n_sessions=len(draws),
            n_notes=sum(e.kind == NOTE for e in entries),
            head=head_hash(self.protocol, entries),
            arm_counts=arm_counts,
        )

    # -- writing ------------------------------------------------------------------------------
    def next(self, *, note: str = "", now: str | None = None) -> Allocation:
        """Draw the next session, log it durably, and return it."""
        note = clean_note(note)
        with FileLock(self.lock_path):
            entries = self._intact_entries()
            session = 1 + max((e.session for e in entries if e.kind == DRAW), default=0)
            allocation = draw(self.protocol, session)
            entry = make_entry(
                self.protocol,
                entries,
                kind=DRAW,
                session=session,
                timestamp=now or _now(),
                allocation=allocation,
                note=note,
            )
            self._append(entry)
        return allocation

    def annotate(self, session: int, text: str, *, now: str | None = None) -> Entry:
        """Add a remark about an earlier session (e.g. that it was not run)."""
        text = clean_note(text)
        if not text:
            raise ValueError("the note is empty")
        with FileLock(self.lock_path):
            entries = self._intact_entries()
            drawn = max((e.session for e in entries if e.kind == DRAW), default=0)
            if not 1 <= session <= drawn:
                raise ValueError(f"session {session} has not been drawn (last is {drawn})")
            entry = make_entry(
                self.protocol,
                entries,
                kind=NOTE,
                session=session,
                timestamp=now or _now(),
                note=text,
            )
            self._append(entry)
        return entry

    # -- internals ----------------------------------------------------------------------------
    def _intact_entries(self) -> list[Entry]:
        entries = self.entries()
        problems = check(self.protocol, entries)
        if problems:
            raise LogError(
                f"{problems[0]}. Refusing to add to a log that fails verification; "
                "run `exprand verify` for the full list"
            )
        return entries

    def _append(self, entry: Entry) -> None:
        text = format_row(entry)
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            text = format_header(self.protocol.n_rounds) + text
        with self.log_path.open("a", encoding="utf-8-sig", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
