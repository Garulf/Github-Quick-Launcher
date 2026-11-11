from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path_factory, monkeypatch):
    """Keep every test away from the real Flow Launcher folders.

    The plugin resolves its cache under %APPDATA% and prunes snapshots of
    other identities there, so a test that builds a service must never see
    the developer's own cache.
    """
    appdata = tmp_path_factory.mktemp("appdata")
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata
