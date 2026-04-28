"""阶段五：统一编排 ingest -> score -> write -> deliver 主链路。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .contracts import (
    IngestRunStatus,
    IngestValidationError,
    build_ingest_rejection,
    normalize_ingest_payload,
)
from .delivery import build_archive_only_delivery_result as delivery_build_archive_only_delivery_result, topic_radar_deliver
from .real_source import RealSourceUnavailableError, load_real_source_payload
from .scoring import (
    ScoreDecisionStatus,
    ScoreRunStatus,
    build_score_rejection,
    score_topic_candidates,
)
from .topics import TopicRunStatus, UserTopicValidationError, build_crawl_results, build_topic_cards, load_user_topic_payload
from .writing import WriteExecutor, WriteOperation, WriteRunStatus, build_write_rejection, topic_radar_write
from .notifications import build_notification_payload, topic_radar_notify


class OrchestratorExecutionMode(str, Enum):
    """统一编排入口支持的执行模式。"""

    FULL_PIPELINE = "full_pipeline"
    CRAWL_ONLY = "crawl_only"
    TOPICS_ONLY = "topics_only"
    SCORE_ONLY = "score_only"
    WRITE_ONLY = "write_only"
    DELIVER_ONLY = "deliver_only"
    RESUME = "resume"


class OrchestratorTriggerSource(str, Enum):
    """统一编排入口支持的触发方式。"""

    MANUAL = "manual"
    CRON = "cron"
    SINGLE_EVENT_RERUN = "single_event_rerun"


class OrchestratorRunStatus(str, Enum):
    """统一编排顶层执行状态。"""

    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    DELIVERY_FAILED = "delivery_failed"


class OrchestratorStageStatus(str, Enum):
    """统一编排阶段级状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrchestratorErrorCode(str, Enum):
    """统一编排入口错误码。"""

    INVALID_EXECUTION_MODE = "invalid_execution_mode"
    INVALID_ENTRY_OPTION = "invalid_entry_option"
    MISSING_TARGET_EVENT_ID = "missing_target_event_id"
    TARGET_EVENT_NOT_FOUND = "target_event_not_found"
    INPUT_MODE_UNAVAILABLE = "input_mode_unavailable"
    WRITE_EXECUTOR_UNAVAILABLE = "write_executor_unavailable"


_MODE_ALIASES = {
    "delivery_only": OrchestratorExecutionMode.DELIVER_ONLY.value,
}


_TRIGGER_SOURCE_ALIASES = {
    "manual_run": OrchestratorTriggerSource.MANUAL.value,
    "scheduled": OrchestratorTriggerSource.CRON.value,
    "event_rerun": OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
    "rerun": OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
    "single_event_retry": OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
    "single_event_replay": OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
}

_VALID_TRIGGER_SOURCES = {item.value for item in OrchestratorTriggerSource}

_ENTRY_INPUT_MODES = {"inline_candidates", "inline_normalized", "inline_topic_cards", "real_source", "user_topic"}
_ENTRY_WRITE_EXECUTORS = {"openclaw_builtin", "external_writer"}
_ENTRY_DELIVERY_TARGET_MODES = {"feishu", "wechat", "wechat_official_account", "archive_only"}
_ENTRY_INPUT_DEGRADE_STRATEGIES = {"fail", "fallback_inline_candidates", "fallback_inline_normalized"}
_ENTRY_WRITE_DEGRADE_STRATEGIES = {"fail", "fallback_openclaw_builtin", "skip"}
_ENTRY_DELIVERY_DEGRADE_STRATEGIES = {"fail", "archive_only"}

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = WORKSPACE_ROOT / "outputs"



def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")



def _shanghai_run_id() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M")



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



def _resolve_output_context(payload: Dict[str, Any], runs_root: Optional[Path], *, mode: str) -> Dict[str, str]:
    request_id = str(payload.get("request_id") or "openclaw-run").strip() or "openclaw-run"
    run_id = _shanghai_run_id()
    started_at = _utc_timestamp()
    base_root = Path(runs_root or DEFAULT_RUNS_ROOT).resolve()
    mode_root = (base_root / mode).resolve()
    output_root = (mode_root / run_id).resolve()
    reports_root = (output_root / "reports").resolve()
    recovery_root = (output_root / "recovery").resolve()
    debug_root = (output_root / "debug").resolve()
    summary_path = (output_root / "summary.json").resolve()
    latest_path = (mode_root / "latest.json").resolve()
    recovery_summary_path = (recovery_root / "recovery_summary.json").resolve()

    for path in (mode_root, output_root, reports_root, recovery_root, debug_root):
        path.mkdir(parents=True, exist_ok=True)

    return {
        "base_root": base_root.as_posix(),
        "mode_root": mode_root.as_posix(),
        "output_root": output_root.as_posix(),
        "reports_root": reports_root.as_posix(),
        "recovery_root": recovery_root.as_posix(),
        "debug_root": debug_root.as_posix(),
        "summary_path": summary_path.as_posix(),
        "latest_path": latest_path.as_posix(),
        "recovery_summary_path": recovery_summary_path.as_posix(),
        "started_at": started_at,
        "workspace_relative_output_root": _relative_path(output_root) or output_root.as_posix(),
        "run_id": run_id,
        "mode": mode,
        "request_id": request_id,
    }



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



def _has_items(value: Any) -> bool:
    return isinstance(value, list) and bool(value)



def _normalize_entry_choice(raw_value: Any, *, default: str, allowed: Set[str], option_path: str) -> tuple[str, str]:
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return default, "default"
    if normalized not in allowed:
        raise ValueError(f"{option_path}:{normalized}")
    return normalized, "entry_options"



def _default_input_mode(payload: Dict[str, Any], execution_mode: str) -> str:
    has_topic_candidates = _has_items(payload.get("topic_candidates"))
    has_normalized_events = _has_items(payload.get("normalized_events"))
    has_topic_cards = _has_items(payload.get("topic_cards"))
    has_user_topic = isinstance(payload.get("user_topic"), dict) or any(
        str(payload.get(field) or "").strip() for field in ("topic", "user_topic_title", "keyword")
    )

    if execution_mode in {
        OrchestratorExecutionMode.SCORE_ONLY.value,
        OrchestratorExecutionMode.TOPICS_ONLY.value,
    }:
        if has_topic_cards and not has_normalized_events and not has_topic_candidates:
            return "inline_topic_cards"
        if has_normalized_events and not has_topic_candidates:
            return "inline_normalized"

    if has_user_topic and not has_topic_candidates and not has_normalized_events and not has_topic_cards:
        return "user_topic"
    return "inline_candidates"



def _record_entry_fallback(
    entry_resolution: Dict[str, Any],
    *,
    category: str,
    requested: str,
    applied: str,
    reason: str,
) -> None:
    degrade_resolution = entry_resolution.setdefault("degrade", {})
    fallback_items = degrade_resolution.setdefault("fallbacks", [])
    fallback_items.append(
        {
            "category": category,
            "requested": requested,
            "applied": applied,
            "reason": reason,
        }
    )
    degrade_resolution["fallback_triggered"] = True



def _build_entry_resolution(
    payload: Dict[str, Any],
    *,
    execution_mode: str,
    delivery_channel: Optional[str],
    delivery_target: Optional[str],
    delivery_time: Optional[str],
) -> Dict[str, Any]:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    input_options = entry_options.get("input") if isinstance(entry_options.get("input"), dict) else {}
    write_options = entry_options.get("write") if isinstance(entry_options.get("write"), dict) else {}
    delivery_options = entry_options.get("delivery") if isinstance(entry_options.get("delivery"), dict) else {}
    degrade_options = entry_options.get("degrade") if isinstance(entry_options.get("degrade"), dict) else {}

    input_mode, input_mode_source = _normalize_entry_choice(
        input_options.get("mode"),
        default=_default_input_mode(payload, execution_mode),
        allowed=_ENTRY_INPUT_MODES,
        option_path="entry_options.input.mode",
    )
    write_executor, write_executor_source = _normalize_entry_choice(
        write_options.get("executor"),
        default="external_writer",
        allowed=_ENTRY_WRITE_EXECUTORS,
        option_path="entry_options.write.executor",
    )
    write_operation, write_operation_source = _normalize_entry_choice(
        write_options.get("operation"),
        default=WriteOperation.GENERATE.value,
        allowed={item.value for item in WriteOperation},
        option_path="entry_options.write.operation",
    )
    delivery_target_mode, delivery_target_mode_source = _normalize_entry_choice(
        delivery_options.get("target_mode"),
        default="archive_only",
        allowed=_ENTRY_DELIVERY_TARGET_MODES,
        option_path="entry_options.delivery.target_mode",
    )
    input_unavailable_strategy, _ = _normalize_entry_choice(
        degrade_options.get("input_unavailable"),
        default="fail",
        allowed=_ENTRY_INPUT_DEGRADE_STRATEGIES,
        option_path="entry_options.degrade.input_unavailable",
    )
    write_unavailable_strategy, _ = _normalize_entry_choice(
        degrade_options.get("write_unavailable"),
        default="fail",
        allowed=_ENTRY_WRITE_DEGRADE_STRATEGIES,
        option_path="entry_options.degrade.write_unavailable",
    )
    delivery_unavailable_strategy, _ = _normalize_entry_choice(
        degrade_options.get("delivery_unavailable"),
        default="fail",
        allowed=_ENTRY_DELIVERY_DEGRADE_STRATEGIES,
        option_path="entry_options.degrade.delivery_unavailable",
    )

    default_write_enabled = execution_mode not in {
        OrchestratorExecutionMode.CRAWL_ONLY.value,
        OrchestratorExecutionMode.TOPICS_ONLY.value,
        OrchestratorExecutionMode.SCORE_ONLY.value,
        OrchestratorExecutionMode.DELIVER_ONLY.value,
    }
    if "enabled" in write_options:
        write_enabled = _coerce_bool(write_options.get("enabled"), default=default_write_enabled)
        write_enabled_source = "entry_options"
    elif not default_write_enabled:
        write_enabled = False
        write_enabled_source = "legacy_execution_mode"
    else:
        write_enabled = True
        write_enabled_source = "default"

    default_delivery_enabled = execution_mode not in {
        OrchestratorExecutionMode.CRAWL_ONLY.value,
        OrchestratorExecutionMode.TOPICS_ONLY.value,
        OrchestratorExecutionMode.SCORE_ONLY.value,
        OrchestratorExecutionMode.WRITE_ONLY.value,
    }
    if "enabled" in delivery_options:
        delivery_enabled = _coerce_bool(delivery_options.get("enabled"), default=default_delivery_enabled)
        delivery_enabled_source = "entry_options"
    elif not default_delivery_enabled:
        delivery_enabled = False
        delivery_enabled_source = "legacy_execution_mode"
    else:
        delivery_enabled = True
        delivery_enabled_source = "default"

    if delivery_target_mode == "archive_only":
        if delivery_channel is not None:
            resolved_delivery_channel = str(delivery_channel).strip()
            delivery_channel_source = "function_arg"
        elif "channel" in delivery_options:
            resolved_delivery_channel = str(delivery_options.get("channel") or "").strip()
            delivery_channel_source = "entry_options"
        else:
            resolved_delivery_channel = "archive_only"
            delivery_channel_source = "default"

        if delivery_target is not None:
            resolved_delivery_target = str(delivery_target).strip()
            delivery_target_source = "function_arg"
        elif "target" in delivery_options:
            resolved_delivery_target = str(delivery_options.get("target") or "").strip()
            delivery_target_source = "entry_options"
        else:
            resolved_delivery_target = "archive://clawradar"
            delivery_target_source = "default"
    else:
        if delivery_channel is not None:
            resolved_delivery_channel = str(delivery_channel).strip()
            delivery_channel_source = "function_arg"
        elif "channel" in delivery_options:
            resolved_delivery_channel = str(delivery_options.get("channel") or "").strip()
            delivery_channel_source = "entry_options"
        elif delivery_target_mode != "archive_only":
            resolved_delivery_channel = "wechat" if delivery_target_mode == "wechat_official_account" else delivery_target_mode
            delivery_channel_source = "entry_options"
        elif "delivery_channel" in payload:
            resolved_delivery_channel = str(payload.get("delivery_channel") or "").strip()
            delivery_channel_source = "legacy_payload"
        else:
            resolved_delivery_channel = "wechat" if delivery_target_mode == "wechat_official_account" else delivery_target_mode
            delivery_channel_source = "default"

        if delivery_target is not None:
            resolved_delivery_target = str(delivery_target).strip()
            delivery_target_source = "function_arg"
        elif "target" in delivery_options:
            resolved_delivery_target = str(delivery_options.get("target") or "").strip()
            delivery_target_source = "entry_options"
        elif "delivery_target" in payload:
            resolved_delivery_target = str(payload.get("delivery_target") or "").strip()
            delivery_target_source = "legacy_payload"
        else:
            resolved_delivery_target = ""
            delivery_target_source = "default"

    if delivery_time is not None:
        resolved_delivery_time = str(delivery_time).strip()
        delivery_time_source = "function_arg"
    elif "time" in delivery_options:
        resolved_delivery_time = str(delivery_options.get("time") or "").strip()
        delivery_time_source = "entry_options"
    elif "delivery_time" in payload:
        resolved_delivery_time = str(payload.get("delivery_time") or "").strip()
        delivery_time_source = "legacy_payload"
    else:
        resolved_delivery_time = ""
        delivery_time_source = "default"

    return {
        "input": {
            "requested_mode": input_mode,
            "effective_mode": input_mode,
            "selection_source": input_mode_source,
            "inline_candidates_available": _has_items(payload.get("topic_candidates")),
            "inline_normalized_available": _has_items(payload.get("normalized_events")),
            "inline_topic_cards_available": _has_items(payload.get("topic_cards")),
            "real_source_loaded": False,
            "real_source_provider": None,
            "real_source_candidate_count": 0,
            "real_source_requested_source_ids": [],
            "real_source_applied_source_ids": [],
            "real_source_failed_sources": [],
            "user_topic_loaded": False,
            "user_topic_provider": None,
            "user_topic_candidate_count": 0,
        },
        "write": {
            "enabled": write_enabled,
            "enabled_source": write_enabled_source,
            "requested_executor": write_executor,
            "executor": write_executor,
            "executor_source": write_executor_source,
            "operation": write_operation,
            "operation_source": write_operation_source,
        },
        "delivery": {
            "enabled": delivery_enabled,
            "enabled_source": delivery_enabled_source,
            "requested_target_mode": delivery_target_mode,
            "target_mode": delivery_target_mode,
            "target_mode_source": delivery_target_mode_source,
            "channel": resolved_delivery_channel,
            "channel_source": delivery_channel_source,
            "target": resolved_delivery_target,
            "target_source": delivery_target_source,
            "delivery_time": resolved_delivery_time,
            "delivery_time_source": delivery_time_source,
        },
        "degrade": {
            "strategies": {
                "input_unavailable": input_unavailable_strategy,
                "write_unavailable": write_unavailable_strategy,
                "delivery_unavailable": delivery_unavailable_strategy,
            },
            "fallback_triggered": False,
            "fallbacks": [],
        },
    }



