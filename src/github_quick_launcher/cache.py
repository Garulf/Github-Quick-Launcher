from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable, Iterable, List, Optional, Set

from github_quick_launcher.client import GitHubError, Listing, RateLimited, Repo

Fetch = Callable[[Optional[str]], Awaitable[Listing]]

MAX_COOLDOWN_SECONDS = 60.0
# A revalidation asked for by a miss (a filter matching nothing, a search
# hit that should have been cached) happens at most this often, so typing
# gibberish cannot turn every keystroke into a request.
MISS_COOLDOWN_SECONDS = 60.0
CACHE_SUFFIXES = (".json", ".tmp")

# pyflowlauncher attaches the plugin.log handler to its own logger, so logging
# under a child of it is what reaches the log Flow Launcher ships to users.
_LOGGER = logging.getLogger(f"pyflowlauncher.{__name__}")

# The loop only holds weak references to tasks, and clear() lets go of a
# refresh that is still running.
_abandoned: Set["asyncio.Task[None]"] = set()


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
        self._failed_at: Optional[float] = None
        self.last_error: Optional[GitHubError] = None
        self._persist = True
        self._revalidated_at: Optional[float] = None
        self._generation = 0
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def has_snapshot(self) -> bool:
        return self._fetched_at is not None

    @property
    def is_stale(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at >= self._ttl

    @property
    def _in_cooldown(self) -> bool:
        if self._failed_at is None:
            return False
        until = self._failed_at + min(self._ttl, MAX_COOLDOWN_SECONDS)
        if isinstance(self.last_error, RateLimited):
            until = max(until, float(self.last_error.reset_at))
        return self._clock() < until

    async def repos(self) -> List[Repo]:
        cooling = self._in_cooldown
        if self.is_stale and not cooling:
            self._start_refresh()
        if not self.has_snapshot:
            if self._refresh_task is not None and not cooling:
                # shield: the host cancels superseded queries, which must not
                # restart a cold fetch that the next keystroke needs too.
                await asyncio.shield(self._refresh_task)
            if not self.has_snapshot and self.last_error is not None:
                raise self.last_error
        return list(self._repos)

    def snapshot(self) -> List[Repo]:
        if self.is_stale and not self._in_cooldown:
            self._start_refresh()
        return list(self._repos)

    async def refresh(self) -> None:
        generation = self._generation
        listing = await self._fetch(self._etag)
        if generation != self._generation:
            # clear() ran while GitHub was answering. The answer belongs to
            # the list that was just deleted: "not modified" would now mean
            # an empty list, and saving would bring the file back.
            return
        if listing.repos is not None:
            self._repos = listing.repos
            self._etag = listing.etag
        self._fetched_at = self._clock()
        self._failed_at = None
        self.last_error = None
        self._save()

    def _may_revalidate(self) -> bool:
        if not self.has_snapshot or self._in_cooldown:
            return False
        now = self._clock()
        for last in (self._revalidated_at, self._fetched_at):
            if last is not None and now - last < MISS_COOLDOWN_SECONDS:
                return False
        return True

    def nudge(self) -> bool:
        """Revalidate in the background because the snapshot looks out of date.

        The TTL is long because GitHub's ETags change on every push, but a
        new repository or star should not wait hours to show up. Misses are
        the signal that it is worth asking GitHub early.
        """
        if not self._may_revalidate():
            return False
        self._revalidated_at = self._clock()
        self._start_refresh()
        return self._refresh_task is not None

    async def revalidate(self, wait: float) -> bool:
        """Revalidate now and wait up to ``wait`` seconds for the result.

        Returns True only when a refresh finished successfully in time, so
        the caller knows a second look at the snapshot is worthwhile.
        """
        if not self.nudge():
            return False
        task = self._refresh_task
        assert task is not None
        try:
            # shield: a timeout or a superseded query must not cancel the
            # refresh itself; it still lands for the next keystroke.
            await asyncio.wait_for(asyncio.shield(task), wait)
        except asyncio.TimeoutError:
            return False
        return self.last_error is None

    def stop_persisting(self) -> None:
        """Keep serving from memory but never write this store to disk again.

        Called when the store's identity is retired, so an in-flight refresh
        cannot recreate a snapshot the user just asked to be removed.
        """
        self._persist = False

    def clear(self) -> None:
        self._generation += 1
        if self._refresh_task is not None and not self._refresh_task.done():
            _abandoned.add(self._refresh_task)
            self._refresh_task.add_done_callback(_abandoned.discard)
        self._refresh_task = None
        self._repos, self._etag, self._fetched_at = [], None, None
        self._failed_at = None
        self._revalidated_at = None
        self.last_error = None
        _remove(self._path)
        _remove(self._path.with_suffix(".tmp"))

    def _start_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        try:
            self._refresh_task = asyncio.create_task(self._refresh_recording_errors())
        except RuntimeError:
            _LOGGER.warning("No running loop to refresh the repo cache")

    async def _refresh_recording_errors(self) -> None:
        generation = self._generation
        try:
            await self.refresh()
        except GitHubError as exc:
            self._record_failure(exc, generation)
        except Exception as exc:
            _LOGGER.exception("Unexpected error refreshing repo cache")
            error = GitHubError(f"Refresh failed: {exc}")
            error.__cause__ = exc
            self._record_failure(error, generation)

    def _record_failure(self, error: GitHubError, generation: int) -> None:
        if generation != self._generation:
            return
        self.last_error = error
        self._failed_at = self._clock()

    def _load(self) -> None:
        try:
            snapshot = json.loads(self._path.read_text(encoding="utf-8"))
            self._repos = [Repo(**repo) for repo in snapshot["repos"]]
            self._etag = snapshot["etag"]
            self._fetched_at = float(snapshot["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError):
            self._repos, self._etag, self._fetched_at = [], None, None

    def _save(self) -> None:
        if not self._persist:
            return
        snapshot = {
            "fetched_at": self._fetched_at,
            "etag": self._etag,
            "repos": [asdict(repo) for repo in self._repos],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot), encoding="utf-8")
        os.replace(temporary, self._path)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _LOGGER.warning("Could not remove cache file %s", path.name)


def prune(cache_dir: Path, keep: Iterable[Path]) -> None:
    """Delete every cached snapshot in ``cache_dir`` except ``keep``.

    Snapshots of a token's repositories include private names and
    descriptions, so they must not outlive the identity that fetched them.
    """
    kept = {path.name for path in keep}
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.suffix in CACHE_SUFFIXES and entry.name not in kept and entry.is_file():
            _remove(entry)
