"""The window, driven without a mainloop. Needs a display, so it only runs when asked:

EXPRAND_GUI_TESTS=1 xvfb-run -a python -m pytest tests/test_gui.py
"""

import os
import subprocess

import pytest

tk = pytest.importorskip("tkinter", reason="this Python has no tkinter")
messagebox = pytest.importorskip("tkinter.messagebox")

from exprand import Protocol, Study  # noqa: E402
from exprand.gui import App, open_folder  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("EXPRAND_GUI_TESTS") != "1", reason="set EXPRAND_GUI_TESTS=1 (needs a display)"
)


@pytest.fixture
def root():
    window = tk.Tk()
    yield window
    window.destroy()


@pytest.fixture
def dialogs(monkeypatch):
    shown = {"info": [], "error": [], "asked": []}
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: shown["info"].append(a))
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown["error"].append(a))
    monkeypatch.setattr(
        messagebox,
        "askyesno",
        lambda *a, **k: shown["asked"].append(a) or shown.get("answer", True),
    )
    return shown


def test_nothing_is_drawn_until_the_button_is_pressed(root, study):
    app = App(root, study, "en", confirm=False)
    assert study.entries() == []
    assert app.session_label.cget("text") == "Session: —"
    assert app.reveal_button.cget("state") == "disabled"


def test_a_new_session_is_logged_shown_and_its_arm_hidden_until_revealed(root, study):
    app = App(root, study, "en", confirm=False)
    app.new_session()
    allocation = study.entries()[0]
    assert app.session_label.cget("text") == "Session: 0001"
    assert app.arm_value.cget("text") == "(hidden)"
    assert str(app.reveal_button.cget("state")) == "normal"
    shown = [[cell.cget("text") for cell in cells] for cells in app.round_cells]
    assert ["-".join(r) for r in shown] == list(allocation.rounds)
    app.reveal_arm()
    assert app.arm_value.cget("text") == allocation.arm
    app.new_session()
    assert app.session_label.cget("text") == "Session: 0002"
    assert app.arm_value.cget("text") == "(hidden)"  # hidden again for the next one
    assert study.verify().n_sessions == 2


def test_the_button_asks_first_and_does_nothing_on_no(root, study, dialogs):
    app = App(root, study, "en")
    dialogs["answer"] = False
    app.new_session()
    assert study.entries() == [] and len(dialogs["asked"]) == 1
    dialogs["answer"] = True
    app.new_session()
    assert len(study.entries()) == 1


def test_a_failing_log_is_shown_as_an_error_not_a_crash(root, study, dialogs):
    app = App(root, study, "en", confirm=False)
    app.new_session()
    rows = study.log_path.read_text(encoding="utf-8-sig").replace("c1", "cX", 1)
    study.log_path.write_text(rows, encoding="utf-8-sig")
    app.new_session()
    assert len(dialogs["error"]) == 1 and "Refusing" in dialogs["error"][0][1]
    app.verify_log()
    assert len(dialogs["error"]) == 2 and "Problems found" in dialogs["error"][1][1]


def test_verify_reports_a_clean_log(root, study, dialogs):
    app = App(root, study, "en", confirm=False)
    app.new_session()
    app.verify_log()
    assert "1 sessions" in dialogs["info"][0][1]


def test_portuguese_labels(root, study):
    app = App(root, study, "pt", confirm=False)
    assert root.title() == "Sorteador do experimento"
    assert app.session_label.cget("text") == "Sessão: —"
    assert app.arm_value.cget("text") == "(oculto)"
    app.new_session()
    assert app.status.cget("text") == "Registrado no log (sessão 1)."


def test_spanish_labels(root, study):
    app = App(root, study, "es", confirm=False)
    assert root.title() == "Aleatorizador del experimento"
    assert app.session_label.cget("text") == "Sesión: —"
    assert app.arm_value.cget("text") == "(oculto)"
    app.new_session()
    assert app.status.cget("text") == "Guardado en el registro (sesión 1)."


def test_a_study_without_arms_has_no_arm_controls_and_one_without_conditions_no_rounds(
    root, tmp_path
):
    orders = Study.init(tmp_path / "o", Protocol(conditions=("x", "y", "z"), n_rounds=2, seed=1))
    app = App(root, orders, "en", confirm=False)
    assert app.arm_value is None and len(app.round_cells) == 2
    app.new_session()
    app.reveal_arm()  # harmless
    assert app.session_label.cget("text") == "Session: 0001"
    arms = Study.init(tmp_path / "a", Protocol(arms=("A", "B"), seed=1))
    with_arms = App(root, arms, "en", confirm=False)
    assert with_arms.round_cells == []
    with_arms.new_session()
    with_arms.reveal_arm()
    assert with_arms.arm_value.cget("text") in ("A", "B")


def test_the_data_folder_button_falls_back_to_a_message(root, study, dialogs, monkeypatch):
    app = App(root, study, "en", confirm=False)

    def no_file_manager(*args, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(subprocess, "run", no_file_manager)  # macOS and Linux
    monkeypatch.setattr(os, "startfile", no_file_manager, raising=False)  # Windows only
    assert open_folder(study.directory) is False
    app.show_folder()
    assert str(study.directory.resolve()) in dialogs["info"][0][1]
