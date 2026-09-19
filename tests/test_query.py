from __future__ import annotations

import pytest

from github_quick_launcher.query import Global, Own, Refresh, Stars, UserSearch, route


@pytest.mark.parametrize("text, expected", [
    ("", Own("")),
    ("   ", Own("")),
    ("/", Own("")),
    ("/flow", Own("flow")),
    ("/ flow ", Own("flow")),
    ("*", Stars("")),
    ("*render", Stars("render")),
    ("garulf/", UserSearch("garulf", "")),
    ("garulf/flow", UserSearch("garulf", "flow")),
    ("garulf/flow/extra", UserSearch("garulf", "flow/extra")),
    ("flow launcher", Global("flow launcher")),
    ("!refresh", Refresh()),
    ("!REFRESH ", Refresh()),
])
def test_route(text, expected):
    assert route(text) == expected
