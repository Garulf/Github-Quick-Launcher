from __future__ import annotations

from typing import List, Optional

from github_quick_launcher.client import Listing, Repo
from github_quick_launcher.service import RepoService, listing_paths
from github_quick_launcher.settings import Settings

ONE = Repo("me/one", "", "https://github.com/me/one", "")
STAR = Repo("them/star", "", "https://github.com/them/star", "")


class FakeClient:

    def __init__(self) -> None:
        self.listed: List[str] = []
        self.searched: List[str] = []
        self.closed = False

    async def list_repos(self, path: str, etag: Optional[str] = None) -> Listing:
        self.listed.append(path)
        return Listing([STAR] if path.endswith("starred") else [ONE], '"v1"')

    async def search(self, q: str, limit: int = 15) -> List[Repo]:
        self.searched.append(q)
        return [ONE]

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

    assert await service.own_repos() == [ONE]
    assert await service.starred() == [STAR]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "user-garulf-repos.json", "user-garulf-stars.json"]


async def test_without_identity_lists_are_empty_and_nothing_is_fetched(tmp_path):
    client = FakeClient()
    service = RepoService(Settings(), client, tmp_path, FakeClock())

    assert service.has_identity is False
    assert await service.own_repos() == []
    assert await service.starred() == []
    assert client.listed == []


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
    await service.own_repos()

    await service.refresh_all()

    assert client.listed == ["/user/repos", "/user/repos", "/user/starred"]


async def test_aclose_closes_the_client(tmp_path):
    client = FakeClient()
    await RepoService(Settings(), client, tmp_path, FakeClock()).aclose()
    assert client.closed is True
