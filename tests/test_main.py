from __future__ import annotations

from pathlib import Path

from github_quick_launcher.__main__ import _cache_dir


def test_cache_dir_prefers_appdata(tmp_path: Path):
    result = _cache_dir(tmp_path / "plugin-root", {"APPDATA": str(tmp_path)})
    assert result == (
        tmp_path / "FlowLauncher" / "Settings" / "Plugins" / "Github Quick Launcher" / "cache")


def test_cache_dir_falls_back_to_plugin_root(tmp_path: Path):
    assert _cache_dir(tmp_path, {}) == tmp_path / ".cache"
