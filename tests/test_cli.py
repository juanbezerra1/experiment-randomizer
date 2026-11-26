import json
import subprocess
import sys

import pytest

import exprand
from exprand import Study, draw
from exprand.cli import main


def run(capsys, *args):
    code = main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "s"


def init(capsys, folder, *extra):
    return run(
        capsys, "init", "--dir", folder, "--arms", "A,B", "--conditions", "c1,c2,c3,c4",
        "--rounds", 3, "--seed", 42, *extra,
    )  # fmt: skip


def test_init_prints_the_hash_and_warns_about_the_seed(capsys, folder):
    code, out, _ = init(capsys, folder)
    assert code == 0
    study = Study(folder)
    assert study.protocol.hash in out and "seed           42" in out
    assert "predict every" in out
    assert study.protocol.arms == ("A", "B") and study.protocol.n_rounds == 3


def test_init_options_reach_the_protocol(capsys, folder):
    code, _, _ = run(
        capsys, "init", "--dir", folder, "--arms", "A, B", "--weights", "2,1",
        "--block-sizes", "3,6", "--conditions", "x,y,z", "--rounds", 4,
        "--design", "williams", "--seed", 9,
    )  # fmt: skip
    p = Study(folder).protocol
    assert code == 0 and p.arm_weights == (2, 1) and p.arm_block_sizes == (3, 6)
    assert p.design == "williams" and p.n_rounds == 4 and p.seed == 9


def test_init_without_a_seed_picks_and_stores_a_random_one(capsys, folder):
    run(capsys, "init", "--dir", folder, "--arms", "A,B")
    assert Study(folder).protocol.seed > 0
    assert Study(folder).protocol.n_rounds == 0


def test_next_prints_a_card_and_logs_it(capsys, folder):
    init(capsys, folder)
    code, out, _ = run(capsys, "next", "--dir", folder, "--note", "pilot")
    expected = draw(Study(folder).protocol, 1)
    assert code == 0 and out.startswith("session 0001") and f"arm      {expected.arm}" in out
    assert f"round 1  {' '.join(expected.rounds[0])}" in out and "row hash" in out
    assert Study(folder).entries()[0].note == "pilot"


def test_next_json_is_machine_readable(capsys, folder):
    init(capsys, folder)
    code, out, _ = run(capsys, "next", "--dir", folder, "--json")
    data = json.loads(out)
    expected = draw(Study(folder).protocol, 1)
    assert code == 0 and data["session"] == 1 and data["arm"] == expected.arm
    assert data["rounds"] == [list(r) for r in expected.rounds]
    assert data["hash"] == Study(folder).entries()[0].hash == Study(folder).head()


def test_plan_shows_future_sessions_without_logging_them(capsys, folder):
    init(capsys, folder)
    code, out, _ = run(capsys, "plan", "--dir", folder, 5)
    rows = out.strip().splitlines()
    assert code == 0 and len(rows) == 5 and rows[0].startswith("0001  ")
    assert Study(folder).entries() == []
    for k in range(1, 6):  # what plan promised is what next delivers
        _, drawn, _ = run(capsys, "next", "--dir", folder, "--json")
        _, planned, _ = run(capsys, "plan", "--dir", folder, 5, "--json")
        assert json.loads(planned.splitlines()[k - 1])["rounds"] == json.loads(drawn)["rounds"]
        assert json.loads(planned.splitlines()[k - 1])["arm"] == json.loads(drawn)["arm"]


def test_show_lists_sessions_and_notes(capsys, folder):
    init(capsys, folder)
    assert run(capsys, "show", "--dir", folder)[1].strip() == "nothing drawn yet"
    for _ in range(3):
        run(capsys, "next", "--dir", folder)
    run(capsys, "annotate", "--dir", folder, 2, "did not attend")
    _, out, _ = run(capsys, "show", "--dir", folder)
    assert len(out.strip().splitlines()) == 4 and "(note)  # did not attend" in out
    _, last, _ = run(capsys, "show", "--dir", folder, "--last", 1)
    assert len(last.strip().splitlines()) == 1 and "(note)" in last
    _, as_json, _ = run(capsys, "show", "--dir", folder, "--json")
    assert [e["kind"] for e in json.loads(as_json)] == ["draw", "draw", "draw", "note"]


