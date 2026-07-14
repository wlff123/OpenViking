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
