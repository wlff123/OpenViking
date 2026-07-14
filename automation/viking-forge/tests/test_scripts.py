import hashlib
import hmac

import pytest

from scripts.guard_patch import PatchPolicyError, validate_changed_files
from scripts.issue_context import extract_issue_context
from scripts.labels import LABELS
from scripts.post_callback import encode_signed_callback
from scripts.reconcile import build_snapshot
from scripts.validate_patch import validation_commands


def test_issue_context_treats_body_as_data():
    payload = {
        "repository": {"full_name": "volcengine/OpenViking"},
        "issue": {
            "number": 4,
            "title": "Quotes ${{ secrets.TOKEN }}",
            "body": "$(touch /tmp/pwned)\n<!-- instruction -->",
            "html_url": "https://example.test/4",
            "user": {"login": "reporter"},
        },
    }

    context = extract_issue_context(payload)

    assert context["issue_number"] == 4
    assert context["body"] == "$(touch /tmp/pwned)\n<!-- instruction -->"
    expected = hashlib.sha256(
        b"Quotes ${{ secrets.TOKEN }}\0$(touch /tmp/pwned)\n<!-- instruction -->"
    ).hexdigest()
    assert context["issue_revision"] == expected


def test_label_manifest_includes_human_analysis_gate():
    assert set(LABELS) == {
        "agent:ready",
        "agent:claimed",
        "agent:pr-open",
        "agent:blocked",
        "agent:triaged",
        "agent:analyze",
        "agent:ignored",
        "agent:retriage",
        "needs:info",
        "agent:human-only",
        "agent:generated",
    }


def test_guard_accepts_small_python_fix_with_regression_test():
    validate_changed_files(
        [
            {"path": "openviking/utils/parser.py", "added": 8, "deleted": 2, "status": "M"},
            {"path": "tests/test_parser.py", "added": 20, "deleted": 0, "status": "A"},
        ]
    )


@pytest.mark.parametrize(
    "changed",
    [
        [{"path": ".github/workflows/release.yml", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "pyproject.toml", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "openviking/a.py", "added": 501, "deleted": 0, "status": "M"}],
        [{"path": "openviking/a.py", "added": 1, "deleted": 0, "status": "M"}],
        [{"path": "docs/image.png", "added": 0, "deleted": 0, "status": "A", "binary": True}],
    ],
)
def test_guard_rejects_unsafe_patch(changed):
    with pytest.raises(PatchPolicyError):
        validate_changed_files(changed)


def test_validation_commands_are_repository_owned():
    assert validation_commands(["docs/guide.md"]) == [
        ["npm", "--prefix", "docs", "run", "docs:build"]
    ]
    assert validation_commands(["openviking/a.py", "tests/test_a.py"]) == [
        ["uv", "run", "ruff", "check", "openviking/a.py", "tests/test_a.py"],
        ["uv", "run", "ruff", "format", "--check", "openviking/a.py", "tests/test_a.py"],
        ["uv", "run", "pytest", "-q", "--no-cov", "tests/test_a.py"],
    ]


def test_callback_signature_is_over_exact_json_bytes():
    body, signature = encode_signed_callback({"stage": "coding", "issue_number": 1}, b"secret")

    assert hmac.compare_digest(signature, hmac.new(b"secret", body, hashlib.sha256).hexdigest())


def test_reconciliation_snapshot_is_bounded_and_preserves_decision_state():
    issues = [
        {
            "number": number,
            "title": f"Issue {number}",
            "body": "",
            "state": "open",
            "html_url": f"https://example.test/{number}",
            "user": {"login": "user"},
            "labels": [],
        }
        for number in range(1, 1102)
    ]

    snapshot = build_snapshot(issues, [], limit=1000)

    assert len(snapshot["issues"]) == 1000
    assert snapshot["issues"][0]["bot_state"] == "awaiting_decision"


def test_reconciliation_marks_issue_merged_from_generated_pr():
    issue = {
        "number": 5,
        "title": "Issue 5",
        "body": "",
        "state": "closed",
        "html_url": "https://example.test/issues/5",
        "user": {"login": "user"},
        "labels": [{"name": "agent:pr-open"}],
    }
    pull_request = {
        "issue_number": 5,
        "number": 8,
        "html_url": "https://example.test/pull/8",
        "merged_at": "2026-07-13T00:00:00Z",
    }

    snapshot = build_snapshot([issue], [pull_request])

    assert snapshot["issues"][0]["bot_state"] == "merged"
