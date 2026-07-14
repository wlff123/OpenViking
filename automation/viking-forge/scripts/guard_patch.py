from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import PurePosixPath
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


class PatchPolicyError(RuntimeError):
    pass


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


def _git_records(base: str) -> list[dict[str, Any]]:
    numstat = subprocess.run(
        ["git", "diff", "--numstat", "--no-renames", "-z", base, "--"],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    status_rows = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", "-z", base, "--"],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    statuses: dict[str, str] = {}
    for index in range(0, len(status_rows) - 1, 2):
        statuses[status_rows[index + 1].decode("utf-8", "surrogateescape")] = status_rows[
            index
        ].decode()
    records = []
    for raw in numstat:
        if not raw:
            continue
        added, deleted, raw_path = raw.split(b"\t", 2)
        path = raw_path.decode("utf-8", "surrogateescape")
        binary = added == b"-" or deleted == b"-"
        records.append(
            {
                "path": path,
                "added": 0 if binary else int(added),
                "deleted": 0 if binary else int(deleted),
                "binary": binary,
                "status": statuses.get(path, "M"),
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    records = _git_records(args.base)
    validate_changed_files(records)
    print(
        json.dumps(
            {"files": records, "changed_lines": sum(r["added"] + r["deleted"] for r in records)}
        )
    )


if __name__ == "__main__":
    main()
