import json
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor

import pytest

from exprand import FileLock, LockTimeout, Protocol, Study


def test_the_lock_is_exclusive_until_released(tmp_path):
    path = tmp_path / ".lock"
    with FileLock(path), pytest.raises(LockTimeout, match="another copy"):
        FileLock(path, timeout=0.15).acquire()
    with FileLock(path, timeout=0.15):  # free again
        pass


def test_the_lock_is_released_when_the_block_raises(tmp_path):
    path = tmp_path / ".lock"
    with pytest.raises(RuntimeError, match="boom"), FileLock(path):
        raise RuntimeError("boom")
    with FileLock(path, timeout=0.15):
        pass


def test_a_lock_object_cannot_be_taken_twice_and_release_is_idempotent(tmp_path):
    lock = FileLock(tmp_path / ".lock")
    lock.acquire()
    with pytest.raises(RuntimeError, match="already held"):
        lock.acquire()
    lock.release()
    lock.release()


def test_the_lock_dies_with_its_process(tmp_path):
    """A program that crashes while holding the lock must not block the next one."""
    path = tmp_path / ".lock"
    code = textwrap.dedent(
        f"""
        import os, sys
        from exprand import FileLock
        FileLock({str(path)!r}).acquire()
        os._exit(0)  # no release, no cleanup
        """
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True, timeout=60)
    with FileLock(path, timeout=1.0):
        pass


def draw_from_a_new_process(directory):
    done = subprocess.run(
        [sys.executable, "-I", "-m", "exprand", "next", "--dir", str(directory), "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["session"]


def test_simultaneous_programs_never_draw_the_same_session(tmp_path):
    """Four terminals drawing at once: every session number is used exactly once."""
    study = Study.init(
        tmp_path / "s", Protocol(arms=("A", "B"), conditions=("c1", "c2", "c3"), n_rounds=2, seed=3)
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        sessions = list(pool.map(lambda _: draw_from_a_new_process(study.directory), range(24)))
    assert sorted(sessions) == list(range(1, 25))
    report = study.verify()
    assert report.ok and report.n_sessions == 24
