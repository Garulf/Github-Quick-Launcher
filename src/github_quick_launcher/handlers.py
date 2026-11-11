from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

from pyflowlauncher import Plugin, Result
from pyflowlauncher.plugin import _default_context_menu
from pyflowlauncher.string_matcher import DEFAULT_QUERY_SEARCH_PRECISION, string_matcher

from github_quick_launcher import avatar
from github_quick_launcher.client import (
    BadCredentials, GitHubError, NotFound, Offline, RateLimited, Repo,
)
from github_quick_launcher.query import Clear, Global, Own, Refresh, Stars, UserSearch, route
from github_quick_launcher.service import RepoService

PLUGIN_ICON = "icon.png"
# Each global search is a GitHub API call (and a rate-limited one: 10/min
# anonymous, 30/min with a token), so wait for a real pause in typing and
# for enough characters to mean something before sending anything.
DEBOUNCE_SECONDS = 0.4
MIN_SEARCH_CHARS = 3
PROMPT_SCORE = 1000
OWN_MATCH_BOOST = 1000
# Flow shows only the top handful of results, so sending every repository on
# every keystroke only costs serialization time on both sides of the pipe.
MAX_RESULTS = 30
GITHUB_WEB = "https://github.com/"
FULL_NAME_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


@dataclass
class Handlers:
    query: Callable[[str], AsyncIterator[Result]]
    refresh_cache: Callable[[], Awaitable[Any]]
    error_result: Callable[[GitHubError], Result]
    context_menu: Callable[[Any], Optional[List[Result]]]
    clear_cache: Callable[[], Any]


def top_matches(
    text: str, repos: Sequence[Repo], limit: int = MAX_RESULTS,
) -> List[Tuple[Repo, int, Optional[List[int]]]]:
    """Return at most ``limit`` (repo, score, highlight) tuples, best first.

    Matching runs on plain strings so that Result objects are only built for
    what is actually sent. With no text, the API order is kept.
    """
    if not text:
        top = repos[:limit]
        return [(repo, len(top) - position, None) for position, repo in enumerate(top)]
    # Every non-space query character must appear in the name for the fuzzy
    # matcher to succeed, so this cheap check skips most names outright.
    needle = set(text.lower()) - {" "}
    scored = []
    for position, repo in enumerate(repos):
        name = repo.full_name
        if needle and not needle.issubset(name.lower()):
            continue
        match = string_matcher(
            text, name, query_search_precision=DEFAULT_QUERY_SEARCH_PRECISION)
        if match.matched:
            scored.append((-match.score, position, repo, match.index_list))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [(repo, -negative, index_list) for negative, _, repo, index_list in scored[:limit]]


