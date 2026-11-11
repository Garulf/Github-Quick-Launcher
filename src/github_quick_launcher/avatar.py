from __future__ import annotations

import math
import sys
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Flow draws result icons at about 32 device-independent pixels. Asking for
# twice the physical size keeps rounded avatars sharp after Flow scales them,
# while staying far below the 400-460 px originals GitHub serves by default.
ICON_DIP = 32
SUPERSAMPLE = 2
MIN_SIZE = 64
MAX_SIZE = 192
SIZE_STEP = 16
BASE_DPI = 96


def system_dpi() -> int:
    """Primary display DPI, or 96 when it cannot be read.

    The registry value is used instead of GetDpiForSystem because this
    process is not DPI aware, and Windows reports 96 to such processes.
    """
    if sys.platform != "win32":
        return BASE_DPI
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\Desktop\WindowMetrics") as key:
            value, _ = winreg.QueryValueEx(key, "AppliedDPI")
        dpi = int(value)
    except (OSError, ValueError, TypeError):
        return BASE_DPI
    return dpi if dpi > 0 else BASE_DPI


def size_for_dpi(dpi: int) -> int:
    pixels = ICON_DIP * SUPERSAMPLE * dpi / BASE_DPI
    rounded = int(math.ceil(pixels / SIZE_STEP) * SIZE_STEP)
    return max(MIN_SIZE, min(MAX_SIZE, rounded))


def sized(url: str, size: int) -> str:
    """Ask GitHub's avatar CDN for a ``size`` px image instead of the original."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not host.endswith(".githubusercontent.com"):
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "s"]
    query.append(("s", str(size)))
    return urlunsplit(parts._replace(query=urlencode(query)))


_size: Optional[int] = None


def default_size() -> int:
    global _size
    if _size is None:
        _size = size_for_dpi(system_dpi())
    return _size
