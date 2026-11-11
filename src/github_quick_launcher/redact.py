from __future__ import annotations

import logging
import re
from typing import Iterable, Optional, Set

# Classic and fine-grained GitHub tokens, Authorization headers, and a
# "token" key inside a logged settings dictionary or JSON-RPC line.
_PATTERNS = (
    re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"(?i)(bearer\s+)[^\s'\",]+"),
    re.compile(r"""(?i)(['"]token['"]\s*:\s*['"])[^'"]*"""),
)
MASK = "***"

_secrets: Set[str] = set()


def remember_secret(secret: str) -> None:
    """Mask this exact value too, whatever its format."""
    if len(secret) >= 8:
        _secrets.add(secret)


def scrub(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + MASK, text)
    return text


class RedactingFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg, record.args = scrub(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def install(logger: Optional[logging.Logger] = None) -> None:
    """Attach the filter to every handler that writes the plugin log.

    A filter on the handler, unlike one on the logger, also sees records
    from child loggers such as pyflowlauncher.jsonrpc.
    """
    target = logger or logging.getLogger("pyflowlauncher")
    handlers: Iterable[logging.Handler] = target.handlers
    for handler in handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
