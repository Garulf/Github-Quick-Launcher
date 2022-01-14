import json
from pathlib import Path

from flox import Flox, utils, ICON_BROWSER, ICON_OPEN
from utils import strip_keywords

from github import Github
from github.GithubException import RateLimitExceededException, BadCredentialsException, UnknownObjectException

GITHUB_BASE_URL = "https://github.com/"
GITHUB_URI = 'x-github-client://openRepo/'
USER_KEY = '@'
STAR_KEY = '*'
KEYS = [USER_KEY, STAR_KEY]
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

    def get_user_repos(self, query):
        if self.token:
            user = self.gh.get_user()
        elif self.username != "" and self.username is not None:
            self.logger.warning(self.username)
            user = self.gh.get_user(self.settings.get('username'))
        elif query.startswith(USER_KEY) and len(query) > 1:
            query = query[1:]
            username = query.split(' ')[0]
            query = query.replace(username, '')
            user = self.gh.get_user(username)
        elif len(query) > 1:
            user = self.gh.get_user(query.split('/')[0])
        else:
            return []
        return user.get_repos()

    def results(self, query, repos: list, default_glyph: str=REPO_GLYPH):
        self.font_family = "#octicons"
        query = strip_keywords(query, KEYS)
        for repo in repos:
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
        return self._results

    def query(self, query):
        try:
            self.init_github()
            repos = []
            stars = []
            if self.settings.get('token', None) is not None and query.startswith(STAR_KEY):
                stars = self.get_user_stars(query)
                self.results(query, stars, STAR_GLYPH)
            else:
                repos = self.get_user_repos(query)
                self.results(query, repos)
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
