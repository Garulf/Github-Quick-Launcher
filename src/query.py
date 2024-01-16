from github import Github
from pyflowlauncher.result import ResultResponse, send_results
from pyflowlauncher.jsonrpc import JsonRPCClient

import results

STARS_PREFIX = "*"
SEPERATOR = "/"


def query(query: str) -> ResultResponse:
    if not query:
        return send_results([])

    settings = JsonRPCClient().recieve().get("settings", {})
    token = settings.get("token", None) or None
    gh = Github(login_or_token=token, per_page=15)

    if SEPERATOR in query:
        user, query = query.split(SEPERATOR)
        repos = gh.search_repositories(f"user:{user} {query}")
    else:
        repos = gh.search_repositories(query)
    return send_results(results.repo_results(repos))
