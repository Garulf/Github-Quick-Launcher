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

    repo_query = query
    parsed_query = query.split(SEPERATOR)

    if query.startswith(STARS_PREFIX) and token:
        stars = query[1:]
        repos = gh.get_user().get_starred()
        return send_results(results.starred_repo_results(stars, repos))
    else:
        if len(parsed_query) > 1:
            user, search = parsed_query
            if not user and token is not None:
                user = gh.get_user().login
            if user:
                repo_query = f"user:{user} {search}"
        repos = gh.search_repositories(repo_query)
    return send_results(results.repo_results(repos))
