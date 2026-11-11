from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import pytest

from github_quick_launcher.client import Listing, Offline, Repo
from github_quick_launcher.service import RepoService, listing_paths
from github_quick_launcher.settings import Settings

ONE = Repo("me/one", "", "https://github.com/me/one", "")
STAR = Repo("them/star", "", "https://github.com/them/star", "")


class FakeClient:

    def __init__(self) -> None:
        self.listed: List[str] = []
        self.searched: List[str] = []
        self.closed = False
        self.fail_for: Dict[str, Exception] = {}
        self.logins: List[object] = ["octocat"]
        self.login_calls = 0

    async def list_repos(self, path: str, etag: Optional[str] = None) -> Listing:
        self.listed.append(path)
        failure = self.fail_for.get(path)
        if failure is not None:
            raise failure
        return Listing([STAR] if path.endswith("starred") else [ONE], '"v1"')

    async def search(self, q: str, limit: int = 15) -> List[Repo]:
        self.searched.append(q)
        return [ONE]

    async def login(self) -> str:
        self.login_calls += 1
        answer = self.logins.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return str(answer)

    async def aclose(self) -> None:
        self.closed = True


class FakeClock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_uses_authenticated_paths():
    assert listing_paths(Settings(token="t", username="garulf")) == ("/user/repos", "/user/starred")


def test_username_uses_public_paths():
    assert listing_paths(Settings(username="garulf")) == (
        "/users/garulf/repos", "/users/garulf/starred")


async def test_own_and_starred_use_separate_identity_keyed_files(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(username="Garulf"), client, tmp_path, FakeClock())

    assert await service.own.repos() == [ONE]
    assert await service.stars.repos() == [STAR]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "user-garulf-repos.json", "user-garulf-stars.json"]


async def test_without_identity_lists_are_empty_and_nothing_is_fetched(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(), client, tmp_path, FakeClock())

    assert service.has_identity is False
    assert service.own is None
    assert service.stars is None
    assert service.cache_files() == []


async def test_own_snapshot_returns_memory_without_waiting(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(username="garulf"), client, tmp_path, FakeClock())

    assert service.own.snapshot() == []
    assert await service.own.repos() == [ONE]
    assert service.own.snapshot() == [ONE]


async def test_search_is_memoized_for_sixty_seconds(tmp_path):
    client, clock = FakeClient(), FakeClock()
    service = RepoService(Settings(), client, tmp_path, clock)

    await service.search("flow")
    await service.search("flow")
    clock.now += 61
    await service.search("flow")

    assert client.searched == ["flow", "flow"]


async def test_refresh_all_refetches_both_lists(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(token="t"), client, tmp_path, FakeClock())
    await service.own.repos()

    await service.refresh_all()

    assert client.listed == ["/user/repos", "/user/repos", "/user/starred"]


async def test_refresh_all_refreshes_stars_even_when_repos_fail(tmp_path):
    client = FakeClient()
    client.fail_for["/user/repos"] = Offline("down")
    service = RepoService(Settings(token="t"), client, tmp_path, FakeClock())

    with pytest.raises(Offline):
        await service.refresh_all()

    assert client.listed == ["/user/repos", "/user/starred"]


async def test_invalid_username_has_no_identity_and_writes_nothing(tmp_path):
    client = FakeClient()
    settings = Settings.from_raw({"username": "../../escape"})
    service = RepoService(settings, client, tmp_path, FakeClock())

    assert service.has_identity is False
    assert service.own is None
    assert list(tmp_path.iterdir()) == []


async def test_aclose_closes_the_client(tmp_path):
    client = FakeClient()
    await RepoService(Settings(), client, tmp_path, FakeClock()).aclose()
    assert client.closed is True


async def test_clear_cache_forgets_lists_in_memory_and_on_disk(tmp_path):
    client = FakeClient()
    clock = FakeClock()
    service = RepoService(Settings(username="Garulf"), client, tmp_path, clock)
    await service.own.repos()
    await service.stars.repos()
    (tmp_path / "token-abc-repos.json").write_text("{}")

    service.clear_cache()

    assert list(tmp_path.iterdir()) == []
    assert service.own.snapshot() == []


async def test_prune_keeps_only_this_identity(tmp_path):
    (tmp_path / "token-old-repos.json").write_text("{}")
    (tmp_path / "token-old-stars.tmp").write_text("{}")
    (tmp_path / "unrelated.txt").write_text("keep me")
    service = RepoService(Settings(username="Garulf"), FakeClient(), tmp_path, FakeClock())
    await service.own.repos()

    service.prune_other_caches()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["unrelated.txt", "user-garulf-repos.json"]


async def test_retired_service_never_writes_again(tmp_path):
    service = RepoService(Settings(username="Garulf"), FakeClient(), tmp_path, FakeClock())
    service.retire()

    assert await service.own.repos() == [ONE]
    assert list(tmp_path.iterdir()) == []


def test_without_a_token_the_own_login_is_the_username(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(username="Garulf"), client, tmp_path, FakeClock())

    assert service.own_login() == "Garulf"
    assert client.login_calls == 0


async def test_with_a_token_the_own_login_is_asked_for_once(tmp_path):
    client = FakeClient()
    settings = Settings(username="someone-else", token="secret")
    service = RepoService(settings, client, tmp_path, FakeClock())

    assert service.own_login() == ""  # not known yet, and the username may be another account
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert service.own_login() == "octocat"
    assert service.own_login() == "octocat"
    assert client.login_calls == 1


async def test_a_failed_login_lookup_is_retried_after_a_pause(tmp_path):
    client = FakeClient()
    client.logins = [Offline("down"), "octocat"]
    clock = FakeClock()
    service = RepoService(Settings(token="secret"), client, tmp_path, clock)

    for _ in range(3):
        assert service.own_login() == ""
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert client.login_calls == 1

    clock.now += 61
    service.own_login()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert service.own_login() == "octocat"


async def test_early_revalidation_is_rarer_without_a_token(tmp_path):
    clock = FakeClock()
    anonymous = RepoService(Settings(username="Garulf"), FakeClient(), tmp_path / "a", clock)
    with_token = RepoService(Settings(token="secret"), FakeClient(), tmp_path / "t", clock)
    await anonymous.own.repos()
    await with_token.own.repos()

    clock.now += 120
    assert anonymous.own.nudge() is False
    assert with_token.own.nudge() is True

    clock.now += 600
    assert anonymous.own.nudge() is True
