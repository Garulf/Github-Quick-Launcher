from __future__ import annotations

from dataclasses import dataclass
from typing import Union

STARS_PREFIX = "*"
SEPARATOR = "/"
REFRESH_COMMAND = "!refresh"
CLEAR_COMMAND = "!clear"


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


@dataclass(frozen=True)
class Clear:
    pass


Route = Union[Own, Stars, UserSearch, Global, Refresh, Clear]


def route(text: str) -> Route:
    # Collapsing runs of whitespace is not cosmetic: pyflowlauncher's fuzzy
    # matcher raises IndexError on the empty word between two spaces.
    text = " ".join(text.split())
    if text.lower() == REFRESH_COMMAND:
        return Refresh()
    if text.lower() == CLEAR_COMMAND:
        return Clear()
    if text.startswith(STARS_PREFIX):
        return Stars(text[len(STARS_PREFIX):].strip())
    if SEPARATOR not in text:
        return Global(text) if text else Own("")
    user, _, rest = text.partition(SEPARATOR)
    user = user.strip()
    if not user:
        return Own(rest.strip())
    return UserSearch(user, rest.strip())
