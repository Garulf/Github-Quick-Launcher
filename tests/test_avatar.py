from __future__ import annotations

import pytest

from github_quick_launcher import avatar


@pytest.mark.parametrize("dpi, size", [
    (96, 64), (120, 80), (144, 96), (192, 128), (288, 192), (480, 192), (48, 64),
])
def test_size_follows_display_scaling_with_headroom(dpi, size):
    assert avatar.size_for_dpi(dpi) == size


def test_sized_replaces_any_existing_size():
    url = "https://avatars.githubusercontent.com/u/17491?v=4&s=460"
    assert avatar.sized(url, 64) == "https://avatars.githubusercontent.com/u/17491?v=4&s=64"


def test_sized_leaves_other_hosts_alone():
    assert avatar.sized("http://avatars.githubusercontent.com/u/1", 64) == (
        "http://avatars.githubusercontent.com/u/1")
    assert avatar.sized("https://example.com/a.png", 64) == "https://example.com/a.png"
    lookalike = "https://evilgithubusercontent.com/u/1"
    assert avatar.sized(lookalike, 64) == lookalike


def test_system_dpi_is_a_positive_number():
    assert avatar.system_dpi() > 0
