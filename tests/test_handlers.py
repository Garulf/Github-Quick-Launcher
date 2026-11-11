from __future__ import annotations

import json
from typing import List, Optional

import pytest
from pyflowlauncher import Plugin
from pyflowlauncher.jsonrpc import _json_default
from pyflowlauncher.launcher import FlowLauncherV2

from github_quick_launcher import handlers
from github_quick_launcher.client import GitHubError, NotFound, Offline, RateLimited, Repo
from github_quick_launcher.settings import Settings

FLOW = Repo("me/flow-thing", "A thing", "https://github.com/me/flow-thing", "https://a/me")
OTHER = Repo("me/other", "", "https://github.com/me/other", "https://a/me")
STAR = Repo("them/starred-flow", "", "https://github.com/them/starred-flow", "https://a/them")
REMOTE = Repo("org/flow-remote", "", "https://github.com/org/flow-remote", "https://a/org")


class FakeStore:

    def __init__(self, listed: List[Repo]) -> None:
        self.listed = listed
        self.in_memory: Optional[List[Repo]] = None
        self.error = None
        self.awaited = False
        self.revalidated = 0
        self.after_revalidate: Optional[List[Repo]] = None
        self.nudged = 0

    async def repos(self):
        self.awaited = True
        if self.error is not None:
            raise self.error
        return self.listed

    def snapshot(self):
        return self.listed if self.in_memory is None else self.in_memory

    async def revalidate(self, wait):
        self.revalidated += 1
        if self.after_revalidate is None:
            return False
        self.listed = self.after_revalidate
        return True

    def nudge(self):
        self.nudged += 1


class FakeService:

    def __init__(self, has_identity: bool = True, login: str = "me", **settings) -> None:
        self.settings = Settings(**settings)
        self.cleared = False
        self.has_identity = has_identity
        self.last_error = None
        self.own = FakeStore([FLOW, OTHER]) if has_identity else None
        self.stars = FakeStore([STAR]) if has_identity else None
        self.login = login
        self.search_results: List[Repo] = [REMOTE, FLOW]
        self.search_error = None
        self.searched: List[str] = []
        self.refreshed = False
        self.refresh_error = None

    def own_login(self):
        return self.login

    async def search(self, q):
        self.searched.append(q)
        if self.search_error is not None:
            raise self.search_error
        return self.search_results

    def clear_cache(self):
        self.cleared = True

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
    service.own.in_memory = []
    service.own.error = Offline("down")
    built = build(service, monkeypatch)

    assert await titles(built, "flow") == ["org/flow-remote", "me/flow-thing"]
    assert service.own.awaited is False


async def test_global_hides_a_repo_list_failure(monkeypatch):
    service = FakeService()
    service.own.in_memory = []
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
    assert repo_result.icon == "https://a/me"  # not a GitHub avatar URL, left alone
    assert repo_result.context_data == FLOW.full_name


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


async def test_context_menu_is_built_lazily_from_the_echoed_context_data(monkeypatch):
    built = build(FakeService(), monkeypatch)
    results = [r async for r in built.query("/flow")]

    wire = json.loads(json.dumps(results[0].to_json(), default=_json_default))
    menu = built.context_menu(wire["ContextData"])

    assert [item.title for item in menu] == [
        "Open in browser", "Open with GitHub Desktop", "Open in VS Code", "Copy full name",
        "Copy URL", "Clone with HTTPS", "Clone with SSH", "Clone with GitHub CLI",
    ]
    assert menu[0].json_rpc_action["Method"].endswith("OpenUrl")
    assert menu[0].json_rpc_action["Parameters"][0] == FLOW.html_url


@pytest.mark.parametrize("context_data", [
    "me/..", "me/.", "../x", "me", "me/x/y", "me/x; rm -rf ~", "", None,
    ["me/x", "https://github.com/evil/y"], {"Title": "me/x"},
])
def test_context_menu_rejects_data_that_is_not_a_repo_name(context_data):
    built = handlers.build(Plugin(launcher=FlowLauncherV2()), lambda: FakeService())
    assert built.context_menu(context_data) == []


