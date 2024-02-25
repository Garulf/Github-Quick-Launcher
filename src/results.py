from typing import AsyncGenerator, Optional
from urllib.parse import quote_plus

from pyflowlauncher.result import Result
from pyflowlauncher.api import open_url, copy_to_clipboard
from pyflowlauncher.icons import BROWSER, OPEN, COPY
from repo import Repo
from pyflowlauncher.string_matcher import string_matcher


def repo_result(repo: Repo) -> Result:
    return Result(
        Title=repo["full_name"],
        SubTitle=repo["description"] or "No description",
        IcoPath=repo["owner"]["avatar_url"],
        JsonRPCAction=open_url(repo["html_url"]),
        CopyText=repo["full_name"],
        ContextData=[repo["full_name"], repo["html_url"]],
    )


async def repo_results(repos: AsyncGenerator[Repo, None], limit: Optional[int] = None) -> AsyncGenerator[Result, None]:
    i = 0
    async for repo in repos:
        if limit and i >= limit:
            break
        yield repo_result(repo)
        i += 1


async def scored_repo_results(query: str, repos: AsyncGenerator[Repo, None]) -> AsyncGenerator[Result, None]:
    async for result in repo_results(repos):
        match = string_matcher(query, result.Title)
        if match:
            result.Score = match.score
            yield result


def context_menu_results(full_name: str, html_url: str):
    yield Result(
        Title="Open in browser",
        SubTitle="Open repository in browser",
        IcoPath=BROWSER,
        JsonRPCAction=open_url(html_url)
    )
    yield Result(
        Title="Open with GitHub Desktop",
        SubTitle="Open repository in GitHub Desktop",
        IcoPath=OPEN,
        JsonRPCAction=open_url(
            f"x-github-client://openRepo/{quote_plus(full_name)}"
        )
    )
    yield Result(
        Title="Open in VS Code",
        SubTitle="Open repository in VS Code",
        IcoPath=OPEN,
        JsonRPCAction=open_url(
            f"vscode://vscode.git/clone?url={quote_plus(html_url)}"
        )
    )
    yield Result(
        Title="Copy full name",
        SubTitle=full_name,
        IcoPath=COPY,
        JsonRPCAction=copy_to_clipboard(full_name)
    )
    yield Result(
        Title="Copy URL",
        SubTitle=html_url,
        IcoPath=COPY,
        JsonRPCAction=copy_to_clipboard(html_url)
    )
    https_clone_url = f"{html_url}.git"
    yield Result(
        Title="Clone with HTTPS",
        SubTitle=https_clone_url,
        IcoPath=COPY,
        JsonRPCAction=copy_to_clipboard(https_clone_url)
    )
    ssh_clone_url = f"git@github.com:{full_name}.git"
    yield Result(
        Title="Clone with SSH",
        SubTitle=ssh_clone_url,
        IcoPath=COPY,
        JsonRPCAction=copy_to_clipboard(ssh_clone_url)
    )
    github_cli_url = f"gh repo clone {full_name}"
    yield Result(
        Title="Clone with GitHub CLI",
        SubTitle=github_cli_url,
        IcoPath=COPY,
        JsonRPCAction=copy_to_clipboard(github_cli_url)
    )
