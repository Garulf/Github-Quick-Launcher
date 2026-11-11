from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from github_quick_launcher import cache
from github_quick_launcher.cache import RepoStore
from github_quick_launcher.client import GitHubClient, GitHubError, Listing, Repo
from github_quick_launcher.settings import Settings

SEARCH_TTL_SECONDS = 60
SEARCH_MEMO_LIMIT = 64
LOGIN_RETRY_SECONDS = 60.0
# Without a token every page of an early revalidation counts against 60
# requests an hour, even when GitHub answers 304.
ANONYMOUS_MISS_COOLDOWN_SECONDS = 600.0


def listing_paths(settings: Settings) -> Tuple[str, str]:
    if settings.token:
        return "/user/repos", "/user/starred"
    return f"/users/{settings.username}/repos", f"/users/{settings.username}/starred"


class RepoService:

    def __init__(
        self, settings: Settings, client: GitHubClient, cache_dir: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._client = client
        self._cache_dir = cache_dir
        self._clock = clock
        self._searches: Dict[str, Tuple[float, List[Repo]]] = {}
        self._login: Optional[str] = None
        self._login_asked_at: Optional[float] = None
        self._login_task: Optional["asyncio.Task[None]"] = None
        self.own: Optional[RepoStore] = None
        self.stars: Optional[RepoStore] = None
        key = settings.identity_key
        if key is not None:
            own_path, stars_path = listing_paths(settings)
            self.own = self._store(cache_dir / f"{key}-repos.json", own_path, settings)
            self.stars = self._store(cache_dir / f"{key}-stars.json", stars_path, settings)

    def _store(self, file: Path, api_path: str, settings: Settings) -> RepoStore:
        async def fetch(etag: Optional[str]) -> Listing:
            return await self._client.list_repos(api_path, etag)
        miss_cooldown = (
            cache.MISS_COOLDOWN_SECONDS if settings.token else ANONYMOUS_MISS_COOLDOWN_SECONDS)
        return RepoStore(file, settings.ttl_seconds, fetch, self._clock, miss_cooldown)

    @property
    def _stores(self) -> List[RepoStore]:
        return [store for store in (self.own, self.stars) if store is not None]

    @property
    def has_identity(self) -> bool:
        return self.own is not None

    @property
    def last_error(self) -> Optional[GitHubError]:
        for store in self._stores:
            if store.last_error is not None:
                return store.last_error
        return None

    def own_login(self) -> str:
        """The account whose repositories the own list holds in full, or "".

        With a username that is the username. A token's list also has
        repositories the account only collaborates on, so GitHub is asked
        who the token belongs to; until it has answered, nobody is.
        """
        if not self.settings.token:
            return self.settings.username
        if self._login is None:
            self._start_login_lookup()
        return self._login or ""

    def _start_login_lookup(self) -> None:
        if self._login_task is not None and not self._login_task.done():
            return
        now = self._clock()
        if self._login_asked_at is not None and now - self._login_asked_at < LOGIN_RETRY_SECONDS:
            return
        self._login_asked_at = now
        self._login_task = asyncio.get_running_loop().create_task(self._look_up_login())

    async def _look_up_login(self) -> None:
        try:
            self._login = await self._client.login() or None
        except GitHubError:
            # Asked again later; the list itself reports what is wrong.
            pass

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
        for store in self._stores:
            try:
                await store.refresh()
            except Exception as failure:
                if first_failure is None:
                    first_failure = failure
        if first_failure is not None:
            raise first_failure

    def cache_files(self) -> List[Path]:
        return [store.path for store in self._stores]

    def prune_other_caches(self) -> None:
        """Delete snapshots left behind by identities other than this one."""
        cache.prune(self._cache_dir, self.cache_files())

    def retire(self) -> None:
        """Stop writing this identity's snapshots; their files may be deleted."""
        for store in self._stores:
            store.stop_persisting()

    def clear_cache(self) -> None:
        """Forget every repository list, in memory and on disk."""
        self._searches.clear()
        for store in self._stores:
            store.clear()
        cache.prune(self._cache_dir, [])

    async def aclose(self) -> None:
        await self._client.aclose()
