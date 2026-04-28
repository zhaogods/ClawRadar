"""ClawRadar 通知能力入口，负责运行结果与发布结果的通用通知。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = WORKSPACE_ROOT / "outputs"


class NotificationChannel(str, Enum):
    """通知渠道。"""

    PUSHPLUS = "pushplus"


class NotificationRunStatus(str, Enum):
    """通知阶段执行状态。"""

    COMPLETED = "completed"
    NOTIFICATION_FAILED = "notification_failed"
    SKIPPED = "skipped"


class NotificationReason(str, Enum):
    """通知触发原因。"""

    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    PUBLISH_SUCCEEDED = "publish_succeeded"
    PUBLISH_FAILED = "publish_failed"


class NotificationErrorCode(str, Enum):
    """通知阶段错误码。"""

    INVALID_INPUT = "invalid_input"
    NOTIFICATION_TARGET_REQUIRED = "notification_target_required"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    NOTIFICATION_CHANNEL_UNAVAILABLE = "notification_channel_unavailable"
    ARCHIVE_WRITE_FAILED = "archive_write_failed"


class NotificationValidationError(ValueError):
    """通知输入校验失败。"""

    def __init__(self, *, code: NotificationErrorCode, missing_fields: List[str], message: str):
        super().__init__(message)
        self.code = code
        self.missing_fields = missing_fields
        self.message = message

    def to_error_response(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "missing_fields": list(self.missing_fields),
        }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative_path(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on", "enabled"}:
        return True
    if normalized in {"false", "0", "no", "off", "disabled"}:
        return False
    return default


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _extract_entry_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    notification = entry_options.get("notification") if isinstance(entry_options.get("notification"), dict) else {}
    return deepcopy(notification)


def _sanitize_notification_entry_options(entry_options: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(entry_options)
    notification_options = sanitized.get("notification") if isinstance(sanitized.get("notification"), dict) else None
    if notification_options is None:
        return sanitized
    pushplus_options = notification_options.get("pushplus") if isinstance(notification_options.get("pushplus"), dict) else None
    if pushplus_options is not None:
        for field in ("token", "access_key", "access-key"):
            pushplus_options.pop(field, None)
    return sanitized


def _sanitize_notification_options(notification_options: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(notification_options)
    pushplus_options = sanitized.get("pushplus") if isinstance(sanitized.get("pushplus"), dict) else None
    if pushplus_options is not None:
        for field in ("token", "access_key", "access-key"):
            pushplus_options.pop(field, None)
    for field in ("token", "access_key", "access-key"):
        sanitized.pop(field, None)
    return sanitized


def _resolve_notification_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    notification_entry = _extract_entry_notification(payload)
    channel = str(notification_entry.get("channel") or payload.get("notification_channel") or "").strip().lower()
    target = str(notification_entry.get("target") or payload.get("notification_target") or "").strip()
    enabled_default = bool(notification_entry) or bool(channel) or bool(target) or isinstance(payload.get("notification_options"), dict)
    enabled = _coerce_bool(notification_entry.get("enabled"), default=enabled_default)
    notify_on = _normalize_string_list(notification_entry.get("notify_on") or payload.get("notify_on") or [])
    notification_options = deepcopy(notification_entry)
    notification_options.pop("enabled", None)
    notification_options.pop("channel", None)
    notification_options.pop("target", None)
    notification_options.pop("notify_on", None)
    if isinstance(payload.get("notification_options"), dict):
        notification_options = {
            **deepcopy(payload.get("notification_options") or {}),
            **notification_options,
        }
    return {
        "enabled": enabled and bool(channel),
        "channel": channel,
        "target": target,
        "notify_on": notify_on,
        "notification_options": notification_options,
    }


def build_notification_payload(
    result: Dict[str, Any],
    *,
    channel: Optional[str] = None,
    target: Optional[str] = None,
    notify_on: Optional[Sequence[str]] = None,
    notification_options: Optional[Dict[str, Any]] = None,
    reason_override: Optional[str] = None,
) -> Dict[str, Any]:
    config = _resolve_notification_config(result)
    resolved_channel = str(channel or config.get("channel") or "").strip().lower()
    resolved_target = str(target or config.get("target") or "").strip()
    resolved_notify_on = list(notify_on) if notify_on is not None else list(config.get("notify_on") or [])
    resolved_options = deepcopy(notification_options) if isinstance(notification_options, dict) else deepcopy(config.get("notification_options") or {})

    payload = deepcopy(result)
    payload["notification_channel"] = resolved_channel
    payload["notification_target"] = resolved_target
    payload["notify_on"] = resolved_notify_on
    payload["notification_options"] = resolved_options
    payload["notification_reason"] = reason_override or _determine_notification_reason(payload)
    if isinstance(payload.get("entry_options"), dict):
        payload["entry_options"] = _sanitize_notification_entry_options(payload["entry_options"])
    return payload


def _determine_notification_reason(payload: Dict[str, Any]) -> str:
    run_status = str(payload.get("run_status") or "").strip().lower()
    delivery_receipt = payload.get("delivery_receipt") if isinstance(payload.get("delivery_receipt"), dict) else {}
    event_receipts = delivery_receipt.get("events") if isinstance(delivery_receipt.get("events"), list) else []
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []

    if event_receipts:
        if errors or any(isinstance(item, dict) and item.get("status") == "failed" for item in event_receipts):
            return NotificationReason.PUBLISH_FAILED.value
        return NotificationReason.PUBLISH_SUCCEEDED.value
    if run_status == NotificationRunStatus.COMPLETED.value:
        return NotificationReason.RUN_COMPLETED.value
    return NotificationReason.RUN_FAILED.value


def _should_send_notification(payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    config = _resolve_notification_config(payload)
    if not config["enabled"]:
        return False, "notification not configured"
    reason = str(payload.get("notification_reason") or _determine_notification_reason(payload)).strip().lower()
    notify_on = [item.strip().lower() for item in (payload.get("notify_on") or config["notify_on"]) if str(item).strip()]
    if notify_on and reason not in notify_on:
        return False, f"reason {reason} not enabled"
    return True, None


def _resolve_notification_channel(payload: Dict[str, Any], channel: Optional[str]) -> str:
    resolved = str(channel or payload.get("notification_channel") or "").strip().lower()
    allowed = {item.value for item in NotificationChannel}
    if resolved not in allowed:
        raise NotificationValidationError(
            code=NotificationErrorCode.UNSUPPORTED_CHANNEL,
            missing_fields=[],
            message="notify currently supports pushplus only",
        )
    return resolved


def _resolve_notification_target(payload: Dict[str, Any], target: Optional[str]) -> str:
    resolved = str(target or payload.get("notification_target") or "").strip()
    if not resolved:
        raise NotificationValidationError(
            code=NotificationErrorCode.NOTIFICATION_TARGET_REQUIRED,
            missing_fields=["notification_target"],
            message="notify requires explicit notification_target",
        )
    return resolved


def _collect_notification_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    delivery_receipt = payload.get("delivery_receipt") if isinstance(payload.get("delivery_receipt"), dict) else {}
    events = delivery_receipt.get("events") if isinstance(delivery_receipt.get("events"), list) else []
    delivered_count = sum(1 for item in events if isinstance(item, dict) and item.get("status") == "delivered")
    failed_count = sum(1 for item in events if isinstance(item, dict) and item.get("status") == "failed")
    first_failure = None
    for item in events:
        if isinstance(item, dict) and isinstance(item.get("failure_info"), dict):
            first_failure = item["failure_info"]
            break
    if first_failure is None:
        errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
        if errors and isinstance(errors[0], dict):
            first_failure = errors[0]
    return {
        "event_count": len(events),
        "delivered_count": delivered_count,
        "failed_count": failed_count,
        "first_failure": deepcopy(first_failure) if isinstance(first_failure, dict) else None,
    }


def build_notification_summary(payload: Dict[str, Any], *, notification_target: str) -> Dict[str, Any]:
    stats = _collect_notification_stats(payload)
    request_id = str(payload.get("request_id") or "").strip()
    final_stage = str(payload.get("final_stage") or "").strip()
    run_status = str(payload.get("run_status") or "").strip()
    decision_status = str(payload.get("decision_status") or "").strip()
    reason = str(payload.get("notification_reason") or _determine_notification_reason(payload)).strip()
    delivery_receipt = payload.get("delivery_receipt") if isinstance(payload.get("delivery_receipt"), dict) else {}
    delivery_channel = str(delivery_receipt.get("delivery_channel") or payload.get("delivery_channel") or "").strip()
    delivery_target = str(delivery_receipt.get("delivery_target") or payload.get("delivery_target") or "").strip()
    output_root = str(payload.get("output_root") or "").strip()

    title_map = {
        NotificationReason.RUN_COMPLETED.value: "ClawRadar 通知｜任务完成",
        NotificationReason.RUN_FAILED.value: "ClawRadar 通知｜任务失败",
        NotificationReason.PUBLISH_SUCCEEDED.value: "ClawRadar 通知｜发布成功",
        NotificationReason.PUBLISH_FAILED.value: "ClawRadar 通知｜发布失败",
    }
    title = title_map.get(reason, "ClawRadar 通知｜运行状态")

    lines = [
        f"**请求 ID**：{request_id or '-'}",
        f"**通知原因**：{reason or '-'}",
        f"**运行状态**：{run_status or '-'}",
        f"**最终阶段**：{final_stage or '-'}",
        f"**决策状态**：{decision_status or '-'}",
        f"**发布渠道**：{delivery_channel or '-'}",
        f"**发布目标**：{delivery_target or '-'}",
        f"**通知目标**：{notification_target}",
        f"**交付事件数**：{stats['event_count']}",
        f"**成功交付数**：{stats['delivered_count']}",
        f"**失败交付数**：{stats['failed_count']}",
        f"**输出目录**：{output_root or '-'}",
    ]
    first_failure = stats.get("first_failure")
    if isinstance(first_failure, dict):
        lines.append(f"**首个错误**：{str(first_failure.get('message') or first_failure.get('code') or '').strip() or '-'}")

    return {
        "title": title,
        "body_markdown": "\n".join(lines),
        "metadata": {
            "request_id": request_id,
            "notification_reason": reason,
            "run_status": run_status,
            "final_stage": final_stage,
            "decision_status": decision_status,
            "delivery_channel": delivery_channel or None,
            "delivery_target": delivery_target or None,
            "notification_target": notification_target,
            "event_count": stats["event_count"],
            "delivered_count": stats["delivered_count"],
            "failed_count": stats["failed_count"],
        },
    }


def _sanitize_notification_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(payload)
    if isinstance(sanitized.get("entry_options"), dict):
        sanitized["entry_options"] = _sanitize_notification_entry_options(sanitized["entry_options"])
    if isinstance(sanitized.get("notification_options"), dict):
        sanitized["notification_options"] = _sanitize_notification_options(sanitized["notification_options"])
    return sanitized


def sanitize_notification_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _sanitize_notification_payload(payload)


def _archive_notification_workspace(
    payload: Dict[str, Any],
    message: Dict[str, Any],
    *,
    notification_channel: str,
    notification_target: str,
    runs_root: Optional[Path] = None,
) -> Dict[str, str]:
    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    output_root = Path(output_context.get("output_root")) if output_context.get("output_root") else None
    resolved_runs_root = Path(runs_root or output_root or DEFAULT_RUNS_ROOT).resolve()
    if output_root is not None:
        notifications_root = output_root / "notifications"
    else:
        notifications_root = resolved_runs_root / "notifications"
    timestamp = _utc_timestamp().replace(":", "-")
    archive_dir = notifications_root / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    message_path = archive_dir / "notification_message.json"
    _write_json(message_path, message)
    payload_path = archive_dir / "payload_snapshot.json"
    _write_json(payload_path, _sanitize_notification_payload(payload))
    receipt_path = archive_dir / "notification_receipt.json"

    return {
        "archive_dir": archive_dir.as_posix(),
        "message_path": message_path.as_posix(),
        "payload_path": payload_path.as_posix(),
        "receipt_path": receipt_path.as_posix(),
        "notification_channel": notification_channel,
        "notification_target": notification_target,
    }



def _build_notification_receipt(
    *,
    payload: Dict[str, Any],
    notification_channel: str,
    notification_target: str,
    notification_reason: str,
    archive_paths: Dict[str, str],
    message: Dict[str, Any],
    run_status: str,
    failure_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    receipt = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "run_status": run_status,
        "notification_channel": notification_channel,
        "notification_target": notification_target,
        "notification_reason": notification_reason,
        "archive_path": _relative_path(Path(archive_paths["archive_dir"])) or archive_paths["archive_dir"],
        "message_path": _relative_path(Path(archive_paths["message_path"])) or archive_paths["message_path"],
        "receipt_path": _relative_path(Path(archive_paths["receipt_path"])) or archive_paths["receipt_path"],
        "title": str(message.get("title") or "").strip(),
        "failure_info": deepcopy(failure_info) if isinstance(failure_info, dict) else None,
        "metadata": deepcopy(message.get("metadata")) if isinstance(message.get("metadata"), dict) else None,
    }
    _write_json(Path(archive_paths["receipt_path"]), receipt)
    return receipt


def _send_notification_message(
    payload: Dict[str, Any],
    *,
    notification_channel: str,
    notification_target: str,
) -> Dict[str, Any]:
    if notification_channel == NotificationChannel.PUSHPLUS.value:
        from .notifiers.pushplus.service import send_pushplus_notification

        return send_pushplus_notification(
            payload,
            notification_target=notification_target,
            options=deepcopy(payload.get("notification_options") or {}),
        )
    raise NotificationValidationError(
        code=NotificationErrorCode.UNSUPPORTED_CHANNEL,
        missing_fields=[],
        message="notify currently supports pushplus only",
    )


def build_notification_rejection(
    payload: Optional[Dict[str, Any]] = None,
    *,
    error: Optional[NotificationValidationError] = None,
    skip_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    notification_reason = str(payload.get("notification_reason") or _determine_notification_reason(payload)).strip()
    receipt = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "run_status": NotificationRunStatus.SKIPPED.value if skip_reason else NotificationRunStatus.NOTIFICATION_FAILED.value,
        "notification_channel": str(payload.get("notification_channel") or "").strip(),
        "notification_target": str(payload.get("notification_target") or "").strip(),
        "notification_reason": notification_reason,
        "archive_path": None,
        "message_path": None,
        "receipt_path": None,
        "title": "",
        "failure_info": None if skip_reason else ({"code": error.code.value, "message": error.message} if error else None),
        "metadata": None,
    }
    return {
        "request_id": str(payload.get("request_id") or "").strip(),
        "run_status": receipt["run_status"],
        "notification_receipt": receipt,
        "errors": [] if skip_reason else [error.to_error_response()] if error else [],
        "skip_reason": skip_reason,
    }


def topic_radar_notify(
    payload: Dict[str, Any],
    *,
    channel: Optional[str] = None,
    target: Optional[str] = None,
    runs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    normalized_payload = deepcopy(payload)
    should_send, skip_reason = _should_send_notification(normalized_payload)
    if not should_send:
        return build_notification_rejection(normalized_payload, skip_reason=skip_reason or "notification skipped")

    try:
        notification_channel = _resolve_notification_channel(normalized_payload, channel)
        notification_target = _resolve_notification_target(normalized_payload, target)
    except NotificationValidationError as exc:
        return build_notification_rejection(normalized_payload, error=exc)

    notification_reason = str(normalized_payload.get("notification_reason") or _determine_notification_reason(normalized_payload)).strip()
    try:
        message = _send_notification_message(
            normalized_payload,
            notification_channel=notification_channel,
            notification_target=notification_target,
        )
        archive_paths = _archive_notification_workspace(
            normalized_payload,
            message,
            notification_channel=notification_channel,
            notification_target=notification_target,
            runs_root=runs_root,
        )
        receipt = _build_notification_receipt(
            payload=normalized_payload,
            notification_channel=notification_channel,
            notification_target=notification_target,
            notification_reason=notification_reason,
            archive_paths=archive_paths,
            message=message,
            run_status=NotificationRunStatus.COMPLETED.value,
        )
        return {
            "request_id": str(normalized_payload.get("request_id") or "").strip(),
            "run_status": NotificationRunStatus.COMPLETED.value,
            "notification_receipt": receipt,
            "errors": [],
            "skip_reason": None,
        }
    except OSError as exc:
        error = NotificationValidationError(
            code=NotificationErrorCode.ARCHIVE_WRITE_FAILED,
            missing_fields=[],
            message=str(exc),
        )
        return build_notification_rejection(normalized_payload, error=error)
    except Exception as exc:
        error = NotificationValidationError(
            code=NotificationErrorCode.NOTIFICATION_CHANNEL_UNAVAILABLE,
            missing_fields=[],
            message=str(exc),
        )
        return build_notification_rejection(normalized_payload, error=error)
