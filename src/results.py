from typing import Generator

from pyflowlauncher.result import Result
from pyflowlauncher.api import open_url
from github.Repository import Repository
from github.PaginatedList import PaginatedList


def repo_result(repo: Repository) -> Result:
    return Result(
        Title=repo.full_name,
        SubTitle=repo.description,
        IcoPath=repo.owner.avatar_url,
        JsonRPCAction=open_url(repo.html_url),
    )


def repo_results(repos: PaginatedList) -> Generator[Result, None, None]:
    for repo in repos.get_page(0):
        yield repo_result(repo)
