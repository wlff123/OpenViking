import json
import re
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


def test_triage_workflow_requires_human_analysis_label():
    workflow = (REPOSITORY / ".github/workflows/agent-triage.yml").read_text()

    assert "issues:" in workflow
    assert "types: [labeled]" in workflow
    assert "opened" not in workflow
    assert "reopened" not in workflow
    assert "agent:analyze" in workflow
    assert "agent:retriage" in workflow
    assert "automation/viking-forge/prompts/triage.md" in workflow


def test_fix_workflow_creates_only_draft_prs_after_guard():
    workflow = (REPOSITORY / ".github/workflows/agent-fix.yml").read_text()

    assert "agent:ready" in workflow
    assert "guard_patch.py" in workflow
    assert "--draft" in workflow
    assert "agent:generated" in workflow
    assert "persist-credentials: false" in workflow


def test_reconciliation_runs_hourly_without_codex():
    workflow = (REPOSITORY / ".github/workflows/agent-reconcile.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "cron: '17 * * * *'" in workflow
    assert "reconcile.py" in workflow
    assert "codex-action" not in workflow


def test_external_actions_are_pinned_to_full_sha():
    workflows = "\n".join(
        path.read_text() for path in (REPOSITORY / ".github/workflows").glob("agent-*.yml")
    )
    action_refs = re.findall(r"uses:\s+[^\s@]+@([^\s#]+)", workflows)

    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", value) for value in action_refs)


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
