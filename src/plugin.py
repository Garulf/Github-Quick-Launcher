from pyflowlauncher import Plugin


def main(plugin: Plugin) -> Plugin:
    @plugin.on_method
    def query(query: str):
        pass

    return plugin
