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
        ".dockerignore",
        "deploy/Dockerfile",
        "deploy/docker-compose.yml",
        "deploy/Caddyfile",
        "deploy/.env.example",
        "docs/deployment.md",
        "README.md",
    ):
        assert (PROJECT / relative).is_file(), relative


def test_docker_context_uses_a_source_allowlist():
    dockerignore = (PROJECT / ".dockerignore").read_text()

    assert dockerignore.startswith("*\n")
    assert "!src/**" in dockerignore
    assert "!.env" not in dockerignore


def test_docker_image_prepares_writable_data_directory():
    dockerfile = (PROJECT / "deploy/Dockerfile").read_text()

    prepare_data = dockerfile.index("mkdir -p /data")
    run_as_app = dockerfile.index("USER app")

    assert prepare_data < run_as_app
    assert "chown app:app /data" in dockerfile
