"""Create a study, draw a few sessions, verify the log, then tamper with it and watch it get caught.

python examples/quickstart.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import exprand as ex


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        protocol = ex.Protocol(
            arms=("A", "B"),
            conditions=("c1", "c2", "c3"),
            n_rounds=3,
            design="williams",
            seed=2024,
        )
        study = ex.Study.init(Path(tmp) / "demo", protocol)
        print(f"protocol hash {protocol.hash[:16]}...  (seed {protocol.seed})")

        for _ in range(4):
            allocation = study.next()
            print(f"session {allocation.session}: arm {allocation.arm}", allocation.round_strings())
        study.annotate(2, "did not attend")

        report = study.verify()
        print(f"\nverify: ok={report.ok}, {report.n_sessions} sessions, arms {report.arm_counts}")
        head = study.head()
        print(f"chain head to write down elsewhere: {head[:16]}...")

        # Someone "corrects" the arm of session 3 by editing the file.
        with study.log_path.open(encoding="utf-8-sig", newline="") as handle:
            text = handle.read()
        rows = text.split("\r\n")
        cells = rows[3].split(";")
        cells[3] = "B" if cells[3] == "A" else "A"
        rows[3] = ";".join(cells)
        study.log_path.write_text("\r\n".join(rows), encoding="utf-8-sig", newline="")

        report = study.verify(expect_head=head)
        print(f"\nafter the edit: ok={report.ok}")
        for problem in report.problems:
            print("  -", problem)


if __name__ == "__main__":
    main()
