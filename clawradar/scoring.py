"""阶段二：ClawRadar score contract 与结构化评分实现。"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .contracts import IngestValidationError, normalize_ingest_payload
from .topics import UserTopicValidationError, topic_cards_to_score_payload


class ScoreRunStatus(str, Enum):
    """阶段二 score 执行状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScoreDecisionStatus(str, Enum):
    """阶段二 score 结论状态。"""

    NEED_MORE_EVIDENCE = "need_more_evidence"
    WATCHLIST = "watchlist"
    NO_PUBLISH = "no_publish"
    PUBLISH_READY = "publish_ready"


class ScoreDimension(str, Enum):
    """固化选题评分维度。"""

    TIMELINESS = "timeliness"
    EVIDENCE_STRENGTH = "evidence_strength"
    NOVELTY = "novelty"
    BUSINESS_RELEVANCE = "business_relevance"
    EXECUTION_READINESS = "execution_readiness"


class ScoreErrorCode(str, Enum):
    """阶段二错误码。"""

    INVALID_INPUT = "invalid_input"


SCORE_REQUIRED_FIELDS: Tuple[str, ...] = (
    "request_id",
    "trigger_source",
    "normalized_events",
)


SCORE_WEIGHTS: Dict[str, int] = {
    ScoreDimension.TIMELINESS.value: 20,
    ScoreDimension.EVIDENCE_STRENGTH.value: 30,
    ScoreDimension.NOVELTY.value: 15,
    ScoreDimension.BUSINESS_RELEVANCE.value: 20,
    ScoreDimension.EXECUTION_READINESS.value: 15,
}


class ScoreValidationError(ValueError):
    """score 输入校验失败。"""

    def __init__(self, *, code: ScoreErrorCode, missing_fields: List[str], message: str):
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


def _remap_ingest_missing_fields(missing_fields: Sequence[str]) -> List[str]:
    remapped: List[str] = []
    for field in missing_fields:
        if field.startswith("topic_candidates["):
            remapped.append(field.replace("topic_candidates", "normalized_events", 1))
        else:
            remapped.append(str(field))
    return remapped


def _normalize_score_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "normalized_events" in payload:
        return payload
    if "topic_cards" in payload:
        return topic_cards_to_score_payload(payload)
    return normalize_ingest_payload(payload)


def _collect_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing_fields: List[str] = []

    for field in SCORE_REQUIRED_FIELDS:
        if field not in payload or _is_blank(payload.get(field)):
            missing_fields.append(field)

    normalized_events = payload.get("normalized_events")
    if not isinstance(normalized_events, list) or not normalized_events:
        missing_fields.append("normalized_events")
        return missing_fields

    for index, event in enumerate(normalized_events):
        if not isinstance(event, dict):
            missing_fields.append(f"normalized_events[{index}]")
            continue
        for field in ("event_id", "event_title", "event_time", "source_url"):
            if field not in event or _is_blank(event.get(field)):
                missing_fields.append(f"normalized_events[{index}].{field}")

    return missing_fields


def validate_score_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """校验并返回 score 阶段可消费载荷。"""

    try:
        normalized_payload = _normalize_score_payload(payload)
    except IngestValidationError as exc:
        raise ScoreValidationError(
            code=ScoreErrorCode.INVALID_INPUT,
            missing_fields=_remap_ingest_missing_fields(exc.missing_fields),
            message="score payload missing required fields",
        ) from exc
    except UserTopicValidationError as exc:
        raise ScoreValidationError(
            code=ScoreErrorCode.INVALID_INPUT,
            missing_fields=["topic_cards"],
            message=str(exc),
        ) from exc

    missing_fields = _collect_missing_fields(normalized_payload)
    if missing_fields:
        raise ScoreValidationError(
            code=ScoreErrorCode.INVALID_INPUT,
            missing_fields=missing_fields,
            message="score payload missing required fields",
        )
    return normalized_payload


