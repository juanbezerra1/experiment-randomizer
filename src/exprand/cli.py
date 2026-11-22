"""``exprand init | next | annotate | show | plan | verify | head | gui``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import __version__
from .designs import DESIGNS
from .lock import LockTimeout
from .log import DRAW, LogError
from .protocol import Allocation, Protocol, draw
from .study import Study

__all__ = ["main"]


def _split(text: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip()) if text else ()


def _ints(text: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in _split(text))
    except ValueError:
        raise ValueError(f"expected comma-separated integers, got {text!r}") from None


def _card(allocation: Allocation, row_hash: str | None = None) -> str:
    lines = [f"session {allocation.session:04d}"]
    if allocation.arm:
        lines.append(f"arm      {allocation.arm}")
    for i, order in enumerate(allocation.rounds, start=1):
        lines.append(f"round {i:<3d}{' '.join(order)}")
    if row_hash:
        lines.append(f"logged   (row hash {row_hash[:12]}...)")
    return "\n".join(lines)


def _json(allocation: Allocation, row_hash: str | None = None) -> str:
    data = {
        "session": allocation.session,
        "arm": allocation.arm,
        "rounds": [list(r) for r in allocation.rounds],
    }
    if row_hash:
        data["hash"] = row_hash
    return json.dumps(data)


# -- commands ---------------------------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    seed: dict[str, Any] = {} if args.seed is None else {"seed": args.seed}  # else: random
    protocol = Protocol(
        arms=_split(args.arms),
        arm_weights=_ints(args.weights),
        arm_block_sizes=_ints(args.block_sizes),
        conditions=_split(args.conditions),
        n_rounds=args.rounds if args.conditions else 0,
        design=args.design,
        **seed,
    )
    study = Study.init(args.dir, protocol)
    print(f"created {study.protocol_path}")
    print(f"protocol hash  {protocol.hash}")
    print(f"seed           {protocol.seed}")
    print("The seed is stored in the protocol file: whoever can read it can predict every")
    print("allocation, so keep the folder away from whoever enrols participants if that matters.")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    study = Study(args.dir)
    allocation = study.next(note=args.note or "")
    row_hash = study.entry_for(allocation.session).hash
    print(_json(allocation, row_hash) if args.json else _card(allocation, row_hash))
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    study = Study(args.dir)
    study.annotate(args.session, args.text)
    print(f"noted on session {args.session:04d}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    study = Study(args.dir)
    entries = study.entries()
    if args.last:
        entries = entries[-args.last :]
    if args.json:
        print(json.dumps([asdict(e) for e in entries]))
        return 0
    for e in entries:
        what = " ".join([e.arm, *e.rounds]).strip() if e.kind == DRAW else "(note)"
        extra = f"  # {e.note}" if e.note else ""
        print(f"{e.session:04d}  {e.timestamp}  {what}{extra}")
    if not entries:
        print("nothing drawn yet")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    study = Study(args.dir)
    for k in range(1, args.n + 1):
        allocation = draw(study.protocol, k)
        if args.json:
            print(_json(allocation))
        else:
            print(f"{k:04d}  {' '.join([allocation.arm, *allocation.round_strings()]).strip()}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    study = Study(args.dir)
    report = study.verify(args.expect_head)
    if report.ok:
        arms = ", ".join(f"{n} {arm}" for arm, n in report.arm_counts.items())
        detail = f" ({arms}; largest difference {report.imbalance})" if arms else ""
        notes = f", notes: {report.n_notes}" if report.n_notes else ""
        print(f"OK: {report.n_sessions} sessions{detail}{notes}")
        print(f"chain head {report.head}")
        return 0
    print(f"FAILED: {len(report.problems)} problem(s)")
    for problem in report.problems:
        print(f"  - {problem}")
    return 1


def cmd_head(args: argparse.Namespace) -> int:
    print(Study(args.dir).head())
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui import run
    except ImportError as exc:
        raise ValueError(f"the window needs tkinter, which is missing here: {exc}") from exc
    run(Study(args.dir), language=args.lang)
    return 0


# -- parser -----------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exprand",
        description="Reproducible, auditable randomisation for small experiments.",
    )
    parser.add_argument("--version", action="version", version=f"exprand {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    def add(
        name: str, func: Callable[[argparse.Namespace], int], help_: str
    ) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument("--dir", default=".", type=Path, help="study folder (default: .)")
        p.set_defaults(func=func)
        return p

    p = add("init", cmd_init, "create a study: write its protocol file")
    p.add_argument("--arms", help="comma-separated arm labels, e.g. A,B (omit for none)")
    p.add_argument("--weights", help="allocation ratio, e.g. 2,1 (default: equal)")
    p.add_argument("--block-sizes", help="permuted block sizes, multiples of the weights' sum")
    p.add_argument("--conditions", help="comma-separated condition labels, e.g. c1,c2,c3")
    p.add_argument(
        "--rounds", type=int, default=1, help="passes through the conditions per session"
    )
    p.add_argument("--design", choices=DESIGNS, default="shuffle", help="order of conditions")
    p.add_argument("--seed", type=int, help="master seed (default: random, then stored)")

    p = add("next", cmd_next, "draw the next session, log it, and print it")
    p.add_argument("--note", help="a short remark stored with the session")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")

    p = add("annotate", cmd_annotate, "add a remark about an earlier session")
    p.add_argument("session", type=int)
    p.add_argument("text")

    p = add("show", cmd_show, "list what has been logged")
    p.add_argument("--last", type=int, help="only the last N rows")
    p.add_argument("--json", action="store_true")

    p = add("plan", cmd_plan, "print the allocations of sessions 1..N without logging them")
    p.add_argument("n", type=int)
    p.add_argument("--json", action="store_true")

    p = add("verify", cmd_verify, "check the log; exit status 1 if anything is wrong")
    p.add_argument("--expect-head", help="the chain head you wrote down earlier")

    add("head", cmd_head, "print the latest chain hash (write it down somewhere else)")

    p = add("gui", cmd_gui, "open the window")
    p.add_argument("--lang", choices=("en", "pt"), help="window language")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not know every character
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except (ValueError, LogError, LockTimeout, FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
