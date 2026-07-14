from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any


ALLOWED_PREFIXES = ("openviking/", "tests/", "docs/")
DENIED_PREFIXES = (
    ".github/",
    "deploy/",
    "docker/",
    "automation/",
    "openviking/server/oauth/",
    "openviking/server/auth/",
)
DENIED_FILES = {
    "AGENTS.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
}
MAX_FILES = 5
MAX_CHANGED_LINES = 500
MAX_VALIDATION_OUTPUT = 8192
_ALLOWED_ENVIRONMENT = {
    "HOME",
    "LANG",
    "LC_ALL",
    "NODE_EXTRA_CA_CERTS",
    "PATH",
    "PIP_CACHE_DIR",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TMPDIR",
    "UV_CACHE_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "XDG_CACHE_HOME",
}


class PatchPolicyError(RuntimeError):
    pass


class ValidationError(RuntimeError):
    def __init__(self, results: list[dict[str, Any]]):
        self.results = results
        failed = results[-1] if results else None
        message = "Validation failed"
        if failed:
            message += f" with exit code {failed['exit_code']}"
        super().__init__(message)


def validate_changed_files(changed: list[dict[str, Any]]) -> None:
    if not changed:
        raise PatchPolicyError("Patch is empty")
    if len(changed) > MAX_FILES:
        raise PatchPolicyError("Patch changes more than 5 files")
    changed_lines = sum(int(item.get("added", 0)) + int(item.get("deleted", 0)) for item in changed)
    if changed_lines > MAX_CHANGED_LINES:
        raise PatchPolicyError("Patch changes more than 500 lines")
    paths = [str(item["path"]).replace("\\", "/") for item in changed]
    for item, path in zip(changed, paths, strict=True):
        if item.get("binary"):
            raise PatchPolicyError(f"Binary patch is not allowed: {path}")
        if str(item.get("status", ""))[:1] in {"R", "C"}:
            raise PatchPolicyError(f"Rename or copy is not allowed: {path}")
        if not path.startswith(ALLOWED_PREFIXES) or path.startswith(DENIED_PREFIXES):
            raise PatchPolicyError(f"Path is not allowed: {path}")
        if PurePosixPath(path).name in DENIED_FILES:
            raise PatchPolicyError(f"File is protected: {path}")
        if item.get("mode") == "120000":
            raise PatchPolicyError(f"Symlink is not allowed: {path}")
        if str(item.get("status", "")) == "D" and "/test_" in f"/{path}":
            raise PatchPolicyError(f"Deleting tests is not allowed: {path}")
    docs_only = all(path.startswith("docs/") for path in paths)
    if docs_only:
        if not all(path.endswith(".md") for path in paths):
            raise PatchPolicyError("Documentation patches may contain only Markdown")
        return
    has_test = any(
        path.endswith(".py")
        and (path.startswith("tests/test_") or "/test_" in f"/{path}")
        and item.get("status") != "D"
        for item, path in zip(changed, paths, strict=True)
    )
    if not has_test:
        raise PatchPolicyError("Python patch must add or modify a regression test")


def _git(worktree: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True).stdout


def _mode(worktree: Path, base_sha: str, path: str, status: str) -> str:
    if status == "D":
        output = _git(worktree, "ls-tree", base_sha, "--", path)
    else:
        output = _git(worktree, "ls-files", "-s", "--", path)
    return output.split(None, 1)[0].decode() if output else "100644"


def inspect_changes(worktree: str | Path, base_sha: str) -> list[dict[str, Any]]:
    root = Path(worktree).resolve()
    numstat = _git(root, "diff", "--numstat", "--no-renames", "-z", base_sha, "--").split(b"\0")
    status_rows = _git(root, "diff", "--name-status", "--no-renames", "-z", base_sha, "--").split(
        b"\0"
    )
    statuses: dict[str, str] = {}
    for index in range(0, len(status_rows) - 1, 2):
        path = status_rows[index + 1].decode("utf-8", "surrogateescape")
        statuses[path] = status_rows[index].decode()

    records: list[dict[str, Any]] = []
    known_paths: set[str] = set()
    for raw in numstat:
        if not raw:
            continue
        added, deleted, raw_path = raw.split(b"\t", 2)
        path = raw_path.decode("utf-8", "surrogateescape")
        status = statuses.get(path, "M")
        binary = added == b"-" or deleted == b"-"
        records.append(
            {
                "path": path,
                "added": 0 if binary else int(added),
                "deleted": 0 if binary else int(deleted),
                "binary": binary,
                "status": status,
                "mode": _mode(root, base_sha, path, status),
            }
        )
        known_paths.add(path)

    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    for raw_path in untracked:
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", "surrogateescape")
        if path in known_paths:
            continue
        file_path = root / path
        mode = (
            "120000"
            if file_path.is_symlink()
            else "100755"
            if os.access(file_path, os.X_OK)
            else "100644"
        )
        content = (
            os.readlink(file_path).encode() if file_path.is_symlink() else file_path.read_bytes()
        )
        binary = b"\0" in content
        records.append(
            {
                "path": path,
                "added": 0 if binary else len(content.splitlines()),
                "deleted": 0,
                "binary": binary,
                "status": "A",
                "mode": mode,
            }
        )
    return sorted(records, key=lambda item: str(item["path"]))


def validation_commands(changed_files: list[str]) -> list[list[str]]:
    if changed_files and all(path.startswith("docs/") for path in changed_files):
        return [["npm", "--prefix", "docs", "run", "docs:build"]]
    validation_venv = os.environ.get("VALIDATION_VENV")
    ruff = (
        [str(Path(validation_venv) / "bin" / "ruff")] if validation_venv else ["uv", "run", "ruff"]
    )
    pytest = (
        [str(Path(validation_venv) / "bin" / "pytest")]
        if validation_venv
        else ["uv", "run", "pytest"]
    )
    python_files = [path for path in changed_files if path.endswith(".py")]
    test_files = [
        path for path in python_files if path.startswith("tests/test_") or "/test_" in f"/{path}"
    ]
    return [
        [*ruff, "check", *python_files],
        [*ruff, "format", "--check", *python_files],
        [*pytest, "-q", "--no-cov", *test_files],
    ]


def run_validation(worktree: str | Path, changed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = Path(worktree).resolve()
    files = [str(item["path"]) for item in changed if item.get("status") != "D"]
    results: list[dict[str, Any]] = []
    for command in validation_commands(files):
        started = time.monotonic()
        environment = {
            key: value for key, value in os.environ.items() if key in _ALLOWED_ENVIRONMENT
        }
        environment["PYTHONPATH"] = str(root)
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        result = {
            "command": command,
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": (completed.stdout + completed.stderr)[-MAX_VALIDATION_OUTPUT:],
        }
        results.append(result)
        if completed.returncode:
            raise ValidationError(results)
    return results
