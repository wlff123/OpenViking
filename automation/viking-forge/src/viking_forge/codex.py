from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class CodexExecutionError(RuntimeError):
    pass


_ALLOWED_ENVIRONMENT = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "NODE_EXTRA_CA_CERTS",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "VALIDATION_VENV",
}
_MAX_LOG_SIZE = 200_000


class CodexRunner:
    def __init__(
        self,
        executable: str | Path,
        prompts_directory: str | Path,
        schemas_directory: str | Path,
        *,
        source_environment: Mapping[str, str] | None = None,
        timeout_seconds: int = 1800,
    ):
        self.executable = str(executable)
        self.prompts_directory = Path(prompts_directory).resolve()
        self.schemas_directory = Path(schemas_directory).resolve()
        self.source_environment = dict(source_environment or os.environ)
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        kind: str,
        worktree: str | Path,
        run_directory: str | Path,
        issue_context: dict[str, Any],
        triage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"triage", "fix"}:
            raise ValueError(f"Unknown Codex run kind: {kind}")
        if kind == "fix" and triage is None:
            raise ValueError("Fix runs require triage context")

        worktree_path = Path(worktree).resolve()
        artifacts = Path(run_directory).resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        context_files = [worktree_path / "issue-context.json"]
        if triage is not None:
            context_files.append(worktree_path / "triage.json")
        for path in context_files:
            if path.exists() or path.is_symlink():
                raise CodexExecutionError(f"Refusing to overwrite repository file: {path.name}")

        result_path = artifacts / "result.json"
        prompt_path = self.prompts_directory / f"{kind}.md"
        schema_path = self.schemas_directory / f"{kind}.json"
        sandbox = "read-only" if kind == "triage" else "workspace-write"
        command = [
            self.executable,
            "exec",
            "--ephemeral",
            "--sandbox",
            sandbox,
            "--output-schema",
            str(schema_path),
            "-o",
            str(result_path),
            "-",
        ]
        environment = {
            key: value
            for key, value in self.source_environment.items()
            if key in _ALLOWED_ENVIRONMENT
        }

        try:
            context_files[0].write_text(
                json.dumps(issue_context, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if triage is not None:
                context_files[1].write_text(
                    json.dumps(triage, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            try:
                completed = subprocess.run(
                    command,
                    cwd=worktree_path,
                    env=environment,
                    input=prompt_path.read_text(encoding="utf-8"),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexExecutionError(
                    f"Codex timed out after {self.timeout_seconds} seconds"
                ) from exc

            (artifacts / "stdout.log").write_text(
                completed.stdout[-_MAX_LOG_SIZE:], encoding="utf-8"
            )
            (artifacts / "stderr.log").write_text(
                completed.stderr[-_MAX_LOG_SIZE:], encoding="utf-8"
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip()[-2000:]
                suffix = f": {detail}" if detail else ""
                raise CodexExecutionError(
                    f"Codex exited with status {completed.returncode}{suffix}"
                )
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CodexExecutionError("Codex returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise CodexExecutionError("Codex returned invalid JSON object")
            return result
        finally:
            for path in context_files:
                path.unlink(missing_ok=True)
