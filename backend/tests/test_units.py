"""Pure helpers: ordering keys, UUIDv7 and rich text."""

from __future__ import annotations

import random
import uuid

import pytest

from seltzer import richtext
from seltzer.ids import uuid7
from seltzer.ordering import OrderingError, key_between, spread


def test_keys_stay_ordered_under_random_inserts() -> None:
    rng = random.Random(7)
    keys: list[str] = []
    for _ in range(2000):
        i = rng.randint(0, len(keys))
        lo = keys[i - 1] if i else None
        hi = keys[i] if i < len(keys) else None
        key = key_between(lo, hi)
        assert (lo is None or lo < key) and (hi is None or key < hi)
        keys.insert(i, key)
    assert keys == sorted(keys)


def test_key_errors_and_spread() -> None:
    with pytest.raises(OrderingError):
        key_between("b", "a")
    with pytest.raises(OrderingError):
        key_between("a0", None)
    keys = spread(500)
    assert keys == sorted(keys) and len(set(keys)) == 500 and all(k[-1] != "0" for k in keys)


def test_uuid7_is_time_ordered() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(i.version == 7 for i in ids)


def test_rich_text_plain_text_and_mentions() -> None:
    uid = uuid.uuid4()
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Steps"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Ask "},
                    {"type": "mention", "attrs": {"id": str(uid), "label": "Ada"}},
                    {
                        "type": "text",
                        "text": " about it",
                        "marks": [{"type": "link", "attrs": {"href": "https://x.test"}}],
                    },
                ],
            },
        ],
    }
    richtext.validate(doc)
    assert richtext.plain_text(doc) == "Steps\nAsk @Ada about it"
    assert richtext.mentioned_user_ids(doc) == {uid}


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "paragraph"},
        {"type": "doc", "content": [{"type": "script"}]},
        {"type": "doc", "content": [{"type": "text", "text": "x", "marks": [{"type": "font"}]}]},
        {"type": "doc", "content": [{"type": "mention", "attrs": {"id": "not-a-uuid"}}]},
    ],
)
def test_rich_text_rejects_unsafe_documents(bad: dict) -> None:
    with pytest.raises(richtext.RichTextError):
        richtext.validate(bad)


def test_volume_setting_accepts_full_names_and_paths() -> None:
    from seltzer.config import Settings

    assert (
        Settings(seltzer_volume="main.seltzer.attachments").volume_root
        == "/Volumes/main/seltzer/attachments"
    )
    assert Settings(seltzer_volume="/Volumes/a/b/c/").volume_root == "/Volumes/a/b/c"
    assert Settings(seltzer_volume=None).volume_root is None
    with pytest.raises(ValueError):
        _ = Settings(seltzer_volume="just-a-name").volume_root