def test_context_menu_urls_are_derived_from_the_name():
    built = handlers.build(Plugin(launcher=FlowLauncherV2()), lambda: FakeService())
    menu = built.context_menu("mona_acme/.github")
    assert menu[0].json_rpc_action["Parameters"][0] == "https://github.com/mona_acme/.github"
    assert menu[5].subtitle == "https://github.com/mona_acme/.github.git"
    assert menu[6].subtitle == "git@github.com:mona_acme/.github.git"


async def test_a_result_stays_small_on_the_wire(monkeypatch):
    results = [r async for r in build(FakeService(), monkeypatch).query("/flow")]
    wire = json.dumps(results[0].to_json(), default=_json_default)
    assert len(wire) < 1024


async def test_every_repo_is_listed_however_long_the_list(monkeypatch):
    service = FakeService()
    service.own.listed = [
        Repo(f"me/repo-{i}", "", f"https://github.com/me/repo-{i}", "") for i in range(450)]
    built = build(service, monkeypatch)

    listed = await titles(built, "/")
    filtered = await titles(built, "/repo")

    assert listed == [repo.full_name for repo in service.own.listed]
    assert len(filtered) == 450


def test_matches_keep_api_order_on_ties_and_skip_non_matches():
    tied = [Repo(f"me/flow-{name}", "", "", "") for name in ("b", "a", "c")]
    found = handlers.matches("flow", [OTHER, *tied])
    assert [repo.full_name for repo, _, _ in found] == ["me/flow-b", "me/flow-a", "me/flow-c"]
    assert len({score for _, score, _ in found}) == 1


async def test_repeated_spaces_in_a_filter_do_not_break_matching(monkeypatch):
    built = build(FakeService(), monkeypatch)
    assert await titles(built, "/flow  thing") == ["me/flow-thing"]
    assert (await titles(built, "fl  th"))[0] == "me/flow-thing"


async def test_short_global_queries_never_leave_the_machine(monkeypatch):
    service = FakeService()
    built = build(service, monkeypatch)

    assert await titles(built, "fl") == ["me/flow-thing"]
    assert service.searched == []

    await titles(built, "flo")
    assert service.searched == ["flo"]


async def test_online_search_off_keeps_global_queries_local(monkeypatch):
    service = FakeService(online_search=False)
    built = build(service, monkeypatch)

    assert await titles(built, "flow") == ["me/flow-thing"]
    assert await titles(built, "garulf/flow") == ["Online search is off"]
    assert await titles(built, "nothing-local") == ["Online search is off"]
    assert service.searched == []


async def test_a_short_query_with_no_local_match_says_why_nothing_is_listed(monkeypatch):
    service = FakeService()
    built = build(service, monkeypatch)

    assert await titles(built, "zz") == ["Keep typing to search GitHub"]
    assert service.searched == []


async def test_avatars_are_downsized_or_hidden(monkeypatch):
    monkeypatch.setattr(handlers.avatar, "_size", 64)
    real = Repo("me/flow-x", "", "https://github.com/me/flow-x",
                "https://avatars.githubusercontent.com/u/1?v=4")
    service = FakeService()
    service.own.listed = [real]
    shown = [r async for r in build(service, monkeypatch).query("/")]
    assert shown[0].icon == "https://avatars.githubusercontent.com/u/1?v=4&s=64"

    hidden_service = FakeService(show_avatars=False)
    hidden_service.own.listed = [real]
    hidden = [r async for r in build(hidden_service, monkeypatch).query("/")]
    assert hidden[0].icon == handlers.PLUGIN_ICON


async def test_clear_command_deletes_cached_lists(monkeypatch):
    service = FakeService()
    built = build(service, monkeypatch)
    results = [r async for r in built.query("!clear")]
    assert results[0].json_rpc_action["Method"] == "clear_cache"

    command = built.clear_cache()
    assert service.cleared is True
    assert command["Method"].endswith("ShowMsg")


