"""WeChat Official Account publishing adapter."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import dotenv_values

from .image_handler import describe_image_policy, resolve_image_mode
from .markdown_converter import convert_markdown_to_wechat_html
from .report_html_cleaner import (
    build_wechat_article_from_report_html,
    html_fragment_to_text,
    looks_like_embedded_report_html,
)


class WeChatOfficialAccountPublishError(RuntimeError):
    """Raised when a draft cannot be created in WeChat Official Account."""


def _channel_dir() -> Path:
    return Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _channel_env() -> Dict[str, str]:
    env_path = _channel_dir() / ".env"
    if not env_path.exists():
        return {}
    loaded = dotenv_values(env_path)
    return {str(key): str(value) for key, value in loaded.items() if value is not None}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _load_wechat_publisher_class():
    module_path = _repo_root() / "third_party" / "wechat_publisher" / "publisher.py"
    if not module_path.exists():
        raise WeChatOfficialAccountPublishError(f"missing third_party publisher: {module_path}")

    spec = importlib.util.spec_from_file_location("clawradar_third_party_wechat_publisher", module_path)
    if spec is None or spec.loader is None:
        raise WeChatOfficialAccountPublishError(f"unable to load publisher module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    publisher_class = getattr(module, "WeChatPublisher", None)
    if publisher_class is None:
        raise WeChatOfficialAccountPublishError("third_party publisher missing WeChatPublisher")
    return publisher_class


def _first_non_blank(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _bool_option(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _option_value(options: Dict[str, Any], *keys: str) -> str:
    return _first_non_blank(*(options.get(key) for key in keys))


def _wechat_delivery_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    delivery_options = entry_options.get("delivery") if isinstance(entry_options.get("delivery"), dict) else {}
    wechat_options = delivery_options.get("wechat") if isinstance(delivery_options.get("wechat"), dict) else {}
    payload_options = payload.get("delivery_options") if isinstance(payload.get("delivery_options"), dict) else {}
    return {**_channel_env(), **wechat_options, **payload_options}


def _resolve_credentials(channel_env: Dict[str, Any]) -> tuple[str, str]:
    appid = _option_value(channel_env, "WECHAT_APPID", "WECHAT_APP_ID", "appid", "app_id")
    secret = _option_value(channel_env, "WECHAT_SECRET", "WECHAT_APP_SECRET", "secret", "app_secret")
    if not appid or not secret:
        raise WeChatOfficialAccountPublishError(
            "wechat credentials are required in clawradar/publishers/wechat/.env"
        )
    return appid, secret


def _resolve_author(payload: Dict[str, Any], options: Dict[str, Any]) -> str:
    return _first_non_blank(
        _option_value(options, "author", "WECHAT_AUTHOR", "wechat_author"),
        payload.get("author"),
        default="ClawRadar",
    )


def _resolve_cover_image_path(payload: Dict[str, Any], options: Dict[str, Any]) -> str:
    return _first_non_blank(
        _option_value(
            options,
            "cover_image_path",
            "WECHAT_COVER_IMAGE_PATH",
            "wechat_cover_image_path",
        ),
        payload.get("cover_image_path"),
    )


def _resolve_use_default_cover(options: Dict[str, Any]) -> bool:
    if any(key in options for key in ("use_default_cover", "WECHAT_USE_DEFAULT_COVER", "wechat_use_default_cover")):
        return _bool_option(
            _option_value(options, "use_default_cover", "WECHAT_USE_DEFAULT_COVER", "wechat_use_default_cover"),
            default=True,
        )
    if "no_cover" in options:
        return _bool_option(options.get("no_cover"), default=True)
    return True

def _resolve_report_image_mode(options: Dict[str, Any]) -> str:
    return resolve_image_mode(
        _option_value(
            options,
            "report_image_mode",
            "WECHAT_REPORT_IMAGE_MODE",
            "wechat_report_image_mode",
        ),
        default="fallback_table",
    )


def _resolve_report_path(content_bundle: Dict[str, Any]) -> Optional[Path]:
    for section_name in ("writer_receipt", "report_artifacts"):
        section = content_bundle.get(section_name) if isinstance(content_bundle.get(section_name), dict) else {}
        for field in ("report_filepath", "report_relative_path"):
            raw_path = str(section.get(field) or "").strip()
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (_repo_root() / candidate).resolve()
            if candidate.exists():
                return candidate
    return None


def _read_report_html(content_bundle: Dict[str, Any]) -> str:
    report_path = _resolve_report_path(content_bundle)
    if report_path is None:
        return ""
    return report_path.read_text(encoding="utf-8", errors="replace")


def _resolve_title_and_content(
    content_bundle: Dict[str, Any],
    *,
    publisher: Any = None,
    image_mode: str = "fallback_table",
) -> tuple[str, str, str, str]:
    title_text = str(content_bundle.get("title", {}).get("text") or "").strip()
    summary_text = str(content_bundle.get("summary", {}).get("text") or "").strip()
    draft_markdown = str(content_bundle.get("draft", {}).get("body_markdown") or "").strip()
    report_html = _read_report_html(content_bundle)
    report_base_dir = str(_resolve_report_path(content_bundle).parent) if _resolve_report_path(content_bundle) else None
    wechat_article_html = build_wechat_article_from_report_html(
        report_html,
        image_mode=image_mode,
        publisher=publisher,
        base_dir=report_base_dir,
    )
    if not title_text:
        title_text = str(content_bundle.get("event_id") or "Untitled").strip()
    if wechat_article_html:
        article_text = html_fragment_to_text(wechat_article_html)
        if not summary_text:
            summary_text = (article_text[:120] or title_text).strip()
        if not draft_markdown or looks_like_embedded_report_html(draft_markdown):
            draft_markdown = article_text or summary_text or title_text
        return title_text, summary_text, draft_markdown, wechat_article_html
    if not draft_markdown:
        draft_markdown = summary_text or title_text
    return title_text, summary_text, draft_markdown, ""


def build_wechat_delivery_message(
    payload: Dict[str, Any],
    content_bundle: Dict[str, Any],
    *,
    delivery_target: str,
) -> Dict[str, Any]:
    channel_env = _channel_env()
    options = _wechat_delivery_options(payload)
    appid, secret = _resolve_credentials(channel_env)
    author = _resolve_author(payload, options)
    cover_image_path = _resolve_cover_image_path(payload, options)
    use_default_cover = _resolve_use_default_cover(options)
    report_image_mode = _resolve_report_image_mode(options)
    publisher_class = _load_wechat_publisher_class()
    publisher = publisher_class(appid, secret)
    access_token = publisher.get_access_token()
    if not access_token:
        raise WeChatOfficialAccountPublishError("failed to obtain wechat access token")

    title_text, summary_text, draft_markdown, report_article_html = _resolve_title_and_content(
        content_bundle,
        publisher=publisher,
        image_mode=report_image_mode,
    )

    if report_article_html:
        html_content = report_article_html
    else:
        html_content = convert_markdown_to_wechat_html(draft_markdown, publisher)

    thumb_media_id: Optional[str] = None
    cover_source = "none"
    if cover_image_path and Path(cover_image_path).exists():
        thumb_media_id = publisher.upload_image(cover_image_path)
        cover_source = "custom"
    elif use_default_cover:
        thumb_media_id = publisher.upload_default_cover(title=title_text)
        cover_source = "default"

    if not thumb_media_id:
        raise WeChatOfficialAccountPublishError("wechat official account draft requires a cover image")

    digest = summary_text[:120]
    media_id = publisher.upload_draft(
        title=title_text,
        content=html_content,
        author=author,
        digest=digest,
        thumb_media_id=thumb_media_id,
    )
    if not media_id:
        raise WeChatOfficialAccountPublishError("wechat official account draft creation failed")

    return {
        "channel": "wechat",
        "template_id": "clawradar_wechat_draft_v1",
        "msg_type": "draft",
        "title": f"WeChat Draft: {title_text}",
        "body_markdown": draft_markdown,
        "body_html": html_content,
        "metadata": {
            "request_id": str(payload.get("request_id") or "").strip(),
            "event_id": str(content_bundle.get("event_id") or "").strip(),
            "delivery_target": delivery_target,
            "author": author,
            "media_id": media_id,
            "thumb_media_id": thumb_media_id,
            "cover_source": cover_source,
            "content_source": "report_html" if report_article_html else "draft_markdown",
            "report_image_policy": describe_image_policy(report_image_mode),
            "access_token_obtained": bool(access_token),
        },
        "draft": {
            "media_id": media_id,
            "status": "draft_created",
            "requires_manual_publish": True,
        },
    }


def build_wechat_official_account_delivery_message(
    payload: Dict[str, Any],
    content_bundle: Dict[str, Any],
    *,
    delivery_target: str,
) -> Dict[str, Any]:
    return build_wechat_delivery_message(payload, content_bundle, delivery_target=delivery_target)
