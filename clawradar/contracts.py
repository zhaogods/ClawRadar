"""阶段一：BettaFish -> ClawRadar ingest contract。"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class IngestRunStatus(str, Enum):
    """阶段一 ingest 总状态。"""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CandidateEventStatus(str, Enum):
    """标准化后候选事件状态。"""

    ACCEPTED = "accepted"


class ErrorCode(str, Enum):
    """阶段一错误码。"""

    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    INVALID_TOPIC_CANDIDATES = "invalid_topic_candidates"


REQUIRED_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "request_id",
    "trigger_source",
    "topic_candidates",
)

REQUIRED_EVENT_FIELDS: Tuple[str, ...] = (
    "event_id",
    "event_title",
    "event_time",
    "source_url",
)

OPTIONAL_EVENT_PASSTHROUGH_FIELDS: Tuple[str, ...] = (
    "source_metadata",
    "source_snapshot",
)


class IngestValidationError(ValueError):
    """输入校验失败。"""

    def __init__(self, *, code: ErrorCode, missing_fields: List[str], message: str):
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


def _collect_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing_fields: List[str] = []

    for field in REQUIRED_PAYLOAD_FIELDS:
        if field not in payload or _is_blank(payload.get(field)):
            missing_fields.append(field)

    topic_candidates = payload.get("topic_candidates")
    if isinstance(topic_candidates, Sequence) and not isinstance(topic_candidates, (str, bytes)):
        for index, event in enumerate(topic_candidates):
            if not isinstance(event, dict):
                missing_fields.append(f"topic_candidates[{index}]")
                continue
            for field in REQUIRED_EVENT_FIELDS:
                if field not in event or _is_blank(event.get(field)):
                    missing_fields.append(f"topic_candidates[{index}].{field}")

    return missing_fields


def validate_ingest_payload(payload: Dict[str, Any]) -> None:
    """校验阶段一 ingest 输入载荷。"""

    missing_fields = _collect_missing_fields(payload)
    if missing_fields:
        raise IngestValidationError(
            code=ErrorCode.MISSING_REQUIRED_FIELDS,
            missing_fields=missing_fields,
            message="ingest payload missing required fields",
        )

    topic_candidates = payload.get("topic_candidates")
    if not isinstance(topic_candidates, list) or not topic_candidates:
        raise IngestValidationError(
            code=ErrorCode.INVALID_TOPIC_CANDIDATES,
            missing_fields=["topic_candidates"],
            message="topic_candidates must be a non-empty list",
        )


def _normalize_event(event: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    initial_tags = event.get("initial_tags") or []
    if not isinstance(initial_tags, list):
        initial_tags = [str(initial_tags)]
    timeline_candidates = event.get("timeline_candidates") or []
    if not isinstance(timeline_candidates, list):
        timeline_candidates = []
    fact_candidates = event.get("fact_candidates") or []
    if not isinstance(fact_candidates, list):
        fact_candidates = []

    normalized_event = {
        "request_id": request_id,
        "event_id": str(event["event_id"]),
        "event_title": str(event["event_title"]).strip(),
        "company": (event.get("company") or "").strip(),
        "event_time": str(event["event_time"]).strip(),
        "source_url": str(event["source_url"]).strip(),
        "source_type": (event.get("source_type") or "unknown").strip() or "unknown",
        "raw_excerpt": (event.get("raw_excerpt") or "").strip(),
        "initial_tags": [str(tag).strip() for tag in initial_tags if str(tag).strip()],
        "confidence": event.get("confidence"),
        "timeline_candidates": timeline_candidates,
        "fact_candidates": fact_candidates,
        "status": CandidateEventStatus.ACCEPTED.value,
    }
    # Preserve search-enrichment fields when present
    for passthrough_key in (
        "image_urls",
        "structured_data",
        "time_weight",
        "time_window",
    ):
        if passthrough_key in event and event.get(passthrough_key) is not None:
            normalized_event[passthrough_key] = deepcopy(event[passthrough_key])
    for field in OPTIONAL_EVENT_PASSTHROUGH_FIELDS:
        if field in event and event.get(field) is not None:
            normalized_event[field] = deepcopy(event[field])
    return normalized_event


def normalize_ingest_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """返回阶段一 ingest 标准化结果。"""

    validate_ingest_payload(payload)

    request_id = str(payload["request_id"]).strip()
    normalized_events = [
        _normalize_event(event, request_id)
        for event in payload["topic_candidates"]
    ]

    result = {
        "request_id": request_id,
        "trigger_source": str(payload["trigger_source"]).strip(),
        "run_status": IngestRunStatus.ACCEPTED.value,
        "decision_status": IngestRunStatus.ACCEPTED.value,
        "normalized_events": normalized_events,
        "accepted_count": len(normalized_events),
        "rejected_count": 0,
        "errors": [],
    }
    if "real_source_context" in payload and payload.get("real_source_context") is not None:
        result["real_source_context"] = deepcopy(payload["real_source_context"])
    return result


def build_ingest_rejection(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回阶段一 ingest 拒收结构。"""

    payload = payload or {}
    request_id = payload.get("request_id")

    try:
        validate_ingest_payload(payload)
    except IngestValidationError as exc:
        return {
            "request_id": request_id,
            "run_status": IngestRunStatus.REJECTED.value,
            "decision_status": IngestRunStatus.REJECTED.value,
            "normalized_events": [],
            "accepted_count": 0,
            "rejected_count": len(exc.missing_fields) or 1,
            "errors": [exc.to_error_response()],
        }

    return {
        "request_id": request_id,
        "run_status": IngestRunStatus.REJECTED.value,
        "decision_status": IngestRunStatus.REJECTED.value,
        "normalized_events": [],
        "accepted_count": 0,
        "rejected_count": 1,
        "errors": [
            {
                "code": ErrorCode.INVALID_TOPIC_CANDIDATES.value,
                "message": "payload rejected",
                "missing_fields": [],
            }
        ],
    }
