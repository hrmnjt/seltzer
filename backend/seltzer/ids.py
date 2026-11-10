"""UUIDv7 generation (RFC 9562), so primary keys sort by creation time on any Postgres."""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a UUIDv7 that is monotonic within this process.

    Layout: 48-bit Unix ms timestamp, 4-bit version, 12-bit counter (rand_a),
    2-bit variant, 62 random bits (rand_b). The counter keeps ids generated in
    the same millisecond in order.
    """
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x07FF  # leave headroom
        else:
            _counter += 1
            if _counter > 0x0FFF:  # counter overflow: borrow the next millisecond
                _last_ms += 1
                _counter = 0
            ms = _last_ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= _counter << 64
        value |= 0b10 << 62
        value |= rand_b
    return uuid.UUID(int=value)


def uuid7_floor(ms: int) -> uuid.UUID:
    """The smallest UUIDv7 for a millisecond timestamp, for time-based cursors."""
    return uuid.UUID(int=((ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (0b10 << 62))
