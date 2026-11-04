"""Fractional-index keys for columns, cards, steps and pins.

A key is a string over DIGITS. Keys compare bytewise, so the database column
must use the "C" collation. A key never ends in DIGITS[0], which guarantees a
key can always be generated between any two neighbours, so a drag updates
exactly one row.
"""

from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE = len(DIGITS)
_INDEX = {c: i for i, c in enumerate(DIGITS)}

# When a key grows past this length the caller should rebalance its siblings.
REBALANCE_LENGTH = 48


class OrderingError(ValueError):
    pass


def _validate(key: str) -> None:
    if not key or key[-1] == DIGITS[0] or any(c not in _INDEX for c in key):
        raise OrderingError(f"invalid position key: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """A key strictly between a and b. a may be "" (start); b may be None (end)."""
    if b is not None:
        # Copy the shared prefix, treating a as padded with DIGITS[0].
        n = 0
        while n < len(b) and (a[n] if n < len(a) else DIGITS[0]) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = _INDEX[a[0]] if a else 0
    digit_b = _INDEX[b[0]] if b is not None else _BASE
    if digit_b - digit_a > 1:
        return DIGITS[(digit_a + digit_b + 1) // 2]
    # Adjacent digits: keep a's first digit and recurse on the rest.
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:], None)


def key_between(before: str | None, after: str | None) -> str:
    """Return a key that sorts after `before` and before `after`.

    `before` is the key of the item above the new position (None = top);
    `after` is the key of the item below it (None = bottom).
    """
    if before is not None:
        _validate(before)
    if after is not None:
        _validate(after)
    if before is not None and after is not None and before >= after:
        raise OrderingError(f"{before!r} must sort before {after!r}")
    return _midpoint(before or "", after)


def spread(count: int) -> list[str]:
    """Evenly spaced keys for rebalancing `count` siblings."""
    keys: list[str] = []
    prev: str | None = None
    # Build with a fixed width so keys stay short and ordered.
    width = 1
    while _BASE**width <= count + 1:
        width += 1
    step = (_BASE**width) // (count + 1)
    for i in range(1, count + 1):
        n = step * i
        digits = []
        for _ in range(width):
            n, r = divmod(n, _BASE)
            digits.append(DIGITS[r])
        key = "".join(reversed(digits)).rstrip(DIGITS[0])
        if prev is not None and key <= prev:  # pragma: no cover - guarded by step >= 1
            key = key_between(prev, None)
        keys.append(key)
        prev = key
    return keys