def test_verify_succeeds_then_fails_after_tampering(capsys, folder):
    init(capsys, folder)
    for _ in range(4):
        run(capsys, "next", "--dir", folder)
    code, out, _ = run(capsys, "verify", "--dir", folder)
    assert code == 0 and out.startswith("OK: 4 sessions") and "chain head" in out
    text = (folder / "log.csv").read_bytes()
    (folder / "log.csv").write_bytes(text.replace(b"c1", b"cX", 1))
    code, out, _ = run(capsys, "verify", "--dir", folder)
    assert code == 1 and out.startswith("FAILED:") and "  - line" in out


def test_head_and_expect_head(capsys, folder):
    init(capsys, folder)
    run(capsys, "next", "--dir", folder)
    _, head, _ = run(capsys, "head", "--dir", folder)
    run(capsys, "next", "--dir", folder)
    assert run(capsys, "verify", "--dir", folder, "--expect-head", head.strip())[0] == 1
    _, newer, _ = run(capsys, "head", "--dir", folder)
    assert run(capsys, "verify", "--dir", folder, "--expect-head", newer.strip())[0] == 0


@pytest.mark.parametrize(
    "args, message",
    [
        (["next"], "exprand init"),  # no study here
        (["init", "--arms", "A"], "two arms"),
        (["init", "--arms", "A,B", "--weights", "1,x"], "comma-separated integers"),
        (["init", "--arms", "A B,C"], "invalid arm label"),
        (["init", "--conditions", "a,b", "--rounds", "0"], "at least 1"),
        (["init"], "arms, conditions"),
    ],
)
def test_mistakes_exit_with_status_2_and_a_message(capsys, folder, args, message):
    code, _, err = run(capsys, *args[:1], "--dir", folder, *args[1:])
    assert code == 2 and err.startswith("error:") and message in err


def test_a_second_init_is_refused_and_leaves_the_protocol_alone(capsys, folder):
    init(capsys, folder)
    before = (folder / "study.json").read_text()
    code, _, err = run(capsys, "init", "--dir", folder, "--arms", "X,Y", "--seed", 1)
    assert code == 2 and "already exists" in err
    assert (folder / "study.json").read_text() == before


def test_annotating_a_session_that_does_not_exist_fails(capsys, folder):
    init(capsys, folder)
    code, _, err = run(capsys, "annotate", "--dir", folder, 1, "x")
    assert code == 2 and "has not been drawn" in err


def test_no_command_prints_help_and_version_works(capsys):
    code, out, _ = run(capsys)
    assert code == 2 and "usage: exprand" in out
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert f"exprand {exprand.__version__}" in capsys.readouterr().out


