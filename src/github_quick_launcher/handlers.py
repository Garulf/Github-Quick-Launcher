from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, List
from urllib.parse import quote_plus

from pyflowlauncher import Plugin, Result
from pyflowlauncher.utils import score_results

from github_quick_launcher.client import (
    BadCredentials, GitHubError, NotFound, Offline, RateLimited, Repo,
)
from github_quick_launcher.query import Global, Own, Refresh, Stars, UserSearch, route
from github_quick_launcher.service import RepoService

PLUGIN_ICON = "icon.png"
DEBOUNCE_SECONDS = 0.2
PROMPT_SCORE = 1000
OWN_MATCH_BOOST = 1000


@dataclass
class Handlers:
    query: Callable[[str], AsyncIterator[Result]]
    refresh_cache: Callable[[], Awaitable[Any]]
    error_result: Callable[[GitHubError], Result]


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

    def repo_result(repo: Repo) -> Result:
        return Result(
            title=repo.full_name,
            subtitle=repo.description,
            icon=repo.avatar_url or PLUGIN_ICON,
            copy_text=repo.full_name,
            context_data=context_menu(repo),
            rounded_icon=True,
        ).add_action(api.open_url(repo.html_url))

    def ranked(text: str, repos: Iterable[Repo], boost: int = 0) -> List[Result]:
        results = [repo_result(repo) for repo in repos]
        if text:
            results = list(score_results(text, results))
            for result in results:
                result.score += boost
            return results
        for position, result in enumerate(results):
            result.score = boost + len(results) - position
        return results

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
        try:
            await service_for().refresh_all()
        except GitHubError as error:
            return api.show_msg("Github Quick Launcher", error_result(error).title)
        return api.show_msg("Github Quick Launcher", "Repository cache refreshed")

    async def query(text: str) -> AsyncIterator[Result]:
        service = service_for()
        parsed = route(text)

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
            for result in ranked(parsed.filter, await fetch()):
                yield result
            if service.last_error is not None:
                yield error_result(service.last_error)
            return

        if isinstance(parsed, UserSearch):
            q = f"user:{parsed.user} {parsed.filter}".strip()
            for result in ranked("", await debounced_search(service, q)):
                yield result
            return

        assert isinstance(parsed, Global)
        own_matches = ranked(parsed.text, service.own_snapshot(), OWN_MATCH_BOOST)
        for result in own_matches:
            yield result
        try:
            found = await debounced_search(service, parsed.text)
        except GitHubError as error:
            yield error_result(error)
            return
        already_listed = {result.title for result in own_matches}
        for result in ranked("", [repo for repo in found if repo.full_name not in already_listed]):
            yield result

    plugin.add_method(query)
    plugin.add_method(refresh_cache)
    plugin.add_exception_handler(GitHubError, error_result)
    return Handlers(query, refresh_cache, error_result)
