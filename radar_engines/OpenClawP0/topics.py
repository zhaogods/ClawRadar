"""显式选题阶段与双输入辅助能力。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Sequence, Tuple
from urllib.parse import quote

from .contracts import IngestValidationError, normalize_ingest_payload
from .real_source import RealSourceUnavailableError, load_real_source_payload


class TopicRunStatus(str, Enum):
    """选题阶段执行状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TopicCardStatus(str, Enum):
    """选题卡片状态。"""

    CANDIDATE = "candidate"


class UserTopicValidationError(ValueError):
    """用户主题输入缺失关键字段。"""



def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")



def _to_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []



def _first_non_blank(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""



def _user_topic_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    input_options = entry_options.get("input") if isinstance(entry_options.get("input"), dict) else {}
    user_topic = payload.get("user_topic") if isinstance(payload.get("user_topic"), dict) else {}
    return {
        "topic": _first_non_blank(
            input_options.get("topic"),
            user_topic.get("topic"),
            payload.get("topic"),
            payload.get("user_topic_title"),
            payload.get("keyword"),
        ),
        "company": _first_non_blank(
            input_options.get("company"),
            user_topic.get("company"),
            payload.get("company"),
        ),
        "track": _first_non_blank(
            input_options.get("track"),
            user_topic.get("track"),
            payload.get("track"),
            payload.get("sector"),
        ),
        "summary": _first_non_blank(
            input_options.get("summary"),
            user_topic.get("summary"),
            payload.get("summary"),
            payload.get("topic_summary"),
        ),
        "keywords": _to_string_list(
            input_options.get("keywords")
            or user_topic.get("keywords")
            or payload.get("keywords")
            or payload.get("topic_keywords")
        ),
    }



def _user_topic_event_id(topic: str) -> str:
    encoded = quote(topic, safe="").lower()[:48] or "user-topic"
    return f"user-topic-{encoded}"



def _build_user_topic_candidates(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    topic = context["topic"]
    company = context.get("company") or ""
    track = context.get("track") or ""
    keywords = list(context.get("keywords") or [])
    summary = context.get("summary") or ""
    requested_at = context.get("requested_at") or _utc_timestamp()
    source_url = f"user_topic://{quote(topic, safe='')}"
    tags = [item for item in [topic, company, track, *keywords] if str(item).strip()]
    unique_tags = list(dict.fromkeys(str(item).strip() for item in tags if str(item).strip()))
    raw_excerpt = summary or f"围绕主题“{topic}”组织后续抓取、聚合与选题。"

    timeline_candidates = [
        {
            "timestamp": requested_at,
            "label": "user_topic_requested",
            "summary": f"收到用户主题输入：{topic}",
            "source_url": source_url,
            "source_type": "user_topic",
        }
    ]
    if company:
        timeline_candidates.append(
            {
                "timestamp": requested_at,
                "label": "company_anchor",
                "summary": f"用户指定公司锚点：{company}",
                "source_url": source_url,
                "source_type": "user_topic",
            }
        )

    fact_candidates = [
        {
            "fact_id": f"{_user_topic_event_id(topic)}-fact-1",
            "claim": f"用户希望围绕“{topic}”生成科技热点选题。",
            "source_url": source_url,
            "confidence": 0.35,
            "citation_excerpt": raw_excerpt,
        }
    ]
    if company:
        fact_candidates.append(
            {
                "fact_id": f"{_user_topic_event_id(topic)}-fact-2",
                "claim": f"用户给出了公司锚点：{company}。",
                "source_url": source_url,
                "confidence": 0.35,
                "citation_excerpt": f"公司锚点：{company}",
            }
        )
    if track or keywords:
        fact_candidates.append(
            {
                "fact_id": f"{_user_topic_event_id(topic)}-fact-3",
                "claim": f"主题相关关键词：{', '.join([item for item in [track, *keywords] if item])}",
                "source_url": source_url,
                "confidence": 0.3,
                "citation_excerpt": f"关键词线索：{', '.join([item for item in [track, *keywords] if item])}",
            }
        )

    return [
        {
            "event_id": _user_topic_event_id(topic),
            "event_title": topic,
            "company": company,
            "event_time": requested_at,
            "source_url": source_url,
            "source_type": "user_topic",
            "raw_excerpt": raw_excerpt,
            "initial_tags": unique_tags,
            "confidence": 0.35,
            "timeline_candidates": timeline_candidates,
            "fact_candidates": fact_candidates,
            "source_metadata": {
                "provider": "user_topic_input",
                "input_mode": "user_topic",
                "track": track,
                "keywords": keywords,
                "requested_at": requested_at,
            },
            "source_snapshot": {
                "topic": topic,
                "company": company,
                "track": track,
                "keywords": keywords,
                "summary": summary,
            },
        }
    ]



def load_user_topic_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """将用户主题输入委托到真实抓取层，再映射为统一候选事件载荷。"""

    context = _user_topic_options(payload)
    if not context["topic"]:
        raise UserTopicValidationError("user_topic mode requires topic")

    requested_at = _utc_timestamp()
    normalized_context = {
        **context,
        "requested_at": requested_at,
        "provider": "user_topic_requested",
        "input_mode": "user_topic",
    }

    delegated_payload = deepcopy(payload)
    delegated_payload["user_topic_context"] = deepcopy(normalized_context)
    delegated_payload.setdefault("entry_options", {})
    delegated_payload["entry_options"] = deepcopy(delegated_payload.get("entry_options") or {})
    delegated_payload["entry_options"].setdefault("input", {})
    delegated_payload["entry_options"]["input"] = deepcopy(delegated_payload["entry_options"].get("input") or {})
    delegated_payload["entry_options"]["input"]["mode"] = "user_topic"

    try:
        user_topic_payload, user_topic_context = load_real_source_payload(delegated_payload)
    except RealSourceUnavailableError as exc:
        raise UserTopicValidationError(str(exc)) from exc

    return user_topic_payload, user_topic_context



def build_crawl_results(
    payload: Dict[str, Any],
    *,
    source_mode: str,
    source_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """构建抓取阶段标准工件。"""

    topic_candidates = [
        deepcopy(item)
        for item in payload.get("topic_candidates") or []
        if isinstance(item, dict)
    ]
    result: Dict[str, Any] = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "run_status": TopicRunStatus.SUCCEEDED.value,
        "decision_status": TopicCardStatus.CANDIDATE.value,
        "input_mode": source_mode,
        "candidate_count": len(topic_candidates),
        "topic_candidates": topic_candidates,
        "errors": [],
    }
    if source_context:
        result["source_context"] = deepcopy(source_context)
    if payload.get("real_source_context") is not None:
        result["real_source_context"] = deepcopy(payload.get("real_source_context"))
    if payload.get("user_topic_context") is not None:
        result["user_topic_context"] = deepcopy(payload.get("user_topic_context"))
    return result



def _recommended_angles(event: Dict[str, Any]) -> List[str]:
    angles: List[str] = []
    company = str(event.get("company") or "").strip()
    if company:
        angles.append(f"从 {company} 的业务动作与市场影响切入")
    for tag in _to_string_list(event.get("initial_tags"))[:2]:
        angles.append(f"围绕标签“{tag}”补充证据与行业对照")
    angles.append("整理可追溯证据后判断是否进入正式写作")
    return list(dict.fromkeys(angles))



def build_topic_cards(payload: Dict[str, Any]) -> Dict[str, Any]:
    """在抓取或标准化输入之上构建显式选题卡片。"""

    if isinstance(payload.get("topic_cards"), list) and payload.get("topic_cards"):
        topic_cards = [deepcopy(item) for item in payload.get("topic_cards") if isinstance(item, dict)]
        return {
            "request_id": str(payload.get("request_id") or "").strip(),
            "trigger_source": str(payload.get("trigger_source") or "").strip(),
            "run_status": TopicRunStatus.SUCCEEDED.value,
            "decision_status": TopicCardStatus.CANDIDATE.value,
            "topic_cards": topic_cards,
            "topic_card_count": len(topic_cards),
            "errors": [],
        }

    if "normalized_events" in payload:
        normalized_payload = {
            "request_id": str(payload.get("request_id") or "").strip(),
            "trigger_source": str(payload.get("trigger_source") or "").strip(),
            "normalized_events": [
                deepcopy(item)
                for item in payload.get("normalized_events") or []
                if isinstance(item, dict)
            ],
        }
        if payload.get("real_source_context") is not None:
            normalized_payload["real_source_context"] = deepcopy(payload.get("real_source_context"))
        if payload.get("user_topic_context") is not None:
            normalized_payload["user_topic_context"] = deepcopy(payload.get("user_topic_context"))
    else:
        normalized_payload = normalize_ingest_payload(payload)
        if payload.get("user_topic_context") is not None:
            normalized_payload["user_topic_context"] = deepcopy(payload.get("user_topic_context"))

    topic_cards: List[Dict[str, Any]] = []
    for event in normalized_payload.get("normalized_events") or []:
        if not isinstance(event, dict):
            continue
        event_title = str(event.get("event_title") or "").strip()
        summary = str(event.get("raw_excerpt") or event_title).strip()
        topic_cards.append(
            {
                "request_id": str(normalized_payload.get("request_id") or "").strip(),
                "topic_id": str(event.get("event_id") or "").strip(),
                "event_id": str(event.get("event_id") or "").strip(),
                "event_title": event_title,
                "topic_summary": summary,
                "status": TopicCardStatus.CANDIDATE.value,
                "event_time": str(event.get("event_time") or "").strip(),
                "company": str(event.get("company") or "").strip(),
                "source_url": str(event.get("source_url") or "").strip(),
                "source_type": str(event.get("source_type") or "unknown").strip() or "unknown",
                "recommended_angles": _recommended_angles(event),
                "evidence_overview": {
                    "timeline_candidate_count": len(event.get("timeline_candidates") or []) if isinstance(event.get("timeline_candidates"), list) else 0,
                    "fact_candidate_count": len(event.get("fact_candidates") or []) if isinstance(event.get("fact_candidates"), list) else 0,
                    "initial_tags": list(event.get("initial_tags") or []),
                },
                "normalized_event": deepcopy(event),
            }
        )

    result: Dict[str, Any] = {
        "request_id": str(normalized_payload.get("request_id") or "").strip(),
        "trigger_source": str(normalized_payload.get("trigger_source") or "").strip(),
        "run_status": TopicRunStatus.SUCCEEDED.value,
        "decision_status": TopicCardStatus.CANDIDATE.value,
        "topic_cards": topic_cards,
        "topic_card_count": len(topic_cards),
        "normalized_events": [
            deepcopy(item)
            for item in normalized_payload.get("normalized_events") or []
            if isinstance(item, dict)
        ],
        "errors": [],
    }
    if normalized_payload.get("real_source_context") is not None:
        result["real_source_context"] = deepcopy(normalized_payload.get("real_source_context"))
    if normalized_payload.get("user_topic_context") is not None:
        result["user_topic_context"] = deepcopy(normalized_payload.get("user_topic_context"))
    return result



def topic_cards_to_score_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """将显式选题工件还原为评分阶段可消费载荷。"""

    if "normalized_events" in payload and isinstance(payload.get("normalized_events"), list):
        normalized_payload = {
            "request_id": str(payload.get("request_id") or "").strip(),
            "trigger_source": str(payload.get("trigger_source") or "").strip(),
            "normalized_events": [
                deepcopy(item)
                for item in payload.get("normalized_events") or []
                if isinstance(item, dict)
            ],
        }
        if payload.get("real_source_context") is not None:
            normalized_payload["real_source_context"] = deepcopy(payload.get("real_source_context"))
        if payload.get("user_topic_context") is not None:
            normalized_payload["user_topic_context"] = deepcopy(payload.get("user_topic_context"))
        return normalized_payload

    topic_cards = payload.get("topic_cards")
    if not isinstance(topic_cards, list) or not topic_cards:
        raise UserTopicValidationError("topic_cards required")

    normalized_events: List[Dict[str, Any]] = []
    for card in topic_cards:
        if not isinstance(card, dict):
            continue
        if isinstance(card.get("normalized_event"), dict):
            normalized_events.append(deepcopy(card.get("normalized_event")))
            continue
        normalized_events.append(
            {
                "request_id": str(payload.get("request_id") or "").strip(),
                "event_id": str(card.get("event_id") or card.get("topic_id") or "").strip(),
                "event_title": str(card.get("event_title") or "").strip(),
                "company": str(card.get("company") or "").strip(),
                "event_time": str(card.get("event_time") or _utc_timestamp()).strip(),
                "source_url": str(card.get("source_url") or "topic_card://unknown").strip(),
                "source_type": str(card.get("source_type") or "topic_card").strip(),
                "raw_excerpt": str(card.get("topic_summary") or card.get("event_title") or "").strip(),
                "initial_tags": _to_string_list((card.get("evidence_overview") or {}).get("initial_tags")),
                "timeline_candidates": [],
                "fact_candidates": [],
                "status": TopicCardStatus.CANDIDATE.value,
            }
        )

    normalized_payload = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "normalized_events": normalized_events,
    }
    if payload.get("real_source_context") is not None:
        normalized_payload["real_source_context"] = deepcopy(payload.get("real_source_context"))
    if payload.get("user_topic_context") is not None:
        normalized_payload["user_topic_context"] = deepcopy(payload.get("user_topic_context"))
    return normalized_payload


__all__ = [
    "TopicCardStatus",
    "TopicRunStatus",
    "UserTopicValidationError",
    "build_crawl_results",
    "build_topic_cards",
    "load_user_topic_payload",
    "topic_cards_to_score_payload",
]