def _to_string_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _build_timeline(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    timeline = [
        {
            "timestamp": str(event["event_time"]).strip(),
            "label": "candidate_detected",
            "summary": str(event["event_title"]).strip(),
            "source_url": str(event["source_url"]).strip(),
            "source_type": (event.get("source_type") or "unknown").strip() or "unknown",
        }
    ]

    for index, item in enumerate(event.get("timeline_candidates") or [], start=1):
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or item.get("event_time") or "").strip()
        label = str(item.get("label") or f"timeline_{index}").strip()
        summary = str(item.get("summary") or item.get("event_title") or "").strip()
        source_url = str(item.get("source_url") or event["source_url"]).strip()
        if timestamp and summary:
            timeline.append(
                {
                    "timestamp": timestamp,
                    "label": label,
                    "summary": summary,
                    "source_url": source_url,
                    "source_type": str(item.get("source_type") or event.get("source_type") or "unknown").strip() or "unknown",
                }
            )

    timeline.sort(key=lambda item: item["timestamp"])
    return timeline


def _build_facts(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    fact_points: List[Dict[str, Any]] = []
    for index, item in enumerate(event.get("fact_candidates") or [], start=1):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or item.get("summary") or "").strip()
        if not claim:
            continue
        fact_points.append(
            {
                "fact_id": str(item.get("fact_id") or f"{event['event_id']}-fact-{index}"),
                "claim": claim,
                "source_url": str(item.get("source_url") or event["source_url"]).strip(),
                "confidence": item.get("confidence", event.get("confidence")),
                "citation_excerpt": str(item.get("citation_excerpt") or event.get("raw_excerpt") or "").strip(),
            }
        )

    if fact_points:
        return fact_points

    return [
        {
            "fact_id": f"{event['event_id']}-fact-1",
            "claim": str(event.get("raw_excerpt") or event["event_title"]).strip(),
            "source_url": str(event["source_url"]).strip(),
            "confidence": event.get("confidence"),
            "citation_excerpt": str(event.get("raw_excerpt") or "").strip(),
        }
    ]


