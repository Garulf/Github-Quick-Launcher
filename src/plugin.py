from typing import Optional

from pyflowlauncher import Plugin
from .query import query


def main(plugin: Optional[Plugin] = None):
    plugin = plugin or Plugin()

    plugin.add_method(query)
    plugin.run()
