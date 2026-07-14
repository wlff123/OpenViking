import json
import os
from pathlib import Path

import pytest

from viking_forge.codex import CodexExecutionError, CodexRunner


PROJECT_ROOT = Path(__file__).parents[1]


def make_fake_codex(tmp_path, result='{"summary": "ok"}', exit_code=0):
    executable = tmp_path / "codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

record = pathlib.Path(__file__).with_name("record.json")
record.write_text(json.dumps({"args": sys.argv[1:], "env": dict(os.environ)}))
args = sys.argv[1:]
output = pathlib.Path(args[args.index("-o") + 1])
output.write_text(%r)
print("fake stdout")
print("fake stderr", file=sys.stderr)
sys.exit(%d)
"""
        % (result, exit_code),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def make_runner(executable, source_environment):
    return CodexRunner(
        executable,
        PROJECT_ROOT / "prompts",
        PROJECT_ROOT / "schemas",
        source_environment=source_environment,
    )


def test_triage_uses_read_only_ephemeral_session_and_sanitized_environment(tmp_path):
    executable = make_fake_codex(
        tmp_path,
        '{"summary":"clear","candidate":true}',
    )
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": "/home/test",
        "CODEX_HOME": "/home/test/.codex",
        "GITHUB_APP_PRIVATE_KEY": "secret",
        "VIKING_FORGE_WEBHOOK_SECRET": "secret",
        "FEISHU_WEBHOOK_URL": "secret",
    }
    runner = make_runner(executable, environment)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    run_dir = tmp_path / "artifacts"

    result = runner.run("triage", worktree, run_dir, {"number": 42})

    record = json.loads((tmp_path / "record.json").read_text())
    command = record["args"]
    assert command[0] == "exec"
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert record["env"]["CODEX_HOME"] == "/home/test/.codex"
    assert "GITHUB_APP_PRIVATE_KEY" not in record["env"]
    assert "VIKING_FORGE_WEBHOOK_SECRET" not in record["env"]
    assert "FEISHU_WEBHOOK_URL" not in record["env"]
    assert result == {"summary": "clear", "candidate": True}
    assert not (worktree / "issue-context.json").exists()
    assert (run_dir / "stdout.log").read_text() == "fake stdout\n"
    assert (run_dir / "stderr.log").read_text() == "fake stderr\n"


def test_fix_uses_workspace_write_and_temporary_triage_context(tmp_path):
    executable = make_fake_codex(tmp_path)
    runner = make_runner(executable, {"PATH": os.environ["PATH"]})
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    runner.run(
        "fix",
        worktree,
        tmp_path / "artifacts",
        {"number": 42},
        triage={"candidate": True},
    )

    command = json.loads((tmp_path / "record.json").read_text())["args"]
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert not (worktree / "issue-context.json").exists()
    assert not (worktree / "triage.json").exists()


@pytest.mark.parametrize(
    ("result", "exit_code", "message"),
    [("{}", 7, "exited with status 7"), ("not-json", 0, "invalid JSON")],
)
def test_codex_failure_is_reported_and_context_is_removed(tmp_path, result, exit_code, message):
    executable = make_fake_codex(tmp_path, result, exit_code)
    runner = make_runner(executable, {"PATH": os.environ["PATH"]})
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(CodexExecutionError, match=message):
        runner.run("triage", worktree, tmp_path / "artifacts", {"number": 42})

    assert not (worktree / "issue-context.json").exists()
