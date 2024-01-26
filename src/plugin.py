from typing import Optional

from pyflowlauncher import Plugin
import requests_cache
from query import query
from context_menu import context_menu


def main(plugin: Optional[Plugin] = None):
    requests_cache.install_cache(".cache", backend="sqlite", expire_after=300)

    plugin = plugin or Plugin()

    plugin.add_method(query)
    plugin.add_method(context_menu)
    plugin.run()
