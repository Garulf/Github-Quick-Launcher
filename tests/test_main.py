from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import pytest

from github_quick_launcher import __main__ as main
from github_quick_launcher.__main__ import _cache_dir


def test_cache_dir_prefers_appdata(tmp_path: Path):
    result = _cache_dir(tmp_path / "plugin-root", {"APPDATA": str(tmp_path)})
    assert result == (
        tmp_path / "FlowLauncher" / "Settings" / "Plugins" / "Github Quick Launcher" / "cache")


def test_cache_dir_falls_back_to_plugin_root(tmp_path: Path):
    assert _cache_dir(tmp_path, {}) == tmp_path / ".cache"


@pytest.fixture
def clean_main(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_service", None)
    monkeypatch.setattr(main, "_service_settings", None)
    monkeypatch.setattr(main, "_retiring", set())
    monkeypatch.setattr(main, "_root_dir", lambda: tmp_path)
    monkeypatch.setattr(main.plugin._launcher, "_settings", {})
    return main


def _set_settings(module: Any, raw: Mapping[str, Any]) -> None:
    module.plugin._launcher._settings = dict(raw)


async def test_same_settings_returns_the_same_service(clean_main):
    _set_settings(clean_main, {"username": "octocat"})

    first = clean_main._service_for_current_settings()
    second = clean_main._service_for_current_settings()

    assert first is second


async def test_changed_settings_swaps_and_retires_the_old_service_after_grace(
    clean_main, monkeypatch,
):
    monkeypatch.setattr(clean_main, "RETIRE_GRACE_SECONDS", 0)
    _set_settings(clean_main, {"username": "octocat"})
    old_service = clean_main._service_for_current_settings()

    closed = []

    async def fake_aclose() -> None:
        closed.append(True)

    monkeypatch.setattr(old_service, "aclose", fake_aclose)

    _set_settings(clean_main, {"username": "someone-else"})
    new_service = clean_main._service_for_current_settings()

    assert new_service is not old_service
    assert closed == []
    assert len(clean_main._retiring) == 1

    await asyncio.gather(*clean_main._retiring)

    assert closed == [True]
    assert clean_main._retiring == set()
