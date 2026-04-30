"""阶段四：ClawRadar 可调用交付能力。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .publishers.wechat.service import (
    WeChatOfficialAccountPublishError,
    build_wechat_delivery_message,
)
from .scoring import ScoreDecisionStatus
from .writing import MAX_WECHAT_DIGEST_TEXT_UNITS, MAX_WECHAT_DIGEST_UTF8_BYTES


class DeliveryRunStatus(str, Enum):
    """阶段四 deliver 执行状态。"""

    COMPLETED = "completed"
    DELIVERY_FAILED = "delivery_failed"
    SUCCEEDED = "completed"
    FAILED = "delivery_failed"


class DeliveryChannel(str, Enum):
    """阶段四交付渠道。"""

    FEISHU = "feishu"
    WECHAT = "wechat"
    WECHAT_OFFICIAL_ACCOUNT = "wechat_official_account"


class DeliveryErrorCode(str, Enum):
    """阶段四错误码。"""

    INVALID_INPUT = "invalid_input"
    DECISION_NOT_PUBLISH_READY = "decision_not_publish_ready"
    DELIVERY_TARGET_REQUIRED = "delivery_target_required"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    DELIVERY_CHANNEL_UNAVAILABLE = "delivery_channel_unavailable"
    ARCHIVE_WRITE_FAILED = "archive_write_failed"


DELIVERY_REQUIRED_FIELDS: Tuple[str, ...] = (
    "request_id",
    "trigger_source",
    "decision_status",
    "delivery_target",
)

CONTENT_BUNDLE_REQUIRED_FIELDS: Tuple[str, ...] = (
    "event_id",
    "content_status",
    "evidence_pack",
    "title",
    "draft",
    "summary",
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = WORKSPACE_ROOT / "outputs"


class DeliveryValidationError(ValueError):
    """deliver 输入校验失败。"""

    def __init__(self, *, code: DeliveryErrorCode, missing_fields: List[str], message: str):
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


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_string_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_content_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    normalized_bundle = deepcopy(bundle)
    evidence_pack = normalized_bundle.get("evidence_pack")
    if not isinstance(evidence_pack, dict) and isinstance(normalized_bundle.get("evidence_packet"), dict):
        evidence_pack = deepcopy(normalized_bundle["evidence_packet"])
    normalized_bundle["evidence_pack"] = deepcopy(evidence_pack) if isinstance(evidence_pack, dict) else {}
    normalized_bundle.pop("evidence_packet", None)
    return normalized_bundle


def _extract_content_bundles(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload.get("content_bundle"), dict):
        return [_normalize_content_bundle(payload["content_bundle"])]

    bundles = payload.get("content_bundles")
    if not isinstance(bundles, list):
        return []

    normalized_bundles: List[Dict[str, Any]] = []
    for bundle in bundles:
        if isinstance(bundle, dict):
            normalized_bundles.append(_normalize_content_bundle(bundle))
        else:
            normalized_bundles.append(bundle)
    return normalized_bundles


def _find_scored_event(payload: Dict[str, Any], event_id: str) -> Optional[Dict[str, Any]]:
    scored_events = payload.get("scored_events")
    if not isinstance(scored_events, list):
        return None

    for event in scored_events:
        if isinstance(event, dict) and str(event.get("event_id") or "").strip() == event_id:
            return deepcopy(event)
    return None


def _derive_timeline_from_evidence_pack(evidence_pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    timeline_support = evidence_pack.get("timeline_support")
    if not isinstance(timeline_support, list):
        return []
    return [deepcopy(item) for item in timeline_support if isinstance(item, dict)]


def _derive_evidence_pack_from_scored_event(scored_event: Dict[str, Any], *, event_title: str) -> Dict[str, Any]:
    source_support = []
    for fact in scored_event.get("fact_points", []):
        if not isinstance(fact, dict):
            continue
        source_support.append(
            {
                "fact_id": str(fact.get("fact_id") or "").strip(),
                "claim": str(fact.get("claim") or "").strip(),
                "source_url": str(fact.get("source_url") or "").strip(),
                "confidence": fact.get("confidence"),
                "citation_excerpt": str(fact.get("citation_excerpt") or "").strip(),
                "uncertainty": "待补充交叉验证"
                if fact.get("confidence") is not None and fact.get("confidence", 0) < 0.9
                else "",
            }
        )

    risk_notes = []
    for risk in scored_event.get("risk_flags", []):
        if not isinstance(risk, dict):
            continue
        risk_notes.append(
            {
                "code": str(risk.get("code") or "").strip(),
                "severity": str(risk.get("severity") or "").strip(),
                "message": str(risk.get("message") or "").strip(),
            }
        )

    uncertainty_markers = [
        str(item.get("uncertainty") or "").strip()
        for item in source_support
        if str(item.get("uncertainty") or "").strip()
    ]

    return {
        "core_claim": event_title,
        "source_support": source_support,
        "timeline_support": [
            deepcopy(item) for item in scored_event.get("timeline", []) if isinstance(item, dict)
        ],
        "risk_notes": risk_notes,
        "uncertainty_markers": uncertainty_markers
        or ["当前结论基于已收集证据，仍需持续跟踪新增来源。"],
    }


def _derive_normalized_event(
    payload: Dict[str, Any],
    *,
    content_bundle: Dict[str, Any],
    timeline: List[Dict[str, Any]],
    scored_event: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    trace = scored_event.get("trace", {}) if isinstance(scored_event, dict) else {}
    title_text = str(content_bundle.get("title", {}).get("text") or "").strip()
    event_title = str((scored_event or {}).get("event_title") or title_text or content_bundle.get("event_id") or "").strip()
    source_url = str(trace.get("source_url") or "").strip()
    if not source_url:
        for item in timeline:
            if isinstance(item, dict) and str(item.get("source_url") or "").strip():
                source_url = str(item.get("source_url") or "").strip()
                break
    event_time = ""
    if timeline:
        event_time = str(timeline[0].get("timestamp") or "").strip()

    return {
        "request_id": str(payload.get("request_id") or "").strip(),
        "event_id": str(content_bundle.get("event_id") or "").strip(),
        "event_title": event_title,
        "event_time": event_time,
        "source_url": source_url,
        "source_type": str(trace.get("source_type") or "unknown").strip() or "unknown",
        "company": str(trace.get("company") or "").strip(),
        "initial_tags": _to_string_list(trace.get("initial_tags")),
    }


def _build_protocol_event_payload(payload: Dict[str, Any], content_bundle: Dict[str, Any]) -> Dict[str, Any]:
    event_id = str(content_bundle.get("event_id") or "").strip()
    scored_event = _find_scored_event(payload, event_id)

    if isinstance(payload.get("evidence_pack"), dict):
        evidence_pack = deepcopy(payload["evidence_pack"])
    elif isinstance(content_bundle.get("evidence_pack"), dict):
        evidence_pack = deepcopy(content_bundle["evidence_pack"])
    elif isinstance(scored_event, dict):
        title_text = str(scored_event.get("event_title") or content_bundle.get("title", {}).get("text") or event_id).strip()
        evidence_pack = _derive_evidence_pack_from_scored_event(scored_event, event_title=title_text)
    else:
        evidence_pack = {}

    if isinstance(payload.get("timeline"), list):
        timeline = [deepcopy(item) for item in payload["timeline"] if isinstance(item, dict)]
    elif isinstance(scored_event, dict) and isinstance(scored_event.get("timeline"), list):
        timeline = [deepcopy(item) for item in scored_event["timeline"] if isinstance(item, dict)]
    else:
        timeline = _derive_timeline_from_evidence_pack(evidence_pack)

    if isinstance(payload.get("scorecard"), dict):
        scorecard = deepcopy(payload["scorecard"])
    elif isinstance(scored_event, dict) and isinstance(scored_event.get("scorecard"), dict):
        scorecard = deepcopy(scored_event["scorecard"])
    else:
        scorecard = {
            "dimensions": [],
            "total_score": None,
            "decision_status": str(payload.get("decision_status") or "").strip(),
        }

    if isinstance(payload.get("normalized_events"), list):
        normalized_events = [deepcopy(item) for item in payload["normalized_events"] if isinstance(item, dict)]
    else:
        normalized_events = [
            _derive_normalized_event(
                payload,
                content_bundle=content_bundle,
                timeline=timeline,
                scored_event=scored_event,
            )
        ]

    protocol_payload = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "event_id": event_id,
        "decision_status": str(payload.get("decision_status") or "").strip(),
        "normalized_events": normalized_events,
        "timeline": timeline,
        "evidence_pack": evidence_pack,
        "scorecard": scorecard,
        "content_bundle": deepcopy(content_bundle),
    }
    protocol_payload["content_bundle"]["evidence_pack"] = deepcopy(evidence_pack)

    # Preserve deep_crawl and search_enrichment from scored_event
    if isinstance(scored_event, dict):
        evidence_overview = scored_event.get("evidence_overview") or {}
        if isinstance(evidence_overview, dict) and evidence_overview.get("deep_crawl"):
            protocol_payload["deep_crawl"] = deepcopy(evidence_overview["deep_crawl"])
        trace = scored_event.get("trace") or {}
        if isinstance(trace, dict) and trace.get("search_enrichment"):
            protocol_payload["search_enrichment"] = deepcopy(trace["search_enrichment"])

    return protocol_payload


def _build_protocol_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    bundles = _extract_content_bundles(payload)
    primary_bundle = bundles[0] if bundles and isinstance(bundles[0], dict) else {}
    protocol_view = _build_protocol_event_payload(payload, primary_bundle) if primary_bundle else {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "event_id": "",
        "decision_status": str(payload.get("decision_status") or "").strip(),
        "normalized_events": [deepcopy(item) for item in payload.get("normalized_events", []) if isinstance(item, dict)]
        if isinstance(payload.get("normalized_events"), list)
        else [],
        "timeline": [deepcopy(item) for item in payload.get("timeline", []) if isinstance(item, dict)]
        if isinstance(payload.get("timeline"), list)
        else [],
        "evidence_pack": deepcopy(payload.get("evidence_pack")) if isinstance(payload.get("evidence_pack"), dict) else {},
        "scorecard": deepcopy(payload.get("scorecard")) if isinstance(payload.get("scorecard"), dict) else {},
        "content_bundle": {},
    }
    protocol_view["content_bundles"] = bundles
    return protocol_view


def _collect_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing_fields: List[str] = []
    for field in DELIVERY_REQUIRED_FIELDS:
        if field not in payload or _is_blank(payload.get(field)):
            missing_fields.append(field)

    content_bundles = _extract_content_bundles(payload)
    if not content_bundles:
        missing_fields.append("content_bundle")
        return missing_fields

    for index, bundle in enumerate(content_bundles):
        if not isinstance(bundle, dict):
            missing_fields.append(f"content_bundle[{index}]")
            continue
        for field in CONTENT_BUNDLE_REQUIRED_FIELDS:
            if field not in bundle or _is_blank(bundle.get(field)):
                missing_fields.append(f"content_bundle[{index}].{field}")
    return missing_fields


def validate_delivery_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """校验并返回阶段四 deliver 可消费载荷。"""

    missing_fields = _collect_missing_fields(payload)
    if missing_fields:
        if "delivery_target" in missing_fields:
            raise DeliveryValidationError(
                code=DeliveryErrorCode.DELIVERY_TARGET_REQUIRED,
                missing_fields=["delivery_target"],
                message="deliver requires explicit delivery_target",
            )
        raise DeliveryValidationError(
            code=DeliveryErrorCode.INVALID_INPUT,
            missing_fields=missing_fields,
            message="deliver payload missing required fields",
        )

    normalized_payload = _build_protocol_view(payload)
    normalized_payload["delivery_channel"] = str(
        payload.get("delivery_channel") or DeliveryChannel.FEISHU.value
    ).strip().lower()
    normalized_payload["delivery_target"] = str(payload.get("delivery_target") or "").strip()
    if "simulate_delivery_failure" in payload:
        normalized_payload["simulate_delivery_failure"] = payload.get("simulate_delivery_failure")
    if "delivery_time" in payload:
        normalized_payload["delivery_time"] = payload.get("delivery_time")
    if isinstance(payload.get("output_context"), dict):
        normalized_payload["output_context"] = deepcopy(payload["output_context"])
    _copy_delivery_passthrough_fields(payload, normalized_payload)
    return normalized_payload


def _resolve_delivery_channel(payload: Dict[str, Any], channel: Optional[str]) -> str:
    resolved = str(channel or payload.get("delivery_channel") or DeliveryChannel.FEISHU.value).strip().lower()
    allowed = {DeliveryChannel.FEISHU.value, DeliveryChannel.WECHAT.value, DeliveryChannel.WECHAT_OFFICIAL_ACCOUNT.value}
    if resolved not in allowed:
        raise DeliveryValidationError(
            code=DeliveryErrorCode.UNSUPPORTED_CHANNEL,
            missing_fields=[],
            message="deliver currently supports feishu and wechat only",
        )
    return resolved


def _resolve_delivery_target(payload: Dict[str, Any], target: Optional[str]) -> str:
    resolved = str(target or payload.get("delivery_target") or "").strip()
    if not resolved:
        raise DeliveryValidationError(
            code=DeliveryErrorCode.DELIVERY_TARGET_REQUIRED,
            missing_fields=["delivery_target"],
            message="deliver requires explicit delivery_target",
        )
    return resolved


def _resolve_delivery_time(payload: Dict[str, Any], delivery_time: Optional[str]) -> str:
    if isinstance(delivery_time, str) and delivery_time.strip():
        return delivery_time.strip()
    if isinstance(payload.get("delivery_time"), str) and str(payload["delivery_time"]).strip():
        return str(payload["delivery_time"]).strip()
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify_timestamp(delivery_time: str) -> str:
    return delivery_time.replace(":", "-").replace(".", "-")


def _relative_path(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    return path.resolve().as_posix()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize_delivery_entry_options(entry_options: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(entry_options)
    delivery_options = sanitized.get("delivery") if isinstance(sanitized.get("delivery"), dict) else None
    if delivery_options is None:
        return sanitized

    wechat_options = delivery_options.get("wechat") if isinstance(delivery_options.get("wechat"), dict) else None
    if wechat_options is not None:
        for field in (
            "appid",
            "app_id",
            "secret",
            "app_secret",
            "WECHAT_APPID",
            "WECHAT_APP_ID",
            "WECHAT_SECRET",
            "WECHAT_APP_SECRET",
        ):
            wechat_options.pop(field, None)
    return sanitized


def _sanitize_delivery_options(delivery_options: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = deepcopy(delivery_options)
    for field in (
        "appid",
        "app_id",
        "secret",
        "app_secret",
        "WECHAT_APPID",
        "WECHAT_APP_ID",
        "WECHAT_SECRET",
        "WECHAT_APP_SECRET",
    ):
        sanitized.pop(field, None)
    return sanitized


def _copy_delivery_passthrough_fields(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    for field in (
        "delivery_channel",
        "delivery_target",
        "delivery_time",
    ):
        if field in source and source.get(field) is not None:
            target[field] = deepcopy(source.get(field))
    if isinstance(source.get("entry_options"), dict):
        target["entry_options"] = _sanitize_delivery_entry_options(source["entry_options"])
    if isinstance(source.get("delivery_options"), dict):
        target["delivery_options"] = _sanitize_delivery_options(source["delivery_options"])


def build_feishu_delivery_message(payload: Dict[str, Any], content_bundle: Dict[str, Any], *, delivery_target: str) -> Dict[str, Any]:
    """构造阶段四飞书交付消息模板。"""

    normalized_bundle = _normalize_content_bundle(content_bundle)
    title_text = str(normalized_bundle.get("title", {}).get("text") or "未命名交付内容").strip()
    summary_text = str(normalized_bundle.get("summary", {}).get("text") or "").strip()
    draft_text = str(normalized_bundle.get("draft", {}).get("body_markdown") or "").strip()
    uncertainty_markers = list(
        normalized_bundle.get("draft", {}).get("uncertainty_markers")
        or normalized_bundle.get("summary", {}).get("uncertainty_markers")
        or normalized_bundle.get("evidence_pack", {}).get("uncertainty_markers")
        or []
    )
    uncertainty_text = uncertainty_markers[0] if uncertainty_markers else "当前交付仅代表已归档的结构化结果，需结合后续审核继续确认。"
    draft_preview = draft_text[:160] + ("..." if len(draft_text) > 160 else "")

    # Deep crawl coverage summary line
    deep_crawl_info = payload.get("deep_crawl") or content_bundle.get("evidence_pack", {}).get("deep_crawl_evidence")
    dc_line = ""
    if isinstance(deep_crawl_info, dict):
        platforms = deep_crawl_info.get("platforms", []) or []
        summary_info = deep_crawl_info.get("summary", {}) or {}
        total_notes = summary_info.get("total_notes", 0)
        if platforms or total_notes:
            dc_line = f"**深度爬取**：覆盖 {len(platforms)} 个平台，共 {total_notes} 条笔记"

    lines = [
        f"**请求 ID**：{str(payload.get('request_id') or '').strip()}",
        f"**事件 ID**：{str(normalized_bundle.get('event_id') or '').strip()}",
        f"**交付目标**：{delivery_target}",
        f"**阶段结论**：{str(payload.get('decision_status') or '').strip()}",
        f"**摘要**：{summary_text}",
        f"**稿件预览**：{draft_preview}",
        f"**不确定性提示**：{uncertainty_text}",
    ]
    if dc_line:
        lines.append(dc_line)
    body_markdown = "\n".join(lines)

    return {
        "channel": DeliveryChannel.FEISHU.value,
        "template_id": "clawradar_feishu_summary_v1",
        "msg_type": "post",
        "title": f"ClawRadar 交付｜{title_text}",
        "body_markdown": body_markdown,
        "metadata": {
            "request_id": str(payload.get("request_id") or "").strip(),
            "event_id": str(normalized_bundle.get("event_id") or "").strip(),
            "delivery_target": delivery_target,
        },
    }


def _message_filename_for_channel(delivery_channel: str) -> str:
    if delivery_channel in {DeliveryChannel.WECHAT.value, DeliveryChannel.WECHAT_OFFICIAL_ACCOUNT.value}:
        return "wechat_delivery_message.json"
    return "feishu_message.json"


def _build_delivery_message(payload: Dict[str, Any], content_bundle: Dict[str, Any], *, delivery_channel: str, delivery_target: str) -> Dict[str, Any]:
    if delivery_channel in {DeliveryChannel.WECHAT.value, DeliveryChannel.WECHAT_OFFICIAL_ACCOUNT.value}:
        return build_wechat_delivery_message(payload, content_bundle, delivery_target=delivery_target)
    return build_feishu_delivery_message(payload, content_bundle, delivery_target=delivery_target)



def _archive_root_from_output_context(output_context: Dict[str, Any]) -> Optional[str]:
    archive_root = output_context.get("recovery_root") or output_context.get("events_root")
    if archive_root is None:
        return None
    return str(archive_root)



def _merge_wechat_retry_details(
    previous_details: Optional[Dict[str, Any]],
    current_details: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(previous_details, dict) and not isinstance(current_details, dict):
        return None
    if not isinstance(previous_details, dict):
        return deepcopy(current_details) if isinstance(current_details, dict) else None
    if not isinstance(current_details, dict):
        return deepcopy(previous_details)
    merged = deepcopy(current_details)
    previous_attempts = previous_details.get("publish_attempts") if isinstance(previous_details.get("publish_attempts"), list) else []
    current_attempts = current_details.get("publish_attempts") if isinstance(current_details.get("publish_attempts"), list) else []
    if previous_attempts or current_attempts:
        merged["publish_attempts"] = [*deepcopy(previous_attempts), *deepcopy(current_attempts)]
    return merged


def _rewrite_message_metadata(message_path: Optional[str], metadata: Optional[Dict[str, Any]]) -> None:
    if not message_path or not isinstance(metadata, dict):
        return
    path = Path(message_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    payload["metadata"] = deepcopy(metadata)
    _write_json(path, payload)


def _archive_delivery_workspace(
    payload: Dict[str, Any],
    event_payload: Dict[str, Any],
    *,
    delivery_channel: str,
    delivery_target: str,
    delivery_time: str,
    runs_root: Path,
) -> Dict[str, Optional[str]]:
    event_id = str(event_payload.get("event_id") or "unknown-event").strip() or "unknown-event"
    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    archive_root = _archive_root_from_output_context(output_context)
    if archive_root:
        archive_dir = Path(archive_root) / event_id / "deliver" / _slugify_timestamp(delivery_time)
    else:
        archive_dir = runs_root / str(payload["request_id"]).strip() / event_id / "deliver" / _slugify_timestamp(delivery_time)
    archive_dir.mkdir(parents=True, exist_ok=True)

    scorecard_payload = {
        "request_id": str(event_payload.get("request_id") or "").strip(),
        "event_id": event_id,
        "decision_status": str(event_payload.get("decision_status") or "").strip(),
        "scorecard": deepcopy(event_payload.get("scorecard") or {}),
    }
    scorecard_path = archive_dir / "scorecard.json"
    _write_json(scorecard_path, scorecard_payload)

    payload_snapshot = {
        "request_id": str(event_payload.get("request_id") or "").strip(),
        "event_id": event_id,
        "trigger_source": str(event_payload.get("trigger_source") or "").strip(),
        "decision_status": str(event_payload.get("decision_status") or "").strip(),
        "normalized_events": deepcopy(event_payload.get("normalized_events") or []),
        "timeline": deepcopy(event_payload.get("timeline") or []),
        "evidence_pack": deepcopy(event_payload.get("evidence_pack") or {}),
        "scorecard": deepcopy(event_payload.get("scorecard") or {}),
        "content_bundle": deepcopy(event_payload.get("content_bundle") or {}),
        "delivery_request": {
            "delivery_time": delivery_time,
            "delivery_channel": delivery_channel,
            "delivery_target": delivery_target,
        },
        "scorecard_path": _relative_path(scorecard_path),
    }
    # Preserve deep_crawl and search_enrichment in archive
    if event_payload.get("deep_crawl"):
        payload_snapshot["deep_crawl"] = deepcopy(event_payload["deep_crawl"])
    if event_payload.get("search_enrichment"):
        payload_snapshot["search_enrichment"] = deepcopy(event_payload["search_enrichment"])
    _copy_delivery_passthrough_fields(payload, payload_snapshot)
    payload_path = archive_dir / "payload_snapshot.json"
    _write_json(payload_path, payload_snapshot)

    message_payload = _build_delivery_message(
        payload_snapshot,
        payload_snapshot["content_bundle"],
        delivery_channel=delivery_channel,
        delivery_target=delivery_target,
    )
    message_path = archive_dir / _message_filename_for_channel(delivery_channel)
    _write_json(message_path, message_payload)

    return {
        "archive_path": _relative_path(archive_dir),
        "scorecard_path": _relative_path(scorecard_path),
        "payload_path": _relative_path(payload_path),
        "message_path": _relative_path(message_path),
        "message_metadata": _message_metadata(archive_dir, message_path),
    }


def _message_metadata(archive_dir: Path, message_path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(message_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict):
        return None
    return deepcopy(metadata)


def build_archive_only_delivery_result(
    payload: Dict[str, Any],
    *,
    delivery_time: Optional[str],
    delivery_target: Optional[str],
    runs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """建立 archive_only 本地留档并返回可追溯回执。"""

    protocol_view = _build_protocol_view(payload)
    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    resolved_delivery_time = _resolve_delivery_time(payload, delivery_time)
    resolved_delivery_target = str(delivery_target or payload.get("delivery_target") or "archive://clawradar").strip()
    resolved_runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
    resolved_runs_root.mkdir(parents=True, exist_ok=True)

    event_receipts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for content_bundle in protocol_view["content_bundles"]:
        if not isinstance(content_bundle, dict):
            continue

        event_payload = _build_protocol_event_payload(payload, content_bundle)
        archive_paths: Dict[str, Optional[str]] = {
            "archive_path": None,
            "scorecard_path": None,
            "payload_path": None,
            "message_path": None,
            "message_metadata": None,
        }

        try:
            archive_paths = _archive_delivery_workspace(
                payload,
                event_payload,
                delivery_channel="archive_only",
                delivery_target=resolved_delivery_target,
                delivery_time=resolved_delivery_time,
                runs_root=resolved_runs_root,
            )
        except OSError as exc:
            event_receipts.append(
                _build_event_failure_receipt(
                    event_payload=event_payload,
                    delivery_time=resolved_delivery_time,
                    delivery_channel="archive_only",
                    archive_path=archive_paths["archive_path"],
                    scorecard_path=archive_paths["scorecard_path"],
                    payload_path=archive_paths["payload_path"],
                    message_path=archive_paths["message_path"],
                    message_metadata=archive_paths["message_metadata"],
                    failure_code=DeliveryErrorCode.ARCHIVE_WRITE_FAILED.value,
                    failure_message=str(exc),
                    delivery_target=resolved_delivery_target,
                )
            )
            errors.append(
                {
                    "code": DeliveryErrorCode.ARCHIVE_WRITE_FAILED.value,
                    "message": str(exc),
                    "missing_fields": [],
                }
            )
            continue

        event_receipts.append(
            {
                "request_id": str(event_payload.get("request_id") or "").strip(),
                "event_id": str(event_payload.get("event_id") or "").strip(),
                "decision_status": str(event_payload.get("decision_status") or "").strip(),
                "delivery_time": resolved_delivery_time,
                "delivery_channel": "archive_only",
                "delivery_target": resolved_delivery_target,
                "archive_path": archive_paths["archive_path"],
                "scorecard_path": archive_paths["scorecard_path"],
                "payload_path": archive_paths["payload_path"],
                "message_path": archive_paths["message_path"],
                "message_metadata": archive_paths["message_metadata"],
                "status": "archived",
                "failure_info": None,
            }
        )

    run_status = DeliveryRunStatus.COMPLETED.value if not errors else DeliveryRunStatus.DELIVERY_FAILED.value
    primary_view = _build_protocol_view(payload)
    return {
        "request_id": str(primary_view["request_id"]).strip(),
        "trigger_source": str(primary_view["trigger_source"]).strip(),
        "event_id": str(primary_view.get("event_id") or "").strip(),
        "run_status": run_status,
        "decision_status": str(primary_view["decision_status"]).strip(),
        "normalized_events": deepcopy(primary_view.get("normalized_events") or []),
        "timeline": deepcopy(primary_view.get("timeline") or []),
        "evidence_pack": deepcopy(primary_view.get("evidence_pack") or {}),
        "scorecard": deepcopy(primary_view.get("scorecard") or {}),
        "content_bundle": deepcopy(primary_view.get("content_bundle") or {}),
        "delivery_receipt": {
            "delivery_time": resolved_delivery_time,
            "delivery_channel": "archive_only",
            "delivery_target": resolved_delivery_target,
            "archive_root": str(_archive_root_from_output_context(output_context) or _relative_path(resolved_runs_root)),
            "failed_count": sum(1 for item in event_receipts if item["status"] == "failed"),
            "events": event_receipts,
        },
        "errors": errors,
    }


def _simulate_delivery(payload: Dict[str, Any], *, delivery_channel: str, delivery_target: str) -> None:
    del delivery_target
    if payload.get("simulate_delivery_failure"):
        raise RuntimeError("simulated delivery channel unavailable")
    allowed = {DeliveryChannel.FEISHU.value, DeliveryChannel.WECHAT.value, DeliveryChannel.WECHAT_OFFICIAL_ACCOUNT.value}
    if delivery_channel not in allowed:
        raise RuntimeError("unsupported delivery channel")


def _build_event_failure_receipt(
    *,
    event_payload: Dict[str, Any],
    delivery_time: str,
    delivery_channel: str,
    archive_path: Optional[str],
    scorecard_path: Optional[str],
    payload_path: Optional[str],
    message_path: Optional[str],
    failure_code: str,
    failure_message: str,
    delivery_target: Optional[str],
    failure_details: Optional[Dict[str, Any]] = None,
    message_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    failure_info = {
        "code": failure_code,
        "message": failure_message,
    }
    if isinstance(failure_details, dict) and failure_details:
        failure_info["details"] = deepcopy(failure_details)
    receipt_message_metadata = message_metadata
    if not isinstance(receipt_message_metadata, dict) and isinstance(failure_details, dict) and failure_details:
        receipt_message_metadata = failure_details
    return {
        "request_id": str(event_payload.get("request_id") or "").strip(),
        "event_id": str(event_payload.get("event_id") or "").strip(),
        "decision_status": str(event_payload.get("decision_status") or "").strip(),
        "delivery_time": delivery_time,
        "delivery_channel": delivery_channel,
        "delivery_target": delivery_target,
        "archive_path": archive_path,
        "scorecard_path": scorecard_path,
        "payload_path": payload_path,
        "message_path": message_path,
        "message_metadata": deepcopy(receipt_message_metadata) if isinstance(receipt_message_metadata, dict) else None,
        "status": "failed",
        "failure_info": failure_info,
    }


def _build_event_success_receipt(
    *,
    event_payload: Dict[str, Any],
    delivery_time: str,
    delivery_channel: str,
    delivery_target: str,
    archive_path: str,
    scorecard_path: str,
    payload_path: str,
    message_path: str,
    message_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "request_id": str(event_payload.get("request_id") or "").strip(),
        "event_id": str(event_payload.get("event_id") or "").strip(),
        "decision_status": str(event_payload.get("decision_status") or "").strip(),
        "delivery_time": delivery_time,
        "delivery_channel": delivery_channel,
        "delivery_target": delivery_target,
        "archive_path": archive_path,
        "scorecard_path": scorecard_path,
        "payload_path": payload_path,
        "message_path": message_path,
        "message_metadata": deepcopy(message_metadata) if isinstance(message_metadata, dict) else None,
        "status": "delivered",
        "failure_info": None,
    }


def topic_radar_deliver(
    payload: Dict[str, Any],
    *,
    channel: Optional[str] = None,
    target: Optional[str] = None,
    delivery_time: Optional[str] = None,
    runs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """执行阶段四交付，建立留档并生成交付回执。"""

    try:
        normalized_payload = validate_delivery_payload(payload)
    except DeliveryValidationError as exc:
        return build_delivery_rejection(payload, error=exc)

    if normalized_payload.get("decision_status") != ScoreDecisionStatus.PUBLISH_READY.value:
        return build_delivery_rejection(
            payload,
            error=DeliveryValidationError(
                code=DeliveryErrorCode.DECISION_NOT_PUBLISH_READY,
                missing_fields=[],
                message="deliver requires publish_ready content bundle",
            ),
        )

    resolved_channel = str(channel or normalized_payload.get("delivery_channel") or DeliveryChannel.FEISHU.value).strip().lower()
    output_context = normalized_payload.get("output_context") if isinstance(normalized_payload.get("output_context"), dict) else {}
    resolved_delivery_time = _resolve_delivery_time(normalized_payload, delivery_time)
    resolved_runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
    resolved_runs_root.mkdir(parents=True, exist_ok=True)

    event_receipts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for content_bundle in normalized_payload["content_bundles"]:
        working_bundle = deepcopy(content_bundle) if isinstance(content_bundle, dict) else content_bundle
        event_payload = _build_protocol_event_payload(normalized_payload, working_bundle)
        archive_paths: Dict[str, Optional[str]] = {
            "archive_path": None,
            "scorecard_path": None,
            "payload_path": None,
            "message_path": None,
            "message_metadata": None,
        }
        resolved_target = str(target or normalized_payload.get("delivery_target") or "").strip()
        retry_summary_feedback: Optional[Dict[str, Any]] = None
        retry_publish_details: Optional[Dict[str, Any]] = None

        for attempt in range(2):
            try:
                resolved_channel = _resolve_delivery_channel(normalized_payload, resolved_channel)
                resolved_target = _resolve_delivery_target(normalized_payload, resolved_target)
                attempt_payload = deepcopy(normalized_payload)
                attempt_payload["content_bundles"] = [working_bundle] if isinstance(working_bundle, dict) else [content_bundle]
                if retry_summary_feedback and isinstance(working_bundle, dict):
                    working_bundle = deepcopy(working_bundle)
                    working_bundle["summary_rewrite_feedback"] = deepcopy(retry_summary_feedback)
                    attempt_payload["content_bundles"] = [working_bundle]
                archive_paths = _archive_delivery_workspace(
                    attempt_payload,
                    event_payload,
                    delivery_channel=resolved_channel,
                    delivery_target=resolved_target,
                    delivery_time=resolved_delivery_time,
                    runs_root=resolved_runs_root,
                )
                _simulate_delivery(
                    attempt_payload,
                    delivery_channel=resolved_channel,
                    delivery_target=resolved_target,
                )
                success_message_metadata = archive_paths["message_metadata"]
                if retry_publish_details and isinstance(success_message_metadata, dict):
                    success_message_metadata = _merge_wechat_retry_details(retry_publish_details, success_message_metadata)
                    _rewrite_message_metadata(archive_paths["message_path"], success_message_metadata)
                    archive_paths["message_metadata"] = success_message_metadata
                event_receipts.append(
                    _build_event_success_receipt(
                        event_payload=event_payload,
                        delivery_time=resolved_delivery_time,
                        delivery_channel=resolved_channel,
                        delivery_target=resolved_target,
                        archive_path=str(archive_paths["archive_path"]),
                        scorecard_path=str(archive_paths["scorecard_path"]),
                        payload_path=str(archive_paths["payload_path"]),
                        message_path=str(archive_paths["message_path"]),
                        message_metadata=archive_paths["message_metadata"],
                    )
                )
                break
            except DeliveryValidationError as exc:
                event_receipts.append(
                    _build_event_failure_receipt(
                        event_payload=event_payload,
                        delivery_time=resolved_delivery_time,
                        delivery_channel=resolved_channel,
                        archive_path=archive_paths["archive_path"],
                        scorecard_path=archive_paths["scorecard_path"],
                        payload_path=archive_paths["payload_path"],
                        message_path=archive_paths["message_path"],
                        message_metadata=archive_paths["message_metadata"],
                        failure_code=exc.code.value,
                        failure_message=exc.message,
                        delivery_target=resolved_target or None,
                    )
                )
                errors.append(exc.to_error_response())
                break
            except OSError as exc:
                event_receipts.append(
                    _build_event_failure_receipt(
                        event_payload=event_payload,
                        delivery_time=resolved_delivery_time,
                        delivery_channel=resolved_channel,
                        archive_path=archive_paths["archive_path"],
                        scorecard_path=archive_paths["scorecard_path"],
                        payload_path=archive_paths["payload_path"],
                        message_path=archive_paths["message_path"],
                        message_metadata=archive_paths["message_metadata"],
                        failure_code=DeliveryErrorCode.ARCHIVE_WRITE_FAILED.value,
                        failure_message=str(exc),
                        delivery_target=resolved_target or None,
                    )
                )
                errors.append(
                    {
                        "code": DeliveryErrorCode.ARCHIVE_WRITE_FAILED.value,
                        "message": str(exc),
                        "missing_fields": [],
                    }
                )
                break
            except (RuntimeError, WeChatOfficialAccountPublishError) as exc:
                failure_details = exc.details if isinstance(exc, WeChatOfficialAccountPublishError) else None
                if (
                    attempt == 0
                    and resolved_channel in {DeliveryChannel.WECHAT.value, DeliveryChannel.WECHAT_OFFICIAL_ACCOUNT.value}
                    and isinstance(failure_details, dict)
                    and str(failure_details.get("errcode") or "").strip() == "45004"
                ):
                    retry_summary_feedback = {
                        "reason": "description size out of limit",
                        "requiredAction": "请直接重写一个更短且语义完整的微信公众号摘要，不要截断上一版摘要。",
                        "maxUtf8Bytes": MAX_WECHAT_DIGEST_UTF8_BYTES,
                        "maxTextUnits": MAX_WECHAT_DIGEST_TEXT_UNITS,
                        "maxChars": MAX_WECHAT_DIGEST_TEXT_UNITS,
                        "previousDigest": str(failure_details.get("attempted_digest") or failure_details.get("requested_digest") or "").strip(),
                    }
                    retry_publish_details = deepcopy(failure_details)
                    write_payload = deepcopy(payload)
                    write_payload["content_bundle"] = deepcopy(working_bundle)
                    write_payload["delivery_channel"] = resolved_channel
                    write_payload["delivery_target"] = resolved_target
                    write_payload["decision_status"] = normalized_payload.get("decision_status")
                    write_payload["request_id"] = normalized_payload.get("request_id")
                    write_payload["trigger_source"] = normalized_payload.get("trigger_source")
                    if isinstance(write_payload["content_bundle"], dict):
                        write_payload["content_bundle"]["summary_rewrite_feedback"] = deepcopy(retry_summary_feedback)
                        if not isinstance(write_payload["content_bundle"].get("evidence_packet"), dict) and isinstance(
                            write_payload["content_bundle"].get("evidence_pack"), dict
                        ):
                            write_payload["content_bundle"]["evidence_packet"] = deepcopy(
                                write_payload["content_bundle"]["evidence_pack"]
                            )
                    write_payload["summary_rewrite_feedback"] = deepcopy(retry_summary_feedback)
                    try:
                        from .writing import WriteOperation, topic_radar_write

                        write_result = topic_radar_write(
                            write_payload,
                            operation=WriteOperation.REGENERATE_SUMMARY.value,
                            executor="clawradar_builtin",
                        )
                        refreshed_bundles = write_result.get("content_bundles") if isinstance(write_result, dict) else []
                        if refreshed_bundles and isinstance(refreshed_bundles[0], dict):
                            working_bundle = refreshed_bundles[0]
                            event_payload = _build_protocol_event_payload(normalized_payload, working_bundle)
                            continue
                    except Exception as write_exc:
                        failure_details = {
                            **(failure_details or {}),
                            "summary_retry_error": str(write_exc),
                        }
                if retry_publish_details and isinstance(failure_details, dict):
                    failure_details = _merge_wechat_retry_details(retry_publish_details, failure_details)
                event_receipts.append(
                    _build_event_failure_receipt(
                        event_payload=event_payload,
                        delivery_time=resolved_delivery_time,
                        delivery_channel=resolved_channel,
                        archive_path=archive_paths["archive_path"],
                        scorecard_path=archive_paths["scorecard_path"],
                        payload_path=archive_paths["payload_path"],
                        message_path=archive_paths["message_path"],
                        message_metadata=archive_paths["message_metadata"],
                        failure_code=DeliveryErrorCode.DELIVERY_CHANNEL_UNAVAILABLE.value,
                        failure_message=str(exc),
                        delivery_target=resolved_target or None,
                        failure_details=failure_details,
                    )
                )
                errors.append(
                    {
                        "code": DeliveryErrorCode.DELIVERY_CHANNEL_UNAVAILABLE.value,
                        "message": str(exc),
                        "missing_fields": [],
                        "details": deepcopy(failure_details) if isinstance(failure_details, dict) and failure_details else None,
                    }
                )
                break
        else:
            continue

    run_status = DeliveryRunStatus.COMPLETED.value if not errors else DeliveryRunStatus.DELIVERY_FAILED.value
    primary_view = _build_protocol_view(normalized_payload)
    return {
        "request_id": str(primary_view["request_id"]).strip(),
        "trigger_source": str(primary_view["trigger_source"]).strip(),
        "event_id": str(primary_view.get("event_id") or "").strip(),
        "run_status": run_status,
        "decision_status": str(primary_view["decision_status"]).strip(),
        "normalized_events": deepcopy(primary_view.get("normalized_events") or []),
        "timeline": deepcopy(primary_view.get("timeline") or []),
        "evidence_pack": deepcopy(primary_view.get("evidence_pack") or {}),
        "scorecard": deepcopy(primary_view.get("scorecard") or {}),
        "content_bundle": deepcopy(primary_view.get("content_bundle") or {}),
        "delivery_receipt": {
            "delivery_time": resolved_delivery_time,
            "delivery_channel": resolved_channel,
            "delivery_target": normalized_payload.get("delivery_target"),
            "archive_root": str(_archive_root_from_output_context(output_context) or _relative_path(resolved_runs_root)),
            "failed_count": sum(1 for item in event_receipts if item["status"] == "failed"),
            "events": event_receipts,
        },
        "errors": errors,
    }


def build_delivery_rejection(
    payload: Optional[Dict[str, Any]] = None,
    *,
    error: Optional[DeliveryValidationError] = None,
) -> Dict[str, Any]:
    """返回阶段四 deliver 拒收结构。"""

    payload = payload or {}
    protocol_view = _build_protocol_view(payload)

    if error is None:
        try:
            validate_delivery_payload(payload)
        except DeliveryValidationError as exc:
            error = exc
        else:
            error = DeliveryValidationError(
                code=DeliveryErrorCode.INVALID_INPUT,
                missing_fields=[],
                message="deliver payload rejected",
            )

    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    resolved_delivery_time = _resolve_delivery_time(payload, None)
    resolved_delivery_channel = str(payload.get("delivery_channel") or DeliveryChannel.FEISHU.value).strip().lower()

    event_payload = {
        "request_id": protocol_view.get("request_id"),
        "event_id": protocol_view.get("event_id"),
        "decision_status": protocol_view.get("decision_status", ScoreDecisionStatus.NEED_MORE_EVIDENCE.value),
    }

    return {
        "request_id": protocol_view.get("request_id"),
        "trigger_source": protocol_view.get("trigger_source"),
        "event_id": protocol_view.get("event_id"),
        "run_status": DeliveryRunStatus.DELIVERY_FAILED.value,
        "decision_status": protocol_view.get("decision_status", ScoreDecisionStatus.NEED_MORE_EVIDENCE.value),
        "normalized_events": deepcopy(protocol_view.get("normalized_events") or []),
        "timeline": deepcopy(protocol_view.get("timeline") or []),
        "evidence_pack": deepcopy(protocol_view.get("evidence_pack") or {}),
        "scorecard": deepcopy(protocol_view.get("scorecard") or {}),
        "content_bundle": deepcopy(protocol_view.get("content_bundle") or {}),
        "delivery_receipt": {
            "delivery_time": resolved_delivery_time,
            "delivery_channel": resolved_delivery_channel,
            "delivery_target": payload.get("delivery_target"),
            "archive_root": str(_archive_root_from_output_context(output_context) or _relative_path(DEFAULT_RUNS_ROOT)),
            "failed_count": 1,
            "events": [
                _build_event_failure_receipt(
                    event_payload=event_payload,
                    delivery_time=resolved_delivery_time,
                    delivery_channel=resolved_delivery_channel,
                    archive_path=None,
                    scorecard_path=None,
                    payload_path=None,
                    message_path=None,
                    failure_code=error.code.value,
                    failure_message=error.message,
                    delivery_target=payload.get("delivery_target"),
                )
            ],
        },
        "errors": [error.to_error_response()],
    }
