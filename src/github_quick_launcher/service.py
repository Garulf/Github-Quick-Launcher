from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from github_quick_launcher.cache import RepoStore
from github_quick_launcher.client import GitHubClient, GitHubError, Listing, Repo
from github_quick_launcher.settings import Settings

SEARCH_TTL_SECONDS = 60
SEARCH_MEMO_LIMIT = 64


def listing_paths(settings: Settings) -> Tuple[str, str]:
    if settings.token:
        return "/user/repos", "/user/starred"
    return f"/users/{settings.username}/repos", f"/users/{settings.username}/starred"


class RepoService:

    def __init__(
        self, settings: Settings, client: GitHubClient, cache_dir: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._clock = clock
        self._searches: Dict[str, Tuple[float, List[Repo]]] = {}
        self._own: Optional[RepoStore] = None
        self._stars: Optional[RepoStore] = None
        key = settings.identity_key
        if key is not None:
            own_path, stars_path = listing_paths(settings)
            self._own = self._store(cache_dir / f"{key}-repos.json", own_path, settings)
            self._stars = self._store(cache_dir / f"{key}-stars.json", stars_path, settings)

    def _store(self, file: Path, api_path: str, settings: Settings) -> RepoStore:
        async def fetch(etag: Optional[str]) -> Listing:
            return await self._client.list_repos(api_path, etag)
        return RepoStore(file, settings.ttl_seconds, fetch, self._clock)

    @property
    def has_identity(self) -> bool:
        return self._own is not None

    @property
    def last_error(self) -> Optional[GitHubError]:
        for store in (self._own, self._stars):
            if store is not None and store.last_error is not None:
                return store.last_error
        return None

    async def own_repos(self) -> List[Repo]:
        return await self._own.repos() if self._own is not None else []

    def own_snapshot(self) -> List[Repo]:
        return self._own.snapshot() if self._own is not None else []

    async def starred(self) -> List[Repo]:
        return await self._stars.repos() if self._stars is not None else []

    async def search(self, q: str) -> List[Repo]:
        memo = self._searches.get(q)
        if memo is not None and self._clock() - memo[0] < SEARCH_TTL_SECONDS:
            return memo[1]
        repos = await self._client.search(q)
        if len(self._searches) >= SEARCH_MEMO_LIMIT:
            self._searches.clear()
        self._searches[q] = (self._clock(), repos)
        return repos

    async def refresh_all(self) -> None:
        first_failure: Optional[BaseException] = None
        for store in (self._own, self._stars):
            if store is None:
                continue
            try:
                await store.refresh()
            except Exception as failure:
                if first_failure is None:
                    first_failure = failure
        if first_failure is not None:
            raise first_failure

    async def aclose(self) -> None:
        await self._client.aclose()
