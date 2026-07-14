from __future__ import annotations

import argparse
import json
import subprocess
import time


def validation_commands(changed_files: list[str]) -> list[list[str]]:
    if changed_files and all(path.startswith("docs/") for path in changed_files):
        return [["npm", "--prefix", "docs", "run", "docs:build"]]
    python_files = [path for path in changed_files if path.endswith(".py")]
    test_files = [
        path for path in python_files if path.startswith("tests/test_") or "/test_" in f"/{path}"
    ]
    return [
        ["uv", "run", "ruff", "check", *python_files],
        ["uv", "run", "ruff", "format", "--check", *python_files],
        ["uv", "run", "pytest", "-q", "--no-cov", *test_files],
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    files = json.loads(args.files_json)
    results = []
    for command in validation_commands(files):
        started = time.monotonic()
        completed = subprocess.run(command, capture_output=True, text=True)
        results.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": (completed.stdout + completed.stderr)[-8192:],
            }
        )
        if completed.returncode:
            break
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(results, output, ensure_ascii=False, indent=2)
    raise SystemExit(next((r["exit_code"] for r in results if r["exit_code"]), 0))


if __name__ == "__main__":
    main()
