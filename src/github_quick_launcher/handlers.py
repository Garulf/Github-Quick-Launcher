from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

from pyflowlauncher import Plugin, Result
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
# How long a filter that matched nothing waits for a fresh list before
# answering with what it has.
MISS_WAIT_SECONDS = 3.0
PROMPT_SCORE = 1000
OWN_MATCH_BOOST = 1000
GITHUB_WEB = "https://github.com/"
# "_" is not valid in an ordinary login but Enterprise Managed User logins
# have one (mona_acme). "." and ".." are the only names made of valid
# characters that GitHub refuses, and both would walk up a URL path.
FULL_NAME_RE = re.compile(r"[A-Za-z0-9_-]+/(?!\.{1,2}$)[A-Za-z0-9._-]+")


@dataclass
class Handlers:
    query: Callable[[str], AsyncIterator[Result]]
    refresh_cache: Callable[[], Awaitable[Any]]
    error_result: Callable[[GitHubError], Result]
    context_menu: Callable[[Any], List[Result]]
    clear_cache: Callable[[], Any]


def matches(
    text: str, repos: Sequence[Repo],
) -> List[Tuple[Repo, int, Optional[List[int]]]]:
    """Return a (repo, score, highlight) tuple per matching repo, best first.

    Matching runs on plain strings so that Result objects are only built for
    what matched. With no text everything matches and the API order is kept.
    Nothing is cut off: Flow's list scrolls, and Flow boosts the results a
    user picks often, which it can only do for results it was sent.
    """
    if not text:
        return [(repo, len(repos) - position, None) for position, repo in enumerate(repos)]
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
    return [(repo, -negative, index_list) for negative, _, repo, index_list in scored]


def _owner(repo: Repo) -> str:
    return repo.full_name.split("/", 1)[0].lower()


def _missing_from_own(found: Sequence[Repo], own: Sequence[Repo], username: str) -> bool:
    """True when search found a repository of an owner we list but don't have.

    That means the cached list predates it, e.g. a repository created after
    the last refresh.
    """
    owners = {_owner(repo) for repo in own}
    if username:
        owners.add(username.lower())
    if not owners:
        return False
    known = {repo.full_name.lower() for repo in own}
    return any(_owner(repo) in owners and repo.full_name.lower() not in known for repo in found)


def build(plugin: Plugin, service_for: Callable[[], RepoService]) -> Handlers:
    api = plugin.launcher.api
    icons = plugin.launcher.icons

    def context_menu(full_name: str, html_url: str) -> List[Result]:
        https_clone = f"{html_url}.git"
        ssh_clone = f"git@github.com:{full_name}.git"
        cli_clone = f"gh repo clone {full_name}"
        desktop = f"x-github-client://openRepo/{quote_plus(full_name)}"
        vscode = f"vscode://vscode.git/clone?url={quote_plus(html_url)}"
        return [
            Result("Open in browser", "Open repository in browser",
                   icons.browser).add_action(api.open_url(html_url)),
            Result("Open with GitHub Desktop", "Open repository in GitHub Desktop",
                   icons.open).add_action(api.open_url(desktop)),
            Result("Open in VS Code", "Open repository in VS Code",
                   icons.open).add_action(api.open_url(vscode)),
            Result("Copy full name", full_name,
                   icons.copy).add_action(api.copy_to_clipboard(full_name)),
            Result("Copy URL", html_url,
                   icons.copy).add_action(api.copy_to_clipboard(html_url)),
            Result("Clone with HTTPS", https_clone,
                   icons.copy).add_action(api.copy_to_clipboard(https_clone)),
            Result("Clone with SSH", ssh_clone,
                   icons.copy).add_action(api.copy_to_clipboard(ssh_clone)),
            Result("Clone with GitHub CLI", cli_clone,
                   icons.copy).add_action(api.copy_to_clipboard(cli_clone)),
        ]

    def context_menu_handler(context_data: Any) -> List[Result]:
        # Results carry only the full name; the menu is built when the user
        # opens it instead of being serialized with every result. The URL is
        # derived here so the two can never disagree.
        if isinstance(context_data, str) and FULL_NAME_RE.fullmatch(context_data):
            return context_menu(context_data, GITHUB_WEB + context_data)
        return []

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
            context_data=repo.full_name,
            rounded_icon=True,
            title_highlight_data=highlight,
        ).add_action(api.open_url(repo.html_url))

    def ranked(
        text: str, repos: Sequence[Repo], show_avatars: bool, boost: int = 0,
    ) -> List[Result]:
        return [repo_result(repo, boost + score, highlight, show_avatars)
                for repo, score, highlight in matches(text, repos)]

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
            is_own = isinstance(parsed, Own)
            fetch = service.own_repos if is_own else service.starred
            revalidate = service.revalidate_own if is_own else service.revalidate_stars
            results = ranked(parsed.filter, await fetch(), avatars)
            if not results and parsed.filter and await revalidate(MISS_WAIT_SECONDS):
                # Nothing matched: maybe the repository or star is newer than
                # the snapshot. Look again once GitHub has been asked.
                results = ranked(parsed.filter, await fetch(), avatars)
            for result in results:
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
        snapshot = service.own_snapshot()
        own_matches = ranked(parsed.text, snapshot, avatars, OWN_MATCH_BOOST)
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
        if _missing_from_own(found, snapshot, settings.username):
            service.nudge_own()
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
