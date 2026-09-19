from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Mapping, Optional

from pyflowlauncher import Plugin

from github_quick_launcher import handlers
from github_quick_launcher.client import GitHubClient, build_http
from github_quick_launcher.service import RepoService
from github_quick_launcher.settings import Settings

plugin = Plugin()

_service: Optional[RepoService] = None
_service_settings: Optional[Settings] = None


def _root_dir() -> Path:
    try:
        return plugin.root_dir
    except FileNotFoundError:
        return Path(__file__).resolve().parent


def _cache_dir(root_dir: Path, env: Mapping[str, str]) -> Path:
    appdata = env.get("APPDATA")
    if appdata:
        return (Path(appdata) / "FlowLauncher" / "Settings" / "Plugins"
                / "Github Quick Launcher" / "cache")
    return root_dir / ".cache"


def _service_for_current_settings() -> RepoService:
    # plugin.settings is empty until the first request arrives, and changes
    # whenever the user edits settings, so the service is rebuilt on change.
    global _service, _service_settings
    settings = Settings.from_raw(plugin.settings)
    if _service is None or settings != _service_settings:
        if _service is not None:
            asyncio.ensure_future(_service.aclose())
        client = GitHubClient(build_http(settings.token))
        _service = RepoService(settings, client, _cache_dir(_root_dir(), os.environ))
        _service_settings = settings
    return _service


handlers.build(plugin, _service_for_current_settings)


def main() -> None:
    plugin.run()


if __name__ == "__main__":
    main()
