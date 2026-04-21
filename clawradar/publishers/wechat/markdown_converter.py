"""Markdown to WeChat-compatible HTML conversion helpers."""

from __future__ import annotations

from typing import Any


def convert_markdown_to_wechat_html(markdown_text: str, publisher: Any) -> str:
    markdown_to_html = getattr(publisher, "_markdown_to_html", None)
    if callable(markdown_to_html):
        return markdown_to_html(markdown_text)
    return f"<section>{markdown_text}</section>"
