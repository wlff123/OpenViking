from __future__ import annotations

import subprocess
from pathlib import Path


class WorkspaceManager:
    def __init__(
        self,
        repository: str | Path,
        runs_directory: str | Path,
        remote: str,
        base_branch: str,
    ):
        self.repository = Path(repository).resolve()
        self.runs_directory = Path(runs_directory).resolve()
        self.remote = remote
        self.base_branch = base_branch

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def prepare(self, run_id: str) -> tuple[Path, str]:
        if not run_id or Path(run_id).name != run_id:
            raise ValueError("run_id must be a single path component")
        run_directory = self.runs_directory / run_id
        worktree = run_directory / "worktree"
        if worktree.exists():
            raise FileExistsError(worktree)
        run_directory.mkdir(parents=True, exist_ok=True)

        self._git("fetch", "--no-tags", self.remote, self.base_branch)
        base_ref = f"refs/remotes/{self.remote}/{self.base_branch}"
        base_sha = self._git("rev-parse", "--verify", base_ref)
        self._git("worktree", "add", "--detach", str(worktree), base_sha)
        return worktree, base_sha

    def cleanup(self, worktree: str | Path) -> None:
        target = Path(worktree).resolve()
        if target.name != "worktree" or target.parent.parent != self.runs_directory:
            raise ValueError(f"Refusing to remove unmanaged worktree: {target}")
        if target.exists():
            self._git("worktree", "remove", "--force", str(target))
        self._git("worktree", "prune")
