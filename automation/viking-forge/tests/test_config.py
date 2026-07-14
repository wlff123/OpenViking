from viking_forge.config import Config


def test_config_reads_local_private_key_file_and_execution_paths(tmp_path, monkeypatch):
    private_key = tmp_path / "app.pem"
    private_key.write_text("private-key", encoding="utf-8")
    values = {
        "REPOSITORY": "wlff123/OpenViking",
        "REPOSITORY_PATH": "/data/repository",
        "DATABASE_PATH": "/data/runtime/forge.sqlite3",
        "RUNS_DIRECTORY": "/data/runtime/runs",
        "DASHBOARD_USERNAME": "maintainer",
        "DASHBOARD_PASSWORD": "password",
        "DASHBOARD_CSRF_SECRET": "csrf",
        "GITHUB_WEBHOOK_SECRET": "webhook",
        "GITHUB_APP_ID": "123",
        "GITHUB_APP_SLUG": "vikingforge-test",
        "GITHUB_APP_PRIVATE_KEY_FILE": str(private_key),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)

    config = Config.from_env()

    assert config.repository_path == "/data/repository"
    assert config.runs_directory == "/data/runtime/runs"
    assert config.github_app_private_key == "private-key"
    assert config.git_remote == "origin"
    assert config.base_branch == "main"
    assert config.codex_executable == "codex"
