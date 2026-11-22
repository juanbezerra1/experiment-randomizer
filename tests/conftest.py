import pytest

from exprand import Protocol, Study


@pytest.fixture
def protocol():
    return Protocol(arms=("A", "B"), conditions=("c1", "c2", "c3", "c4"), n_rounds=5, seed=123)


@pytest.fixture
def study(tmp_path, protocol):
    return Study.init(tmp_path / "study", protocol)
