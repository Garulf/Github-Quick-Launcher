from typing import AsyncGenerator, List, Literal, Optional as Opt

import hishel
import gidgethub.httpx

from repo import Repo


REQUESTER = "Github-Quick-Launcher"


class Github:

    def __init__(self, api_token: Opt[str] = None):
        self.api = gidgethub.httpx.GitHubAPI(
            client=hishel.AsyncCacheClient(),
            requester=REQUESTER,
            oauth_token=api_token,
        )

    def _build_params(self, **kwargs) -> str:
        params = []
        for key, value in kwargs.items():
            if value is not None:
                params.append(f"{key}={value}")
        return "&".join(params)

    def _iter_request(
            self, endpoint: str) -> AsyncGenerator:
        return self.api.getiter(endpoint)

    def search_repos(
        self,
        query: str,
        sort: Opt[Literal["stars", "forks",
                          "help-wanted-issues", "updated"]] = None,
        order: Opt[Literal["asc", "desc"]] = None,
        per_page: Opt[int] = None,
        page: Opt[int] = None
    ) -> AsyncGenerator[Repo, None]:
        parameters = self._build_params(**{
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": per_page,
            "page": page
        })
        return self.api.getiter(f"/search/repositories?{parameters}")

    def user_repos(
            self,
            visibility: Opt[Literal["all", "public", "private"]] = None,
            affiliation: Opt[List[Literal["owner", "collaborator", "organization_member"]]] = None,
            type: Opt[Literal["all", "owner", "public", "private", "member"]] = None,
            sort: Opt[Literal["created", "updated", "pushed", "full_name"]] = None,
            direction: Opt[Literal["asc", "desc"]] = None,
            per_page: Opt[int] = None,
            page: Opt[int] = None,
            since: Opt[str] = None,
            before: Opt[str] = None
    ) -> AsyncGenerator[Repo, None]:
        parameters = self._build_params(**{
            "visibility": visibility,
            "affiliation": affiliation,
            "type": type,
            "sort": sort,
            "direction": direction,
            "per_page": per_page,
            "page": page,
            "since": since,
            "before": before
        })
        return self.api.getiter(f"/user/repos?{parameters}")

    def get_starred(
            self,
            sort: Opt[Literal["created", "updated"]] = None,
            direction: Opt[Literal["asc", "desc"]] = None,
            per_page: Opt[int] = None,
            page: Opt[int] = None
    ) -> AsyncGenerator[Repo, None]:
        parameters = self._build_params(**{
            "sort": sort,
            "direction": direction,
            "per_page": per_page,
            "page": page
        })
        return self.api.getiter(f"/user/starred?{parameters}")
