from pyflowlauncher.result import ResultResponse, send_results
from pyflowlauncher.jsonrpc import JsonRPCClient

from api import Github
from results import repo_results, scored_repo_results

STARS_PREFIX = "*"
SEPERATOR = "/"

PER_PAGE = 100
SEARCH_LIMIT = 10


async def query(query: str) -> ResultResponse:
    settings = JsonRPCClient().recieve().get("settings", {})
    token = settings.get("token", None) or None
    gh = Github(token)

    repo_query = query
    parsed_query = query.split(SEPERATOR)

    if token:
        if query.startswith("/") or query == "":
            repos = gh.user_repos(sort="updated", per_page=PER_PAGE)
            return send_results([result async for result in scored_repo_results(query, repos)])
        elif query.startswith(STARS_PREFIX):
            query = query[1:]
            repos = gh.get_starred(per_page=PER_PAGE)
            return send_results([result async for result in scored_repo_results(query, repos)])
    if len(parsed_query) == 2:
        user, repo_query = parsed_query
        results = repo_results(gh.search_repos(f"user:{user} {repo_query}", per_page=PER_PAGE), limit=SEARCH_LIMIT)
    else:
        results = repo_results(gh.search_repos(repo_query, per_page=PER_PAGE), limit=SEARCH_LIMIT)
    return send_results([result async for result in results])