def _build_risk_flags(event: Dict[str, Any], fact_points: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    risk_flags: List[Dict[str, str]] = []
    if len(fact_points) < 2:
        risk_flags.append(
            {
                "code": "single_source_signal",
                "severity": "medium",
                "message": "当前事实点数量偏少，需补充更多来源交叉验证。",
            }
        )

    if not str(event.get("company") or "").strip():
        risk_flags.append(
            {
                "code": "missing_company_anchor",
                "severity": "low",
                "message": "事件缺少明确公司主体，后续写作可能出现对象锚点不足。",
            }
        )

    if not _to_string_list(event.get("initial_tags")):
        risk_flags.append(
            {
                "code": "missing_topic_tags",
                "severity": "low",
                "message": "事件缺少主题标签，可能影响后续检索与聚类。",
            }
        )

    return risk_flags


def _compute_score_dimensions(event: Dict[str, Any], fact_points: List[Dict[str, Any]], timeline: List[Dict[str, Any]]) -> Dict[str, int]:
    timeliness = 20 if len(timeline) >= 2 else 14
    evidence_strength = 28 if len(fact_points) >= 3 else 18 if len(fact_points) >= 2 else 10
    novelty = 12 if len(_to_string_list(event.get("initial_tags"))) >= 2 else 8
    business_relevance = 18 if str(event.get("company") or "").strip() else 10
    execution_readiness = 15 if str(event.get("raw_excerpt") or "").strip() else 8
    return {
        ScoreDimension.TIMELINESS.value: timeliness,
        ScoreDimension.EVIDENCE_STRENGTH.value: evidence_strength,
        ScoreDimension.NOVELTY.value: novelty,
        ScoreDimension.BUSINESS_RELEVANCE.value: business_relevance,
        ScoreDimension.EXECUTION_READINESS.value: execution_readiness,
    }


def _resolve_decision(score_total: int, fact_points: List[Dict[str, Any]], risk_flags: List[Dict[str, str]]) -> str:
    if len(fact_points) < 2:
        return ScoreDecisionStatus.NEED_MORE_EVIDENCE.value
    if score_total >= 75:
        return ScoreDecisionStatus.PUBLISH_READY.value
    if score_total >= 55:
        return ScoreDecisionStatus.WATCHLIST.value
    if any(flag["severity"] == "medium" for flag in risk_flags):
        return ScoreDecisionStatus.NEED_MORE_EVIDENCE.value
    return ScoreDecisionStatus.NO_PUBLISH.value


def _build_scorecard(event: Dict[str, Any], fact_points: List[Dict[str, Any]], timeline: List[Dict[str, Any]], risk_flags: List[Dict[str, str]]) -> Dict[str, Any]:
    dimension_scores = _compute_score_dimensions(event, fact_points, timeline)
    total_score = sum(dimension_scores.values())
    decision_status = _resolve_decision(total_score, fact_points, risk_flags)
    return {
        "dimensions": [
            {
                "dimension": dimension,
                "score": score,
                "weight": SCORE_WEIGHTS[dimension],
            }
            for dimension, score in dimension_scores.items()
        ],
        "total_score": total_score,
        "decision_status": decision_status,
    }


def _score_event(event: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    timeline = _build_timeline(event)
    fact_points = _build_facts(event)
    risk_flags = _build_risk_flags(event, fact_points)
    scorecard = _build_scorecard(event, fact_points, timeline, risk_flags)

    return {
        "request_id": request_id,
        "event_id": event["event_id"],
        "event_title": event["event_title"],
        "status": scorecard["decision_status"],
        "timeline": timeline,
        "fact_points": fact_points,
        "risk_flags": risk_flags,
        "scorecard": scorecard,
        "trace": {
            "source_url": event["source_url"],
            "source_type": event.get("source_type", "unknown"),
            "company": event.get("company", ""),
            "initial_tags": list(event.get("initial_tags") or []),
            "source_metadata": deepcopy(event.get("source_metadata") or {}),
            "source_snapshot": deepcopy(event.get("source_snapshot") or {}),
        },
    }


def score_topic_candidates(payload: Dict[str, Any]) -> Dict[str, Any]:
    """执行阶段二 score，支持 ingest 或标准化输入单独调用。"""

    normalized_payload = validate_score_payload(payload)
    request_id = str(normalized_payload["request_id"]).strip()
    scored_events = [
        _score_event(event, request_id)
        for event in normalized_payload["normalized_events"]
    ]

    decision_counts = {
        status.value: sum(1 for item in scored_events if item["status"] == status.value)
        for status in ScoreDecisionStatus
    }
    overall_status = ScoreDecisionStatus.NO_PUBLISH.value
    for status in (
        ScoreDecisionStatus.PUBLISH_READY,
        ScoreDecisionStatus.WATCHLIST,
        ScoreDecisionStatus.NEED_MORE_EVIDENCE,
        ScoreDecisionStatus.NO_PUBLISH,
    ):
        if decision_counts[status.value] > 0:
            overall_status = status.value
            break

    result = {
        "request_id": request_id,
        "trigger_source": str(normalized_payload["trigger_source"]).strip(),
        "run_status": ScoreRunStatus.SUCCEEDED.value,
        "decision_status": overall_status,
        "scored_events": scored_events,
        "decision_counts": decision_counts,
        "errors": [],
    }
    if "real_source_context" in normalized_payload and normalized_payload.get("real_source_context") is not None:
        result["real_source_context"] = deepcopy(normalized_payload["real_source_context"])
    return result


def build_score_rejection(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回阶段二 score 拒收结构。"""

    payload = payload or {}
    request_id = payload.get("request_id")
    trigger_source = payload.get("trigger_source")
    try:
        validate_score_payload(payload)
    except ScoreValidationError as exc:
        return {
            "request_id": request_id,
            "trigger_source": trigger_source,
            "run_status": ScoreRunStatus.FAILED.value,
            "decision_status": ScoreDecisionStatus.NEED_MORE_EVIDENCE.value,
            "scored_events": [],
            "decision_counts": {
                status.value: 0 for status in ScoreDecisionStatus
            },
            "errors": [exc.to_error_response()],
        }

    return {
        "request_id": request_id,
        "trigger_source": trigger_source,
        "run_status": ScoreRunStatus.FAILED.value,
        "decision_status": ScoreDecisionStatus.NEED_MORE_EVIDENCE.value,
        "scored_events": [],
        "decision_counts": {
            status.value: 0 for status in ScoreDecisionStatus
        },
        "errors": [
            {
                "code": ScoreErrorCode.INVALID_INPUT.value,
                "message": "score payload rejected",
                "missing_fields": [],
            }
        ],
    }
