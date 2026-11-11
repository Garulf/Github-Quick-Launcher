from __future__ import annotations

import logging

from github_quick_launcher import redact

CLASSIC = "ghp_" + "a" * 36
FINE = "github_pat_" + "B" * 40


def test_scrub_masks_token_formats_and_settings_dumps():
    line = '{"settings": {"token": "custom-secret-value", "username": "me"}}'
    assert "custom-secret-value" not in redact.scrub(line)
    assert '"username": "me"' in redact.scrub(line)
    assert CLASSIC not in redact.scrub(f"bad line {CLASSIC}")
    assert FINE not in redact.scrub(f"x {FINE} y")
    assert "Bearer ***" in redact.scrub("Authorization: Bearer abc.def")


def test_remembered_secret_is_masked_anywhere():
    redact.remember_secret("plain-old-secret-123")
    assert redact.scrub("value=plain-old-secret-123;") == "value=***;"


def test_filter_masks_records_from_child_loggers(tmp_path):
    parent = logging.getLogger("redact-test-parent")
    parent.propagate = False
    path = tmp_path / "plugin.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    parent.addHandler(handler)
    try:
        redact.install(parent)
        redact.install(parent)  # idempotent
        assert len(handler.filters) == 1
        logging.getLogger("redact-test-parent.jsonrpc").warning("Bad JSON-RPC line: %r", CLASSIC)
        try:
            raise ValueError(f"boom {CLASSIC}")
        except ValueError:
            parent.exception("failed")
    finally:
        parent.removeHandler(handler)
        handler.close()
    written = path.read_text(encoding="utf-8")
    assert CLASSIC not in written
    assert "Bad JSON-RPC line" in written
    assert "ValueError: boom ***" in written
