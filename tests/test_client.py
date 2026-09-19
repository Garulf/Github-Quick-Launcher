from __future__ import annotations

import httpx
import pytest

from github_quick_launcher.client import (
    BadCredentials, GitHubClient, NotFound, Offline, RateLimited, Repo, build_http,
)

API = "https://api.github.com"
FIRST_PAGE = f"{API}/user/repos?per_page=100&sort=updated"


def api_repo(full_name: str) -> dict:
    owner = full_name.split("/")[0]
    return {
        "full_name": full_name,
        "description": None,
        "html_url": f"https://github.com/{full_name}",
        "owner": {"avatar_url": f"https://avatars.example/{owner}"},
    }


@pytest.fixture
async def client():
    github = GitHubClient(build_http(""))
    yield github
    await github.aclose()


def test_build_http_sends_bearer_token_only_when_set():
    assert "Authorization" not in build_http("").headers
    assert build_http("abc").headers["Authorization"] == "Bearer abc"


async def test_list_repos_follows_pagination(client, httpx_mock):
    second_page = f"{API}/user/repos?per_page=100&sort=updated&page=2"
    httpx_mock.add_response(
        url=FIRST_PAGE, json=[api_repo("me/one")],
        headers={"ETag": '"v1"', "Link": f'<{second_page}>; rel="next"'},
    )
    httpx_mock.add_response(url=second_page, json=[api_repo("me/two")])

    listing = await client.list_repos("/user/repos")

    assert [repo.full_name for repo in listing.repos] == ["me/one", "me/two"]
    assert listing.etag == '"v1"'
    assert listing.repos[0] == Repo(
        "me/one", "", "https://github.com/me/one", "https://avatars.example/me")


async def test_list_repos_sends_etag_and_reports_not_modified(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)

    listing = await client.list_repos("/user/repos", etag='"v1"')

    assert listing.repos is None
    assert listing.etag == '"v1"'
    assert httpx_mock.get_request().headers["If-None-Match"] == '"v1"'


async def test_search_returns_limited_items(client, httpx_mock):
    httpx_mock.add_response(
        url=f"{API}/search/repositories?q=user%3Agarulf+flow&per_page=15",
        json={"items": [api_repo("garulf/flow")]},
    )
    repos = await client.search("user:garulf flow")
    assert [repo.full_name for repo in repos] == ["garulf/flow"]


async def test_401_raises_bad_credentials(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=401)
    with pytest.raises(BadCredentials):
        await client.list_repos("/user/repos")


async def test_exhausted_rate_limit_raises_rate_limited(client, httpx_mock):
    httpx_mock.add_response(
        url=FIRST_PAGE, status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
    )
    with pytest.raises(RateLimited) as raised:
        await client.list_repos("/user/repos")
    assert raised.value.reset_at == 1700000000


async def test_404_raises_not_found(client, httpx_mock):
    httpx_mock.add_response(url=f"{API}/users/ghost/repos?per_page=100&sort=updated",
                            status_code=404)
    with pytest.raises(NotFound):
        await client.list_repos("/users/ghost/repos")


async def test_transport_failure_raises_offline(client, httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("no route"))
    with pytest.raises(Offline):
        await client.list_repos("/user/repos")
