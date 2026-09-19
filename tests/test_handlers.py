from __future__ import annotations

import json
from typing import List, Optional

from pyflowlauncher import Plugin
from pyflowlauncher.jsonrpc import _json_default
from pyflowlauncher.launcher import FlowLauncherV2
from pyflowlauncher.plugin import _default_context_menu

from github_quick_launcher import handlers
from github_quick_launcher.client import GitHubError, NotFound, Offline, RateLimited, Repo

FLOW = Repo("me/flow-thing", "A thing", "https://github.com/me/flow-thing", "https://a/me")
OTHER = Repo("me/other", "", "https://github.com/me/other", "https://a/me")
STAR = Repo("them/starred-flow", "", "https://github.com/them/starred-flow", "https://a/them")
REMOTE = Repo("org/flow-remote", "", "https://github.com/org/flow-remote", "https://a/org")


class FakeService:

    def __init__(self, has_identity: bool = True) -> None:
        self.has_identity = has_identity
        self.last_error = None
        self.own = [FLOW, OTHER]
        self.in_memory: Optional[List[Repo]] = None
        self.own_error = None
        self.own_awaited = False
        self.stars = [STAR]
        self.search_results: List[Repo] = [REMOTE, FLOW]
        self.search_error = None
        self.searched: List[str] = []
        self.refreshed = False
        self.refresh_error = None

    def own_snapshot(self):
        return self.own if self.in_memory is None else self.in_memory

    async def own_repos(self):
        self.own_awaited = True
        if self.own_error is not None:
            raise self.own_error
        return self.own

    async def starred(self):
        return self.stars

    async def search(self, q):
        self.searched.append(q)
        if self.search_error is not None:
            raise self.search_error
        return self.search_results

    async def refresh_all(self):
        if self.refresh_error is not None:
            raise self.refresh_error
        self.refreshed = True


def build(service, monkeypatch):
    monkeypatch.setattr(handlers, "DEBOUNCE_SECONDS", 0)
    return handlers.build(Plugin(launcher=FlowLauncherV2()), lambda: service)


async def titles(built, text):
    return [result.title async for result in built.query(text)]


async def test_bare_slash_lists_own_repos_in_api_order(monkeypatch):
    built = build(FakeService(), monkeypatch)
    results = [result async for result in built.query("/")]
    assert [result.title for result in results] == ["me/flow-thing", "me/other"]
    assert results[0].score > results[1].score


async def test_slash_filter_fuzzy_matches_own_repos(monkeypatch):
    assert await titles(build(FakeService(), monkeypatch), "/flow") == ["me/flow-thing"]


async def test_star_prefix_lists_stars(monkeypatch):
    assert await titles(build(FakeService(), monkeypatch), "*") == ["them/starred-flow"]


async def test_own_without_identity_prompts_for_settings(monkeypatch):
    built = build(FakeService(has_identity=False), monkeypatch)
    results = [result async for result in built.query("/")]
    assert len(results) == 1
    assert results[0].json_rpc_action["Method"].endswith("OpenSettingDialog")


async def test_user_search_scopes_to_that_user(monkeypatch):
    service = FakeService()
    await titles(build(service, monkeypatch), "garulf/flow")
    assert service.searched == ["user:garulf flow"]


async def test_global_puts_own_matches_first_and_drops_duplicates(monkeypatch):
    results = [r async for r in build(FakeService(), monkeypatch).query("flow")]
    assert [result.title for result in results] == ["me/flow-thing", "org/flow-remote"]
    assert results[0].score > results[1].score


async def test_global_never_waits_on_the_repo_list(monkeypatch):
    service = FakeService()
    service.in_memory = []
    service.own_error = Offline("down")
    built = build(service, monkeypatch)

    assert await titles(built, "flow") == ["org/flow-remote", "me/flow-thing"]
    assert service.own_awaited is False


async def test_global_hides_a_repo_list_failure(monkeypatch):
    service = FakeService()
    service.in_memory = []
    service.last_error = NotFound("no such user")

    assert await titles(build(service, monkeypatch), "flow") == [
        "org/flow-remote", "me/flow-thing"]


async def test_global_search_failure_keeps_own_matches_and_explains(monkeypatch):
    service = FakeService()
    service.search_error = Offline("down")
    found = await titles(build(service, monkeypatch), "flow")
    assert found == ["me/flow-thing", "Can't reach GitHub"]


async def test_stale_list_with_failed_refresh_appends_the_error(monkeypatch):
    service = FakeService()
    service.last_error = RateLimited(1700000000)
    found = await titles(build(service, monkeypatch), "/")
    assert found == ["me/flow-thing", "me/other", "GitHub rate limit reached"]


async def test_repo_result_opens_url_and_carries_a_context_menu(monkeypatch):
    results = [r async for r in build(FakeService(), monkeypatch).query("/flow")]
    repo_result = results[0]
    assert repo_result.json_rpc_action["Parameters"][0] == FLOW.html_url
    assert repo_result.copy_text == "me/flow-thing"
    assert repo_result.icon == "https://a/me"
    assert [item.title for item in repo_result.context_data] == [
        "Open in browser", "Open with GitHub Desktop", "Open in VS Code", "Copy full name",
        "Copy URL", "Clone with HTTPS", "Clone with SSH", "Clone with GitHub CLI",
    ]


async def test_refresh_command_offers_a_refresh_action(monkeypatch):
    service = FakeService()
    built = build(service, monkeypatch)
    results = [result async for result in built.query("!refresh")]
    assert results[0].json_rpc_action["Method"] == "refresh_cache"

    await built.refresh_cache()
    assert service.refreshed is True


def test_error_results_cover_every_github_error():
    plugin = Plugin(launcher=FlowLauncherV2())
    built = handlers.build(plugin, lambda: FakeService())
    assert built.error_result(RateLimited(0)).title == "GitHub rate limit reached"
    assert built.error_result(GitHubError("HTTP 500")).title == "GitHub request failed"


def test_not_found_points_at_the_username_setting():
    built = handlers.build(Plugin(launcher=FlowLauncherV2()), lambda: FakeService())
    result = built.error_result(NotFound("missing"))
    assert result.title == "GitHub user not found"
    assert result.subtitle == "Press Enter to open settings and check the username"
    assert result.json_rpc_action["Method"].endswith("OpenSettingDialog")


async def test_refresh_failure_reports_the_error_instead_of_hiding_it(monkeypatch):
    service = FakeService()
    service.refresh_error = Offline("down")
    built = build(service, monkeypatch)

    command = await built.refresh_cache()

    assert command["Method"].endswith("ShowMsg")
    assert command["Parameters"][1] == "Can't reach GitHub"


async def test_refresh_without_identity_asks_for_settings_instead(monkeypatch):
    service = FakeService(has_identity=False)
    built = build(service, monkeypatch)

    command = await built.refresh_cache()

    assert command["Method"].endswith("ShowMsg")
    assert command["Parameters"][1] == "Set your GitHub username or token first"
    assert service.refreshed is False


async def test_context_menu_round_trips_through_json(monkeypatch):
    results = [r async for r in build(FakeService(), monkeypatch).query("/flow")]
    repo_result = results[0]

    wire = json.loads(json.dumps(repo_result.to_json(), default=_json_default))
    rebuilt = _default_context_menu(wire["ContextData"])

    assert len(rebuilt) == 8
    assert rebuilt[0].json_rpc_action["Method"].endswith("OpenUrl")
    assert rebuilt[0].json_rpc_action["Parameters"][0] == FLOW.html_url
