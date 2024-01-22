from typing import Generator

from pyflowlauncher.result import Result
from pyflowlauncher.api import open_url
from pyflowlauncher.icons import BROWSER
from github.Repository import Repository
from github.PaginatedList import PaginatedList


def repo_result(repo: Repository) -> Result:
    return Result(
        Title=repo.full_name,
        SubTitle=repo.description,
        IcoPath=repo.owner.avatar_url,
        JsonRPCAction=open_url(repo.html_url),
        CopyText=repo.full_name,
        ContextData=[repo.full_name, repo.html_url],
    )


def repo_results(repos: PaginatedList) -> Generator[Result, None, None]:
    for repo in repos.get_page(0):
        yield repo_result(repo)


def context_menu_results(full_name: str, html_url: str):
    yield Result(
        Title="Open in browser",
        SubTitle="Open repository in browser",
        IcoPath=BROWSER,
        JsonRPCAction=open_url(html_url)
    )
