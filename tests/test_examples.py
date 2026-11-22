"""The examples and the README snippets must only call things that exist, and still run."""

import ast
import importlib.util
import re
from pathlib import Path

import pytest

import exprand

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "examples").glob("*.py"))
READMES = [p for p in (ROOT / "README.md", ROOT / "README.pt-BR.md") if p.exists()]


def missing_attributes(source: str) -> list[str]:
    used = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in ("ex", "exprand")
    }
    return sorted(name for name in used if not hasattr(exprand, name))


def load_example(name):
    spec = importlib.util.spec_from_file_location(
        f"example_{name}", ROOT / "examples" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_scripts_use_only_the_public_api(path):
    assert missing_attributes(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", READMES, ids=lambda p: p.name)
def test_readme_python_snippets_use_the_public_api_and_run(path, tmp_path, monkeypatch):
    blocks = re.findall(r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL)
    assert blocks, "the README should show at least one Python snippet"
    monkeypatch.chdir(tmp_path)  # the snippets create a study in the current folder
    scope: dict[str, object] = {}
    for block in blocks:
        assert missing_attributes(block) == []
        exec(compile(block, f"{path.name} snippet", "exec"), scope)  # noqa: S102


@pytest.mark.parametrize("path", READMES, ids=lambda p: p.name)
def test_readme_cli_commands_exist(path):
    from exprand.cli import main

    text = path.read_text(encoding="utf-8")
    shown = set(re.findall(r"^exprand (\w+)", text, re.MULTILINE))  # in the code blocks
    mentioned = set(re.findall(r"`exprand (\w+)", text))  # in the prose
    assert {"init", "next", "verify", "annotate", "gui"} <= shown
    assert {"show", "plan", "head"} <= mentioned
    commands = shown | mentioned
    for command in commands:
        with pytest.raises(SystemExit) as stop:
            main([command, "--help"])
        assert stop.value.code == 0, command


def test_quickstart_runs_and_catches_the_edit(capsys):
    load_example("quickstart").main()
    out = capsys.readouterr().out
    assert "verify: ok=True, 4 sessions" in out
    assert "after the edit: ok=False" in out and "not what the protocol and seed produce" in out


def test_imbalance_example_matches_the_exact_binomial_and_blocks_stay_balanced(capsys):
    module = load_example("imbalance")
    result = module.main(["--n", "20", "--studies", "3000", "--seed", "4"])
    assert max(result["blocks"]) <= 2
    assert abs(sum(d >= 6 for d in result["coin"]) / 3000 - module.exact_coin(20, 6)) < 0.03
    assert module.exact_coin(20, 6) == pytest.approx(0.2632, abs=1e-3)
    assert "permuted blocks" in capsys.readouterr().out
