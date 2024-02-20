from typing import Optional

from pyflowlauncher import Plugin

from query import query
from context_menu import context_menu


def main(plugin: Optional[Plugin] = None):
    plugin = plugin or Plugin()

    plugin.add_method(query)
    plugin.add_method(context_menu)
    plugin.run()