def _build_archive_only_delivery_result(
    payload: Dict[str, Any],
    *,
    delivery_time: Optional[str],
    delivery_target: Optional[str],
    runs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    return delivery_build_archive_only_delivery_result(
        payload,
        delivery_time=delivery_time,
        delivery_target=delivery_target,
        runs_root=runs_root,
    )



def _normalize_mode(payload: Dict[str, Any], execution_mode: Optional[str]) -> str:
    raw_mode = execution_mode or payload.get("execution_mode") or OrchestratorExecutionMode.FULL_PIPELINE.value
    normalized = str(raw_mode).strip().lower()
    normalized = _MODE_ALIASES.get(normalized, normalized)
    if normalized not in {mode.value for mode in OrchestratorExecutionMode}:
        raise ValueError(normalized)
    return normalized



def _extract_requested_event_ids(payload: Dict[str, Any]) -> List[str]:
    requested_event_ids: List[str] = []

    for field in ("rerun_event_id", "target_event_id"):
        event_id = str(payload.get(field) or "").strip()
        if event_id:
            requested_event_ids.append(event_id)

    target_event_ids = payload.get("target_event_ids")
    if isinstance(target_event_ids, list):
        requested_event_ids.extend(
            str(item).strip()
            for item in target_event_ids
            if str(item).strip()
        )

    return sorted(dict.fromkeys(requested_event_ids))



def _normalize_trigger_source(payload: Dict[str, Any]) -> str:
    raw_trigger_source = str(payload.get("trigger_source") or "").strip()
    normalized = _TRIGGER_SOURCE_ALIASES.get(raw_trigger_source.lower(), raw_trigger_source.lower()) if raw_trigger_source else ""
    requested_event_ids = _extract_requested_event_ids(payload)

    if requested_event_ids and normalized in {"", OrchestratorTriggerSource.MANUAL.value}:
        return OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value
    if normalized in _VALID_TRIGGER_SOURCES:
        return normalized
    if not raw_trigger_source:
        return OrchestratorTriggerSource.MANUAL.value
    return raw_trigger_source



def _stage_errors(stage: str, result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    errors = result.get("errors")
    if not isinstance(errors, list):
        return []
    collected: List[Dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        collected.append({"stage": stage, **deepcopy(item)})
    return collected



def _collect_errors(*stage_results: Optional[tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for item in stage_results:
        if not item:
            continue
        stage_name, stage_result = item
        collected.extend(_stage_errors(stage_name, stage_result))
    return collected



def _list_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]



def _extract_topic_candidates(crawl_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(crawl_result, dict) and isinstance(crawl_result.get("topic_candidates"), list):
        return _list_dicts(crawl_result.get("topic_candidates"))
    return _list_dicts(payload.get("topic_candidates"))



def _extract_normalized_events(ingest_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(ingest_result, dict) and isinstance(ingest_result.get("normalized_events"), list):
        return _list_dicts(ingest_result.get("normalized_events"))
    return _list_dicts(payload.get("normalized_events"))



def _extract_topic_cards(topic_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(topic_result, dict) and isinstance(topic_result.get("topic_cards"), list):
        return _list_dicts(topic_result.get("topic_cards"))
    return _list_dicts(payload.get("topic_cards"))



def _extract_scored_events(score_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(score_result, dict) and isinstance(score_result.get("scored_events"), list):
        return _list_dicts(score_result.get("scored_events"))
    return _list_dicts(payload.get("scored_events"))



def _extract_content_bundles(write_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(write_result, dict) and isinstance(write_result.get("content_bundles"), list):
        return _list_dicts(write_result.get("content_bundles"))
    if isinstance(payload.get("content_bundles"), list):
        return _list_dicts(payload.get("content_bundles"))
    if isinstance(payload.get("content_bundle"), dict):
        return [deepcopy(payload["content_bundle"])]
    return []



def _extract_delivery_receipt(deliver_result: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if isinstance(deliver_result, dict) and isinstance(deliver_result.get("delivery_receipt"), dict):
        return deepcopy(deliver_result["delivery_receipt"])
    if isinstance(payload.get("delivery_receipt"), dict):
        return deepcopy(payload["delivery_receipt"])
    return None



def _publish_ready_event_ids(scored_events: Sequence[Dict[str, Any]]) -> Set[str]:
    return {
        str(item.get("event_id") or "").strip()
        for item in scored_events
        if isinstance(item, dict) and item.get("status") == ScoreDecisionStatus.PUBLISH_READY.value
    }



def _filter_events_by_ids(events: Sequence[Dict[str, Any]], event_ids: Set[str]) -> List[Dict[str, Any]]:
    return [
        deepcopy(item)
        for item in events
        if isinstance(item, dict) and str(item.get("event_id") or "").strip() in event_ids
    ]



def _collect_event_ids_from_sequence(events: Any) -> Set[str]:
    if not isinstance(events, list):
        return set()
    return {
        str(item.get("event_id") or "").strip()
        for item in events
        if isinstance(item, dict) and str(item.get("event_id") or "").strip()
    }



def _collect_available_event_ids(payload: Dict[str, Any]) -> Set[str]:
    event_ids: Set[str] = set()
    for field in ("topic_candidates", "topic_cards", "normalized_events", "scored_events", "content_bundles"):
        event_ids.update(_collect_event_ids_from_sequence(payload.get(field)))

    content_bundle = payload.get("content_bundle")
    if isinstance(content_bundle, dict):
        content_bundle_id = str(content_bundle.get("event_id") or "").strip()
        if content_bundle_id:
            event_ids.add(content_bundle_id)

    if isinstance(payload.get("delivery_receipt"), dict):
        event_ids.update(_collect_event_ids_from_sequence(payload["delivery_receipt"].get("events")))

    return event_ids



def _filter_payload_for_event_ids(payload: Dict[str, Any], event_ids: Set[str]) -> Dict[str, Any]:
    filtered_payload = deepcopy(payload)

    for field in ("topic_candidates", "topic_cards", "normalized_events", "scored_events", "content_bundles"):
        if isinstance(filtered_payload.get(field), list):
            filtered_payload[field] = _filter_events_by_ids(filtered_payload[field], event_ids)

    if isinstance(filtered_payload.get("content_bundle"), dict):
        content_bundle_id = str(filtered_payload["content_bundle"].get("event_id") or "").strip()
        if content_bundle_id not in event_ids:
            filtered_payload.pop("content_bundle")

    if isinstance(filtered_payload.get("delivery_receipt"), dict):
        receipt_events = filtered_payload["delivery_receipt"].get("events") or []
        filtered_payload["delivery_receipt"]["events"] = _filter_events_by_ids(receipt_events, event_ids)

    filtered_payload["target_event_ids"] = sorted(event_ids)
    if len(event_ids) == 1:
        single_event_id = next(iter(event_ids))
        filtered_payload["target_event_id"] = single_event_id
        filtered_payload["rerun_event_id"] = single_event_id

    return filtered_payload



def _collect_processed_event_ids(
    *,
    topic_candidates: Sequence[Dict[str, Any]],
    topic_cards: Sequence[Dict[str, Any]],
    normalized_events: Sequence[Dict[str, Any]],
    scored_events: Sequence[Dict[str, Any]],
    content_bundles: Sequence[Dict[str, Any]],
    delivery_receipt: Optional[Dict[str, Any]],
) -> List[str]:
    processed_event_ids: Set[str] = set()
    processed_event_ids.update(_collect_event_ids_from_sequence(list(topic_candidates)))
    processed_event_ids.update(_collect_event_ids_from_sequence(list(topic_cards)))
    processed_event_ids.update(_collect_event_ids_from_sequence(list(normalized_events)))
    processed_event_ids.update(_collect_event_ids_from_sequence(list(scored_events)))
    processed_event_ids.update(_collect_event_ids_from_sequence(list(content_bundles)))
    if isinstance(delivery_receipt, dict):
        processed_event_ids.update(_collect_event_ids_from_sequence(delivery_receipt.get("events")))
    return sorted(processed_event_ids)



def _build_delivery_payload(
    payload: Dict[str, Any],
    scored_events: Sequence[Dict[str, Any]],
    normalized_events: Sequence[Dict[str, Any]],
    content_bundles: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    publish_ready_ids = _publish_ready_event_ids(scored_events)
    delivery_payload: Dict[str, Any] = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "delivery_channel": payload.get("delivery_channel"),
        "delivery_target": payload.get("delivery_target"),
        "normalized_events": _filter_events_by_ids(normalized_events, publish_ready_ids),
        "scored_events": _filter_events_by_ids(scored_events, publish_ready_ids),
        "content_bundles": _list_dicts(list(content_bundles)),
    }
    if isinstance(payload.get("target_event_ids"), list):
        delivery_payload["target_event_ids"] = deepcopy(payload.get("target_event_ids"))
    if "simulate_delivery_failure" in payload:
        delivery_payload["simulate_delivery_failure"] = payload.get("simulate_delivery_failure")
    if "delivery_time" in payload:
        delivery_payload["delivery_time"] = payload.get("delivery_time")
    if isinstance(payload.get("output_context"), dict):
        delivery_payload["output_context"] = deepcopy(payload["output_context"])
    if isinstance(payload.get("entry_options"), dict):
        delivery_payload["entry_options"] = deepcopy(payload["entry_options"])
    return delivery_payload



def _resolve_resume_target(payload: Dict[str, Any]) -> str:
    if _extract_content_bundles(None, payload):
        return "deliver"
    if _extract_scored_events(None, payload):
        return "write"
    if _extract_topic_cards(None, payload) or _extract_normalized_events(None, payload):
        return "score"
    return "pipeline"



def _build_write_payload(
    payload: Dict[str, Any],
    *,
    publish_ready_events: Sequence[Dict[str, Any]],
    requested_event_ids: Sequence[str],
    entry_resolution: Dict[str, Any],
) -> Dict[str, Any]:
    write_payload = {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "scored_events": _list_dicts(list(publish_ready_events)),
        "operation": entry_resolution["write"]["operation"],
        "executor": entry_resolution["write"]["executor"],
    }
    if requested_event_ids:
        write_payload["target_event_ids"] = list(requested_event_ids)
    if isinstance(payload.get("content_bundle"), dict):
        write_payload["content_bundle"] = deepcopy(payload["content_bundle"])
    else:
        bundle_candidates = _extract_content_bundles(None, payload)
        if bundle_candidates:
            target_event_ids = {
                str(item.get("event_id") or "").strip()
                for item in publish_ready_events
                if isinstance(item, dict) and str(item.get("event_id") or "").strip()
            }
            if len(target_event_ids) == 1:
                target_event_id = next(iter(target_event_ids))
                for candidate in bundle_candidates:
                    if str(candidate.get("event_id") or "").strip() == target_event_id:
                        write_payload["content_bundle"] = deepcopy(candidate)
                        break
            if "content_bundle" not in write_payload:
                write_payload["content_bundle"] = deepcopy(bundle_candidates[0])
    if isinstance(payload.get("report_profile"), dict):
        write_payload["report_profile"] = deepcopy(payload["report_profile"])
    if isinstance(payload.get("writing_brief"), dict):
        write_payload["writing_brief"] = deepcopy(payload["writing_brief"])
    if isinstance(payload.get("custom_template"), str) and payload.get("custom_template", "").strip():
        write_payload["custom_template"] = str(payload.get("custom_template") or "").strip()
    if isinstance(payload.get("output_context"), dict):
        write_payload["output_context"] = deepcopy(payload["output_context"])
    return write_payload



def _build_stage_statuses(
    *,
    execution_mode: str,
    crawl_result: Optional[Dict[str, Any]],
    ingest_result: Optional[Dict[str, Any]],
    topic_result: Optional[Dict[str, Any]],
    score_result: Optional[Dict[str, Any]],
    write_result: Optional[Dict[str, Any]],
    deliver_result: Optional[Dict[str, Any]],
    skipped_reasons: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    skipped_reasons = skipped_reasons or {}

    crawl_status = OrchestratorStageStatus.SKIPPED.value
    if isinstance(crawl_result, dict):
        crawl_status = (
            OrchestratorStageStatus.SUCCEEDED.value
            if crawl_result.get("run_status") == TopicRunStatus.SUCCEEDED.value
            else OrchestratorStageStatus.FAILED.value
        )

    ingest_status = OrchestratorStageStatus.SKIPPED.value
    if execution_mode != OrchestratorExecutionMode.DELIVER_ONLY.value:
        if skipped_reasons.get("ingest") and not isinstance(ingest_result, dict):
            ingest_status = OrchestratorStageStatus.SKIPPED.value
        else:
            ingest_status = (
                OrchestratorStageStatus.SUCCEEDED.value
                if isinstance(ingest_result, dict) and ingest_result.get("run_status") == IngestRunStatus.ACCEPTED.value
                else OrchestratorStageStatus.FAILED.value
            )

    topics_status = OrchestratorStageStatus.SKIPPED.value
    if isinstance(topic_result, dict):
        topics_status = (
            OrchestratorStageStatus.SUCCEEDED.value
            if topic_result.get("run_status") == TopicRunStatus.SUCCEEDED.value
            else OrchestratorStageStatus.FAILED.value
        )

    score_status = OrchestratorStageStatus.SKIPPED.value
    if execution_mode != OrchestratorExecutionMode.DELIVER_ONLY.value and isinstance(score_result, dict):
        score_status = (
            OrchestratorStageStatus.SUCCEEDED.value
            if score_result.get("run_status") == ScoreRunStatus.SUCCEEDED.value
            else OrchestratorStageStatus.FAILED.value
        )

    write_status = OrchestratorStageStatus.SKIPPED.value
    if isinstance(write_result, dict):
        write_status = (
            OrchestratorStageStatus.SUCCEEDED.value
            if write_result.get("run_status") == WriteRunStatus.SUCCEEDED.value
            else OrchestratorStageStatus.FAILED.value
        )

    deliver_status = OrchestratorStageStatus.SKIPPED.value
    if isinstance(deliver_result, dict):
        deliver_status = (
            OrchestratorStageStatus.SUCCEEDED.value
            if deliver_result.get("run_status") == OrchestratorRunStatus.COMPLETED.value
            else OrchestratorStageStatus.FAILED.value
        )

    delivery_receipt = _extract_delivery_receipt(deliver_result, {})

    return {
        "crawl": {
            "status": crawl_status,
            "summary": {
                "candidate_count": int((crawl_result or {}).get("candidate_count", 0)) if isinstance(crawl_result, dict) else 0,
                "input_mode": (crawl_result or {}).get("input_mode") if isinstance(crawl_result, dict) else None,
            },
            "errors": _stage_errors("crawl", crawl_result),
            "skipped_reason": skipped_reasons.get("crawl"),
        },
        "ingest": {
            "status": ingest_status,
            "summary": {
                "accepted_count": int((ingest_result or {}).get("accepted_count", 0)) if isinstance(ingest_result, dict) else 0,
                "rejected_count": int((ingest_result or {}).get("rejected_count", 0)) if isinstance(ingest_result, dict) else 0,
            },
            "errors": _stage_errors("ingest", ingest_result),
            "skipped_reason": skipped_reasons.get("ingest"),
        },
        "topics": {
            "status": topics_status,
            "summary": {
                "topic_card_count": int((topic_result or {}).get("topic_card_count", 0)) if isinstance(topic_result, dict) else 0,
            },
            "errors": _stage_errors("topics", topic_result),
            "skipped_reason": skipped_reasons.get("topics"),
        },
        "score": {
            "status": score_status,
            "summary": {
                "scored_event_count": len(_extract_scored_events(score_result, {})),
                "decision_counts": deepcopy((score_result or {}).get("decision_counts") or {}),
            },
            "errors": _stage_errors("score", score_result),
            "skipped_reason": skipped_reasons.get("score"),
        },
        "write": {
            "status": write_status,
            "summary": {
                "operation": (write_result or {}).get("operation") if isinstance(write_result, dict) else None,
                "content_bundle_count": len(_extract_content_bundles(write_result, {})),
            },
            "errors": _stage_errors("write", write_result),
            "skipped_reason": skipped_reasons.get("write"),
        },
        "deliver": {
            "status": deliver_status,
            "summary": {
                "event_count": len((delivery_receipt or {}).get("events") or []),
                "failed_count": int((delivery_receipt or {}).get("failed_count", 0)) if isinstance(delivery_receipt, dict) else 0,
                "delivery_channel": (delivery_receipt or {}).get("delivery_channel") if isinstance(delivery_receipt, dict) else None,
                "delivery_target": (delivery_receipt or {}).get("delivery_target") if isinstance(delivery_receipt, dict) else None,
            },
            "errors": _stage_errors("deliver", deliver_result),
            "skipped_reason": skipped_reasons.get("deliver"),
        },
    }



def _build_artifact_summary(
    *,
    topic_candidates: Sequence[Dict[str, Any]],
    topic_cards: Sequence[Dict[str, Any]],
    normalized_events: Sequence[Dict[str, Any]],
    scored_events: Sequence[Dict[str, Any]],
    content_bundles: Sequence[Dict[str, Any]],
    delivery_receipt: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    decision_counts: Dict[str, int] = {}
    for event in scored_events:
        decision = str(event.get("status") or "").strip()
        if not decision:
            continue
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    delivered_count = 0
    failed_delivery_count = 0
    if isinstance(delivery_receipt, dict):
        for item in delivery_receipt.get("events") or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "delivered":
                delivered_count += 1
            elif item.get("status") == "failed":
                failed_delivery_count += 1

    return {
        "crawl_candidate_count": len(topic_candidates),
        "topic_card_count": len(topic_cards),
        "normalized_event_count": len(normalized_events),
        "scored_event_count": len(scored_events),
        "publish_ready_count": len(_publish_ready_event_ids(scored_events)),
        "content_bundle_count": len(content_bundles),
        "delivered_count": delivered_count,
        "delivery_failed_count": failed_delivery_count,
        "decision_counts": decision_counts,
    }



def _build_event_statuses(
    *,
    payload: Dict[str, Any],
    request_id: Optional[str],
    ingest_result: Optional[Dict[str, Any]],
    normalized_events: Sequence[Dict[str, Any]],
    scored_events: Sequence[Dict[str, Any]],
    content_bundles: Sequence[Dict[str, Any]],
    delivery_receipt: Optional[Dict[str, Any]],
    score_result: Optional[Dict[str, Any]] = None,
    write_result: Optional[Dict[str, Any]] = None,
    skipped_reasons: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    event_index: Dict[str, Dict[str, Any]] = {}
    skipped_reasons = skipped_reasons or {}

    def ensure(event_id: str) -> Dict[str, Any]:
        if event_id not in event_index:
            event_index[event_id] = {
                "request_id": request_id,
                "event_id": event_id,
                "event_title": "",
                "ingest_status": None,
                "score_status": None,
                "write_status": None,
                "deliver_status": None,
                "decision_status": None,
                "stage_reasons": {},
                "artifact_summary": {
                    "timeline_points": 0,
                    "fact_points": 0,
                    "has_content_bundle": False,
                    "delivery_receipt_status": None,
                },
                "errors": [],
            }
        return event_index[event_id]

    def note(entry: Dict[str, Any], stage: str, reason: Optional[str]) -> None:
        if reason:
            entry["stage_reasons"][stage] = reason

    def seed_from_payload_candidates() -> None:
        for event in payload.get("topic_candidates") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            entry = ensure(event_id)
            entry["event_title"] = str(event.get("event_title") or entry["event_title"] or "").strip()

        for event in payload.get("normalized_events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            entry = ensure(event_id)
            entry["event_title"] = str(event.get("event_title") or entry["event_title"] or "").strip()

        for event in payload.get("scored_events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            entry = ensure(event_id)
            entry["event_title"] = str(event.get("event_title") or entry["event_title"] or "").strip()
            entry["decision_status"] = str(event.get("status") or entry["decision_status"] or "").strip() or entry["decision_status"]

        for bundle in _extract_content_bundles(None, payload):
            event_id = str(bundle.get("event_id") or "").strip()
            if not event_id:
                continue
            ensure(event_id)

        payload_decision_status = str(payload.get("decision_status") or "").strip() or None
        if payload_decision_status:
            for entry in event_index.values():
                if entry["decision_status"] is None:
                    entry["decision_status"] = payload_decision_status

    def attach_stage_errors(stage: str, result: Optional[Dict[str, Any]], *, publish_ready_only: bool = False) -> None:
        stage_errors = _stage_errors(stage, result)
        if not stage_errors:
            return
        for entry in event_index.values():
            if publish_ready_only and entry.get("decision_status") != ScoreDecisionStatus.PUBLISH_READY.value:
                continue
            entry["errors"].extend(deepcopy(stage_errors))

    seed_from_payload_candidates()

    for event in normalized_events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        entry = ensure(event_id)
        entry["event_title"] = str(event.get("event_title") or entry["event_title"] or "").strip()
        entry["ingest_status"] = str(event.get("status") or IngestRunStatus.ACCEPTED.value).strip()

    for event in scored_events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        entry = ensure(event_id)
        entry["event_title"] = str(event.get("event_title") or entry["event_title"] or "").strip()
        entry["score_status"] = str(event.get("status") or "").strip() or None
        entry["decision_status"] = str(event.get("status") or entry["decision_status"] or "").strip() or None
        entry["artifact_summary"]["timeline_points"] = len(event.get("timeline") or []) if isinstance(event.get("timeline"), list) else 0
        entry["artifact_summary"]["fact_points"] = len(event.get("fact_points") or []) if isinstance(event.get("fact_points"), list) else 0

    for bundle in content_bundles:
        event_id = str(bundle.get("event_id") or "").strip()
        if not event_id:
            continue
        entry = ensure(event_id)
        entry["write_status"] = str(bundle.get("content_status") or "").strip() or None
        entry["artifact_summary"]["has_content_bundle"] = True

    if isinstance(delivery_receipt, dict):
        for receipt in delivery_receipt.get("events") or []:
            if not isinstance(receipt, dict):
                continue
            event_id = str(receipt.get("event_id") or "").strip()
            if not event_id:
                continue
            entry = ensure(event_id)
            entry["deliver_status"] = str(receipt.get("status") or "").strip() or None
            entry["artifact_summary"]["delivery_receipt_status"] = entry["deliver_status"]
            failure_info = receipt.get("failure_info")
            if isinstance(failure_info, dict):
                entry["errors"].append(deepcopy(failure_info))
                note(entry, "deliver", str(failure_info.get("message") or failure_info.get("code") or "").strip())

    ingest_rejected = isinstance(ingest_result, dict) and ingest_result.get("run_status") == IngestRunStatus.REJECTED.value
    if ingest_rejected:
        for entry in event_index.values():
            if entry["ingest_status"] is None:
                entry["ingest_status"] = IngestRunStatus.REJECTED.value
                note(entry, "ingest", "ingest rejected")
            if entry["score_status"] is None:
                entry["score_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "score", skipped_reasons.get("score") or "ingest rejected; score not executed")
            if entry["write_status"] is None:
                entry["write_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "write", skipped_reasons.get("write") or "ingest rejected; write not executed")
            if entry["deliver_status"] is None:
                entry["deliver_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "deliver", skipped_reasons.get("deliver") or "ingest rejected; deliver not executed")
        attach_stage_errors("ingest", ingest_result)
    elif skipped_reasons.get("ingest"):
        for entry in event_index.values():
            if entry["ingest_status"] is None:
                entry["ingest_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "ingest", skipped_reasons.get("ingest"))

    score_failed = isinstance(score_result, dict) and score_result.get("run_status") != ScoreRunStatus.SUCCEEDED.value
    if score_failed:
        for entry in event_index.values():
            if entry["score_status"] is None:
                entry["score_status"] = OrchestratorStageStatus.FAILED.value
                note(entry, "score", "score failed")
            if entry["write_status"] is None:
                entry["write_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "write", skipped_reasons.get("write") or "score failed; write not executed")
            if entry["deliver_status"] is None:
                entry["deliver_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "deliver", skipped_reasons.get("deliver") or "score failed; deliver not executed")
        attach_stage_errors("score", score_result)
    elif skipped_reasons.get("score"):
        for entry in event_index.values():
            if entry["score_status"] is None:
                entry["score_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "score", skipped_reasons.get("score"))

    for entry in event_index.values():
        if entry["decision_status"] and entry["decision_status"] != ScoreDecisionStatus.PUBLISH_READY.value:
            if entry["write_status"] is None:
                entry["write_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "write", skipped_reasons.get("write") or "decision_status is not publish_ready; write skipped")
            if entry["deliver_status"] is None:
                entry["deliver_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "deliver", skipped_reasons.get("deliver") or "decision_status is not publish_ready; deliver skipped")

    write_failed = isinstance(write_result, dict) and write_result.get("run_status") != WriteRunStatus.SUCCEEDED.value
    if write_failed:
        for entry in event_index.values():
            if entry["decision_status"] == ScoreDecisionStatus.PUBLISH_READY.value and entry["write_status"] is None:
                entry["write_status"] = OrchestratorStageStatus.FAILED.value
                note(entry, "write", "write failed")
            if entry["decision_status"] == ScoreDecisionStatus.PUBLISH_READY.value and entry["deliver_status"] is None:
                entry["deliver_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "deliver", skipped_reasons.get("deliver") or "write failed; deliver not executed")
        attach_stage_errors("write", write_result, publish_ready_only=True)
    elif skipped_reasons.get("write"):
        for entry in event_index.values():
            if entry["write_status"] is None:
                entry["write_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "write", skipped_reasons.get("write"))

    if skipped_reasons.get("deliver"):
        for entry in event_index.values():
            if entry["deliver_status"] is None:
                entry["deliver_status"] = OrchestratorStageStatus.SKIPPED.value
                note(entry, "deliver", skipped_reasons.get("deliver"))

    return [event_index[key] for key in sorted(event_index)]



def _build_orchestrator_error(
    *,
    code: OrchestratorErrorCode,
    message: str,
    missing_fields: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "stage": "orchestrator",
        "code": code.value,
        "message": message,
        "missing_fields": [str(item) for item in (missing_fields or [])],
    }



def _persist_run_outputs(
    *,
    payload: Dict[str, Any],
    entry_resolution: Optional[Dict[str, Any]],
    stage_statuses: Dict[str, Dict[str, Any]],
    artifact_summary: Dict[str, Any],
    run_summary: Dict[str, Any],
    errors: List[Dict[str, Any]],
    crawl_results: Optional[Dict[str, Any]],
    topic_cards: Sequence[Dict[str, Any]],
    normalized_events: Sequence[Dict[str, Any]],
    scored_events: Sequence[Dict[str, Any]],
    content_bundles: Sequence[Dict[str, Any]],
    delivery_receipt: Optional[Dict[str, Any]],
    score_results: Optional[Dict[str, Any]],
    delivery_result: Optional[Dict[str, Any]],
    notification_result: Optional[Dict[str, Any]],
    stage_results: Dict[str, Any],
) -> Dict[str, str]:
    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    output_root = output_context.get("output_root")
    if not output_root:
        return {}

    output_root_path = Path(output_root)
    debug_root = Path(output_context.get("debug_root") or (output_root_path / "debug"))
    reports_root = Path(output_context.get("reports_root") or (output_root_path / "reports"))
    recovery_root = Path(output_context.get("recovery_root") or (output_root_path / "recovery"))
    summary_path = Path(output_context.get("summary_path") or (output_root_path / "summary.json"))
    latest_path = Path(output_context.get("latest_path") or (output_root_path.parent / "latest.json"))
    recovery_summary_path = Path(output_context.get("recovery_summary_path") or (recovery_root / "recovery_summary.json"))

    manifest: Dict[str, str] = {}

    def persist(path: Path, payload_obj: Any) -> None:
        _write_json(path, payload_obj)
        manifest[_relative_path(path) or path.resolve().as_posix()] = _relative_path(path) or path.resolve().as_posix()

    debug_payload = {
        "input": deepcopy(payload),
        "entry_resolution": deepcopy(entry_resolution) if isinstance(entry_resolution, dict) else None,
        "stage_statuses": deepcopy(stage_statuses),
        "artifact_summary": deepcopy(artifact_summary),
        "errors": deepcopy(errors),
        "output_context": deepcopy(output_context),
        "crawl": deepcopy(crawl_results) if isinstance(crawl_results, dict) else None,
        "topics": deepcopy(topic_cards),
        "ingest": deepcopy(normalized_events),
        "scored_events": deepcopy(scored_events),
        "score": deepcopy(score_results) if isinstance(score_results, dict) else None,
        "content_bundles": deepcopy(content_bundles),
        "writer_receipts": deepcopy((stage_results.get("write") or {}).get("writer_receipts") or []),
        "write": deepcopy(stage_results.get("write")) if isinstance(stage_results.get("write"), dict) else None,
        "delivery_receipt": deepcopy(delivery_receipt) if isinstance(delivery_receipt, dict) else None,
        "deliver": deepcopy(delivery_result) if isinstance(delivery_result, dict) else None,
        "notification": deepcopy(notification_result) if isinstance(notification_result, dict) else None,
    }

    persist(debug_root / "input.json", debug_payload["input"])
    if debug_payload["entry_resolution"] is not None:
        persist(debug_root / "entry_resolution.json", debug_payload["entry_resolution"])
    persist(debug_root / "stage_statuses.json", debug_payload["stage_statuses"])
    persist(debug_root / "artifact_summary.json", debug_payload["artifact_summary"])
    persist(debug_root / "errors.json", debug_payload["errors"])
    persist(debug_root / "output_context.json", debug_payload["output_context"])
    persist(debug_root / "crawl.json", debug_payload["crawl"])
    persist(debug_root / "topics.json", debug_payload["topics"])
    persist(debug_root / "ingest.json", debug_payload["ingest"])
    persist(debug_root / "scored_events.json", debug_payload["scored_events"])
    persist(debug_root / "score.json", debug_payload["score"])
    persist(debug_root / "content_bundles.json", debug_payload["content_bundles"])
    persist(debug_root / "writer_receipts.json", debug_payload["writer_receipts"])
    persist(debug_root / "write.json", debug_payload["write"])
    persist(debug_root / "delivery_receipt.json", debug_payload["delivery_receipt"])
    persist(debug_root / "deliver.json", debug_payload["deliver"])
    persist(debug_root / "notification.json", debug_payload["notification"])
    persist(summary_path, deepcopy(run_summary))
    persist(recovery_summary_path, {
        "recovery_used": bool((run_summary or {}).get("recovery_used")),
        "failed_event_count": int((run_summary or {}).get("failed_event_count", 0) or 0),
        "recovered_event_count": int((run_summary or {}).get("recovered_event_count", 0) or 0),
        "failed_event_ids": list((run_summary or {}).get("failed_event_ids") or []),
        "recovered_event_ids": list((run_summary or {}).get("recovered_event_ids") or []),
        "final_status": str((run_summary or {}).get("status") or "").strip() or None,
    })
    persist(latest_path, {
        "mode": output_context.get("mode"),
        "latest_run": output_context.get("run_id"),
        "status": run_summary.get("status"),
        "summary_path": f"{output_context.get('run_id')}/summary.json",
    })

    if isinstance(crawl_results, dict):
        persist(reports_root / "crawl_results.json", deepcopy(crawl_results))
    if topic_cards:
        persist(reports_root / "topic_cards.json", deepcopy(list(topic_cards)))
    if normalized_events:
        persist(reports_root / "normalized_events.json", deepcopy(list(normalized_events)))
    if scored_events:
        persist(reports_root / "scored_events.json", deepcopy(list(scored_events)))
    if isinstance(score_results, dict):
        persist(reports_root / "score_results.json", deepcopy(score_results))
    if content_bundles:
        persist(debug_root / "content_bundles.json", deepcopy(list(content_bundles)))
    write_stage = stage_results.get("write") if isinstance(stage_results.get("write"), dict) else None
    if isinstance(write_stage, dict):
        if isinstance(write_stage.get("writer_receipts"), list):
            persist(debug_root / "writer_receipts.json", deepcopy(write_stage.get("writer_receipts") or []))
        persist(debug_root / "write.json", deepcopy(write_stage))
    if isinstance(delivery_receipt, dict):
        persist(debug_root / "delivery_receipt.json", deepcopy(delivery_receipt))
    if isinstance(delivery_result, dict):
        persist(debug_root / "deliver.json", deepcopy(delivery_result))
    if isinstance(notification_result, dict):
        persist(debug_root / "notification.json", deepcopy(notification_result))

    return manifest



def _notify_final_result(result: Dict[str, Any], *, payload: Dict[str, Any], runs_root: Optional[Path]) -> Dict[str, Any]:
    notification_payload = deepcopy(result)
    if isinstance(payload.get("entry_options"), dict):
        notification_payload["entry_options"] = deepcopy(payload["entry_options"])
    notification_result = topic_radar_notify(
        build_notification_payload(notification_payload),
        runs_root=runs_root,
    )
    final_result = deepcopy(result)
    final_result["notification_result"] = notification_result
    final_result["notification_receipt"] = deepcopy(notification_result.get("notification_receipt"))
    return final_result



def _finalize_orchestration(
    *,
    payload: Dict[str, Any],
    execution_mode: str,
    final_stage: str,
    run_status: str,
    decision_status: str,
    crawl_result: Optional[Dict[str, Any]] = None,
    ingest_result: Optional[Dict[str, Any]] = None,
    topic_result: Optional[Dict[str, Any]] = None,
    score_result: Optional[Dict[str, Any]] = None,
    write_result: Optional[Dict[str, Any]] = None,
    deliver_result: Optional[Dict[str, Any]] = None,
    skipped_reasons: Optional[Dict[str, str]] = None,
    extra_errors: Optional[List[Dict[str, Any]]] = None,
    requested_event_ids: Optional[Sequence[str]] = None,
    entry_resolution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_id = str(
        (deliver_result or {}).get("request_id")
        or (write_result or {}).get("request_id")
        or (score_result or {}).get("request_id")
        or (topic_result or {}).get("request_id")
        or (ingest_result or {}).get("request_id")
        or (crawl_result or {}).get("request_id")
        or payload.get("request_id")
        or ""
    ).strip()
    raw_trigger_source = str(
        (deliver_result or {}).get("trigger_source")
        or (write_result or {}).get("trigger_source")
        or (score_result or {}).get("trigger_source")
        or (topic_result or {}).get("trigger_source")
        or (ingest_result or {}).get("trigger_source")
        or (crawl_result or {}).get("trigger_source")
        or payload.get("trigger_source")
        or ""
    ).strip()
    trigger_source = _normalize_trigger_source({"trigger_source": raw_trigger_source, "target_event_ids": requested_event_ids or []})

    crawl_results = deepcopy(crawl_result) if isinstance(crawl_result, dict) else None
    topic_candidates = _extract_topic_candidates(crawl_results, payload)
    normalized_events = _extract_normalized_events(ingest_result, payload)
    topic_cards = _extract_topic_cards(topic_result, payload)
    scored_events = _extract_scored_events(score_result, payload)
    content_bundles = _extract_content_bundles(write_result, payload)
    delivery_receipt = _extract_delivery_receipt(deliver_result, payload)

    errors = _collect_errors(
        ("crawl", crawl_result) if isinstance(crawl_result, dict) else None,
        ("ingest", ingest_result) if isinstance(ingest_result, dict) else None,
        ("topics", topic_result) if isinstance(topic_result, dict) else None,
        ("score", score_result) if isinstance(score_result, dict) else None,
        ("write", write_result) if isinstance(write_result, dict) else None,
        ("deliver", deliver_result) if isinstance(deliver_result, dict) else None,
    )
    if extra_errors:
        errors.extend(deepcopy(extra_errors))

    requested_event_ids_list = sorted(
        {
            str(item).strip()
            for item in (requested_event_ids or [])
            if str(item).strip()
        }
    )
    stage_statuses = _build_stage_statuses(
        execution_mode=execution_mode,
        crawl_result=crawl_results,
        ingest_result=ingest_result,
        topic_result=topic_result,
        score_result=score_result,
        write_result=write_result,
        deliver_result=deliver_result,
        skipped_reasons=skipped_reasons,
    )
    artifact_summary = _build_artifact_summary(
        topic_candidates=topic_candidates,
        topic_cards=topic_cards,
        normalized_events=normalized_events,
        scored_events=scored_events,
        content_bundles=content_bundles,
        delivery_receipt=delivery_receipt,
    )
    processed_event_ids = _collect_processed_event_ids(
        topic_candidates=topic_candidates,
        topic_cards=topic_cards,
        normalized_events=normalized_events,
        scored_events=scored_events,
        content_bundles=content_bundles,
        delivery_receipt=delivery_receipt,
    )
    event_statuses = _build_event_statuses(
        payload=payload,
        request_id=request_id or None,
        ingest_result=ingest_result,
        normalized_events=normalized_events,
        scored_events=scored_events,
        content_bundles=content_bundles,
        delivery_receipt=delivery_receipt,
        score_result=score_result,
        write_result=write_result,
        skipped_reasons=skipped_reasons,
    )

    output_context = deepcopy(payload.get("output_context")) if isinstance(payload.get("output_context"), dict) else None
    completed_at = _utc_timestamp()
    run_summary = {
        "mode": (output_context or {}).get("mode") or execution_mode,
        "run_id": (output_context or {}).get("run_id"),
        "request_id": request_id,
        "status": run_status,
        "final_stage": final_stage,
        "started_at": (output_context or {}).get("started_at"),
        "completed_at": completed_at,
        "candidate_count": int(artifact_summary.get("crawl_candidate_count", 0) or 0),
        "publish_ready_count": int(artifact_summary.get("publish_ready_count", 0) or 0),
        "write_success_count": int(artifact_summary.get("content_bundle_count", 0) or 0),
        "deliver_success_count": int(artifact_summary.get("delivered_count", 0) or 0),
        "recovery_used": bool(
            (deliver_result or {}).get("recovery_used")
            or (write_result or {}).get("recovery_used")
            or (score_result or {}).get("recovery_used")
            or payload.get("recovery_used")
        ),
        "main_reports_path": "reports/",
        "debug_path": "debug/",
    }
    stage_results = {
        "crawl": deepcopy(crawl_result) if isinstance(crawl_result, dict) else None,
        "ingest": deepcopy(ingest_result) if isinstance(ingest_result, dict) else None,
        "topics": deepcopy(topic_result) if isinstance(topic_result, dict) else None,
        "score": deepcopy(score_result) if isinstance(score_result, dict) else None,
        "write": deepcopy(write_result) if isinstance(write_result, dict) else None,
        "deliver": deepcopy(deliver_result) if isinstance(deliver_result, dict) else None,
    }
    notification_result = _notify_final_result(
        {
            "request_id": request_id,
            "trigger_source": trigger_source,
            "trigger_context": {
                "source": trigger_source,
                "is_single_event_rerun": trigger_source == OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
                "target_event_ids": requested_event_ids_list,
            },
            "execution_mode": execution_mode,
            "run_status": run_status,
            "decision_status": decision_status,
            "final_stage": final_stage,
            "entry_resolution": deepcopy(entry_resolution) if isinstance(entry_resolution, dict) else None,
            "stage_statuses": stage_statuses,
            "artifact_summary": artifact_summary,
            "requested_event_ids": requested_event_ids_list,
            "processed_event_ids": processed_event_ids,
            "event_statuses": event_statuses,
            "crawl_results": crawl_results,
            "topic_cards": topic_cards,
            "normalized_events": normalized_events,
            "scored_events": scored_events,
            "content_bundles": content_bundles,
            "delivery_receipt": delivery_receipt,
            "score_results": deepcopy(score_result) if isinstance(score_result, dict) else None,
            "delivery_result": deepcopy(deliver_result) if isinstance(deliver_result, dict) else None,
            "run_summary": deepcopy(run_summary),
            "stage_results": deepcopy(stage_results),
            "errors": errors,
            "output_context": output_context,
            "output_root": (output_context or {}).get("output_root"),
        },
        payload=payload,
        runs_root=Path((output_context or {}).get("output_root")) if (output_context or {}).get("output_root") else None,
    )["notification_result"]
    if isinstance(notification_result.get("notification_receipt"), dict):
        run_summary["notification_receipt"] = deepcopy(notification_result["notification_receipt"])

    output_manifest = _persist_run_outputs(
        payload=payload,
        entry_resolution=entry_resolution,
        stage_statuses=stage_statuses,
        artifact_summary=artifact_summary,
        run_summary=run_summary,
        errors=errors,
        crawl_results=crawl_results,
        topic_cards=topic_cards,
        normalized_events=normalized_events,
        scored_events=scored_events,
        content_bundles=content_bundles,
        delivery_receipt=delivery_receipt,
        score_results=deepcopy(score_result) if isinstance(score_result, dict) else None,
        delivery_result=deepcopy(deliver_result) if isinstance(deliver_result, dict) else None,
        notification_result=deepcopy(notification_result),
        stage_results=stage_results,
    )

    result = {
        "request_id": request_id,
        "trigger_source": trigger_source,
        "trigger_context": {
            "source": trigger_source,
            "is_single_event_rerun": trigger_source == OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value,
            "target_event_ids": requested_event_ids_list,
        },
        "execution_mode": execution_mode,
        "run_status": run_status,
        "decision_status": decision_status,
        "final_stage": final_stage,
        "entry_resolution": deepcopy(entry_resolution) if isinstance(entry_resolution, dict) else None,
        "stage_statuses": stage_statuses,
        "artifact_summary": artifact_summary,
        "requested_event_ids": requested_event_ids_list,
        "processed_event_ids": processed_event_ids,
        "event_statuses": event_statuses,
        "crawl_results": crawl_results,
        "topic_cards": topic_cards,
        "normalized_events": normalized_events,
        "scored_events": scored_events,
        "content_bundles": content_bundles,
        "delivery_receipt": delivery_receipt,
        "score_results": deepcopy(score_result) if isinstance(score_result, dict) else None,
        "delivery_result": deepcopy(deliver_result) if isinstance(deliver_result, dict) else None,
        "run_summary": run_summary,
        "stage_results": stage_results,
        "notification_result": deepcopy(notification_result),
        "notification_receipt": deepcopy(notification_result.get("notification_receipt")),
        "errors": errors,
        "output_context": output_context,
        "output_root": (output_context or {}).get("output_root"),
        "output_manifest": output_manifest,
    }
    return result



def topic_radar_orchestrate(
    payload: Dict[str, Any],
    *,
    execution_mode: Optional[str] = None,
    delivery_channel: Optional[str] = None,
    delivery_target: Optional[str] = None,
    delivery_time: Optional[str] = None,
    runs_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """执行阶段七统一编排主链路，统一收口真实输入、写作、交付与降级选择。"""

    working_payload = deepcopy(payload)
    requested_event_ids = _extract_requested_event_ids(working_payload)
    working_payload["trigger_source"] = _normalize_trigger_source(working_payload)

    try:
        resolved_mode = _normalize_mode(working_payload, execution_mode)
    except ValueError as exc:
        invalid_mode = str(exc).strip()
        return _finalize_orchestration(
            payload=working_payload,
            execution_mode=invalid_mode or str(execution_mode or working_payload.get("execution_mode") or "").strip(),
            final_stage="orchestrator",
            run_status=OrchestratorRunStatus.FAILED.value,
            decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
            skipped_reasons={
                "ingest": "orchestrator validation failed",
                "score": "orchestrator validation failed",
                "write": "orchestrator validation failed",
                "deliver": "orchestrator validation failed",
            },
            extra_errors=[
                _build_orchestrator_error(
                    code=OrchestratorErrorCode.INVALID_EXECUTION_MODE,
                    message=f"unsupported execution_mode: {invalid_mode}",
                )
            ],
            requested_event_ids=requested_event_ids,
        )

    try:
        entry_resolution = _build_entry_resolution(
            working_payload,
            execution_mode=resolved_mode,
            delivery_channel=delivery_channel,
            delivery_target=delivery_target,
            delivery_time=delivery_time,
        )
    except ValueError as exc:
        option_error = str(exc).strip()
        option_path, _, option_value = option_error.partition(":")
        return _finalize_orchestration(
            payload=working_payload,
            execution_mode=resolved_mode,
            final_stage="orchestrator",
            run_status=OrchestratorRunStatus.FAILED.value,
            decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
            skipped_reasons={
                "ingest": "orchestrator validation failed",
                "score": "orchestrator validation failed",
                "write": "orchestrator validation failed",
                "deliver": "orchestrator validation failed",
            },
            extra_errors=[
                _build_orchestrator_error(
                    code=OrchestratorErrorCode.INVALID_ENTRY_OPTION,
                    message=f"unsupported {option_path}: {option_value}",
                    missing_fields=[option_path] if option_path else [],
                )
            ],
            requested_event_ids=requested_event_ids,
        )

    working_payload["output_context"] = _resolve_output_context(
        working_payload,
        runs_root,
        mode=entry_resolution["input"]["effective_mode"],
    )

    if working_payload["trigger_source"] == OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value:
        if not requested_event_ids:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="orchestrator",
                run_status=OrchestratorRunStatus.FAILED.value,
                decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                skipped_reasons={
                    "ingest": "orchestrator validation failed",
                    "score": "orchestrator validation failed",
                    "write": "orchestrator validation failed",
                    "deliver": "orchestrator validation failed",
                },
                extra_errors=[
                    _build_orchestrator_error(
                        code=OrchestratorErrorCode.MISSING_TARGET_EVENT_ID,
                        message="single_event_rerun requires target_event_id or target_event_ids",
                        missing_fields=["target_event_id"],
                    )
                ],
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        available_event_ids = _collect_available_event_ids(working_payload)
        missing_target_event_ids = sorted(set(requested_event_ids) - available_event_ids)
        if missing_target_event_ids:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="orchestrator",
                run_status=OrchestratorRunStatus.FAILED.value,
                decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                skipped_reasons={
                    "ingest": "orchestrator validation failed",
                    "score": "orchestrator validation failed",
                    "write": "orchestrator validation failed",
                    "deliver": "orchestrator validation failed",
                },
                extra_errors=[
                    _build_orchestrator_error(
                        code=OrchestratorErrorCode.TARGET_EVENT_NOT_FOUND,
                        message=f"target events not found: {', '.join(missing_target_event_ids)}",
                        missing_fields=missing_target_event_ids,
                    )
                ],
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        working_payload = _filter_payload_for_event_ids(working_payload, set(requested_event_ids))

    if resolved_mode == OrchestratorExecutionMode.DELIVER_ONLY.value:
        delivery_resolution = entry_resolution["delivery"]
        if not delivery_resolution["enabled"]:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="deliver",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(working_payload.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value).strip(),
                skipped_reasons={
                    "write": "deliver_only mode skips write",
                    "score": "deliver_only mode skips score",
                    "ingest": "deliver_only mode skips ingest",
                    "deliver": "entry_options.delivery.enabled=false; deliver skipped",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        deliver_payload = deepcopy(working_payload)
        resolved_delivery_time = delivery_resolution["delivery_time"] or None
        resolved_delivery_channel = delivery_resolution["channel"] or None
        resolved_delivery_target = delivery_resolution["target"] or None

        if delivery_resolution["target_mode"] == "archive_only":
            deliver_result = _build_archive_only_delivery_result(
                deliver_payload,
                delivery_time=resolved_delivery_time,
                delivery_target=resolved_delivery_target,
                runs_root=runs_root,
            )
            return _finalize_orchestration(
                payload=deliver_payload,
                execution_mode=resolved_mode,
                final_stage="deliver",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(deliver_result.get("decision_status") or working_payload.get("decision_status") or "").strip(),
                deliver_result=deliver_result,
                skipped_reasons={
                    "write": "deliver_only mode skips write",
                    "score": "deliver_only mode skips score",
                    "ingest": "deliver_only mode skips ingest",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if resolved_delivery_channel and resolved_delivery_channel not in {"feishu", "wechat", "wechat_official_account"}:
            if entry_resolution["degrade"]["strategies"]["delivery_unavailable"] == "archive_only":
                _record_entry_fallback(
                    entry_resolution,
                    category="delivery",
                    requested=delivery_resolution["target_mode"],
                    applied="archive_only",
                    reason=f"delivery channel '{resolved_delivery_channel}' is unavailable; fallback to archive_only",
                )
                delivery_resolution["target_mode"] = "archive_only"
                delivery_resolution["channel"] = "archive_only"
                deliver_result = _build_archive_only_delivery_result(
                    deliver_payload,
                    delivery_time=resolved_delivery_time,
                    delivery_target=resolved_delivery_target or "archive://clawradar",
                    runs_root=runs_root,
                )
                return _finalize_orchestration(
                    payload=deliver_payload,
                    execution_mode=resolved_mode,
                    final_stage="deliver",
                    run_status=OrchestratorRunStatus.COMPLETED.value,
                    decision_status=str(deliver_result.get("decision_status") or working_payload.get("decision_status") or "").strip(),
                    deliver_result=deliver_result,
                    skipped_reasons={
                        "write": "deliver_only mode skips write",
                        "score": "deliver_only mode skips score",
                        "ingest": "deliver_only mode skips ingest",
                    },
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )

            return _finalize_orchestration(
                payload=deliver_payload,
                execution_mode=resolved_mode,
                final_stage="deliver",
                run_status=OrchestratorRunStatus.FAILED.value,
                decision_status=str(working_payload.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value).strip(),
                skipped_reasons={
                    "write": "deliver_only mode skips write",
                    "score": "deliver_only mode skips score",
                    "ingest": "deliver_only mode skips ingest",
                },
                extra_errors=[
                    _build_orchestrator_error(
                        code=OrchestratorErrorCode.INVALID_ENTRY_OPTION,
                        message=f"unsupported entry_options.delivery.channel: {resolved_delivery_channel}",
                        missing_fields=["entry_options.delivery.channel"],
                    )
                ],
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if resolved_delivery_channel is not None:
            deliver_payload["delivery_channel"] = resolved_delivery_channel
        if resolved_delivery_target is not None:
            deliver_payload["delivery_target"] = resolved_delivery_target
        if resolved_delivery_time is not None:
            deliver_payload["delivery_time"] = resolved_delivery_time
        deliver_result = topic_radar_deliver(
            deliver_payload,
            channel=resolved_delivery_channel,
            target=resolved_delivery_target,
            delivery_time=resolved_delivery_time,
            runs_root=runs_root,
        )
        return _finalize_orchestration(
            payload=deliver_payload,
            execution_mode=resolved_mode,
            final_stage="deliver",
            run_status=str(deliver_result.get("run_status") or OrchestratorRunStatus.DELIVERY_FAILED.value),
            decision_status=str(deliver_result.get("decision_status") or working_payload.get("decision_status") or "").strip(),
            deliver_result=deliver_result,
            skipped_reasons={
                "write": "deliver_only mode skips write",
                "score": "deliver_only mode skips score",
                "ingest": "deliver_only mode skips ingest",
            },
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

    input_resolution = entry_resolution["input"]
    input_strategy = entry_resolution["degrade"]["strategies"]["input_unavailable"]
    requested_input_mode = input_resolution["effective_mode"]

    crawl_result: Optional[Dict[str, Any]] = None
    ingest_result: Optional[Dict[str, Any]] = None
    topic_result: Optional[Dict[str, Any]] = None
    score_result: Optional[Dict[str, Any]] = None
    stage_skipped_reasons: Dict[str, str] = {}
    resume_target = _resolve_resume_target(working_payload) if resolved_mode == OrchestratorExecutionMode.RESUME.value else "pipeline"
    bypass_input_pipeline = resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value or resume_target in {"score", "write", "deliver"}

    if not bypass_input_pipeline:
        if requested_input_mode == "real_source":
            try:
                real_source_payload, real_source_context = load_real_source_payload(working_payload)
            except RealSourceUnavailableError as exc:
                unavailable_reason = str(exc).strip() or "real_source unavailable"
                if input_strategy == "fallback_inline_candidates" and input_resolution["inline_candidates_available"]:
                    _record_entry_fallback(
                        entry_resolution,
                        category="input",
                        requested="real_source",
                        applied="inline_candidates",
                        reason=f"{unavailable_reason}; fallback to inline_candidates",
                    )
                    input_resolution["effective_mode"] = "inline_candidates"
                elif input_strategy == "fallback_inline_normalized" and input_resolution["inline_normalized_available"]:
                    _record_entry_fallback(
                        entry_resolution,
                        category="input",
                        requested="real_source",
                        applied="inline_normalized",
                        reason=f"{unavailable_reason}; fallback to inline_normalized",
                    )
                    input_resolution["effective_mode"] = "inline_normalized"
                else:
                    return _finalize_orchestration(
                        payload=working_payload,
                        execution_mode=resolved_mode,
                        final_stage="orchestrator",
                        run_status=OrchestratorRunStatus.FAILED.value,
                        decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                        skipped_reasons={
                            "ingest": "input mode unavailable",
                            "score": "input mode unavailable",
                            "write": "input mode unavailable",
                            "deliver": "input mode unavailable",
                        },
                        extra_errors=[
                            _build_orchestrator_error(
                                code=OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE,
                                message=f"entry_options.input.mode=real_source unavailable: {unavailable_reason}",
                                missing_fields=["entry_options.input.mode"],
                            )
                        ],
                        requested_event_ids=requested_event_ids,
                        entry_resolution=entry_resolution,
                    )
            else:
                working_payload["topic_candidates"] = deepcopy(real_source_payload.get("topic_candidates") or [])
                if "real_source_context" in real_source_payload:
                    working_payload["real_source_context"] = deepcopy(real_source_payload["real_source_context"])
                input_resolution["real_source_loaded"] = True
                input_resolution["real_source_provider"] = real_source_context.get("provider")
                input_resolution["real_source_candidate_count"] = int(real_source_context.get("candidate_count") or 0)
                input_resolution["real_source_requested_source_ids"] = list(real_source_context.get("requested_source_ids") or [])
                input_resolution["real_source_applied_source_ids"] = list(real_source_context.get("applied_source_ids") or [])
                input_resolution["real_source_failed_sources"] = deepcopy(real_source_context.get("failed_sources") or [])
                input_resolution["inline_candidates_available"] = True

        if requested_input_mode == "user_topic":
            try:
                user_topic_payload, user_topic_context = load_user_topic_payload(working_payload)
            except UserTopicValidationError as exc:
                unavailable_reason = str(exc).strip() or "user_topic unavailable"
                if input_strategy == "fallback_inline_candidates" and input_resolution["inline_candidates_available"]:
                    _record_entry_fallback(
                        entry_resolution,
                        category="input",
                        requested="user_topic",
                        applied="inline_candidates",
                        reason=f"{unavailable_reason}; fallback to inline_candidates",
                    )
                    input_resolution["effective_mode"] = "inline_candidates"
                elif input_strategy == "fallback_inline_normalized" and input_resolution["inline_normalized_available"]:
                    _record_entry_fallback(
                        entry_resolution,
                        category="input",
                        requested="user_topic",
                        applied="inline_normalized",
                        reason=f"{unavailable_reason}; fallback to inline_normalized",
                    )
                    input_resolution["effective_mode"] = "inline_normalized"
                else:
                    return _finalize_orchestration(
                        payload=working_payload,
                        execution_mode=resolved_mode,
                        final_stage="orchestrator",
                        run_status=OrchestratorRunStatus.FAILED.value,
                        decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                        skipped_reasons={
                            "ingest": "input mode unavailable",
                            "score": "input mode unavailable",
                            "write": "input mode unavailable",
                            "deliver": "input mode unavailable",
                        },
                        extra_errors=[
                            _build_orchestrator_error(
                                code=OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE,
                                message=f"entry_options.input.mode=user_topic unavailable: {unavailable_reason}",
                                missing_fields=["entry_options.input.mode"],
                            )
                        ],
                        requested_event_ids=requested_event_ids,
                        entry_resolution=entry_resolution,
                    )
            else:
                working_payload["topic_candidates"] = deepcopy(user_topic_payload.get("topic_candidates") or [])
                if "user_topic_context" in user_topic_payload:
                    working_payload["user_topic_context"] = deepcopy(user_topic_payload["user_topic_context"])
                input_resolution["user_topic_loaded"] = True
                input_resolution["user_topic_provider"] = user_topic_context.get("provider")
                input_resolution["user_topic_candidate_count"] = len(user_topic_payload.get("topic_candidates") or [])
                input_resolution["inline_candidates_available"] = True

        if input_resolution["effective_mode"] == "inline_candidates" and not input_resolution["inline_candidates_available"]:
            if input_strategy == "fallback_inline_normalized" and input_resolution["inline_normalized_available"]:
                _record_entry_fallback(
                    entry_resolution,
                    category="input",
                    requested="inline_candidates",
                    applied="inline_normalized",
                    reason="inline_candidates unavailable; fallback to inline_normalized",
                )
                input_resolution["effective_mode"] = "inline_normalized"
            else:
                return _finalize_orchestration(
                    payload=working_payload,
                    execution_mode=resolved_mode,
                    final_stage="orchestrator",
                    run_status=OrchestratorRunStatus.FAILED.value,
                    decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                    skipped_reasons={
                        "ingest": "input mode unavailable",
                        "score": "input mode unavailable",
                        "write": "input mode unavailable",
                        "deliver": "input mode unavailable",
                    },
                    extra_errors=[
                        _build_orchestrator_error(
                            code=OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE,
                            message="entry_options.input.mode=inline_candidates requires topic_candidates",
                            missing_fields=["topic_candidates"],
                        )
                    ],
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )

        if input_resolution["effective_mode"] == "inline_normalized" and not input_resolution["inline_normalized_available"]:
            if input_strategy == "fallback_inline_candidates" and input_resolution["inline_candidates_available"]:
                _record_entry_fallback(
                    entry_resolution,
                    category="input",
                    requested="inline_normalized",
                    applied="inline_candidates",
                    reason="inline_normalized unavailable; fallback to inline_candidates",
                )
                input_resolution["effective_mode"] = "inline_candidates"
            else:
                return _finalize_orchestration(
                    payload=working_payload,
                    execution_mode=resolved_mode,
                    final_stage="orchestrator",
                    run_status=OrchestratorRunStatus.FAILED.value,
                    decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                    skipped_reasons={
                        "ingest": "input mode unavailable",
                        "score": "input mode unavailable",
                        "write": "input mode unavailable",
                        "deliver": "input mode unavailable",
                    },
                    extra_errors=[
                        _build_orchestrator_error(
                            code=OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE,
                            message="entry_options.input.mode=inline_normalized requires normalized_events",
                            missing_fields=["normalized_events"],
                        )
                    ],
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )

        if input_resolution["effective_mode"] == "inline_topic_cards" and not input_resolution["inline_topic_cards_available"]:
            if input_strategy == "fallback_inline_normalized" and input_resolution["inline_normalized_available"]:
                _record_entry_fallback(
                    entry_resolution,
                    category="input",
                    requested="inline_topic_cards",
                    applied="inline_normalized",
                    reason="inline_topic_cards unavailable; fallback to inline_normalized",
                )
                input_resolution["effective_mode"] = "inline_normalized"
            elif input_strategy == "fallback_inline_candidates" and input_resolution["inline_candidates_available"]:
                _record_entry_fallback(
                    entry_resolution,
                    category="input",
                    requested="inline_topic_cards",
                    applied="inline_candidates",
                    reason="inline_topic_cards unavailable; fallback to inline_candidates",
                )
                input_resolution["effective_mode"] = "inline_candidates"
            else:
                return _finalize_orchestration(
                    payload=working_payload,
                    execution_mode=resolved_mode,
                    final_stage="orchestrator",
                    run_status=OrchestratorRunStatus.FAILED.value,
                    decision_status=str(working_payload.get("decision_status") or "rejected").strip() or "rejected",
                    skipped_reasons={
                        "ingest": "input mode unavailable",
                        "score": "input mode unavailable",
                        "write": "input mode unavailable",
                        "deliver": "input mode unavailable",
                    },
                    extra_errors=[
                        _build_orchestrator_error(
                            code=OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE,
                            message="entry_options.input.mode=inline_topic_cards requires topic_cards",
                            missing_fields=["topic_cards"],
                        )
                    ],
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )

        if input_resolution["effective_mode"] in {"inline_candidates", "real_source", "user_topic"}:
            crawl_context = None
            if isinstance(working_payload.get("real_source_context"), dict):
                crawl_context = deepcopy(working_payload.get("real_source_context"))
            elif isinstance(working_payload.get("user_topic_context"), dict):
                crawl_context = deepcopy(working_payload.get("user_topic_context"))
            crawl_result = build_crawl_results(
                working_payload,
                source_mode=input_resolution["effective_mode"],
                source_context=crawl_context,
            )
        else:
            stage_skipped_reasons["crawl"] = f"entry_options.input.mode={input_resolution['effective_mode']}; crawl skipped"

        if resolved_mode == OrchestratorExecutionMode.CRAWL_ONLY.value:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="crawl",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str((crawl_result or {}).get("decision_status") or "candidate"),
                crawl_result=crawl_result,
                skipped_reasons={
                    **stage_skipped_reasons,
                    "ingest": "crawl_only mode skips ingest",
                    "topics": "crawl_only mode skips topics",
                    "score": "crawl_only mode skips score",
                    "write": "crawl_only mode skips write",
                    "deliver": "crawl_only mode skips deliver",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if input_resolution["effective_mode"] == "inline_normalized":
            stage_skipped_reasons["ingest"] = "entry_options.input.mode=inline_normalized; ingest skipped"
            topic_result = build_topic_cards(working_payload)
        elif input_resolution["effective_mode"] == "inline_topic_cards":
            stage_skipped_reasons["ingest"] = "entry_options.input.mode=inline_topic_cards; ingest skipped"
            topic_result = build_topic_cards(working_payload)
        else:
            try:
                ingest_result = normalize_ingest_payload(working_payload)
            except IngestValidationError:
                ingest_result = build_ingest_rejection(working_payload)
                return _finalize_orchestration(
                    payload=working_payload,
                    execution_mode=resolved_mode,
                    final_stage="ingest",
                    run_status=OrchestratorRunStatus.REJECTED.value,
                    decision_status=str(ingest_result.get("decision_status") or IngestRunStatus.REJECTED.value),
                    crawl_result=crawl_result,
                    ingest_result=ingest_result,
                    skipped_reasons={
                        **stage_skipped_reasons,
                        "topics": "ingest rejected; topics not executed",
                        "score": "ingest rejected; score not executed",
                        "write": "ingest rejected; write not executed",
                        "deliver": "ingest rejected; deliver not executed",
                    },
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )
            topic_result = build_topic_cards(ingest_result)

        if resolved_mode == OrchestratorExecutionMode.TOPICS_ONLY.value:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="topics",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str((topic_result or {}).get("decision_status") or "candidate"),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                skipped_reasons={
                    **stage_skipped_reasons,
                    "score": "topics_only mode skips score",
                    "write": "topics_only mode skips write",
                    "deliver": "topics_only mode skips deliver",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )
    elif resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value:
        stage_skipped_reasons.update(
            {
                "crawl": "write_only mode skips crawl",
                "ingest": "write_only mode skips ingest",
                "topics": "write_only mode skips topics",
                "score": "write_only mode reuses existing scored_events",
            }
        )
    elif resume_target == "deliver":
        stage_skipped_reasons.update(
            {
                "crawl": "resume mode resumed from existing content_bundles; crawl skipped",
                "ingest": "resume mode resumed from existing content_bundles; ingest skipped",
                "topics": "resume mode resumed from existing content_bundles; topics skipped",
                "score": "resume mode resumed from existing content_bundles; score skipped",
                "write": "resume mode resumed from existing content_bundles; write skipped",
            }
        )
    elif resume_target == "write":
        stage_skipped_reasons.update(
            {
                "crawl": "resume mode resumed from existing scored_events; crawl skipped",
                "ingest": "resume mode resumed from existing scored_events; ingest skipped",
                "topics": "resume mode resumed from existing scored_events; topics skipped",
                "score": "resume mode resumed from existing scored_events; score skipped",
            }
        )
    elif resume_target == "score":
        stage_skipped_reasons["crawl"] = "resume mode reused existing upstream artifacts; crawl skipped"
        if _extract_topic_cards(None, working_payload):
            stage_skipped_reasons["ingest"] = "resume mode resumed from existing topic_cards; ingest skipped"
        else:
            stage_skipped_reasons["ingest"] = "resume mode resumed from existing normalized_events; ingest skipped"
        topic_result = build_topic_cards(working_payload)

    score_result: Optional[Dict[str, Any]] = None
    publish_ready_events: List[Dict[str, Any]] = []

    if resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value or resume_target == "write":
        publish_ready_events = [
            deepcopy(item)
            for item in _extract_scored_events(None, working_payload)
            if isinstance(item, dict) and item.get("status") == ScoreDecisionStatus.PUBLISH_READY.value
        ]
    elif resume_target == "deliver":
        publish_ready_events = [
            deepcopy(item)
            for item in _extract_scored_events(None, working_payload)
            if isinstance(item, dict) and item.get("status") == ScoreDecisionStatus.PUBLISH_READY.value
        ]
    else:
        score_input = topic_result or working_payload
        try:
            score_result = score_topic_candidates(score_input)
        except Exception:
            score_result = build_score_rejection(score_input)

        if score_result.get("run_status") != ScoreRunStatus.SUCCEEDED.value:
            failed_skipped_reasons = {
                **stage_skipped_reasons,
                "write": "score failed; write not executed",
                "deliver": "score failed; deliver not executed",
            }
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="score",
                run_status=OrchestratorRunStatus.FAILED.value,
                decision_status=str(score_result.get("decision_status") or ScoreDecisionStatus.NEED_MORE_EVIDENCE.value),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                skipped_reasons=failed_skipped_reasons,
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if resolved_mode == OrchestratorExecutionMode.SCORE_ONLY.value:
            score_only_skipped_reasons = {
                **stage_skipped_reasons,
                "write": "score_only mode skips write",
                "deliver": "score_only mode skips deliver",
            }
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="score",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(score_result.get("decision_status") or ScoreDecisionStatus.NO_PUBLISH.value),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                skipped_reasons=score_only_skipped_reasons,
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        publish_ready_events = [
            deepcopy(item)
            for item in score_result.get("scored_events") or []
            if isinstance(item, dict) and item.get("status") == ScoreDecisionStatus.PUBLISH_READY.value
        ]
    if not publish_ready_events and resume_target != "deliver":
        return _finalize_orchestration(
            payload=working_payload,
            execution_mode=resolved_mode,
            final_stage="write" if resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value or resume_target == "write" else "score",
            run_status=OrchestratorRunStatus.COMPLETED.value,
            decision_status=str(
                (score_result or {}).get("decision_status")
                or working_payload.get("decision_status")
                or ScoreDecisionStatus.NO_PUBLISH.value
            ),
            crawl_result=crawl_result,
            ingest_result=ingest_result,
            topic_result=topic_result,
            score_result=score_result,
            skipped_reasons={
                **stage_skipped_reasons,
                "write": "decision_status is not publish_ready; write skipped",
                "deliver": "decision_status is not publish_ready; deliver skipped",
            },
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

    write_result: Optional[Dict[str, Any]] = None
    if resume_target != "deliver":
        if not entry_resolution["write"]["enabled"]:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="write" if resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value or resume_target == "write" else "score",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(
                    (score_result or {}).get("decision_status")
                    or working_payload.get("decision_status")
                    or ScoreDecisionStatus.PUBLISH_READY.value
                ),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                skipped_reasons={
                    **stage_skipped_reasons,
                    "write": "entry_options.write.enabled=false; write skipped",
                    "deliver": "write disabled at entry; deliver skipped",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if entry_resolution["write"]["executor"] == "external_writer":
            if not isinstance(working_payload.get("report_profile"), dict):
                working_payload["report_profile"] = {}
            if not isinstance(working_payload.get("writing_brief"), dict):
                working_payload["writing_brief"] = {}

        write_payload = _build_write_payload(
            working_payload,
            publish_ready_events=publish_ready_events,
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

        try:
            write_result = topic_radar_write(
                write_payload,
                operation=entry_resolution["write"]["operation"],
                executor=entry_resolution["write"]["executor"],
            )
        except Exception:
            write_result = build_write_rejection(write_payload)

        if write_result.get("run_status") != WriteRunStatus.SUCCEEDED.value:
            write_strategy = entry_resolution["degrade"]["strategies"]["write_unavailable"]
            if entry_resolution["write"]["executor"] == WriteExecutor.EXTERNAL_WRITER.value and write_strategy == "fallback_openclaw_builtin":
                _record_entry_fallback(
                    entry_resolution,
                    category="write",
                    requested="external_writer",
                    applied="openclaw_builtin",
                    reason="external_writer failed and degrade strategy fell back to openclaw_builtin",
                )
                entry_resolution["write"]["executor"] = "openclaw_builtin"
                write_payload["executor"] = WriteExecutor.OPENCLAW_BUILTIN.value
                try:
                    write_result = topic_radar_write(
                        write_payload,
                        operation=entry_resolution["write"]["operation"],
                        executor=WriteExecutor.OPENCLAW_BUILTIN.value,
                    )
                except Exception:
                    write_result = build_write_rejection(write_payload)
            elif entry_resolution["write"]["executor"] == WriteExecutor.EXTERNAL_WRITER.value and write_strategy == "skip":
                _record_entry_fallback(
                    entry_resolution,
                    category="write",
                    requested="external_writer",
                    applied="skip",
                    reason="external_writer failed and degrade strategy skipped write",
                )
                entry_resolution["write"]["executor"] = "skip"
                return _finalize_orchestration(
                    payload=working_payload,
                    execution_mode=resolved_mode,
                    final_stage="write" if resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value or resume_target == "write" else "score",
                    run_status=OrchestratorRunStatus.COMPLETED.value,
                    decision_status=str(
                        (score_result or {}).get("decision_status")
                        or working_payload.get("decision_status")
                        or ScoreDecisionStatus.PUBLISH_READY.value
                    ),
                    crawl_result=crawl_result,
                    ingest_result=ingest_result,
                    topic_result=topic_result,
                    score_result=score_result,
                    write_result=write_result,
                    skipped_reasons={
                        **stage_skipped_reasons,
                        "write": "external_writer failed; degrade strategy skipped write",
                        "deliver": "write skipped due to external_writer failure",
                    },
                    requested_event_ids=requested_event_ids,
                    entry_resolution=entry_resolution,
                )

        if write_result.get("run_status") != WriteRunStatus.SUCCEEDED.value:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="write",
                run_status=OrchestratorRunStatus.FAILED.value,
                decision_status=str(write_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                write_result=write_result,
                skipped_reasons={
                    **stage_skipped_reasons,
                    "deliver": "write failed; deliver not executed",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        if resolved_mode == OrchestratorExecutionMode.WRITE_ONLY.value:
            return _finalize_orchestration(
                payload=working_payload,
                execution_mode=resolved_mode,
                final_stage="write",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(write_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                write_result=write_result,
                skipped_reasons={
                    **stage_skipped_reasons,
                    "deliver": "write_only mode skips deliver",
                },
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

    if not entry_resolution["delivery"]["enabled"]:
        return _finalize_orchestration(
            payload=working_payload,
            execution_mode=resolved_mode,
            final_stage="write",
            run_status=OrchestratorRunStatus.COMPLETED.value,
            decision_status=str(
                (write_result or {}).get("decision_status")
                or (score_result or {}).get("decision_status")
                or working_payload.get("decision_status")
                or ScoreDecisionStatus.PUBLISH_READY.value
            ),
            crawl_result=crawl_result,
            ingest_result=ingest_result,
            topic_result=topic_result,
            score_result=score_result,
            write_result=write_result,
            skipped_reasons={
                **stage_skipped_reasons,
                "deliver": "entry_options.delivery.enabled=false; deliver skipped",
            },
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

    delivery_scored_events = publish_ready_events or _extract_scored_events(score_result, working_payload)
    delivery_content_bundles = _extract_content_bundles(write_result, working_payload)
    normalized_events_for_delivery = (
        (topic_result or {}).get("normalized_events")
        or (ingest_result or {}).get("normalized_events")
        or working_payload.get("normalized_events")
        or []
    )
    delivery_seed_payload = _build_delivery_payload(
        payload=working_payload,
        scored_events=delivery_scored_events,
        normalized_events=normalized_events_for_delivery,
        content_bundles=delivery_content_bundles,
    )
    resolved_delivery_time = entry_resolution["delivery"]["delivery_time"] or None
    resolved_delivery_channel = entry_resolution["delivery"]["channel"] or None
    resolved_delivery_target = entry_resolution["delivery"]["target"] or None

    if entry_resolution["delivery"]["target_mode"] == "archive_only":
        deliver_result = _build_archive_only_delivery_result(
            delivery_seed_payload,
            delivery_time=resolved_delivery_time,
            delivery_target=resolved_delivery_target,
            runs_root=runs_root,
        )
        return _finalize_orchestration(
            payload=delivery_seed_payload,
            execution_mode=resolved_mode,
            final_stage="deliver",
            run_status=OrchestratorRunStatus.COMPLETED.value,
            decision_status=str(deliver_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
            crawl_result=crawl_result,
            ingest_result=ingest_result,
            topic_result=topic_result,
            score_result=score_result,
            write_result=write_result,
            deliver_result=deliver_result,
            skipped_reasons=stage_skipped_reasons,
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

    if resolved_delivery_channel and resolved_delivery_channel not in {"feishu", "wechat", "wechat_official_account"}:
        if entry_resolution["degrade"]["strategies"]["delivery_unavailable"] == "archive_only":
            _record_entry_fallback(
                entry_resolution,
                category="delivery",
                requested=entry_resolution["delivery"]["target_mode"],
                applied="archive_only",
                reason=f"delivery channel '{resolved_delivery_channel}' is unavailable; fallback to archive_only",
            )
            entry_resolution["delivery"]["target_mode"] = "archive_only"
            entry_resolution["delivery"]["channel"] = "archive_only"
            deliver_result = _build_archive_only_delivery_result(
                delivery_seed_payload,
                delivery_time=resolved_delivery_time,
                delivery_target=resolved_delivery_target or "archive://clawradar",
                runs_root=runs_root,
            )
            return _finalize_orchestration(
                payload=delivery_seed_payload,
                execution_mode=resolved_mode,
                final_stage="deliver",
                run_status=OrchestratorRunStatus.COMPLETED.value,
                decision_status=str(deliver_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
                crawl_result=crawl_result,
                ingest_result=ingest_result,
                topic_result=topic_result,
                score_result=score_result,
                write_result=write_result,
                deliver_result=deliver_result,
                skipped_reasons=stage_skipped_reasons,
                requested_event_ids=requested_event_ids,
                entry_resolution=entry_resolution,
            )

        return _finalize_orchestration(
            payload=delivery_seed_payload,
            execution_mode=resolved_mode,
            final_stage="deliver",
            run_status=OrchestratorRunStatus.FAILED.value,
            decision_status=str(write_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
            crawl_result=crawl_result,
            ingest_result=ingest_result,
            topic_result=topic_result,
            score_result=score_result,
            write_result=write_result,
            skipped_reasons=stage_skipped_reasons,
            extra_errors=[
                _build_orchestrator_error(
                    code=OrchestratorErrorCode.INVALID_ENTRY_OPTION,
                    message=f"unsupported entry_options.delivery.channel: {resolved_delivery_channel}",
                    missing_fields=["entry_options.delivery.channel"],
                )
            ],
            requested_event_ids=requested_event_ids,
            entry_resolution=entry_resolution,
        )

    if resolved_delivery_channel is not None:
        delivery_seed_payload["delivery_channel"] = resolved_delivery_channel
    if resolved_delivery_target is not None:
        delivery_seed_payload["delivery_target"] = resolved_delivery_target
    if resolved_delivery_time is not None:
        delivery_seed_payload["delivery_time"] = resolved_delivery_time

    deliver_result = topic_radar_deliver(
        delivery_seed_payload,
        channel=resolved_delivery_channel,
        target=resolved_delivery_target,
        delivery_time=resolved_delivery_time,
        runs_root=runs_root,
    )
    orchestrator_run_status = (
        OrchestratorRunStatus.COMPLETED.value
        if deliver_result.get("run_status") == OrchestratorRunStatus.COMPLETED.value
        else OrchestratorRunStatus.DELIVERY_FAILED.value
    )
    return _finalize_orchestration(
        payload=delivery_seed_payload,
        execution_mode=resolved_mode,
        final_stage="deliver",
        run_status=orchestrator_run_status,
        decision_status=str(deliver_result.get("decision_status") or ScoreDecisionStatus.PUBLISH_READY.value),
        crawl_result=crawl_result,
        ingest_result=ingest_result,
        topic_result=topic_result,
        score_result=score_result,
        write_result=write_result,
        deliver_result=deliver_result,
        skipped_reasons=stage_skipped_reasons,
        requested_event_ids=requested_event_ids,
        entry_resolution=entry_resolution,
    )


__all__ = [
    "OrchestratorErrorCode",
    "OrchestratorExecutionMode",
    "OrchestratorRunStatus",
    "OrchestratorStageStatus",
    "OrchestratorTriggerSource",
    "topic_radar_orchestrate",
]
