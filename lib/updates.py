"""Is a newer build published?

The program asks one small file on GitHub - version.json next to the sources -
instead of the API: raw.githubusercontent.com needs no token, has no rate limit
worth worrying about, and answers in a few hundred bytes.

Everything here stays offline-safe: no network error, no missing key and no
nonsense in the file may raise. A failed check is an ordinary answer with
ok=False, because the header button must survive a machine with no internet.
"""

import json
import re
import urllib.error
import urllib.request

VERSION_URL = (
    "https://raw.githubusercontent.com/"
    "Rennart2025/Rennart_aisubs-local/main/version.json"
)
RELEASE_URL = "https://github.com/Rennart2025/Rennart_aisubs-local"
TIMEOUT = 6.0
_MAX_BYTES = 64 * 1024


def parse_version(value):
    """"1.2.1" -> (1, 2, 1). Junk and suffixes are ignored, never raised over."""
    parts = re.findall(r"\d+", str(value or ""))[:4]
    return tuple(int(p) for p in parts) if parts else ()


def is_newer(latest, current):
    """True when `latest` is a strictly higher version than `current`.

    Shorter versions are padded, so 1.3 beats 1.2.9 and 1.2 equals 1.2.0.
    """
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


def check(current, url=VERSION_URL, timeout=TIMEOUT, opener=None):
    """Asks GitHub for the published version and compares it with ours.

    `opener` exists for the tests: anything with the signature of
    urllib.request.urlopen will do.
    """
    result = {
        "ok": False,
        "current": str(current),
        "latest": None,
        "update_available": False,
        "notes": "",
        "url": RELEASE_URL,
        "error": None,
    }
    fetch = opener or urllib.request.urlopen
    try:
        with fetch(url, timeout=timeout) as response:
            raw = response.read(_MAX_BYTES)
    except urllib.error.URLError as exc:
        result["error"] = f"нет связи с GitHub: {getattr(exc, 'reason', exc)}"
        return result
    except Exception as exc:                      # socket, TLS, anything else
        result["error"] = f"не удалось проверить: {exc}"
        return result

    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("ожидался объект JSON")
    except Exception as exc:
        result["error"] = f"непонятный ответ: {exc}"
        return result

    latest = str(data.get("version") or "").strip()
    if not parse_version(latest):
        result["error"] = "в version.json нет номера версии"
        return result

    result["ok"] = True
    result["latest"] = latest
    result["update_available"] = is_newer(latest, current)
    result["notes"] = str(data.get("notes") or "").strip()
    if isinstance(data.get("url"), str) and data["url"].startswith("https://"):
        result["url"] = data["url"]
    return result