def test_python_dash_m_runs_the_same_program():
    done = subprocess.run(
        [sys.executable, "-I", "-m", "exprand", "--version"],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0 and done.stdout.strip() == f"exprand {exprand.__version__}"


def test_output_survives_a_console_that_cannot_print_every_character(capsys, folder):
    init(capsys, folder)
    run(capsys, "next", "--dir", folder, "--note", "café ☃")
    code, out, _ = run(capsys, "show", "--dir", folder)
    assert code == 0 and "caf" in out


def test_the_window_command_hands_over_the_study_and_the_language(capsys, folder, monkeypatch):
    pytest.importorskip("tkinter")
    import exprand.gui as gui

    init(capsys, folder)
    calls = []
    monkeypatch.setattr(gui, "run", lambda study, language=None: calls.append((study, language)))
    assert main(["gui", "--dir", str(folder), "--lang", "pt"]) == 0
    assert calls[0][0].directory == folder and calls[0][1] == "pt"


def test_the_window_command_explains_a_missing_tkinter(capsys, folder, monkeypatch):
    init(capsys, folder)
    monkeypatch.delitem(sys.modules, "exprand.gui", raising=False)
    monkeypatch.setitem(sys.modules, "tkinter", None)  # makes ``import tkinter`` fail
    code, _, err = run(capsys, "gui", "--dir", folder)
    assert code == 2 and "needs tkinter" in err


# -- warnings about a network or synced folder: advice on stderr, never a change of behaviour ---
def risky_place(monkeypatch, *findings):
    monkeypatch.setattr("exprand.cli.folder_warnings", lambda directory: list(findings))


def test_a_local_folder_changes_nothing_and_prints_no_warning(capsys, folder, monkeypatch):
    from exprand import placement

    monkeypatch.delenv(placement.SILENCE_VARIABLE, raising=False)
    monkeypatch.setattr(placement, "read_mounts", lambda system: [("/", "ext4")])
    monkeypatch.setattr(placement, "windows_drive_is_remote", lambda drive: False)
    assert init(capsys, folder)[2] == ""
    for args in (("next",), ("next", "--json"), ("annotate", 1, "x")):
        code, _, err = run(capsys, *args, "--dir", folder)
        assert code == 0 and err == ""


def test_init_next_and_annotate_warn_on_stderr_and_keep_stdout_and_the_exit_status(
    capsys, folder, monkeypatch
):
    from exprand import Finding

    risky_place(monkeypatch, Finding("synced", "Dropbox"))
    code, out, err = init(capsys, folder)
    assert code == 0 and err.startswith("warning: ") and "Dropbox" in err
    assert "created" in out and "warning" not in out
    code, out, err = run(capsys, "next", "--dir", folder, "--json")
    assert code == 0 and "Dropbox" in err
    assert json.loads(out)["session"] == 1  # stdout is still exactly the JSON
    code, out, err = run(capsys, "annotate", 1, "not run", "--dir", folder)
    assert code == 0 and "Dropbox" in err and out == "noted on session 0001\n"
    assert Study(folder).verify().ok  # drawing went on as usual


def test_every_warning_is_printed_and_the_gui_command_warns_too(capsys, folder, monkeypatch):
    pytest.importorskip("tkinter")
    import exprand.gui as gui
    from exprand import Finding

    init(capsys, folder)
    risky_place(monkeypatch, Finding("network", "unc"), Finding("synced", "OneDrive"))
    opened = []
    monkeypatch.setattr(gui, "run", lambda study, language=None: opened.append(study))
    code, _, err = run(capsys, "gui", "--dir", folder)
    assert code == 0 and len(opened) == 1  # the window still opens
    assert err.count("warning: ") == 2 and "UNC" in err and "OneDrive" in err


def test_the_commands_that_only_read_do_not_warn(capsys, folder, monkeypatch):
    from exprand import Finding

    init(capsys, folder)
    run(capsys, "next", "--dir", folder)
    risky_place(monkeypatch, Finding("network", "unc"))
    for args in (("show",), ("plan", 3), ("verify",), ("head",)):
        code, _, err = run(capsys, *args, "--dir", folder)
        assert code == 0 and err == "", args


def test_the_warning_can_be_silenced_for_a_folder_that_is_known_to_be_fine(
    capsys, folder, monkeypatch
):
    from exprand import placement

    monkeypatch.setattr(placement, "read_mounts", lambda system: [("/", "nfs4")])
    monkeypatch.setattr(placement, "windows_drive_is_remote", lambda drive: True)
    monkeypatch.delenv(placement.SILENCE_VARIABLE, raising=False)
    assert "warning" in init(capsys, folder)[2]  # the real detection, on a "network" disk
    monkeypatch.setenv(placement.SILENCE_VARIABLE, "1")
    code, _, err = run(capsys, "next", "--dir", folder)
    assert code == 0 and err == ""
