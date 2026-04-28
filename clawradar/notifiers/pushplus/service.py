"""PushPlus 通知适配器。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from dotenv import dotenv_values

PUSHPLUS_API_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TIMEOUT_SECONDS = 30
PUSHPLUS_DIR = Path(__file__).resolve().parent
PUSHPLUS_ENV_FILE = PUSHPLUS_DIR / ".env"


class PushPlusNotificationError(RuntimeError):
    """PushPlus 调用失败。"""


def _load_pushplus_token_from_env_file() -> str:
    if not PUSHPLUS_ENV_FILE.exists():
        return ""
    values = dotenv_values(PUSHPLUS_ENV_FILE)
    return str(values.get("PUSHPLUS_TOKEN") or values.get("pushplus_token") or "").strip()


def _resolve_pushplus_token(options: Dict[str, Any]) -> str:
    nested = options.get("pushplus") if isinstance(options.get("pushplus"), dict) else {}
    env_token = _load_pushplus_token_from_env_file()
    for field in ("token", "access_key", "access-key"):
        value = str(nested.get(field) or options.get(field) or "").strip()
        if value:
            return value
    if env_token:
        return env_token
    raise PushPlusNotificationError("pushplus token is required")


def _parse_pushplus_target(notification_target: str) -> Dict[str, Optional[str]]:
    parsed = urlparse(str(notification_target or "").strip())
    if parsed.scheme != "pushplus":
        raise PushPlusNotificationError("notification_target must use pushplus:// scheme")

    host = (parsed.netloc or "").strip().lower()
    path = (parsed.path or "").strip("/")
    result: Dict[str, Optional[str]] = {"channel": None, "topic": None}

    if host in {"", "default"}:
        return result
    if host == "channel" and path:
        result["channel"] = path
        return result
    if host == "topic" and path:
        result["topic"] = path
        return result
    if host == "user" and path:
        result["topic"] = path
        return result
    raise PushPlusNotificationError(f"unsupported pushplus target: {notification_target}")


def _resolve_pushplus_channel(options: Dict[str, Any], target_info: Dict[str, Optional[str]]) -> Optional[str]:
    nested = options.get("pushplus") if isinstance(options.get("pushplus"), dict) else {}
    value = str(target_info.get("channel") or nested.get("channel") or options.get("channel") or "").strip()
    return value or None


def _resolve_pushplus_topic(options: Dict[str, Any], target_info: Dict[str, Optional[str]]) -> Optional[str]:
    nested = options.get("pushplus") if isinstance(options.get("pushplus"), dict) else {}
    value = str(target_info.get("topic") or nested.get("topic") or options.get("topic") or "").strip()
    return value or None


def _resolve_pushplus_template(options: Dict[str, Any]) -> str:
    nested = options.get("pushplus") if isinstance(options.get("pushplus"), dict) else {}
    value = str(nested.get("template") or options.get("template") or "markdown").strip().lower()
    return value or "markdown"


def send_pushplus_notification(
    payload: Dict[str, Any],
    *,
    notification_target: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    from ...notifications import build_notification_summary

    resolved_options = deepcopy(options) if isinstance(options, dict) else {}
    token = _resolve_pushplus_token(resolved_options)
    target_info = _parse_pushplus_target(notification_target)
    summary = build_notification_summary(payload, notification_target=notification_target)
    template = _resolve_pushplus_template(resolved_options)
    channel = _resolve_pushplus_channel(resolved_options, target_info)
    topic = _resolve_pushplus_topic(resolved_options, target_info)

    request_body: Dict[str, Any] = {
        "token": token,
        "title": str(summary.get("title") or "").strip(),
        "content": str(summary.get("body_markdown") or "").strip(),
        "template": template,
    }
    if channel:
        request_body["channel"] = channel
    if topic:
        request_body["topic"] = topic

    response = requests.post(PUSHPLUS_API_URL, json=request_body, timeout=PUSHPLUS_TIMEOUT_SECONDS)
    response.raise_for_status()
    response_payload = response.json()
    response_code = response_payload.get("code")
    if response_code not in {0, 200, "0", "200"}:
        raise PushPlusNotificationError(str(response_payload.get("msg") or "pushplus send failed"))

    metadata = summary.get("metadata") if isinstance(summary.get("metadata"), dict) else {}
    return {
        "channel": "pushplus",
        "template_id": "clawradar_pushplus_summary_v1",
        "msg_type": template,
        "title": summary.get("title"),
        "body_markdown": summary.get("body_markdown"),
        "metadata": {
            **deepcopy(metadata),
            "notification_target": notification_target,
            "pushplus_channel": channel,
            "pushplus_topic": topic,
            "provider": "pushplus",
            "provider_code": response_payload.get("code"),
            "provider_msg": response_payload.get("msg"),
            "provider_data": response_payload.get("data"),
        },
    }