NEW = Repo("me/brand-new", "", "https://github.com/me/brand-new", "")


async def test_a_filter_that_matches_nothing_revalidates_and_looks_again(monkeypatch):
    service = FakeService()
    service.own.after_revalidate = [NEW, FLOW, OTHER]
    built = build(service, monkeypatch)

    assert await titles(built, "/brand") == ["me/brand-new"]
    assert (service.own.revalidated, service.stars.revalidated) == (1, 0)


async def test_a_star_miss_revalidates_the_star_list(monkeypatch):
    service = FakeService()
    service.stars.after_revalidate = [NEW]
    built = build(service, monkeypatch)

    assert await titles(built, "*brand") == ["me/brand-new"]
    assert (service.own.revalidated, service.stars.revalidated) == (0, 1)


async def test_matches_and_bare_listings_never_revalidate(monkeypatch):
    service = FakeService()
    built = build(service, monkeypatch)

    await titles(built, "/flow")
    await titles(built, "/")
    await titles(built, "*")

    assert (service.own.revalidated, service.stars.revalidated) == (0, 0)


async def test_a_search_hit_missing_from_own_repos_nudges_a_refresh(monkeypatch):
    service = FakeService()
    service.search_results = [Repo("me/flow-new", "", "https://github.com/me/flow-new", "")]
    await titles(build(service, monkeypatch), "flow")
    assert service.own.nudged == 1


async def test_search_hits_of_other_owners_do_not_nudge(monkeypatch):
    service = FakeService()
    await titles(build(service, monkeypatch), "flow")  # finds org/flow-remote
    assert service.own.nudged == 0


async def test_an_owner_the_account_only_collaborates_with_does_not_nudge(monkeypatch):
    service = FakeService()
    service.own.listed = [FLOW, Repo("microsoft/one", "", "https://github.com/microsoft/one", "")]
    service.search_results = [
        Repo("microsoft/vscode", "", "https://github.com/microsoft/vscode", "")]
    await titles(build(service, monkeypatch), "vscode")
    assert service.own.nudged == 0


async def test_no_nudge_until_the_account_behind_a_token_is_known(monkeypatch):
    service = FakeService(login="")
    service.search_results = [Repo("me/flow-new", "", "https://github.com/me/flow-new", "")]
    await titles(build(service, monkeypatch), "flow")
    assert service.own.nudged == 0


def test_missing_from_own_compares_names_without_case():
    found = [Repo("Garulf/new", "", "https://github.com/Garulf/new", "")]
    assert handlers._missing_from_own(found, [], "garulf") is True
    assert handlers._missing_from_own(found, [], "") is False
    assert handlers._missing_from_own(found, [Repo("garulf/NEW", "", "", "")], "Garulf") is False


def test_a_list_cut_off_at_the_page_cap_never_counts_as_missing_a_repo():
    capped = [Repo(f"me/repo-{i}", "", "", "") for i in range(1000)]
    found = [Repo("me/older-than-the-cap", "", "", "")]
    assert handlers._missing_from_own(found, capped, "me") is False
    assert handlers._missing_from_own(found, capped[:999], "me") is True


async def test_with_online_search_off_a_plain_miss_revalidates_the_own_list(monkeypatch):
    service = FakeService(online_search=False)
    service.own.after_revalidate = [NEW, FLOW, OTHER]
    built = build(service, monkeypatch)

    assert await titles(built, "brand") == ["me/brand-new"]
    assert service.own.revalidated == 1
    assert service.searched == []


async def test_with_online_search_off_short_queries_and_matches_do_not_revalidate(monkeypatch):
    service = FakeService(online_search=False)
    built = build(service, monkeypatch)

    await titles(built, "zz")
    await titles(built, "flow")

    assert service.own.revalidated == 0


async def test_with_online_search_on_a_plain_miss_never_waits_for_the_own_list(monkeypatch):
    service = FakeService()
    await titles(build(service, monkeypatch), "brand")
    assert service.own.revalidated == 0
