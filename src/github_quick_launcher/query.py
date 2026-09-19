from __future__ import annotations

from dataclasses import dataclass
from typing import Union

STARS_PREFIX = "*"
SEPARATOR = "/"
REFRESH_COMMAND = "!refresh"


@dataclass(frozen=True)
class Own:
    filter: str


@dataclass(frozen=True)
class Stars:
    filter: str


@dataclass(frozen=True)
class UserSearch:
    user: str
    filter: str


@dataclass(frozen=True)
class Global:
    text: str


@dataclass(frozen=True)
class Refresh:
    pass


Route = Union[Own, Stars, UserSearch, Global, Refresh]


def route(text: str) -> Route:
    text = text.strip()
    if text.lower() == REFRESH_COMMAND:
        return Refresh()
    if text.startswith(STARS_PREFIX):
        return Stars(text[len(STARS_PREFIX):].strip())
    if SEPARATOR not in text:
        return Global(text) if text else Own("")
    user, _, rest = text.partition(SEPARATOR)
    user = user.strip()
    if not user:
        return Own(rest.strip())
    return UserSearch(user, rest.strip())
