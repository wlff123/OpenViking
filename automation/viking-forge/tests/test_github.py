import base64
import json

import httpx

from viking_forge.github import GitHubClient


def test_github_client_reads_issue_and_adds_label():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"number": 12, "state": "open", "title": "Title", "body": "Body"},
            )
        return httpx.Response(200, json={"labels": [{"name": "agent:analyze"}]})

    transport = httpx.MockTransport(handler)
    client = GitHubClient(
        repository="volcengine/OpenViking",
        token_provider=lambda: "installation-token",
        http_client=httpx.Client(transport=transport, base_url="https://api.github.com"),
    )

    issue = client.get_issue(12)
    client.add_label(12, "agent:analyze")

    assert issue["title"] == "Title"
    assert [request.url.path for request in requests] == [
        "/repos/volcengine/OpenViking/issues/12",
        "/repos/volcengine/OpenViking/issues/12/labels",
    ]
    assert all(
        request.headers["authorization"] == "Bearer installation-token" for request in requests
    )
    assert requests[1].content == b'{"labels":["agent:analyze"]}'


def test_github_client_raises_on_api_error():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, json={"message": "forbidden"})
    )
    client = GitHubClient(
        repository="volcengine/OpenViking",
        token_provider=lambda: "token",
        http_client=httpx.Client(transport=transport, base_url="https://api.github.com"),
    )

    try:
        client.get_issue(1)
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 403
    else:
        raise AssertionError("Expected HTTPStatusError")


def make_client(handler):
    return GitHubClient(
        repository="volcengine/OpenViking",
        token_provider=lambda: "token",
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://api.github.com"
        ),
    )


def test_permission_and_label_removal_contract():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"permission": "maintain"})
        return httpx.Response(204)

    client = make_client(handler)

    assert client.get_collaborator_permission("maintainer") == "maintain"
    client.remove_label(7, "agent:ready")

    assert [request.method for request in requests] == ["GET", "DELETE"]
    assert requests[0].url.path == (
        "/repos/volcengine/OpenViking/collaborators/maintainer/permission"
    )
    assert requests[1].url.raw_path.decode().endswith("/issues/7/labels/agent%3Aready")


def test_upsert_triage_comment_updates_existing_marker():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"id": 91, "body": "old\n<!-- viking-forge-triage -->"}],
            )
        return httpx.Response(200, json={"id": 91})

    client = make_client(handler)
    client.upsert_triage_comment(7, "new analysis")

    assert requests[0].url.path == "/repos/volcengine/OpenViking/issues/7/comments"
    assert requests[0].url.params["per_page"] == "100"
    assert requests[1].method == "PATCH"
    assert requests[1].url.path == "/repos/volcengine/OpenViking/issues/comments/91"
    assert json.loads(requests[1].content) == {
        "body": "new analysis\n\n<!-- viking-forge-triage -->"
    }


def test_upsert_triage_comment_creates_when_marker_is_absent():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": 92})

    client = make_client(handler)
    client.upsert_triage_comment(8, "analysis")

    assert requests[1].method == "POST"
    assert requests[1].url.path == "/repos/volcengine/OpenViking/issues/8/comments"


def test_create_branch_from_files_uses_git_data_api(tmp_path):
    requests = []
    responses = iter(
        [
            httpx.Response(201, json={"sha": "blob-1"}),
            httpx.Response(201, json={"sha": "tree-1"}),
            httpx.Response(201, json={"sha": "commit-1"}),
            httpx.Response(201, json={"ref": "refs/heads/agent/issue-7"}),
        ]
    )

    def handler(request):
        requests.append(request)
        return next(responses)

    worktree = tmp_path / "worktree"
    changed_file = worktree / "openviking" / "a.py"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_text("value = 2\n", encoding="utf-8")
    client = make_client(handler)
    changed = [
        {"path": "openviking/a.py", "status": "M", "mode": "100755"},
        {"path": "tests/obsolete.py", "status": "D", "mode": "100644"},
    ]

    commit_sha = client.create_branch_from_files(
        "base-1", "agent/issue-7", worktree, changed, "fix: issue 7"
    )

    assert commit_sha == "commit-1"
    assert [request.url.path for request in requests] == [
        "/repos/volcengine/OpenViking/git/blobs",
        "/repos/volcengine/OpenViking/git/trees",
        "/repos/volcengine/OpenViking/git/commits",
        "/repos/volcengine/OpenViking/git/refs",
    ]
    assert json.loads(requests[0].content) == {
        "content": base64.b64encode(b"value = 2\n").decode(),
        "encoding": "base64",
    }
    assert json.loads(requests[1].content) == {
        "base_tree": "base-1",
        "tree": [
            {
                "path": "openviking/a.py",
                "mode": "100755",
                "type": "blob",
                "sha": "blob-1",
            },
            {
                "path": "tests/obsolete.py",
                "mode": "100644",
                "type": "blob",
                "sha": None,
            },
        ],
    }
    assert json.loads(requests[2].content) == {
        "message": "fix: issue 7",
        "tree": "tree-1",
        "parents": ["base-1"],
    }
    assert json.loads(requests[3].content) == {
        "ref": "refs/heads/agent/issue-7",
        "sha": "commit-1",
    }


def test_create_draft_pr_contract():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"number": 12, "html_url": "https://example/pull/12"})

    client = make_client(handler)

    pull_request = client.create_draft_pr("agent/issue-7", "main", "Fix #7", "Closes #7")

    assert pull_request["number"] == 12
    assert requests[0].url.path == "/repos/volcengine/OpenViking/pulls"
    assert json.loads(requests[0].content) == {
        "head": "agent/issue-7",
        "base": "main",
        "title": "Fix #7",
        "body": "Closes #7",
        "draft": True,
    }
