from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def stage_plugin(destination: Path) -> Path:
    shutil.copy(REPO_ROOT / "run.py", destination)
    shutil.copy(REPO_ROOT / "data" / "plugin.json", destination)
    return destination / "run.py"


def exchange(run_py: Path, *requests: dict) -> dict:
    lines = "".join(json.dumps(request) + "\n" for request in requests)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env.pop("APPDATA", None)
    completed = subprocess.run(
        [sys.executable, str(run_py)], input=lines, capture_output=True, text=True,
        timeout=30, cwd=run_py.parent, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    return {response["id"]: response for response in responses if "id" in response}


def query_request(request_id: int, search: str) -> dict:
    return {
        "jsonrpc": "2.0", "id": request_id, "method": "query",
        "params": [{"search": search, "rawQuery": f"gr {search}", "actionKeyword": "gr"}, {}],
    }


def test_plugin_answers_queries_over_the_v2_protocol(tmp_path):
    run_py = stage_plugin(tmp_path)

    responses = exchange(
        run_py,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [{}]},
        query_request(2, "/"),
        query_request(3, "!refresh"),
        {"jsonrpc": "2.0", "id": 4, "method": "close", "params": []},
    )

    assert responses[1]["error"] is None
    prompt = responses[2]["result"]["result"]
    assert [item["Title"] for item in prompt] == ["Set your GitHub username or token"]
    refresh = responses[3]["result"]["result"]
    assert refresh[0]["JsonRPCAction"]["Method"] == "refresh_cache"
