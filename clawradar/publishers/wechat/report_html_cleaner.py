"""Utilities for converting report HTML into WeChat-friendly article HTML."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from .image_handler import (
    prepare_report_visual_media,
    resolve_image_mode,
)


def extract_report_article_html(report_html: str) -> str:
    if not report_html:
        return ""
    for pattern in (
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<body\b[^>]*>(.*?)</body>",
    ):
        matches = re.findall(pattern, report_html, flags=re.IGNORECASE | re.DOTALL)
        if matches:
            return max(matches, key=len).strip()
    return ""


def sanitize_report_article_html(article_html: str) -> str:
    if not article_html:
        return ""

    sanitized = article_html
    for pattern in (
        r"<script\b[^>]*>.*?</script>",
        r"<style\b[^>]*>.*?</style>",
        r"<noscript\b[^>]*>.*?</noscript>",
        r"<button\b[^>]*>.*?</button>",
    ):
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE | re.DOTALL)
    return sanitized.strip()


def _node_text(node: Tag) -> str:
    return " ".join(node.stripped_strings)


def _node_classes(node: Tag) -> set[str]:
    attrs = getattr(node, "attrs", None) or {}
    classes = attrs.get("class") or []
    if isinstance(classes, str):
        return {classes}
    return {str(value) for value in classes}


def _should_drop_report_node(node: Tag) -> bool:
    if not isinstance(node, Tag):
        return False

    attrs = getattr(node, "attrs", None) or {}
    node_name = str(getattr(node, "name", "") or "").lower()
    if node_name in {"script", "style", "noscript", "button", "form"}:
        return True

    node_id = str(attrs.get("id") or "").strip().lower()
    class_names = {value.lower() for value in _node_classes(node)}
    tokens = {node_id, *class_names}
    return any(
        marker in token
        for token in tokens
        for marker in (
            "toc",
            "hero-actions",
            "export-overlay",
            "export-dialog",
            "export-progress",
            "export-spinner",
            "action-btn",
            "no-print",
            "engine-quote__header",
            "engine-quote__dot",
            "engine-quote__title",
        )
    )


def _render_inline_node(node: Any) -> str:
    if isinstance(node, NavigableString):
        return html.escape(str(node))
    if not isinstance(node, Tag):
        return ""

    if _should_drop_report_node(node):
        return ""

    name = node.name.lower()
    inner = "".join(_render_inline_node(child) for child in node.children)
    if name == "br":
        return "<br>"
    if name in {"strong", "b"}:
        return f"<strong>{inner}</strong>" if inner.strip() else ""
    if name in {"em", "i"}:
        return f"<em>{inner}</em>" if inner.strip() else ""
    if name == "code":
        if not inner.strip():
            return ""
        return (
            '<code style="background:#f6f8fa;padding:2px 6px;border-radius:3px;'
            'font-size:14px;color:#e83e8c;">'
            f"{inner}</code>"
        )
    if name == "img":
        src = str(node.get("src") or "").strip()
        if not src:
            return ""
        alt_text = html.escape(str(node.get("alt") or "").strip(), quote=True)
        return (
            f'<img src="{html.escape(src, quote=True)}" alt="{alt_text}" '
            'style="max-width:100%;height:auto;display:block;margin:10px auto;">'
        )
    if name == "a":
        href = str(node.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            return inner
        return (
            f'<a href="{html.escape(href, quote=True)}" '
            'style="color:#576b95;text-decoration:none;">'
            f"{inner}</a>"
        )
    return inner


def _render_report_heading(node: Tag) -> str:
    styles = {
        "h1": "font-size:20px;font-weight:bold;margin:20px 0 10px;color:#333;",
        "h2": "font-size:18px;font-weight:bold;margin:18px 0 8px;color:#333;",
        "h3": "font-size:16px;font-weight:bold;margin:16px 0 6px;color:#333;",
        "h4": "font-size:15px;font-weight:bold;margin:14px 0 6px;color:#333;",
        "h5": "font-size:14px;font-weight:bold;margin:12px 0 4px;color:#333;",
        "h6": "font-size:14px;font-weight:bold;margin:12px 0 4px;color:#333;",
    }
    content = "".join(_render_inline_node(child) for child in node.children).strip()
    if not content:
        return ""
    return f'<section style="{styles.get(node.name.lower(), styles["h3"])}">{content}</section>'


def _render_report_paragraph(node: Tag) -> str:
    content = "".join(_render_inline_node(child) for child in node.children).strip()
    if not content:
        return ""
    return (
        '<section style="font-size:17px;line-height:1.75;color:#333;'
        f'margin:12px 0;word-break:break-word;">{content}</section>'
    )


def _render_report_blockquote(node: Tag) -> str:
    content = html.escape(_node_text(node))
    if not content:
        return ""
    return (
        '<section style="border-left:4px solid #ddd;padding:8px 12px;margin:12px 0;'
        f'color:#666;font-style:italic;background:#f9f9f9;">{content}</section>'
    )


def _render_report_list(node: Tag) -> str:
    items = []
    prefix = "-" if node.name.lower() == "ul" else None
    for index, item in enumerate(node.find_all("li", recursive=False), start=1):
        content = "".join(_render_inline_node(child) for child in item.children).strip()
        if not content:
            content = html.escape(_node_text(item))
        if not content:
            continue
        marker = prefix or f"{index}."
        items.append(
            '<section style="font-size:16px;line-height:1.75;color:#333;'
            f'margin:6px 0;word-break:break-word;">{marker} {content}</section>'
        )
    if not items:
        return ""
    return "".join(items)


def _table_row_cells(row: Tag) -> list[str]:
    values = []
    for cell in row.find_all(["th", "td"], recursive=False):
        content = "".join(_render_inline_node(child) for child in cell.children).strip()
        if not content:
            content = html.escape(_node_text(cell))
        if content:
            values.append(content)
    return values


def _should_render_compact_table(node: Tag) -> bool:
    if node.find("thead") is not None or node.find("th") is not None:
        return False

    row_cells = [_table_row_cells(row) for row in node.find_all("tr")]
    row_cells = [cells for cells in row_cells if cells]
    if not row_cells:
        return False

    max_columns = max(len(cells) for cells in row_cells)
    return max_columns <= 3


def _render_compact_report_table(node: Tag) -> str:
    caption = node.find("caption", recursive=False)
    parts = []
    if caption is not None:
        caption_text = html.escape(_node_text(caption))
        if caption_text:
            parts.append(
                '<section style="font-size:15px;font-weight:bold;margin:16px 0 8px;color:#333;">'
                f"{caption_text}</section>"
            )

    rows = [_table_row_cells(row) for row in node.find_all("tr")]
    rows = [cells for cells in rows if cells]
    if not rows:
        return "".join(parts)

    header_cells: list[str] = []
    body_rows = rows
    if len(rows) > 1 and len(rows[0]) > 1:
        header_cells = rows[0]
        body_rows = rows[1:]

    if header_cells:
        header_pills = []
        for cell in header_cells:
            header_pills.append(
                '<span style="display:inline-block;margin:0 8px 8px 0;padding:4px 10px;border-radius:999px;'
                'background:#eef2ff;color:#3559c7;font-size:12px;font-weight:bold;line-height:1.4;">'
                f"{cell}</span>"
            )
        parts.append(
            '<section style="margin:8px 0 10px;white-space:nowrap;overflow-x:auto;">'
            + "".join(header_pills)
            + "</section>"
        )

    for index, cells in enumerate(body_rows, start=1):
        title = cells[0]
        details = cells[1:]
        if details:
            detail_html = (
                '<section style="margin-top:10px;padding-top:10px;border-top:1px dashed #d7deeb;">'
                + "".join(
                    '<section style="font-size:14px;line-height:1.72;color:#556070;margin-top:4px;">'
                    f"{detail}</section>"
                    for detail in details
                )
                + "</section>"
            )
        else:
            detail_html = '<section style="font-size:14px;line-height:1.7;color:#6b7280;">No additional notes.</section>'

        parts.append(
            '<section style="margin:12px 0;padding:0;border:1px solid #dde5f0;border-radius:14px;'
            'background:linear-gradient(180deg,#ffffff 0%,#f8fbff 100%);overflow:hidden;">'
            '<section style="padding:10px 14px 8px;border-bottom:1px solid #edf2f7;'
            'background:linear-gradient(180deg,#f7faff 0%,#fdfefe 100%);">'
            f'<span style="display:inline-block;min-width:24px;height:24px;padding:0 7px;border-radius:999px;'
            'background:#2f6fed;color:#fff;font-size:12px;font-weight:bold;line-height:24px;text-align:center;vertical-align:middle;">'
            f"{index}</span>"
            f'<span style="display:inline-block;margin-left:10px;font-size:15px;font-weight:bold;line-height:1.6;color:#1f2a37;vertical-align:middle;">{title}</span>'
            '</section>'
            f'<section style="padding:12px 14px 13px;">{detail_html}</section>'
            '</section>'
        )

    return "".join(parts)


def _render_report_table(node: Tag) -> str:
    if _should_render_compact_table(node):
        return _render_compact_report_table(node)

    caption = node.find("caption", recursive=False)
    parts = []
    if caption is not None:
        caption_text = html.escape(_node_text(caption))
        if caption_text:
            parts.append(
                '<section style="font-size:15px;font-weight:bold;margin:16px 0 8px;color:#333;">'
                f"{caption_text}</section>"
            )

    rows = []
    for row in node.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        rendered_cells = []
        for cell in cells:
            content = "".join(_render_inline_node(child) for child in cell.children).strip()
            if not content:
                content = html.escape(_node_text(cell))
            tag_name = "th" if cell.name.lower() == "th" else "td"
            style = (
                "border:1px solid #ddd;padding:8px;background:#f6f8fa;font-weight:bold;"
                if tag_name == "th"
                else "border:1px solid #ddd;padding:8px;"
            )
            rendered_cells.append(f'<{tag_name} style="{style}">{content}</{tag_name}>')
        if rendered_cells:
            rows.append(f"<tr>{''.join(rendered_cells)}</tr>")

    if not rows:
        return "".join(parts)

    parts.append(
        '<section style="overflow-x:auto;margin:12px 0;">'
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f"{''.join(rows)}</table></section>"
    )
    return "".join(parts)


def _render_report_image_block(node: Tag) -> str:
    content = _render_inline_node(node).strip()
    if not content:
        return ""
    return f'<section style="margin:16px 0;text-align:center;">{content}</section>'


def _render_report_figure(node: Tag) -> str:
    image_html = "".join(_render_inline_node(child) for child in node.children if getattr(child, "name", None) != "figcaption").strip()
    caption_node = node.find("figcaption", recursive=False)
    caption_html = ""
    if caption_node is not None:
        caption_text = "".join(_render_inline_node(child) for child in caption_node.children).strip() or html.escape(_node_text(caption_node))
        if caption_text:
            caption_html = (
                '<section style="font-size:14px;line-height:1.6;color:#666;margin:8px 0 0;text-align:center;">'
                f"{caption_text}</section>"
            )
    if not image_html and not caption_html:
        return ""
    return f'<section style="margin:16px 0;">{image_html}{caption_html}</section>'


def simplify_report_article_html(article_html: str) -> str:
    if not article_html:
        return ""

    soup = BeautifulSoup(article_html, "html.parser")
    root = soup.find("main") or soup.find("article") or soup
    for node in list(root.find_all(True)):
        if _should_drop_report_node(node):
            node.decompose()

    rendered_parts = []
    block_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "ul", "ol", "table", "hr", "img", "figure")
    nested_block_ancestors = set(block_tags) | {"li", "td", "th", "caption", "figcaption"}

    for node in root.find_all(block_tags):
        if any(getattr(parent, "name", None) in nested_block_ancestors for parent in node.parents if parent is not root):
            continue

        rendered = ""
        if node.name.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            rendered = _render_report_heading(node)
        elif node.name.lower() == "p":
            rendered = _render_report_paragraph(node)
        elif node.name.lower() == "blockquote":
            rendered = _render_report_blockquote(node)
        elif node.name.lower() in {"ul", "ol"}:
            rendered = _render_report_list(node)
        elif node.name.lower() == "table":
            rendered = _render_report_table(node)
        elif node.name.lower() == "hr":
            rendered = '<section style="margin:24px 0;border-top:1px solid #e5e5e5;"></section>'
        elif node.name.lower() == "img":
            rendered = _render_report_image_block(node)
        elif node.name.lower() == "figure":
            rendered = _render_report_figure(node)

        if rendered:
            rendered_parts.append(rendered)

    return "".join(rendered_parts).strip()


def html_fragment_to_text(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|section|article|h1|h2|h3|h4|h5|h6|li|blockquote)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r", "")
    return text.strip()


def looks_like_embedded_report_html(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return "chart.js" in normalized or "<!doctype html" in normalized or "<html" in normalized or "<main" in normalized


def build_wechat_article_from_report_html(
    report_html: str,
    *,
    image_mode: str = "fallback_table",
    publisher: Any = None,
    base_dir: str | None = None,
) -> str:
    media_ready_html = prepare_report_visual_media(
        report_html,
        image_mode=resolve_image_mode(image_mode),
        publisher=publisher,
        base_dir=Path(base_dir).resolve() if base_dir else None,
    )
    article_html = extract_report_article_html(media_ready_html)
    article_html = sanitize_report_article_html(article_html)
    return simplify_report_article_html(article_html)
