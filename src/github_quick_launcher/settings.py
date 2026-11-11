from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

# Long on purpose: a repository list's ETag changes whenever any listed
# repository is pushed to, so a short TTL mostly refetches unchanged names.
# Misses trigger an early revalidation instead (see RepoStore.nudge).
DEFAULT_TTL_MINUTES = 360
# Flow saves a template's default with the rest of the settings, so every
# install from before the lifetime was raised has "10" stored. Reading that
# as "never changed" is what lets the new default reach them.
LEGACY_DEFAULT_TTL_MINUTES = 10
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _ttl_minutes(value: Any) -> int:
    minutes = _positive_int(value, DEFAULT_TTL_MINUTES)
    return DEFAULT_TTL_MINUTES if minutes == LEGACY_DEFAULT_TTL_MINUTES else minutes


def _flag(value: Any, default: bool) -> bool:
    # Flow stores checkboxes as JSON booleans, but sends the template's
    # string default until the user saves the settings once.
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


def _clean_username(value: Any) -> str:
    text = str(value or "").strip()
    if ".." in text:
        return ""
    text = text.rstrip("/").rsplit("/", 1)[-1].lstrip("@")
    return text if LOGIN_RE.fullmatch(text) else ""


@dataclass(frozen=True)
class Settings:
    username: str = ""
    token: str = ""
    cache_ttl_minutes: int = DEFAULT_TTL_MINUTES
    online_search: bool = True
    show_avatars: bool = True

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> Settings:
        return cls(
            username=_clean_username(raw.get("username")),
            token=str(raw.get("token") or "").strip(),
            cache_ttl_minutes=_ttl_minutes(raw.get("cache_ttl_minutes")),
            online_search=_flag(raw.get("online_search"), True),
            show_avatars=_flag(raw.get("show_avatars"), True),
        )

    @property
    def has_identity(self) -> bool:
        return bool(self.token or self.username)

    @property
    def ttl_seconds(self) -> int:
        return self.cache_ttl_minutes * 60

    @property
    def identity_key(self) -> Optional[str]:
        if self.token:
            return "token-" + hashlib.sha256(self.token.encode()).hexdigest()[:12]
        if self.username:
            return "user-" + self.username.lower()
        return None
