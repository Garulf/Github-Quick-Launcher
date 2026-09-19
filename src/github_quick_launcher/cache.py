from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from github_quick_launcher.client import GitHubError, Listing, Repo

Fetch = Callable[[Optional[str]], Awaitable[Listing]]


class RepoStore:

    def __init__(
        self, path: Path, ttl: float, fetch: Fetch, clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._ttl = ttl
        self._fetch = fetch
        self._clock = clock
        self._repos: List[Repo] = []
        self._etag: Optional[str] = None
        self._fetched_at: Optional[float] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self.last_error: Optional[GitHubError] = None
        self._load()

    @property
    def has_snapshot(self) -> bool:
        return self._fetched_at is not None

    @property
    def is_stale(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at >= self._ttl

    async def repos(self) -> List[Repo]:
        if self.is_stale:
            self._start_refresh()
        if not self.has_snapshot and self._refresh_task is not None:
            # shield: the host cancels superseded queries, which must not
            # restart a cold fetch that the next keystroke needs too.
            await asyncio.shield(self._refresh_task)
            if not self.has_snapshot and self.last_error is not None:
                raise self.last_error
        return list(self._repos)

    async def refresh(self) -> None:
        listing = await self._fetch(self._etag)
        if listing.repos is not None:
            self._repos = listing.repos
            self._etag = listing.etag
        self._fetched_at = self._clock()
        self.last_error = None
        self._save()

    def _start_refresh(self) -> None:
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh_recording_errors())

    async def _refresh_recording_errors(self) -> None:
        try:
            await self.refresh()
        except GitHubError as exc:
            self.last_error = exc

    def _load(self) -> None:
        try:
            snapshot = json.loads(self._path.read_text(encoding="utf-8"))
            self._repos = [Repo(**repo) for repo in snapshot["repos"]]
            self._etag = snapshot["etag"]
            self._fetched_at = float(snapshot["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError):
            self._repos, self._etag, self._fetched_at = [], None, None

    def _save(self) -> None:
        snapshot = {
            "fetched_at": self._fetched_at,
            "etag": self._etag,
            "repos": [asdict(repo) for repo in self._repos],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot), encoding="utf-8")
        os.replace(temporary, self._path)
