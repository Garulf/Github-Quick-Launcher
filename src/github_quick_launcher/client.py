from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

import httpx

API_URL = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 10
SEARCH_LIMIT = 15
TIMEOUT_SECONDS = 10.0

_now = time.time


class GitHubError(Exception):
    pass


class BadCredentials(GitHubError):
    pass


class NotFound(GitHubError):
    pass


class Offline(GitHubError):
    pass


class RateLimited(GitHubError):

    def __init__(self, reset_at: int) -> None:
        super().__init__("GitHub API rate limit exhausted")
        self.reset_at = reset_at


@dataclass(frozen=True)
class Repo:
    full_name: str
    description: str
    html_url: str
    avatar_url: str

    @classmethod
    def from_api(cls, item: Mapping[str, Any]) -> Repo:
        return cls(
            full_name=item["full_name"],
            description=item.get("description") or "",
            html_url=item["html_url"],
            avatar_url=(item.get("owner") or {}).get("avatar_url") or "",
        )


@dataclass(frozen=True)
class Listing:
    repos: Optional[List[Repo]]
    etag: Optional[str]


def build_http(token: str) -> httpx.AsyncClient:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Github-Quick-Launcher",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(base_url=API_URL, headers=headers, timeout=TIMEOUT_SECONDS)


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    if status == 401:
        raise BadCredentials("GitHub rejected the token")
    if status == 404:
        raise NotFound("GitHub has no such user or repository list")
    if status in (403, 429):
        if response.headers.get("X-RateLimit-Remaining") == "0":
            raise RateLimited(int(response.headers.get("X-RateLimit-Reset", "0")))
        retry_after = _retry_after_seconds(response)
        if retry_after is not None:
            raise RateLimited(int(_now()) + retry_after)
    raise GitHubError(f"GitHub returned HTTP {status}")


def _retry_after_seconds(response: httpx.Response) -> Optional[int]:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return max(0, int(header.strip()))
    except ValueError:
        return None


class GitHubClient:

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def _get(
        self, url: str, params: Optional[Mapping[str, Any]] = None, etag: Optional[str] = None,
    ) -> httpx.Response:
        headers = {"If-None-Match": etag} if etag else {}
        try:
            response = await self._http.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:
            raise Offline(str(exc)) from exc
        _raise_for_status(response)
        return response

    async def list_repos(self, path: str, etag: Optional[str] = None) -> Listing:
        response = await self._get(path, {"per_page": PER_PAGE, "sort": "updated"}, etag)
        if response.status_code == 304:
            return Listing(None, etag)
        fresh_etag = response.headers.get("ETag")
        repos = [Repo.from_api(item) for item in response.json()]
        pages = 1
        while "next" in response.links and pages < MAX_PAGES:
            response = await self._get(response.links["next"]["url"])
            repos.extend(Repo.from_api(item) for item in response.json())
            pages += 1
        return Listing(repos, fresh_etag)

    async def search(self, q: str, limit: int = SEARCH_LIMIT) -> List[Repo]:
        response = await self._get("/search/repositories", {"q": q, "per_page": limit})
        return [Repo.from_api(item) for item in response.json()["items"]]

    async def aclose(self) -> None:
        await self._http.aclose()
