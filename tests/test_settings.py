from __future__ import annotations

import pytest

from github_quick_launcher.settings import Settings


@pytest.mark.parametrize("raw, expected", [
    ("https://github.com/Garulf", "Garulf"),
    ("github.com/Garulf/", "Garulf"),
    ("  @Garulf ", "Garulf"),
    ("../../etc", ""),
    ("a/../b?x", ""),
    ("gar ulf", ""),
    ("-lead", ""),
    ("a" * 40, ""),
    ("naïve", ""),
])
def test_username_is_normalized_and_validated(raw, expected):
    settings = Settings.from_raw({"username": raw})
    assert settings.username == expected
    if expected == "":
        assert settings.identity_key is None
        assert settings.has_identity is False


def test_empty_settings_have_no_identity():
    settings = Settings.from_raw({})
    assert settings.has_identity is False
    assert settings.identity_key is None
    assert settings.ttl_seconds == 600


def test_username_is_trimmed_and_at_sign_removed():
    settings = Settings.from_raw({"username": "  @Garulf "})
    assert settings.username == "Garulf"
    assert settings.identity_key == "user-garulf"


def test_token_identity_key_never_contains_the_token():
    settings = Settings.from_raw({"token": "ghp_secret", "username": "Garulf"})
    assert settings.identity_key is not None
    assert settings.identity_key.startswith("token-")
    assert "ghp_secret" not in settings.identity_key


def test_none_values_from_flow_are_treated_as_blank():
    settings = Settings.from_raw({"username": None, "token": None, "cache_ttl_minutes": None})
    assert settings == Settings()


def test_invalid_ttl_falls_back_to_default():
    assert Settings.from_raw({"cache_ttl_minutes": "abc"}).cache_ttl_minutes == 10
    assert Settings.from_raw({"cache_ttl_minutes": "0"}).cache_ttl_minutes == 10
    assert Settings.from_raw({"cache_ttl_minutes": "30"}).ttl_seconds == 1800