def build(plugin: Plugin, service_for: Callable[[], RepoService]) -> Handlers:
    api = plugin.launcher.api
    icons = plugin.launcher.icons

    def context_menu(repo: Repo) -> List[Result]:
        https_clone = f"{repo.html_url}.git"
        ssh_clone = f"git@github.com:{repo.full_name}.git"
        cli_clone = f"gh repo clone {repo.full_name}"
        desktop = f"x-github-client://openRepo/{quote_plus(repo.full_name)}"
        vscode = f"vscode://vscode.git/clone?url={quote_plus(repo.html_url)}"
        return [
            Result("Open in browser", "Open repository in browser",
                   icons.browser).add_action(api.open_url(repo.html_url)),
            Result("Open with GitHub Desktop", "Open repository in GitHub Desktop",
                   icons.open).add_action(api.open_url(desktop)),
            Result("Open in VS Code", "Open repository in VS Code",
                   icons.open).add_action(api.open_url(vscode)),
            Result("Copy full name", repo.full_name,
                   icons.copy).add_action(api.copy_to_clipboard(repo.full_name)),
            Result("Copy URL", repo.html_url,
                   icons.copy).add_action(api.copy_to_clipboard(repo.html_url)),
            Result("Clone with HTTPS", https_clone,
                   icons.copy).add_action(api.copy_to_clipboard(https_clone)),
            Result("Clone with SSH", ssh_clone,
                   icons.copy).add_action(api.copy_to_clipboard(ssh_clone)),
            Result("Clone with GitHub CLI", cli_clone,
                   icons.copy).add_action(api.copy_to_clipboard(cli_clone)),
        ]

    def context_menu_handler(context_data: Any) -> Optional[List[Result]]:
        # Results carry only [full_name, html_url]; the menu is built when the
        # user actually opens it instead of being serialized with every result.
        if (isinstance(context_data, list) and len(context_data) == 2
                and all(isinstance(item, str) for item in context_data)):
            full_name, html_url = context_data
            if FULL_NAME_RE.fullmatch(full_name) and html_url.startswith(GITHUB_WEB):
                return context_menu(Repo(full_name, "", html_url, ""))
        return _default_context_menu(context_data)

    def icon_for(repo: Repo, show_avatars: bool) -> str:
        if not show_avatars or not repo.avatar_url:
            return PLUGIN_ICON
        return avatar.sized(repo.avatar_url, avatar.default_size())

    def repo_result(
        repo: Repo, score: int, highlight: Optional[List[int]], show_avatars: bool,
    ) -> Result:
        return Result(
            title=repo.full_name,
            subtitle=repo.description,
            icon=icon_for(repo, show_avatars),
            score=score,
            copy_text=repo.full_name,
            context_data=[repo.full_name, repo.html_url],
            rounded_icon=True,
            title_highlight_data=highlight,
        ).add_action(api.open_url(repo.html_url))

    def ranked(
        text: str, repos: Sequence[Repo], show_avatars: bool, boost: int = 0,
    ) -> List[Result]:
        return [repo_result(repo, boost + score, highlight, show_avatars)
                for repo, score, highlight in top_matches(text, repos)]

    def settings_prompt() -> Result:
        return Result(
            title="Set your GitHub username or token",
            subtitle="Press Enter to open settings, then \"/\" lists your repositories",
            icon=PLUGIN_ICON,
            score=PROMPT_SCORE,
        ).add_action(api.open_setting_dialog())

    def error_result(error: GitHubError) -> Result:
        if isinstance(error, RateLimited):
            resets = time.strftime("%H:%M", time.localtime(error.reset_at))
            return Result(
                "GitHub rate limit reached",
                f"Resets at {resets}. Press Enter to add a token in settings and raise the limit",
                PLUGIN_ICON,
            ).add_action(api.open_setting_dialog())
        if isinstance(error, BadCredentials):
            return Result(
                "GitHub rejected your token",
                "Press Enter to open settings and replace it",
                PLUGIN_ICON,
            ).add_action(api.open_setting_dialog())
        if isinstance(error, NotFound):
            return Result(
                "GitHub user not found",
                "Press Enter to open settings and check the username",
                PLUGIN_ICON,
            ).add_action(api.open_setting_dialog())
        if isinstance(error, Offline):
            return Result("Can't reach GitHub", "Check your connection and try again",
                          PLUGIN_ICON)
        return Result("GitHub request failed", str(error), PLUGIN_ICON)

    async def debounced_search(service: RepoService, q: str) -> List[Repo]:
        # The host cancels this task when the user keeps typing, so requests
        # only go out for queries that survive the pause.
        await asyncio.sleep(DEBOUNCE_SECONDS)
        return await service.search(q)

    async def refresh_cache() -> Any:
        service = service_for()
        if not service.has_identity:
            return api.show_msg(
                "Github Quick Launcher", "Set your GitHub username or token first")
        try:
            await service.refresh_all()
        except GitHubError as error:
            return api.show_msg("Github Quick Launcher", error_result(error).title)
        return api.show_msg("Github Quick Launcher", "Repository cache refreshed")

    def clear_cache() -> Any:
        service_for().clear_cache()
        return api.show_msg("Github Quick Launcher", "Cached repository lists deleted")

    def online_search_disabled() -> Result:
        return Result(
            "Online search is off",
            "Only your cached repositories are searched. Press Enter to change this in settings",
            PLUGIN_ICON,
        ).add_action(api.open_setting_dialog())

    async def query(text: str) -> AsyncIterator[Result]:
        service = service_for()
        settings = service.settings
        avatars = settings.show_avatars
        parsed = route(text)

        if isinstance(parsed, Clear):
            yield Result(
                "Delete cached repository lists",
                "Remove your repositories and stars stored on this PC",
                PLUGIN_ICON,
            ).add_action(clear_cache)
            return

        if isinstance(parsed, Refresh):
            yield Result(
                "Refresh repository cache",
                "Fetch your repositories and stars from GitHub again",
                PLUGIN_ICON,
            ).add_action(refresh_cache)
            return

        if isinstance(parsed, (Own, Stars)):
            if not service.has_identity:
                yield settings_prompt()
                return
            fetch = service.own_repos if isinstance(parsed, Own) else service.starred
            for result in ranked(parsed.filter, await fetch(), avatars):
                yield result
            if service.last_error is not None:
                yield error_result(service.last_error)
            return

        if isinstance(parsed, UserSearch):
            if not settings.online_search:
                yield online_search_disabled()
                return
            q = f"user:{parsed.user} {parsed.filter}".strip()
            for result in ranked("", await debounced_search(service, q), avatars):
                yield result
            return

        assert isinstance(parsed, Global)
        own_matches = ranked(parsed.text, service.own_snapshot(), avatars, OWN_MATCH_BOOST)
        for result in own_matches:
            yield result
        if not settings.online_search:
            return
        if len(parsed.text.replace(" ", "")) < MIN_SEARCH_CHARS:
            return
        try:
            found = await debounced_search(service, parsed.text)
        except GitHubError as error:
            yield error_result(error)
            return
        already_listed = {result.title for result in own_matches}
        remote = [repo for repo in found if repo.full_name not in already_listed]
        for result in ranked("", remote, avatars):
            yield result

    plugin.add_method(query)
    plugin.add_method(refresh_cache)
    plugin.add_method(clear_cache)
    plugin.add_method(context_menu_handler, name="context_menu")
    plugin.add_exception_handler(GitHubError, error_result)
    return Handlers(query, refresh_cache, error_result, context_menu_handler, clear_cache)
