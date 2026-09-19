import runpy
import sys
import os

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(PLUGIN_DIR, "site-packages"))
runpy.run_module("github_quick_launcher", run_name="__main__")
