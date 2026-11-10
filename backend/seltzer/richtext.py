"""Rich text is stored as Tiptap (ProseMirror) JSON.

The server validates the document against a small schema, rejects unsafe
links, and derives the plain text used for search and the people @-mentioned.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

MAX_BYTES = 256 * 1024
MAX_DEPTH = 24

NODE_TYPES = {
    "doc",
    "paragraph",
    "text",
    "heading",
    "bulletList",
    "orderedList",
    "listItem",
    "taskList",
    "taskItem",
    "blockquote",
    "codeBlock",
    "hardBreak",
    "horizontalRule",
    "mention",
}
MARK_TYPES = {"bold", "italic", "strike", "code", "underline", "link"}
BLOCK_TYPES = NODE_TYPES - {"text", "mention", "hardBreak", "doc"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")


class RichTextError(ValueError):
    pass


def validate(doc: Any) -> dict[str, Any]:
    """Raise RichTextError unless `doc` is a safe Tiptap document; return it."""
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise RichTextError("rich text must be a Tiptap document with type 'doc'")
    if len(json.dumps(doc, separators=(",", ":"))) > MAX_BYTES:
        raise RichTextError(f"rich text is larger than {MAX_BYTES // 1024} KB")
    _check(doc, 0)
    return doc


def _check(node: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise RichTextError("rich text is nested too deeply")
    if not isinstance(node, dict):
        raise RichTextError("rich text nodes must be objects")
    kind = node.get("type")
    if kind not in NODE_TYPES:
        raise RichTextError(f"unsupported rich text node: {kind!r}")
    if kind == "text" and not isinstance(node.get("text"), str):
        raise RichTextError("text nodes need a string 'text'")
    if kind == "mention":
        attrs = node.get("attrs") or {}
        try:
            uuid.UUID(str(attrs.get("id")))
        except ValueError as exc:
            raise RichTextError("mentions need a user id") from exc
    for mark in node.get("marks") or []:
        if not isinstance(mark, dict) or mark.get("type") not in MARK_TYPES:
            raise RichTextError(f"unsupported mark: {mark!r}")
        if mark["type"] == "link":
            href = str((mark.get("attrs") or {}).get("href", "")).strip().lower()
            if not href.startswith(SAFE_SCHEMES):
                raise RichTextError("links must use http, https or mailto")
    content = node.get("content")
    if content is not None:
        if not isinstance(content, list):
            raise RichTextError("'content' must be a list")
        for child in content:
            _check(child, depth + 1)


def plain_text(doc: dict[str, Any] | None) -> str:
    """Flatten a document to text: blocks on their own lines, mentions as @label."""
    if not doc:
        return ""
    out: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        kind = node.get("type")
        if kind == "text":
            out.append(node.get("text", ""))
        elif kind == "mention":
            attrs = node.get("attrs") or {}
            out.append("@" + str(attrs.get("label") or ""))
        elif kind == "hardBreak":
            out.append("\n")
        for child in node.get("content") or []:
            walk(child)
        if kind in BLOCK_TYPES:
            out.append("\n")

    walk(doc)
    lines = [line.strip() for line in "".join(out).splitlines()]
    return "\n".join(line for line in lines if line)


def mentioned_user_ids(doc: dict[str, Any] | None) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "mention":
            with contextlib.suppress(ValueError):
                found.add(uuid.UUID(str((node.get("attrs") or {}).get("id"))))
        for child in node.get("content") or []:
            walk(child)

    if doc:
        walk(doc)
    return found


def from_plain_text(text: str) -> dict[str, Any]:
    """Wrap plain text in a document, one paragraph per line (used by tests and seeds)."""
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        if line
        else {"type": "paragraph"}
        for line in text.split("\n")
    ]
    return {"type": "doc", "content": paragraphs}
