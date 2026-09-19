from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Optional

DEFAULT_TTL_MINUTES = 10


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


@dataclass(frozen=True)
class Settings:
    username: str = ""
    token: str = ""
    cache_ttl_minutes: int = DEFAULT_TTL_MINUTES

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> Settings:
        return cls(
            username=str(raw.get("username") or "").strip().lstrip("@"),
            token=str(raw.get("token") or "").strip(),
            cache_ttl_minutes=_positive_int(raw.get("cache_ttl_minutes"), DEFAULT_TTL_MINUTES),
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
