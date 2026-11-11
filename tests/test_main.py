from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import pytest

from github_quick_launcher import __main__ as main
from github_quick_launcher.__main__ import _cache_dir
from github_quick_launcher.client import Listing


def test_cache_dir_prefers_appdata(tmp_path: Path):
    result = _cache_dir(tmp_path / "plugin-root", {"APPDATA": str(tmp_path)})
    assert result == (
        tmp_path / "FlowLauncher" / "Settings" / "Plugins" / "Github Quick Launcher" / "cache")


def test_cache_dir_falls_back_to_plugin_root(tmp_path: Path):
    assert _cache_dir(tmp_path, {}) == tmp_path / ".cache"


@pytest.fixture
def clean_main(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_service", None)
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


async def test_removing_the_token_deletes_its_private_snapshot(clean_main, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(clean_main, "_cache_dir", lambda root, env: cache_dir)
    _set_settings(clean_main, {"token": "ghp_" + "x" * 36})
    service = clean_main._service_for_current_settings()
    cache_dir.mkdir()
    for path in service.cache_files():
        path.write_text("{}")

    _set_settings(clean_main, {"username": "octocat"})
    clean_main._service_for_current_settings()

    assert list(cache_dir.iterdir()) == []
    for task in clean_main._retiring:
        task.cancel()


async def test_a_new_cache_lifetime_keeps_the_snapshot(clean_main, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(clean_main, "_cache_dir", lambda root, env: cache_dir)
    _set_settings(clean_main, {"username": "octocat"})
    service = clean_main._service_for_current_settings()
    cache_dir.mkdir()
    for path in service.cache_files():
        path.write_text("{}")

    _set_settings(clean_main, {"username": "octocat", "cache_ttl_minutes": "30"})
    replacement = clean_main._service_for_current_settings()

    assert replacement is not service
    assert len(list(cache_dir.iterdir())) == 2
    for task in clean_main._retiring:
        task.cancel()


async def test_display_options_are_applied_without_a_new_service(clean_main):
    _set_settings(clean_main, {"username": "octocat"})
    service = clean_main._service_for_current_settings()

    _set_settings(clean_main, {
        "username": "octocat", "show_avatars": False, "online_search": False})
    same = clean_main._service_for_current_settings()

    assert same is service
    assert same.settings.show_avatars is False
    assert same.settings.online_search is False
    assert clean_main._retiring == set()


async def test_every_replaced_service_stops_writing_its_snapshot(
    clean_main, tmp_path, monkeypatch,
):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(clean_main, "_cache_dir", lambda root, env: cache_dir)
    token = {"token": "ghp_" + "x" * 36}
    _set_settings(clean_main, token)
    first = clean_main._service_for_current_settings()
    listed = asyncio.Event()

    async def slow_list(path, etag=None):
        await listed.wait()
        return Listing([], None)

    monkeypatch.setattr(first._client, "list_repos", slow_list)
    first.own.snapshot()  # a refresh is now in flight in the first service

    _set_settings(clean_main, {**token, "cache_ttl_minutes": "30"})
    clean_main._service_for_current_settings()
    _set_settings(clean_main, {"username": "octocat"})
    clean_main._service_for_current_settings()
    listed.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not cache_dir.exists() or list(cache_dir.iterdir()) == []
    for task in clean_main._retiring:
        task.cancel()


async def test_tests_never_resolve_the_real_appdata(clean_main, isolated_appdata):
    _set_settings(clean_main, {"username": "octocat"})
    service = clean_main._service_for_current_settings()
    assert all(str(path).startswith(str(isolated_appdata)) for path in service.cache_files())
