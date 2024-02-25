import pytest

import src.results


AVATAR_URL = "https://avatars.githubusercontent.com/u/535299?v=4"
FULL_NAME = "Garulf/PyFlowLauncher"
DESCRIPTION = "A Python plugin for Flow Launcher"
HTML_URL = "https://github.com/garulf/pyflowlauncher"


result = {
    "full_name": FULL_NAME,
    "description": DESCRIPTION,
    "owner": {
        "avatar_url": AVATAR_URL
    },
    "html_url": HTML_URL
}


async def async_results():
    yield result


@pytest.mark.asyncio
async def test_result():
    repos = async_results()
    async for result in src.results.repo_results(repos):
        assert result.Title == FULL_NAME
        assert result.SubTitle == DESCRIPTION
        assert result.IcoPath == AVATAR_URL
        assert result.JsonRPCAction == {
            "method": "Flow.Launcher.OpenUrl",
            "parameters": (HTML_URL, False)
        }


@pytest.mark.asyncio
async def test_results():
    repos = async_results()
    results = src.results.repo_results(repos)
    async for result in results:
        assert result.Title == FULL_NAME
        assert result.SubTitle == DESCRIPTION
        assert result.IcoPath == AVATAR_URL
        assert result.JsonRPCAction == {
            "method": "Flow.Launcher.OpenUrl",
            "parameters": (HTML_URL, False)
        }
