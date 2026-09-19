from __future__ import annotations

import asyncio
import gc
import json

import pytest

from github_quick_launcher.cache import RepoStore
from github_quick_launcher.client import GitHubError, Listing, Offline, RateLimited, Repo

ONE = Repo("me/one", "", "https://github.com/me/one", "")
TWO = Repo("me/two", "", "https://github.com/me/two", "")


class FakeClock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeFetch:

    def __init__(self, *listings) -> None:
        self._listings = list(listings)
        self.etags = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def __call__(self, etag):
        self.etags.append(etag)
        await self.gate.wait()
        outcome = self._listings.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_cold_store_fetches_and_persists(tmp_path):
    fetch = FakeFetch(Listing([ONE], '"v1"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())

    assert await store.repos() == [ONE]
    assert json.loads((tmp_path / "repos.json").read_text())["etag"] == '"v1"'


async def test_fresh_snapshot_on_disk_is_served_without_fetching(tmp_path):
    clock = FakeClock()
    await RepoStore(tmp_path / "repos.json", 600, FakeFetch(Listing([ONE], '"v1"')), clock).repos()

    fetch = FakeFetch()
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)

    assert await store.repos() == [ONE]
    assert fetch.etags == []


async def test_stale_snapshot_is_served_then_refreshed_with_etag(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), Listing([ONE, TWO], '"v2"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    assert await store.repos() == [ONE]
    # Await the actual background refresh task rather than a fixed number
    # of asyncio.sleep(0) ticks, so this does not depend on how many hops
    # the refresh happens to need to reach completion.
    await store._refresh_task

    assert fetch.etags == [None, '"v1"']
    assert await store.repos() == [ONE, TWO]


async def test_not_modified_keeps_repos_and_resets_age(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), Listing(None, '"v1"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    await store.refresh()

    assert store.is_stale is False
    assert await store.repos() == [ONE]


async def test_only_one_refresh_runs_at_a_time(tmp_path):
    fetch = FakeFetch(Listing([ONE], '"v1"'))
    fetch.gate.clear()
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())

    first = asyncio.create_task(store.repos())
    second = asyncio.create_task(store.repos())
    await asyncio.sleep(0)
    fetch.gate.set()

    assert await first == [ONE]
    assert await second == [ONE]
    assert fetch.etags == [None]


async def test_cancelled_query_does_not_cancel_the_cold_fetch(tmp_path):
    fetch = FakeFetch(Listing([ONE], '"v1"'))
    fetch.gate.clear()
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())

    abandoned = asyncio.create_task(store.repos())
    await asyncio.sleep(0)
    abandoned.cancel()
    fetch.gate.set()

    assert await store.repos() == [ONE]
    assert fetch.etags == [None]

    with pytest.raises(asyncio.CancelledError):
        await abandoned


async def test_cold_failure_raises(tmp_path):
    store = RepoStore(tmp_path / "repos.json", 600, FakeFetch(Offline("down")), FakeClock())
    with pytest.raises(Offline):
        await store.repos()


async def test_background_failure_keeps_stale_repos_and_records_error(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), Offline("down"))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    assert await store.repos() == [ONE]
    await store._refresh_task

    assert isinstance(store.last_error, Offline)


async def test_snapshot_on_a_cold_store_is_empty_and_starts_one_refresh(tmp_path):
    fetch = FakeFetch(Listing([ONE], '"v1"'))
    fetch.gate.clear()
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())

    assert store.snapshot() == []
    assert store.snapshot() == []
    fetch.gate.set()
    await store._refresh_task

    assert fetch.etags == [None]
    assert store.snapshot() == [ONE]


async def test_snapshot_serves_stale_repos_while_refreshing(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), Listing([ONE, TWO], '"v2"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    assert store.snapshot() == [ONE]
    await store._refresh_task

    assert fetch.etags == [None, '"v1"']
    assert store.snapshot() == [ONE, TWO]


async def test_snapshot_never_raises_when_the_refresh_fails(tmp_path):
    store = RepoStore(tmp_path / "repos.json", 600, FakeFetch(Offline("down")), FakeClock())

    assert store.snapshot() == []
    await store._refresh_task

    assert isinstance(store.last_error, Offline)


async def test_a_failed_fetch_is_not_retried_during_the_cooldown(tmp_path):
    fetch = FakeFetch(Offline("down"), Offline("down"))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())

    for _ in range(3):
        with pytest.raises(Offline):
            await store.repos()

    assert fetch.etags == [None]


async def test_a_retry_is_allowed_once_the_cooldown_passes(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Offline("down"), Listing([ONE], '"v1"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    with pytest.raises(Offline):
        await store.repos()

    clock.now += 60

    assert await store.repos() == [ONE]
    assert fetch.etags == [None, None]
    assert store.last_error is None


async def test_rate_limited_waits_for_the_reset_before_retrying(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(RateLimited(int(clock.now) + 300), Listing([ONE], '"v1"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    with pytest.raises(RateLimited):
        await store.repos()

    clock.now += 61
    with pytest.raises(RateLimited):
        await store.repos()
    assert fetch.etags == [None]

    clock.now += 300
    assert await store.repos() == [ONE]


async def test_stale_repos_are_served_without_retrying_during_the_cooldown(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), Offline("down"))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    assert await store.repos() == [ONE]
    await store._refresh_task

    assert await store.repos() == [ONE]
    assert store.snapshot() == [ONE]
    assert fetch.etags == [None, '"v1"']
    assert isinstance(store.last_error, Offline)


async def test_explicit_refresh_ignores_the_cooldown(tmp_path):
    fetch = FakeFetch(Offline("down"), Listing([ONE], '"v1"'))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())
    with pytest.raises(Offline):
        await store.repos()

    await store.refresh()

    assert fetch.etags == [None, None]
    assert await store.repos() == [ONE]


async def test_corrupt_cache_file_is_ignored(tmp_path):
    (tmp_path / "repos.json").write_text("{not json")
    store = RepoStore(tmp_path / "repos.json", 600, FakeFetch(Listing([ONE], None)), FakeClock())
    assert await store.repos() == [ONE]


async def test_unexpected_background_failure_is_recorded_not_lost(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(Listing([ONE], '"v1"'), ValueError("truncated body"))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, clock)
    await store.repos()

    clock.now += 601
    loop = asyncio.get_running_loop()
    unhandled = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: unhandled.append(context))
    try:
        assert await store.repos() == [ONE]
        task = store._refresh_task
        await task
        del task
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(old_handler)

    assert isinstance(store.last_error, GitHubError)
    assert not isinstance(store.last_error, ValueError)
    assert unhandled == []


async def test_cold_unexpected_failure_raises_github_error(tmp_path):
    fetch = FakeFetch(ValueError("truncated body"))
    store = RepoStore(tmp_path / "repos.json", 600, fetch, FakeClock())
    with pytest.raises(GitHubError) as exc_info:
        await store.repos()
    assert not isinstance(exc_info.value, ValueError)
