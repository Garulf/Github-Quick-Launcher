from github import Github
from pyflowlauncher.result import ResultResponse, send_results
from pyflowlauncher.jsonrpc import JsonRPCClient

from results import repo_results, scored_repo_results

STARS_PREFIX = "*"
SEPERATOR = "/"

PER_PAGE = 100
SEARCH_LIMIT = 15


def query(query: str) -> ResultResponse:
    settings = JsonRPCClient().recieve().get("settings", {})
    token = settings.get("token", None) or None
    gh = Github(login_or_token=token, per_page=PER_PAGE)

    repo_query = query
    parsed_query = query.split(SEPERATOR)

    if token:
        if query.startswith("/") or query == "":
            repos = gh.get_user().get_repos(sort="updated")
            return send_results(scored_repo_results(query, repos))
        elif query.startswith(STARS_PREFIX):
            query = query[1:]
            repos = gh.get_user().get_starred()
            return send_results(scored_repo_results(query, repos))
    if len(parsed_query) == 2:
        user, repo_query = parsed_query
        results = repo_results(gh.search_repositories(f"user:{user} {repo_query}")[:SEARCH_LIMIT])
    else:
        results = repo_results(gh.search_repositories(repo_query)[:SEARCH_LIMIT])
    return send_results(results)
