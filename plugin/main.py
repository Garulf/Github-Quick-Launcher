import json
from pathlib import Path

from flox import Flox, utils, ICON_BROWSER, ICON_OPEN, ICON_WARNING
from utils import strip_keywords

from github import Github
from github.GithubException import RateLimitExceededException, BadCredentialsException, UnknownObjectException, GithubException

GITHUB_BASE_URL = "https://github.com/"
GITHUB_URI = 'x-github-client://openRepo/'
USER_KEY = '/'
STAR_KEY = '*'
KEYS = [USER_KEY, STAR_KEY]
RESULT_LIMIT = 100
SEARCH_LIMIT = 10
STAR_GLYPH = ''
REPO_GLYPH = ''
FORK_GLYPH = ''

class GithubQuickLauncher(Flox):

    def init_github(self):
        self.token = self.settings.get('token', None)
        self.username = self.settings.get('username', None)
        if self.token is not None and self.token != "":
            self.gh = Github(self.token)
        else:
            self.gh = Github()

    def get_user_stars(self, query):
        return self.gh.get_user().get_starred()

    def search_repos(self, query):
        return self.gh.search_repositories(query)

    def get_user_repos(self, query):
        if USER_KEY in query:
            user, query = query.split(USER_KEY)
            user = self.gh.get_user(user)
        elif self.token:
            user = self.gh.get_user()
        elif self.username:
            user = self.gh.get_user(self.username)
        else:
            return []
        return user.get_repos()

    def results(self, query, repos: list, default_glyph: str=REPO_GLYPH, **kwargs):
        limit = kwargs.pop('limit', RESULT_LIMIT)
        self.font_family = "#octicons"
        query = strip_keywords(query, KEYS)
        for idx, repo in enumerate(repos):
            glyph = default_glyph
            if query.lower() in repo.full_name.lower():
                if repo.fork and default_glyph != STAR_GLYPH:
                    glyph=FORK_GLYPH
                self.add_item(
                    title=repo.full_name,
                    subtitle=repo.description,
                    glyph=glyph,
                    method=self.default_action,
                    parameters=[repo.full_name],
                    context=[repo.full_name]
            )
            if idx == limit:
                break
        return self._results

    def query(self, query):
        try:
            self.init_github()
            repos = []
            stars = []
            if self.settings.get('token', None) is not None and query.startswith(STAR_KEY):
                stars = self.get_user_stars(query)
                self.results(query, stars, STAR_GLYPH)
            elif not query.startswith(USER_KEY):
                repos = self.get_user_repos(query)
                self.results(query, repos)
            if len(self._results) == 0 and query != '':
                repos = self.search_repos(query)
                self.results(query, repos, limit=SEARCH_LIMIT)
        except RateLimitExceededException:
            self.add_item(
                title='Github Rate Limit Exceeded',
                subtitle='You can avoid this by providing an access token in settings.'
            )
        except BadCredentialsException:
            self.add_item(
                title='Bad Credentials',
                subtitle='Please double check you Access Token in settings.'
            )
        except UnknownObjectException:
            pass
        except GithubException as e:
            self.logger.error(e)
            if e.status == 401:
                self.add_item(
                    title='API requires Authentication',
                    subtitle='Please provide an access token in settings.',
                    icon=ICON_WARNING,
                    method=self.open_setting_dialog
                )
            else:
                self.add_item(
                    title='Github API Error',
                    subtitle=f'{e.data["message"]}',
                    icon=ICON_WARNING
                )
        if self._results == []:
            self.add_item(
                title='No results found',
                subtitle='Please double check your query.'
            )

    def context_menu(self, data):
        self.logger.warning(data)
        if data != {}:
            repo_fullname = data[0]
            self.add_item(
                title='Open in Browser',
                subtitle=f"Open {repo_fullname} in Browser.",
                icon=ICON_BROWSER,
                method=self.open_in_browser,
                parameters=[repo_fullname]
            )
            self.add_item(
                title='Open Desktop Application',
                subtitle=f"Open {repo_fullname} in Desktop Application.",
                icon=ICON_OPEN,
                method=self.open_in_app,
                parameters=[repo_fullname]
            )

    def default_action(self, repo_fullname):
        action = self.settings.get('default_action', 'Open in Browser')
        self.logger.warning(action)
        if action == 'Open in Desktop Application':
            self.open_in_app(f"{GITHUB_URI}{repo_fullname}")
        else:
            self.open_in_browser(repo_fullname)

    def open_in_app(self, repo_fullname):
        self.browser_open(f"{GITHUB_URI}{repo_fullname}")

    def open_in_browser(self, repo_fullname):
        self.browser_open(f"{GITHUB_BASE_URL}{repo_fullname}")


if __name__ == "__main__":
    GithubQuickLauncher()
