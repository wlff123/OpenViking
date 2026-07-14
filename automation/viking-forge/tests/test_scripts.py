import subprocess
import sys

import pytest

from scripts.labels import LABELS
from viking_forge.validation import (
    PatchPolicyError,
    inspect_changes,
    run_validation,
    validate_changed_files,
    validation_commands,
)


def test_label_manifest_includes_human_analysis_gate():
    assert set(LABELS) == {
        "agent:ready",
        "agent:claimed",
        "agent:pr-open",
        "agent:blocked",
        "agent:triaged",
        "agent:analyze",
        "agent:ignored",
        "agent:retriage",
        "needs:info",
        "agent:human-only",
        "agent:generated",
    }


def test_guard_accepts_small_python_fix_with_regression_test():
    validate_changed_files(
        [
            {"path": "openviking/utils/parser.py", "added": 8, "deleted": 2, "status": "M"},
            {"path": "tests/test_parser.py", "added": 20, "deleted": 0, "status": "A"},
        ]
    )


@pytest.mark.parametrize(
    "changed",
    [
        [{"path": ".github/workflows/release.yml", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "pyproject.toml", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "openviking/a.py", "added": 501, "deleted": 0, "status": "M"}],
        [{"path": "openviking/a.py", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "docs/image.png", "added": 0, "deleted": 0, "status": "A", "binary": True}],
    ],
)
def test_guard_rejects_unsafe_patch(changed):
    with pytest.raises(PatchPolicyError):
        validate_changed_files(changed)


def test_inspect_changes_reads_modified_and_untracked_files(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    source = tmp_path / "openviking" / "a.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source.write_text("value = 2\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "test_a.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_a():\n    assert True\n", encoding="utf-8")

    changed = inspect_changes(tmp_path, base_sha)

    assert changed == [
        {
            "path": "openviking/a.py",
            "added": 1,
            "deleted": 1,
            "binary": False,
            "status": "M",
            "mode": "100644",
        },
        {
            "path": "tests/test_a.py",
            "added": 2,
            "deleted": 0,
            "binary": False,
            "status": "A",
            "mode": "100644",
        },
    ]


def test_validation_commands_are_repository_owned():
    assert validation_commands(["docs/guide.md"]) == [
        ["npm", "--prefix", "docs", "run", "docs:build"]
    ]


def test_validation_commands_can_use_prepared_environment(tmp_path, monkeypatch):
    venv = tmp_path / ".venv"
    monkeypatch.setenv("VALIDATION_VENV", str(venv))

    assert validation_commands(["openviking/a.py", "tests/test_a.py"]) == [
        [str(venv / "bin" / "ruff"), "check", "openviking/a.py", "tests/test_a.py"],
        [
            str(venv / "bin" / "ruff"),
            "format",
            "--check",
            "openviking/a.py",
            "tests/test_a.py",
        ],
        [str(venv / "bin" / "pytest"), "-q", "--no-cov", "tests/test_a.py"],
    ]


def test_validation_process_does_not_inherit_service_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "must-not-leak")
    monkeypatch.setattr(
        "viking_forge.validation.validation_commands",
        lambda _: [
            [
                sys.executable,
                "-c",
                "import os; print(os.getenv('GITHUB_APP_PRIVATE_KEY', 'missing'))",
            ]
        ],
    )

    results = run_validation(
        tmp_path,
        [{"path": "tests/test_a.py", "status": "A"}],
    )

    assert results[0]["output"].strip() == "missing"
    assert validation_commands(["openviking/a.py", "tests/test_a.py"]) == [
        ["uv", "run", "ruff", "check", "openviking/a.py", "tests/test_a.py"],
        ["uv", "run", "ruff", "format", "--check", "openviking/a.py", "tests/test_a.py"],
        ["uv", "run", "pytest", "-q", "--no-cov", "tests/test_a.py"],
    ]


def test_validation_process_imports_from_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "viking_forge.validation.validation_commands",
        lambda _: [
            [
                sys.executable,
                "-c",
                "import os; print(os.environ['PYTHONPATH'])",
            ]
        ],
    )

    results = run_validation(tmp_path, [{"path": "tests/test_a.py", "status": "A"}])

    assert results[0]["output"].strip() == str(tmp_path.resolve())
