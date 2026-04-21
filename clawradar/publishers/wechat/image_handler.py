"""Image and chart handling policy for WeChat article generation."""

from __future__ import annotations

import base64
import mimetypes
import tempfile
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup, Tag

from .chart_payload_renderer import extract_chart_payload, render_chart_container_to_png


IMAGE_MODES = {"drop", "placeholder", "fallback_table", "upload"}
CHART_CONTAINER_CLASS_MARKERS = {
    "chart-card",
    "chart-container",
    "chart-fallback",
    "trend-chart",
    "plot-wrapper",
}


def resolve_image_mode(raw_value: Any, *, default: str = "fallback_table") -> str:
    mode = str(raw_value or "").strip().lower()
    if not mode:
        return default
    aliases = {
        "fallback": "fallback_table",
        "table": "fallback_table",
        "keep_table": "fallback_table",
        "keep": "placeholder",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in IMAGE_MODES else default


def describe_image_policy(mode: str = "fallback_table") -> str:
    mode = resolve_image_mode(mode)
    if mode == "upload":
        return "upload_inline_images_and_render_chart_images"
    if mode == "placeholder":
        return "render_text_placeholders_for_images_and_charts"
    if mode == "drop":
        return "drop_report_images_and_charts"
    return "drop_chart_containers_without_table_fallback_and_drop_inline_images"


def _node_classes(node: Tag) -> set[str]:
    attrs = getattr(node, "attrs", None) or {}
    classes = attrs.get("class") or []
    if isinstance(classes, str):
        return {classes}
    return {str(value) for value in classes}


def _node_text(node: Tag) -> str:
    return " ".join(node.stripped_strings)


def _root_soup(node: Tag) -> Optional[BeautifulSoup]:
    current = node
    while getattr(current, "parent", None) is not None:
        current = current.parent
    return current if isinstance(current, BeautifulSoup) else None


def media_caption(node: Tag) -> str:
    attrs = getattr(node, "attrs", None) or {}
    for key in ("alt", "title", "aria-label", "data-caption"):
        value = str(attrs.get(key) or "").strip()
        if value:
            return value
    return _node_text(node).strip()

def chart_caption(node: Tag) -> str:
    payload = extract_chart_payload(node)
    if isinstance(payload, dict):
        for source in (payload.get("props"), payload):
            if not isinstance(source, dict):
                continue
            options = source.get("options") if isinstance(source.get("options"), dict) else {}
            plugins = options.get("plugins") if isinstance(options.get("plugins"), dict) else {}
            title = plugins.get("title") if isinstance(plugins.get("title"), dict) else {}
            title_text = str(title.get("text") or source.get("title") or "").strip()
            if title_text:
                return title_text
    return media_caption(node)



def is_chart_container(node: Tag) -> bool:
    if not isinstance(node, Tag):
        return False
    node_name = str(getattr(node, "name", "") or "").lower()
    if node_name not in {"div", "section", "figure"}:
        return False
    class_names = {value.lower() for value in _node_classes(node)}
    if any(marker in class_names for marker in CHART_CONTAINER_CLASS_MARKERS):
        return True

    attrs = getattr(node, "attrs", None) or {}
    return bool(str(attrs.get("data-chart") or "").strip())


def _has_chart_container_ancestor(node: Tag, root: Tag) -> bool:
    for parent in node.parents:
        if parent is root:
            return False
        if is_chart_container(parent):
            return True
    return False


def is_inline_image(node: Tag) -> bool:
    return isinstance(node, Tag) and str(getattr(node, "name", "") or "").lower() == "img"


def is_visual_tag(node: Tag) -> bool:
    node_name = str(getattr(node, "name", "") or "").lower()
    return node_name in {"img", "canvas", "svg", "iframe"}


def should_drop_image_like_node(node: Tag, *, image_mode: str = "fallback_table") -> bool:
    mode = resolve_image_mode(image_mode)
    if not isinstance(node, Tag):
        return False
    if is_chart_container(node):
        return False
    if not is_visual_tag(node):
        return False
    return mode in {"drop", "fallback_table"}


def _placeholder_node(soup: BeautifulSoup, kind: str, caption: str = "") -> Tag:
    node = soup.new_tag("p")
    node["class"] = ["wechat-media-placeholder"]
    node["style"] = (
        "margin:12px 0;padding:10px 12px;border-left:3px solid #c8c8c8;"
        "background:#f7f7f7;color:#666;font-size:14px;line-height:1.6;"
    )
    body = kind
    if caption:
        body = f"{body}: {caption}"
    node.string = f"[{body}]"
    return node


def _caption_label_node(soup: BeautifulSoup, caption: str) -> Tag:
    node = soup.new_tag("p")
    node["style"] = "margin:12px 0 6px;color:#666;font-size:14px;line-height:1.6;"
    node.string = f"Chart data: {caption}"
    return node


def _sanitize_uploaded_img(node: Tag, image_url: str, original_caption: str = "") -> None:
    node.attrs.clear()
    node["src"] = image_url
    if original_caption:
        node["alt"] = original_caption
    node["style"] = "max-width:100%;height:auto;display:block;margin:10px auto;"


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    header, _, payload = data_url.partition(",")
    mime = "image/png"
    if ";" in header:
        mime = header[5:header.find(";")]
    elif header.startswith("data:"):
        mime = header[5:]
    return base64.b64decode(payload), mime


def _resolve_local_source(src: str, base_dir: Optional[Path]) -> Optional[Path]:
    candidate = Path(src)
    if candidate.exists():
        return candidate.resolve()
    if base_dir is not None:
        relative_candidate = (base_dir / candidate).resolve()
        if relative_candidate.exists():
            return relative_candidate
    return None


def _materialize_image_source(source: str, *, base_dir: Optional[Path]) -> Optional[Path]:
    source = str(source or "").strip()
    if not source:
        return None

    if source.startswith("data:image/"):
        data, mime = _decode_data_url(source)
        suffix = mimetypes.guess_extension(mime) or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.close()
            return Path(tmp.name)
        except Exception:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            return None

    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source, timeout=30)
        response.raise_for_status()
        suffix = mimetypes.guess_extension(response.headers.get("content-type", "")) or ".png"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(response.content)
            tmp.close()
            return Path(tmp.name)
        except Exception:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            return None

    return _resolve_local_source(source, base_dir)


