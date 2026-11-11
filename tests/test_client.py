from __future__ import annotations

import httpx
import pytest

from github_quick_launcher import client as client_module
from github_quick_launcher.client import (
    MAX_PAGES, BadCredentials, GitHubClient, NotFound, Offline, RateLimited, Repo, build_http,
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
    assert listing.etag is None  # page 2 had no ETag, so it cannot be revalidated
    assert listing.repos[0] == Repo(
        "me/one", "", "https://github.com/me/one", "https://avatars.example/me")


async def test_list_repos_stops_following_pages_at_the_cap(client, httpx_mock):
    next_page = f"{API}/user/repos?per_page=100&sort=updated&page=2"
    httpx_mock.add_response(
        url=FIRST_PAGE, json=[api_repo("me/one")],
        headers={"Link": f'<{next_page}>; rel="next"'},
    )
    httpx_mock.add_response(
        url=next_page, json=[api_repo("me/two")], is_reusable=True,
        headers={"Link": f'<{next_page}>; rel="next"'},
    )

    listing = await client.list_repos("/user/repos")

    assert len(httpx_mock.get_requests()) == MAX_PAGES
    assert len(listing.repos) == MAX_PAGES


async def test_retry_after_becomes_a_rate_limit(client, httpx_mock, monkeypatch):
    monkeypatch.setattr(client_module, "_now", lambda: 5000.0)
    httpx_mock.add_response(url=FIRST_PAGE, status_code=403, headers={"Retry-After": "120"})
    with pytest.raises(RateLimited) as raised:
        await client.list_repos("/user/repos")
    assert raised.value.reset_at == 5000 + 120


async def test_list_repos_sends_etag_and_reports_not_modified(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)

    listing = await client.list_repos("/user/repos", etag='pages:"v1"')

    assert listing.repos is None
    assert listing.etag == 'pages:"v1"'
    assert httpx_mock.get_request().headers["If-None-Match"] == '"v1"'


SECOND_PAGE = f"{API}/user/repos?per_page=100&sort=updated&page=2"


def two_pages(httpx_mock, second_etag='"p2"', second="me/two"):
    httpx_mock.add_response(
        url=FIRST_PAGE, json=[api_repo("me/one")],
        headers={"ETag": '"p1"', "Link": f'<{SECOND_PAGE}>; rel="next"'},
    )
    httpx_mock.add_response(url=SECOND_PAGE, json=[api_repo(second)], headers={"ETag": second_etag})


async def test_every_page_etag_is_kept(client, httpx_mock):
    two_pages(httpx_mock)
    listing = await client.list_repos("/user/repos")
    assert listing.etag == 'pages:"p1" "p2"'


async def test_unchanged_only_when_every_page_is_unchanged(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)
    httpx_mock.add_response(url=SECOND_PAGE, status_code=304)

    listing = await client.list_repos("/user/repos", etag='pages:"p1" "p2"')

    assert listing.repos is None
    assert listing.etag == 'pages:"p1" "p2"'
    assert [r.headers["If-None-Match"] for r in httpx_mock.get_requests()] == ['"p1"', '"p2"']


async def test_a_change_beyond_page_one_refetches_the_list(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)
    httpx_mock.add_response(
        url=SECOND_PAGE, json=[api_repo("me/new-star")], headers={"ETag": '"p2b"'})
    two_pages(httpx_mock, second_etag='"p2b"', second="me/new-star")

    listing = await client.list_repos("/user/repos", etag='pages:"p1" "p2"')

    assert [repo.full_name for repo in listing.repos] == ["me/one", "me/new-star"]
    assert listing.etag == 'pages:"p1" "p2b"'
    requests = httpx_mock.get_requests()
    assert requests[1].headers["If-None-Match"] == '"p2"'
    assert "If-None-Match" not in requests[2].headers


async def test_a_snapshot_from_an_older_release_is_refetched_once(client, httpx_mock):
    two_pages(httpx_mock)

    listing = await client.list_repos("/user/repos", etag='"only-page-one"')

    assert listing.repos is not None
    assert "If-None-Match" not in httpx_mock.get_requests()[0].headers
    assert listing.etag == 'pages:"p1" "p2"'


def full_page(start: int) -> list:
    return [api_repo(f"me/repo-{number}") for number in range(start, start + 100)]


async def test_a_list_ending_on_a_full_page_keeps_the_etag_of_the_empty_page_after_it(
    client, httpx_mock,
):
    httpx_mock.add_response(url=FIRST_PAGE, json=full_page(0), headers={"ETag": '"p1"'})
    httpx_mock.add_response(url=SECOND_PAGE, json=[], headers={"ETag": '"empty"'})

    listing = await client.list_repos("/user/repos")

    assert len(listing.repos) == 100
    assert listing.etag == 'pages:"p1" "empty"'


async def test_growth_past_a_full_last_page_is_noticed(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)
    httpx_mock.add_response(
        url=SECOND_PAGE, json=[api_repo("me/dormant-star")], headers={"ETag": '"p2"'})
    httpx_mock.add_response(
        url=FIRST_PAGE, json=full_page(0),
        headers={"ETag": '"p1"', "Link": f'<{SECOND_PAGE}>; rel="next"'},
    )
    httpx_mock.add_response(
        url=SECOND_PAGE, json=[api_repo("me/dormant-star")], headers={"ETag": '"p2"'})

    listing = await client.list_repos("/user/repos", etag='pages:"p1" "empty"')

    assert listing.repos[-1].full_name == "me/dormant-star"
    assert len(listing.repos) == 101
    assert listing.etag == 'pages:"p1" "p2"'


async def test_a_failure_on_a_later_page_is_raised_not_read_as_unchanged(client, httpx_mock):
    httpx_mock.add_response(url=FIRST_PAGE, status_code=304)
    httpx_mock.add_response(
        url=SECOND_PAGE, status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
    )

    with pytest.raises(RateLimited):
        await client.list_repos("/user/repos", etag='pages:"p1" "p2"')


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


async def test_login_names_the_account_behind_the_token(client, httpx_mock):
    httpx_mock.add_response(url=f"{API}/user", json={"login": "octocat", "id": 1})
    assert await client.login() == "octocat"
