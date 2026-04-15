"""阶段四：OpenClaw 可调用交付能力。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .scoring import ScoreDecisionStatus


class DeliveryRunStatus(str, Enum):
    """阶段四 deliver 执行状态。"""

    COMPLETED = "completed"
    DELIVERY_FAILED = "delivery_failed"
    SUCCEEDED = "completed"
    FAILED = "delivery_failed"


class DeliveryChannel(str, Enum):
    """阶段四交付渠道。"""

    FEISHU = "feishu"


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
    return normalized_payload


def _resolve_delivery_channel(payload: Dict[str, Any], channel: Optional[str]) -> str:
    resolved = str(channel or payload.get("delivery_channel") or DeliveryChannel.FEISHU.value).strip().lower()
    if resolved != DeliveryChannel.FEISHU.value:
        raise DeliveryValidationError(
            code=DeliveryErrorCode.UNSUPPORTED_CHANNEL,
            missing_fields=[],
            message="deliver currently supports feishu only",
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
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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

    body_markdown = "\n".join(
        [
            f"**请求 ID**：{str(payload.get('request_id') or '').strip()}",
            f"**事件 ID**：{str(normalized_bundle.get('event_id') or '').strip()}",
            f"**交付目标**：{delivery_target}",
            f"**阶段结论**：{str(payload.get('decision_status') or '').strip()}",
            f"**摘要**：{summary_text}",
            f"**稿件预览**：{draft_preview}",
            f"**不确定性提示**：{uncertainty_text}",
        ]
    )

    return {
        "channel": DeliveryChannel.FEISHU.value,
        "template_id": "clawradar_feishu_summary_v1",
        "msg_type": "post",
        "title": f"OpenClaw 交付｜{title_text}",
        "body_markdown": body_markdown,
        "metadata": {
            "request_id": str(payload.get("request_id") or "").strip(),
            "event_id": str(normalized_bundle.get("event_id") or "").strip(),
            "delivery_target": delivery_target,
        },
    }


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
    events_root = output_context.get("events_root")
    if events_root:
        archive_dir = Path(events_root) / event_id / "deliver" / _slugify_timestamp(delivery_time)
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
    payload_path = archive_dir / "payload_snapshot.json"
    _write_json(payload_path, payload_snapshot)

    message_payload = build_feishu_delivery_message(payload_snapshot, payload_snapshot["content_bundle"], delivery_target=delivery_target)
    message_path = archive_dir / "feishu_message.json"
    _write_json(message_path, message_payload)

    return {
        "archive_path": _relative_path(archive_dir),
        "scorecard_path": _relative_path(scorecard_path),
        "payload_path": _relative_path(payload_path),
        "message_path": _relative_path(message_path),
    }


def build_archive_only_delivery_result(
    payload: Dict[str, Any],
    *,
    delivery_time: Optional[str] = None,
    delivery_target: Optional[str] = None,
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
            "archive_root": str(output_context.get("events_root") or _relative_path(resolved_runs_root)),
            "failed_count": sum(1 for item in event_receipts if item["status"] == "failed"),
            "events": event_receipts,
        },
        "errors": errors,
    }



def _simulate_delivery(payload: Dict[str, Any], *, delivery_channel: str, delivery_target: str) -> None:
    del delivery_target
    if payload.get("simulate_delivery_failure"):
        raise RuntimeError("simulated delivery channel unavailable")
    if delivery_channel != DeliveryChannel.FEISHU.value:
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
        "status": "failed",
        "failure_info": {
            "code": failure_code,
            "message": failure_message,
        },
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
    resolved_delivery_time = _resolve_delivery_time(normalized_payload, delivery_time)
    resolved_runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
    resolved_runs_root.mkdir(parents=True, exist_ok=True)

    event_receipts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for content_bundle in normalized_payload["content_bundles"]:
        event_payload = _build_protocol_event_payload(normalized_payload, content_bundle)
        archive_paths: Dict[str, Optional[str]] = {
            "archive_path": None,
            "scorecard_path": None,
            "payload_path": None,
            "message_path": None,
        }
        resolved_target = str(target or normalized_payload.get("delivery_target") or "").strip()

        try:
            resolved_channel = _resolve_delivery_channel(normalized_payload, resolved_channel)
            resolved_target = _resolve_delivery_target(normalized_payload, resolved_target)
            archive_paths = _archive_delivery_workspace(
                normalized_payload,
                event_payload,
                delivery_channel=resolved_channel,
                delivery_target=resolved_target,
                delivery_time=resolved_delivery_time,
                runs_root=resolved_runs_root,
            )
            _simulate_delivery(
                normalized_payload,
                delivery_channel=resolved_channel,
                delivery_target=resolved_target,
            )
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
                    failure_code=exc.code.value,
                    failure_message=exc.message,
                    delivery_target=resolved_target or None,
                )
            )
            errors.append(exc.to_error_response())
            continue
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
            continue
        except RuntimeError as exc:
            event_receipts.append(
                _build_event_failure_receipt(
                    event_payload=event_payload,
                    delivery_time=resolved_delivery_time,
                    delivery_channel=resolved_channel,
                    archive_path=archive_paths["archive_path"],
                    scorecard_path=archive_paths["scorecard_path"],
                    payload_path=archive_paths["payload_path"],
                    message_path=archive_paths["message_path"],
                    failure_code=DeliveryErrorCode.DELIVERY_CHANNEL_UNAVAILABLE.value,
                    failure_message=str(exc),
                    delivery_target=resolved_target or None,
                )
            )
            errors.append(
                {
                    "code": DeliveryErrorCode.DELIVERY_CHANNEL_UNAVAILABLE.value,
                    "message": str(exc),
                    "missing_fields": [],
                }
            )
            continue

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
            )
        )

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
            "archive_root": _relative_path(resolved_runs_root),
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
            "archive_root": str(output_context.get("events_root") or _relative_path(DEFAULT_RUNS_ROOT)),
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
