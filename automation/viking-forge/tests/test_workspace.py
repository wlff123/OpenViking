import subprocess

from viking_forge.workspace import WorkspaceManager


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_prepare_and_cleanup_detached_worktree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git("init", "-b", "main", cwd=source)
    git("config", "user.name", "Test User", cwd=source)
    git("config", "user.email", "test@example.com", cwd=source)
    (source / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md", cwd=source)
    git("commit", "-m", "base", cwd=source)

    remote = tmp_path / "remote.git"
    git("clone", "--bare", str(source), str(remote), cwd=tmp_path)
    checkout = tmp_path / "checkout"
    git("clone", str(remote), str(checkout), cwd=tmp_path)
    base_sha = git("rev-parse", "HEAD", cwd=checkout)

    manager = WorkspaceManager(checkout, tmp_path / "runs", "origin", "main")
    worktree, prepared_sha = manager.prepare("run-1")

    assert worktree == tmp_path / "runs" / "run-1" / "worktree"
    assert prepared_sha == base_sha
    assert git("rev-parse", "HEAD", cwd=worktree) == base_sha
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree) == "HEAD"

    manager.cleanup(worktree)

    assert not worktree.exists()
    assert checkout.exists()
    assert git("rev-parse", "HEAD", cwd=checkout) == base_sha
