from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Mapping, Optional, Set, Tuple

from pyflowlauncher import Plugin

from github_quick_launcher import handlers, redact
from github_quick_launcher.client import GitHubClient, build_http
from github_quick_launcher.service import RepoService
from github_quick_launcher.settings import Settings

plugin = Plugin()

RETIRE_GRACE_SECONDS = 30.0

_service: Optional[RepoService] = None
_retiring: Set["asyncio.Task[None]"] = set()


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


def _retire(old_service: RepoService) -> None:
    # Its replacement owns the snapshot files from here on. A refresh still
    # in flight in the old service must not write a list back after "!clear"
    # or a changed token deleted the file.
    old_service.retire()

    # A settings edit swaps in a new service on the next keystroke, but Flow
    # re-sends settings with every query, so a query already in flight may
    # still be awaiting the old client. Give it a grace period before
    # closing it instead of racing that in-flight work with an immediate
    # aclose(). Called only from a running handler, so a loop always exists.
    async def close_after_grace() -> None:
        await asyncio.sleep(RETIRE_GRACE_SECONDS)
        await old_service.aclose()

    task = asyncio.get_running_loop().create_task(close_after_grace())
    _retiring.add(task)
    task.add_done_callback(_retiring.discard)


def _connection(settings: Settings) -> Tuple[str, str, int]:
    """The settings a service is built from; the rest is read per query."""
    return settings.username, settings.token, settings.cache_ttl_minutes


def _service_for_current_settings() -> RepoService:
    # plugin.settings is empty until the first request arrives, and changes
    # whenever the user edits settings, so the service is rebuilt on change.
    global _service
    settings = Settings.from_raw(plugin.settings)
    if _service is not None and _connection(settings) == _connection(_service.settings):
        _service.settings = settings
        return _service
    identity_changed = (
        _service is None or settings.identity_key != _service.settings.identity_key)
    if _service is not None:
        _retire(_service)
    redact.remember_secret(settings.token)
    client = GitHubClient(build_http(settings.token))
    _service = RepoService(settings, client, _cache_dir(_root_dir(), os.environ))
    if identity_changed:
        # A removed or replaced token must not leave its private
        # repository list behind on disk.
        _service.prune_other_caches()
    return _service


redact.install()
handlers.build(plugin, _service_for_current_settings)


def main() -> None:
    plugin.run()


if __name__ == "__main__":
    main()
