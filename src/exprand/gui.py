"""A small window for the bench: draw a session, see the order, reveal the arm.

It is deliberately thin. Every decision is made by :class:`exprand.study.Study`; this file only
shows the result. Unlike a program that draws when it starts, nothing is drawn (and no session
number is spent) until the button is pressed, and the button asks first, because a draw is
permanent. The arm stays hidden until “Reveal arm”, so the order of the conditions can be set up
first.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

from .i18n import default_language, t
from .lock import LockTimeout
from .log import LogError
from .placement import folder_warnings
from .protocol import Allocation
from .study import Study

__all__ = ["App", "open_folder", "run"]


def open_folder(path: Path) -> bool:
    """Show a folder in the file manager; False if the platform has no way to do it."""
    try:
        if sys.platform == "win32":  # pragma: no cover - Windows only
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":  # pragma: no cover - macOS only
            subprocess.run(["open", str(path)], check=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


class App:
    """The window. ``confirm=False`` skips the “are you sure” dialog (used by the tests)."""

    def __init__(
        self, root: tk.Tk, study: Study, language: str | None = None, confirm: bool = True
    ) -> None:
        self.root = root
        self.study = study
        self.language = language or default_language()
        self.confirm = confirm
        self.allocation: Allocation | None = None
        self.round_cells: list[list[tk.Label]] = []

        proto = study.protocol
        root.title(self.tr("window_title"))
        root.minsize(560, 420)
        base = tkfont.nametofont("TkDefaultFont")
        self.big = base.copy()
        self.big.configure(size=base.cget("size") + 10, weight="bold")
        self.medium = base.copy()
        self.medium.configure(size=base.cget("size") + 3, weight="bold")

        tk.Label(root, text=self.tr("window_title"), font=self.big).pack(pady=(16, 2))
        tk.Label(root, text=self._protocol_text()).pack()
        self.session_label = tk.Label(root, text=self.tr("no_session"), font=self.medium)
        self.session_label.pack(pady=(10, 4))

        self.arm_value: tk.Label | None = None
        self.reveal_button: tk.Button | None = None
        if proto.arms:
            frame = tk.LabelFrame(root, text=self.tr("arm_frame"), padx=24, pady=8)
            frame.pack(pady=8)
            self.arm_value = tk.Label(frame, text=self.tr("arm_hidden"), font=self.big, width=14)
            self.arm_value.pack()
            self.reveal_button = tk.Button(
                frame, text=self.tr("reveal_arm"), command=self.reveal_arm, state="disabled"
            )
            self.reveal_button.pack(pady=4)

        if proto.conditions:
            frame = tk.LabelFrame(root, text=self.tr("rounds_frame"), padx=10, pady=8)
            frame.pack(pady=8)
            for r in range(proto.n_rounds):
                column = tk.LabelFrame(frame, text=self.tr("round", i=r + 1), padx=8, pady=4)
                column.grid(row=0, column=r, padx=4)
                cells = []
                for _ in proto.conditions:
                    cell = tk.Label(column, text="-", width=6, relief="solid", bd=1)
                    cell.pack(pady=2)
                    cells.append(cell)
                self.round_cells.append(cells)

        controls = tk.Frame(root)
        controls.pack(pady=12)
        self.new_button = tk.Button(
            controls, text=self.tr("new_session"), font=self.medium, command=self.new_session
        )
        self.new_button.grid(row=0, column=0, padx=6)
        tk.Button(controls, text=self.tr("verify"), command=self.verify_log).grid(
            row=0, column=1, padx=6
        )
        tk.Button(controls, text=self.tr("open_folder"), command=self.show_folder).grid(
            row=0, column=2, padx=6
        )
        self.status = tk.Label(root, text=self.tr("ready"), wraplength=520)
        self.status.pack(pady=(0, 10))

        # A network or synced folder gets a standing note, not a dialog: it never blocks a draw.
        self.location_note: tk.Label | None = None
        notes = [finding.message(self.language) for finding in folder_warnings(study.directory)]
        if notes:
            self.location_note = tk.Label(
                root, text="\n\n".join(notes), wraplength=520, justify="left", fg="#8a4b00"
            )
            self.location_note.pack(padx=12, pady=(0, 10))

    # -- text ---------------------------------------------------------------------------------
    def tr(self, key: str, **values: object) -> str:
        return t(self.language, key, **values)

    def _protocol_text(self) -> str:
        p = self.study.protocol
        if p.arms and p.conditions:
            return self.tr(
                "protocol", arms=len(p.arms), conditions=len(p.conditions), rounds=p.n_rounds
            )
        if p.arms:
            return self.tr("protocol_arms_only", arms=len(p.arms))
        return self.tr("protocol_orders_only", conditions=len(p.conditions), rounds=p.n_rounds)

    # -- actions ------------------------------------------------------------------------------
    def new_session(self) -> None:
        if self.confirm and not messagebox.askyesno(
            self.tr("window_title"), self.tr("confirm_new"), parent=self.root
        ):
            return
        try:
            allocation = self.study.next()
        except (LogError, LockTimeout, OSError, ValueError) as exc:
            messagebox.showerror(self.tr("error"), str(exc), parent=self.root)
            return
        self.allocation = allocation
        self.session_label.config(text=self.tr("session", n=f"{allocation.session:04d}"))
        if self.arm_value is not None and self.reveal_button is not None:
            self.arm_value.config(text=self.tr("arm_hidden"))
            self.reveal_button.config(state="normal")
        for cells, order in zip(self.round_cells, allocation.rounds, strict=True):
            for cell, condition in zip(cells, order, strict=True):
                cell.config(text=condition)
        self.status.config(text=self.tr("logged", n=allocation.session))

    def reveal_arm(self) -> None:
        if self.allocation is None or not self.allocation.arm:
            return
        if self.arm_value is not None:
            self.arm_value.config(text=self.allocation.arm)

    def verify_log(self) -> None:
        report = self.study.verify()
        if report.ok:
            messagebox.showinfo(
                self.tr("info"), self.tr("verify_ok", n=report.n_sessions), parent=self.root
            )
        else:
            messagebox.showerror(
                self.tr("error"),
                self.tr("verify_bad", problems="\n".join(report.problems[:8])),
                parent=self.root,
            )

    def show_folder(self) -> None:
        folder = self.study.directory.resolve()
        if not open_folder(folder):
            messagebox.showinfo(
                self.tr("info"), self.tr("folder_message", path=folder), parent=self.root
            )


def run(study: Study, language: str | None = None) -> None:
    """Open the window and block until it is closed."""
    root = tk.Tk()
    App(root, study, language)
    root.mainloop()
