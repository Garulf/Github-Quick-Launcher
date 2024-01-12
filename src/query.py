from github import Github
from pyflowlauncher.result import ResultResponse, send_results

import results

STARS_PREFIX = "*"
SEPERATOR = "/"


def query(query: str) -> ResultResponse:
    gh = Github(per_page=15)

    if query.endswith(SEPERATOR):
        repos = gh.get_user(query[:-1]).get_repos()
    elif SEPERATOR in query:
        user, query = query.split(SEPERATOR)
        repos = gh.search_repositories(f"user:{user} {query}")
    else:
        repos = gh.search_repositories(query)
    return send_results(results.repo_results(repos))
