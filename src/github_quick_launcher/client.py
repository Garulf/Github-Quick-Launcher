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
# A listing's ETag is stored as one ETag per page behind a version prefix.
# A snapshot from an older release holds only page 1's ETag and has no
# prefix, so it is refetched once instead of being trusted. The separator
# must be legal in a header value: a release from before the prefix sends
# the stored string as If-None-Match unchanged, and GitHub answers a value
# it does not recognise with a plain 200. A space never appears in an ETag.
ETAG_PREFIX = "pages:"
ETAG_SEPARATOR = " "

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


def _split_etags(etag: Optional[str]) -> List[str]:
    if not etag or not etag.startswith(ETAG_PREFIX):
        return []
    return [tag for tag in etag[len(ETAG_PREFIX):].split(ETAG_SEPARATOR) if tag]


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
        """Fetch every page of a repository list, or report it unchanged.

        ``etag`` holds one ETag per page. Page 1 alone is not enough: a
        repository added, starred or removed beyond the first 100 leaves
        page 1 untouched, so each later page is revalidated too. Any change
        refetches the whole list, since items shift across page boundaries.

        Only a request with a token gets its 304s free of charge. Without
        one every page checked counts against the 60 requests an hour.
        """
        known = _split_etags(etag)
        params = {"per_page": PER_PAGE, "sort": "updated"}
        response = await self._get(path, params, known[0] if known else None)
        if response.status_code == 304:
            if await self._pages_unchanged(path, params, known[1:]):
                return Listing(None, etag)
            response = await self._get(path, params)
        return await self._read_pages(path, params, response)

    async def _pages_unchanged(
        self, path: str, params: Mapping[str, Any], etags: List[str],
    ) -> bool:
        for number, page_etag in enumerate(etags, start=2):
            response = await self._get(path, {**params, "page": number}, page_etag)
            if response.status_code != 304:
                return False
        return True

    async def _read_pages(
        self, path: str, params: Mapping[str, Any], response: httpx.Response,
    ) -> Listing:
        etags: List[Optional[str]] = []
        repos: List[Repo] = []
        while True:
            items = response.json()
            repos.extend(Repo.from_api(item) for item in items)
            etags.append(response.headers.get("ETag"))
            if len(etags) >= MAX_PAGES:
                break
            if "next" in response.links:
                response = await self._get(response.links["next"]["url"])
            elif len(items) == PER_PAGE:
                # The list ends on a full page, so the next item added at
                # the end starts a new page and changes none of these. Keep
                # the ETag of that still empty page so the growth is seen.
                response = await self._get(path, {**params, "page": len(etags) + 1})
            else:
                break
        if not all(tag and ETAG_SEPARATOR not in tag for tag in etags):
            return Listing(repos, None)
        return Listing(repos, ETAG_PREFIX + ETAG_SEPARATOR.join(tag for tag in etags if tag))

    async def search(self, q: str, limit: int = SEARCH_LIMIT) -> List[Repo]:
        response = await self._get("/search/repositories", {"q": q, "per_page": limit})
        return [Repo.from_api(item) for item in response.json()["items"]]

    async def aclose(self) -> None:
        await self._http.aclose()
