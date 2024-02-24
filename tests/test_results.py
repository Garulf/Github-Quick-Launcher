import src.results


AVATAR_URL = "https://avatars.githubusercontent.com/u/535299?v=4"
FULL_NAME = "Garulf/PyFlowLauncher"
DESCRIPTION = "A Python plugin for Flow Launcher"
HTML_URL = "https://github.com/garulf/pyflowlauncher"


class MockPaginatedResult:

    def __iter__(self):
        return iter([MockRepository()])


class MockOwner:

    @property
    def avatar_url(self):
        return AVATAR_URL


class MockRepository:

    @property
    def full_name(self):
        return FULL_NAME

    @property
    def description(self):
        return DESCRIPTION

    @property
    def owner(self):
        return MockOwner()

    @property
    def html_url(self):
        return HTML_URL


def test_result():
    repo = MockRepository()
    result = src.results.repo_result(repo)
    assert result.Title == FULL_NAME
    assert result.SubTitle == DESCRIPTION
    assert result.IcoPath == AVATAR_URL
    assert result.JsonRPCAction == {
        "method": "Flow.Launcher.OpenUrl",
        "parameters": (HTML_URL, False)
    }


def test_results():
    repos = MockPaginatedResult()
    results = src.results.repo_results(repos)
    for result in results:
        assert result.Title == FULL_NAME
        assert result.SubTitle == DESCRIPTION
        assert result.IcoPath == AVATAR_URL
        assert result.JsonRPCAction == {
            "method": "Flow.Launcher.OpenUrl",
            "parameters": (HTML_URL, False)
        }