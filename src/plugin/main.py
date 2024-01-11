import json
from pathlib import Path

from flox import Flox, utils, ICON_BROWSER, ICON_OPEN, ICON_WARNING, ICON_CANCEL
from utils import strip_keywords

from github import Github, NamedUser, Repository
from github.GithubException import RateLimitExceededException, BadCredentialsException, UnknownObjectException, GithubException
import keyring

GITHUB_BASE_URL = "https://github.com/"
GITHUB_URI = 'x-github-client://openRepo/'
USER_KEY = '/'
STAR_KEY = '*'
SEARCH_USER_KEY = '@'
KEYS = [USER_KEY, STAR_KEY, SEARCH_USER_KEY]
RESULT_LIMIT = 100
MAX_ISSUES = 50
SEARCH_LIMIT = 10
STAR_GLYPH = ''
REPO_GLYPH = ''
FORK_GLYPH = ''
USER_GLYPH = ''

ICON_DIR = Path(__file__).parent.parent.joinpath('icons')
STAR_ICON = ICON_DIR.joinpath('star-fill.png')
PR_OPEN_ICON = ICON_DIR.joinpath('git-pull-request.png')
PR_MERGED_ICON = ICON_DIR.joinpath('git-merge.png')
PR_ICONS = {
    'open': PR_OPEN_ICON,
    'closed': PR_MERGED_ICON
}
ISSUE_OPEN_ICON = ICON_DIR.joinpath('issue-opened.png')
ISSUE_CLOSED_ICON = ICON_DIR.joinpath('issue-closed.png')
ISSUE_ICONS = {
    'open': ISSUE_OPEN_ICON,
    'closed': ISSUE_CLOSED_ICON
}
PULL_SUB_DIR = '/pull/'

class GithubQuickLauncher(Flox):

    def __init__(self):
        super().__init__()
        self.username = self.settings.get('username', None)
        self.token = self.settings.get('token') or keyring.get_password(self.manifest['Name'], self.username)
        if self.settings.get('token', None):
            self.settings['token'] = ''
            keyring.set_password(self.manifest['Name'], self.username, self.token)
        self.font_family = "#octicons"
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

    def results(self, query, results: list, default_glyph: str=REPO_GLYPH, **kwargs):
        limit = kwargs.pop('limit', RESULT_LIMIT)
        dont_filter = kwargs.pop('filter', False)

        query = strip_keywords(query, KEYS)
        for idx, result in enumerate(results):
            if isinstance(result, (Repository.Repository)):
                glyph = default_glyph
                if query.lower() in result.full_name.lower() or dont_filter:
                    if result.fork and default_glyph != STAR_GLYPH:
                        glyph=FORK_GLYPH
                    self.add_item(
                        title=result.full_name,
                        subtitle=result.description,
                        icon=self.icon,
                        glyph=glyph,
                        method=self.default_action,
                        parameters=[result.full_name],
                        context=[result.full_name]
                )
            if isinstance(result, (NamedUser.NamedUser)):
                self.add_item(
                    title=result.login,
                    subtitle='',
                    icon=self.icon,
                    glyph=USER_GLYPH,
                    method=self.change_query,
                    parameters=[f'{self.user_keyword} {result.login}{USER_KEY}'],
                    context=[result.login],
                    dont_hide=True
                )
            if idx == limit:
                break
        return self._results

    def query(self, query):
        self.font_family = "#octicons"
        try:
            results = []
            if self.settings.get('token', None) is not None and query.startswith(STAR_KEY):
                results = self.get_user_stars(query)
                self.results(query, results, STAR_GLYPH)
            elif query.startswith(SEARCH_USER_KEY):
                if query != SEARCH_USER_KEY:
                    results = self.gh.search_users(query=query.replace(SEARCH_USER_KEY, ''))
                self.results(query, results, USER_GLYPH)
            elif not query.startswith(USER_KEY):
                results = self.get_user_repos(query)
                self.results(query, results, dont_filter=True)
            if len(self._results) == 0 and query != '':
                results = self.search_repos(query)
                self.results(query, results, limit=SEARCH_LIMIT, dont_filter=True)
        except RateLimitExceededException:
            self.add_item(
                title='Github Rate Limit Exceeded',
                subtitle='You can avoid this by providing an access token in settings.',
                icon=ICON_WARNING
            )
        except BadCredentialsException:
            self.add_item(
                title='Bad Credentials',
                subtitle='Please double check you Access Token in settings.',
                icon=ICON_WARNING
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
                subtitle='Please double check your query.',
                icon=ICON_CANCEL
            )

    def context_menu(self, data):
        if data != {}:
            sub_dir = data[0]
            self.add_item(
                title='Open in Browser',
                subtitle=f"Open {sub_dir} in Browser.",
                icon=ICON_BROWSER,
                method=self.open_in_browser,
                parameters=[sub_dir]
            )
            if '/' in sub_dir:
                self.add_item(
                    title='Open Desktop Application',
                    subtitle=f"Open {sub_dir} in Desktop Application.",
                    icon=ICON_BROWSER,
                    method=self.open_in_app,
                    parameters=[sub_dir]
                )
                self._results = utils.cache(sub_dir, 120)(self.get_issues)(sub_dir)
                return self._results

    def get_issues(self, repo):
        repo = self.gh.get_repo(repo)
        open_issues = repo.get_issues(state='all', sort='updated')
        for idx, issue in enumerate(open_issues):
            if PULL_SUB_DIR in issue.html_url:
                icon = PR_ICONS[issue.state]
            else:
                icon = ISSUE_ICONS[issue.state]
            self.add_item(
                title=f"#{issue.number} - {issue.title}",
                subtitle=str(issue.body).replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' '),
                icon=icon,
                method=self.browser_open,
                parameters=[issue.html_url]
            )
            if idx == MAX_ISSUES:
                break
        return self._results

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
