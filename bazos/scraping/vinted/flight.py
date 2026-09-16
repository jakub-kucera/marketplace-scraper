"""Parsing for Vinted's Next.js RSC ("flight") payload.

Vinted retired the anonymous `/api/v2/catalog/items` endpoint (see
docs/research/marketplaces/VINTED.md §1), so the catalog page itself is now the data
source: it server-renders the full 96-row result set into a React Server Component
payload. This module turns that payload back into Python objects, and nothing here talks
to the network.

Two shapes arrive, and both are handled by :func:`decode`:

- an **HTML page**, where the payload is split across `self.__next_f.push([1,"<chunk>"])`
  script tags and JSON-string-escaped;
- the **raw flight payload**, returned when the request carries an `RSC: 1` header.

⚠️ The payload is *not* JSON. It is a stream of `id:value` lines with JSON fragments
embedded, so it cannot be `json.loads`-ed whole — values are located by key and then
extracted with a balanced scan.
"""
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.S)

_OPENERS = "[{"
_CLOSERS = "]}"


def decode(text: str) -> str:
    """Return the flight payload, whether `text` is an HTML page or already raw."""
    if "self.__next_f.push" not in text:
        return text
    chunks = []
    for raw in _CHUNK.findall(text):
        try:
            chunks.append(json.loads(raw))
        except json.JSONDecodeError:
            # One unparseable chunk is survivable — the payload is a stream and the
            # interesting values are keyed, not positional. Losing all of them is not,
            # which is what the caller's "did anything parse?" check is for.
            logger.debug("Vinted flight: skipping an undecodable __next_f chunk")
    return "".join(chunks)


def balanced_slice(text: str, start: int) -> str | None:
    """The complete JSON array/object beginning at `text[start]`, or None.

    ⚠️ This is why the item list is not pulled out with a regex. Listing titles routinely
    contain `"`, `[`, `{` and backslashes — measured live: `MacBook Pro 13" Retina
    (A1502)`, `Macbook Air 2018 | Ładowarka |`. A scanner that tracks string state and
    escapes is the only correct way to find the end of the value.
    """
    if start >= len(text) or text[start] not in _OPENERS:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def find_value(flight: str, key: str, pos: int = 0) -> tuple[Any, int] | None:
    """Locate `"<key>":` and return its decoded value plus the offset just past it.

    `key` is the bare name without quotes or colon. Returns None when the key is absent
    or its value is not an array/object (a scalar is never what callers want here).
    """
    needle = f'"{key}":'
    index = flight.find(needle, pos)
    if index < 0:
        return None
    start = index + len(needle)
    while start < len(flight) and flight[start] in " \n\r\t":
        start += 1
    raw = balanced_slice(flight, start)
    if raw is None:
        return None
    try:
        return json.loads(raw), start + len(raw)
    except json.JSONDecodeError:
        return None


def get(flight: str, key: str) -> Any | None:
    """First decodable value for `key`, or None."""
    found = find_value(flight, key)
    return found[0] if found else None


def iter_values(flight: str, key: str):
    """Every decodable value for `key`, in document order.

    Needed because the catalog tree is not shipped as one array: `"catalogs":[…]` appears
    ~2,100 times, each a subtree, and the first match is emphatically not the root.
    """
    pos = 0
    while True:
        found = find_value(flight, key, pos)
        if found is None:
            return
        value, pos = found
        yield value


def items(flight: str) -> list[dict[str, Any]]:
    """The search result rows, or [] when the payload carries none.

    An empty list is the block signal: there is no status code or error body to key on
    (VINTED.md §10), and the word "datadome" appears on healthy pages, so "did any row
    parse" is the only trustworthy check.
    """
    found = find_value(flight, "items")
    while found is not None:
        value, pos = found
        # `"items"` also names the wrapper object `{"items": [...], "pagination": {...}}`,
        # so accept the first value that is actually a list of rows.
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return [row for row in value["items"] if isinstance(row, dict)]
        found = find_value(flight, "items", pos)
    return []