def upload_wechat_article_image(publisher: Any, source: str, *, base_dir: Optional[Path] = None) -> Optional[str]:
    image_path = _materialize_image_source(source, base_dir=base_dir)
    if image_path is None or not image_path.exists():
        return None

    temp_root = Path(tempfile.gettempdir()).resolve()
    should_cleanup = temp_root in image_path.resolve().parents

    try:
        if image_path.stat().st_size > 1 * 1024 * 1024:
            return None
        suffix = image_path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            return None

        access_token = getattr(publisher, "access_token", None) or getattr(publisher, "get_access_token", lambda: None)()
        if not access_token:
            return None

        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"
        with image_path.open("rb") as handle:
            response = requests.post(url, files={"media": handle}, timeout=30)
        data = response.json()
        if data.get("errcode") in (None, 0) and data.get("url"):
            return str(data["url"]).strip()
        return None
    finally:
        if should_cleanup:
            image_path.unlink(missing_ok=True)


def _replace_chart_container(
    node: Tag,
    *,
    mode: str,
    publisher: Any = None,
    base_dir: Optional[Path] = None,
) -> None:
    soup = node if isinstance(node, BeautifulSoup) else _root_soup(node)
    if soup is None:
        node.decompose()
        return

    caption = chart_caption(node)
    if mode == "upload" and publisher is not None:
        chart_image = render_chart_container_to_png(node)
        if chart_image is not None:
            image_url = upload_wechat_article_image(publisher, str(chart_image), base_dir=base_dir)
            if image_url:
                figure = soup.new_tag("figure")
                figure["style"] = "margin:16px 0;text-align:center;"
                img = soup.new_tag("img")
                img["src"] = image_url
                img["style"] = "max-width:100%;height:auto;display:block;margin:0 auto;"
                if caption:
                    img["alt"] = caption
                figure.append(img)
                if caption:
                    figcaption = soup.new_tag("figcaption")
                    figcaption["style"] = "font-size:14px;line-height:1.6;color:#666;margin-top:8px;"
                    figcaption.string = caption
                    figure.append(figcaption)
                node.replace_with(figure)
                return

    if mode == "placeholder":
        node.replace_with(_placeholder_node(soup, "Chart omitted", caption))
    else:
        node.decompose()


def prepare_report_visual_media(
    article_html: str,
    *,
    image_mode: str = "fallback_table",
    publisher: Any = None,
    base_dir: Optional[Path] = None,
) -> str:
    if not article_html:
        return ""

    mode = resolve_image_mode(image_mode)
    soup = BeautifulSoup(article_html, "html.parser")
    root = soup.find("main") or soup.find("article") or soup

    for container in list(root.find_all(True)):
        if is_chart_container(container) and not _has_chart_container_ancestor(container, root):
            _replace_chart_container(
                container,
                mode=mode,
                publisher=publisher,
                base_dir=base_dir,
            )

    for node in list(root.find_all(True)):
        node_name = str(getattr(node, "name", "") or "").lower()
        if node_name in {"canvas", "svg", "iframe"}:
            caption = chart_caption(node)
            if mode == "placeholder":
                node.replace_with(_placeholder_node(soup, "Chart omitted", caption))
            else:
                node.decompose()
            continue

        if not is_inline_image(node):
            continue

        src = str(node.get("src") or "").strip()
        if not src:
            node.decompose()
            continue

        caption = chart_caption(node)
        if mode == "upload" and publisher is not None:
            image_url = upload_wechat_article_image(publisher, src, base_dir=base_dir)
            if image_url:
                _sanitize_uploaded_img(node, image_url, caption)
                continue

        if mode == "placeholder":
            node.replace_with(_placeholder_node(soup, "Image omitted", caption))
        else:
            node.decompose()

    return str(soup)
