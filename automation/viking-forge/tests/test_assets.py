import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = PROJECT.parents[1]


def test_codex_schemas_are_valid_and_closed():
    for name, required in {
        "triage.json": {
            "summary",
            "category",
            "confidence",
            "candidate",
            "needs_info",
            "risk_flags",
        },
        "fix.json": {"summary", "tests", "risks"},
    }.items():
        schema = json.loads((PROJECT / "schemas" / name).read_text())
        assert schema["type"] == "object"
        assert set(schema["required"]) >= required
        assert schema["additionalProperties"] is False


def test_triage_prompt_keeps_candidate_and_risk_flags_consistent():
    prompt = (PROJECT / "prompts" / "triage.md").read_text()

    assert "risk_flags` 非空时，`candidate` 必须为 `false`" in prompt


def test_fix_prompt_uses_prepared_validation_environment():
    prompt = (PROJECT / "prompts" / "fix.md").read_text()

    assert "VALIDATION_VENV" in prompt


def test_github_actions_execution_assets_are_removed():
    for name in ("agent-triage.yml", "agent-fix.yml", "agent-reconcile.yml"):
        assert not (REPOSITORY / ".github" / "workflows" / name).exists()
    for name in ("issue_context.py", "post_callback.py", "reconcile.py"):
        assert not (PROJECT / "scripts" / name).exists()
    assert not (PROJECT / "src" / "viking_forge" / "callbacks.py").exists()


def test_runtime_uses_one_local_worker_and_no_callback_secret():
    main = (PROJECT / "src" / "viking_forge" / "main.py").read_text()
    config = (PROJECT / "src" / "viking_forge" / "config.py").read_text()

    assert "LocalWorker" in main
    assert 'name="viking-forge-worker"' in main
    assert "CALLBACK_SECRET" not in config
    assert "callback_secret" not in config


def test_deployment_assets_stay_in_viking_forge_directory():
    for relative in (
        "deploy/.env.example",
        "deploy/viking-forge.service",
        "docs/deployment.md",
        "README.md",
    ):
        assert (PROJECT / relative).is_file(), relative


def test_obsolete_container_deployment_assets_are_removed():
    for relative in (
        ".dockerignore",
        "deploy/Dockerfile",
        "deploy/docker-compose.yml",
        "deploy/Caddyfile",
    ):
        assert not (PROJECT / relative).exists(), relative


def test_local_service_runs_as_wlf1_with_local_codex_state():
    service = (PROJECT / "deploy" / "viking-forge.service").read_text()
    environment = (PROJECT / "deploy" / ".env.example").read_text()

    assert "User=wlf1" in service
    assert "viking_forge.main:app" in service
    assert "CODEX_HOME=/home/wlf1/.codex" in service
    assert "REPOSITORY_PATH=" in environment
    assert "RUNS_DIRECTORY=" in environment
    assert "GITHUB_APP_PRIVATE_KEY_FILE=" in environment
    assert "OPENAI_API_KEY" not in environment
    assert "CALLBACK_SECRET" not in environment
