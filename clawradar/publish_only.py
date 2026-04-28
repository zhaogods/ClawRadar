"""Publish-only entrypoints for replaying existing write outputs."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .delivery import topic_radar_deliver
from .notifications import build_notification_payload, sanitize_notification_payload, topic_radar_notify
from .scoring import ScoreDecisionStatus


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = WORKSPACE_ROOT / "outputs"


@dataclass(slots=True)
class PublishOnlySource:
    payload: Dict[str, Any]
    source_path: Path
    source_kind: str
    run_root: Path


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_existing_path(raw_path: Any) -> Optional[Path]:
    text = str(raw_path or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = (WORKSPACE_ROOT / candidate).resolve()
    if candidate.exists():
        return candidate
    return None


def _candidate_report_paths(content_bundle: Dict[str, Any]) -> List[Path]:
    paths: List[Path] = []
    for section_name in ("writer_receipt", "report_artifacts"):
        section = content_bundle.get(section_name) if isinstance(content_bundle.get(section_name), dict) else {}
        for field in (
            "report_filepath",
            "state_filepath",
            "ir_filepath",
            "report_relative_path",
            "state_relative_path",
            "ir_relative_path",
        ):
            resolved = _resolve_existing_path(section.get(field))
            if resolved is not None:
                paths.append(resolved)
    return paths


def _select_latest_content_bundle(bundles: List[Dict[str, Any]]) -> Dict[str, Any]:
    def bundle_key(item: tuple[int, Dict[str, Any]]) -> tuple[float, int]:
        index, bundle = item
        report_paths = _candidate_report_paths(bundle)
        if report_paths:
            return max(path.stat().st_mtime for path in report_paths), index
        return -1.0, index

    _, latest_bundle = max(enumerate(bundles), key=bundle_key)
    return deepcopy(latest_bundle)


def _resolve_run_root_from_source_path(path: Path) -> Path:
    resolved = path.resolve()

    for ancestor in resolved.parents:
        if (ancestor / "summary.json").exists():
            return ancestor
        if (ancestor / "meta").is_dir() and (ancestor / "stages").is_dir():
            return ancestor

    if resolved.name == "content_bundles.json":
        if resolved.parent.name == "debug":
            return resolved.parent.parent
        if resolved.parent.name == "write" and resolved.parent.parent.name == "stages":
            return resolved.parents[2]

    if resolved.name == "payload_snapshot.json":
        for ancestor in resolved.parents:
            if ancestor.name in {"recovery", "events"}:
                return ancestor.parent
        if len(resolved.parents) >= 4:
            return resolved.parents[3]

    raise ValueError(f"unable to resolve run root from publish source: {path}")


def _resolve_request_id_from_run_root(run_root: Path) -> str:
    summary_path = run_root / "summary.json"
    if summary_path.exists():
        summary_payload = _read_json(summary_path)
        if isinstance(summary_payload, dict):
            request_id = str(summary_payload.get("request_id") or "").strip()
            if request_id:
                return request_id
    return str(run_root.parent.name or "publish-only").strip() or "publish-only"


def _load_content_bundle_payload(content_bundle: Dict[str, Any], *, request_id: str, trigger_source: str) -> Dict[str, Any]:
    event_id = str(content_bundle.get("event_id") or "").strip()
    return {
        "request_id": request_id,
        "trigger_source": trigger_source,
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "content_bundle": deepcopy(content_bundle),
        "content_bundles": [deepcopy(content_bundle)],
        "event_id": event_id,
        "normalized_events": [],
        "timeline": [],
        "evidence_pack": deepcopy(content_bundle.get("evidence_pack") or {}),
        "scorecard": {"decision_status": ScoreDecisionStatus.PUBLISH_READY.value},
    }


def _pick_content_bundle(bundles: List[Dict[str, Any]], *, target_event_id: Optional[str]) -> Dict[str, Any]:
    if not bundles:
        raise ValueError("publish-only source does not contain any content bundle")
    if target_event_id:
        for bundle in bundles:
            if str(bundle.get("event_id") or "").strip() == target_event_id:
                return deepcopy(bundle)
        raise ValueError(f"target event not found in publish source: {target_event_id}")
    if len(bundles) == 1:
        return deepcopy(bundles[0])
    return _select_latest_content_bundle(bundles)


def _build_publish_payload_from_content_bundles_file(path: Path, *, target_event_id: Optional[str]) -> Dict[str, Any]:
    bundles = _read_json(path)
    if not isinstance(bundles, list):
        raise ValueError("content_bundles.json must contain a list")
    bundle = _pick_content_bundle([item for item in bundles if isinstance(item, dict)], target_event_id=target_event_id)
    run_root = _resolve_run_root_from_source_path(path)
    request_id = _resolve_request_id_from_run_root(run_root)
    return _load_content_bundle_payload(bundle, request_id=request_id, trigger_source="publish_only")


def _build_publish_payload_from_payload_snapshot(path: Path) -> Dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("content_bundle"), dict):
        raise ValueError("payload_snapshot.json must contain content_bundle")
    payload_copy = deepcopy(payload)
    payload_copy["content_bundles"] = [deepcopy(payload_copy["content_bundle"])]
    payload_copy["decision_status"] = ScoreDecisionStatus.PUBLISH_READY.value
    return sanitize_notification_payload(payload_copy)


def _latest_pointer_content_bundles_candidates(runs_root: Path) -> List[Path]:
    candidates: List[Path] = []
    for latest_path in runs_root.glob("*/latest.json"):
        try:
            latest_payload = _read_json(latest_path)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(latest_payload, dict):
            continue
        latest_run = str(latest_payload.get("latest_run") or "").strip()
        if not latest_run:
            continue
        candidate = latest_path.parent / latest_run / "debug" / "content_bundles.json"
        if candidate.exists():
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)


def _debug_content_bundles_candidates(runs_root: Path) -> List[Path]:
    return sorted(
        runs_root.glob("**/debug/content_bundles.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _legacy_content_bundles_candidates(runs_root: Path) -> List[Path]:
    return sorted(
        runs_root.glob("**/stages/write/content_bundles.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _find_latest_content_bundles_file(runs_root: Path) -> Path:
    for candidates in (
        _latest_pointer_content_bundles_candidates(runs_root),
        _debug_content_bundles_candidates(runs_root),
        _legacy_content_bundles_candidates(runs_root),
    ):
        if candidates:
            return candidates[0]
    raise FileNotFoundError(f"no content_bundles.json found under {runs_root}")


def resolve_publish_source(
    *,
    runs_root: Optional[Path] = None,
    publish_file: Optional[Path] = None,
    target_event_id: Optional[str] = None,
) -> PublishOnlySource:
    resolved_runs_root = Path(runs_root or DEFAULT_RUNS_ROOT)
    if publish_file is None:
        source_path = _find_latest_content_bundles_file(resolved_runs_root)
    else:
        source_path = Path(publish_file)
        if not source_path.is_absolute():
            source_path = (WORKSPACE_ROOT / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"publish source not found: {source_path}")

    if source_path.name == "content_bundles.json":
        payload = _build_publish_payload_from_content_bundles_file(source_path, target_event_id=target_event_id)
        run_root = _resolve_run_root_from_source_path(source_path)
        source_kind = "content_bundles"
    elif source_path.name == "payload_snapshot.json":
        payload = _build_publish_payload_from_payload_snapshot(source_path)
        run_root = _resolve_run_root_from_source_path(source_path)
        source_kind = "payload_snapshot"
    else:
        raise ValueError("publish-only currently supports content_bundles.json and payload_snapshot.json only")

    return PublishOnlySource(payload=payload, source_path=source_path, source_kind=source_kind, run_root=run_root)


def _content_hash(payload: Dict[str, Any], delivery_channel: str, delivery_target: str) -> str:
    bundle = payload.get("content_bundle") if isinstance(payload.get("content_bundle"), dict) else {}
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    channel_variants = summary.get("channel_variants") if isinstance(summary.get("channel_variants"), dict) else {}
    digest_source = {
        "event_id": str(bundle.get("event_id") or "").strip(),
        "title": str(bundle.get("title", {}).get("text") or "").strip(),
        "summary": str(summary.get("text") or "").strip(),
        "summary_wechat": str(channel_variants.get("wechat") or "").strip(),
        "body_markdown": str(bundle.get("draft", {}).get("body_markdown") or "").strip(),
        "delivery_channel": delivery_channel,
        "delivery_target": delivery_target,
    }
    encoded = json.dumps(digest_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _publish_records_path(run_root: Path) -> Path:
    return run_root / "publish" / "records.jsonl"


def _load_publish_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _append_publish_record(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


def _find_successful_record(records: List[Dict[str, Any]], *, content_hash: str) -> Optional[Dict[str, Any]]:
    for record in reversed(records):
        if record.get("content_hash") == content_hash and record.get("status") == "success":
            return deepcopy(record)
    return None


def _merge_notification_entry(
    payload: Dict[str, Any],
    *,
    notification_channel: Optional[str],
    notification_target: Optional[str],
    notification_options: Optional[Dict[str, Any]],
    notify_on: Optional[List[str]],
) -> None:
    if not any([notification_channel, notification_target, notification_options, notify_on]):
        return
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    notification_entry = entry_options.get("notification") if isinstance(entry_options.get("notification"), dict) else {}
    if notification_channel:
        notification_entry["channel"] = notification_channel
    if notification_target:
        notification_entry["target"] = notification_target
    if notify_on is not None:
        notification_entry["notify_on"] = list(notify_on)
    if isinstance(notification_options, dict):
        for key, value in deepcopy(notification_options).items():
            notification_entry[key] = value
    entry_options["notification"] = notification_entry
    payload["entry_options"] = entry_options


def publish_existing_output(
    *,
    runs_root: Optional[Path] = None,
    publish_file: Optional[Path] = None,
    delivery_channel: str,
    delivery_target: str,
    target_event_id: Optional[str] = None,
    force_republish: bool = False,
    notification_channel: Optional[str] = None,
    notification_target: Optional[str] = None,
    notification_options: Optional[Dict[str, Any]] = None,
    notify_on: Optional[List[str]] = None,
) -> Dict[str, Any]:
    source = resolve_publish_source(
        runs_root=runs_root,
        publish_file=publish_file,
        target_event_id=target_event_id,
    )
    if not delivery_channel or delivery_channel == "archive_only":
        raise ValueError("publish-only requires an external delivery channel")
    if not delivery_target:
        raise ValueError("publish-only requires delivery_target")

    content_hash = _content_hash(source.payload, delivery_channel, delivery_target)
    records_path = _publish_records_path(source.run_root)
    records = _load_publish_records(records_path)
    existing = None if force_republish else _find_successful_record(records, content_hash=content_hash)
    if existing is not None:
        return {
            "run_status": "skipped",
            "skip_reason": "already_published",
            "publish_source": {
                "kind": source.source_kind,
                "path": _relative_path(source.source_path),
                "run_root": _relative_path(source.run_root),
            },
            "publish_record": existing,
            "delivery_result": None,
            "notification_result": None,
            "errors": [],
        }

    payload = deepcopy(source.payload)
    payload["delivery_channel"] = delivery_channel
    payload["delivery_target"] = delivery_target
    payload["output_root"] = source.run_root.as_posix()
    payload["output_context"] = {"output_root": source.run_root.as_posix()}
    _merge_notification_entry(
        payload,
        notification_channel=notification_channel,
        notification_target=notification_target,
        notification_options=notification_options,
        notify_on=notify_on,
    )

    result = topic_radar_deliver(
        payload,
        channel=delivery_channel,
        target=delivery_target,
        runs_root=source.run_root / "publish_replays",
    )

    bundle = payload.get("content_bundle") if isinstance(payload.get("content_bundle"), dict) else {}
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    channel_variants = summary.get("channel_variants") if isinstance(summary.get("channel_variants"), dict) else {}
    summary_text = str(summary.get("text") or "").strip()
    summary_wechat = str(channel_variants.get("wechat") or "").strip()
    event = ((result.get("delivery_receipt") or {}).get("events") or [{}])[0]
    record = {
        "published_at": _utc_timestamp(),
        "status": "success" if result.get("run_status") == "completed" else "failed",
        "channel": delivery_channel,
        "target": delivery_target,
        "request_id": result.get("request_id"),
        "event_id": result.get("event_id"),
        "source_kind": source.source_kind,
        "source_path": _relative_path(source.source_path),
        "run_root": _relative_path(source.run_root),
        "content_hash": content_hash,
        "summary_text": summary_text,
        "summary_wechat": summary_wechat,
        "message_path": event.get("message_path"),
        "payload_path": event.get("payload_path"),
        "archive_path": event.get("archive_path"),
        "failure_info": deepcopy(event.get("failure_info")),
    }
    _append_publish_record(records_path, record)

    notification_payload = {
        **deepcopy(result),
        "output_root": source.run_root.as_posix(),
        "output_context": {"output_root": source.run_root.as_posix()},
        "entry_options": deepcopy(payload.get("entry_options") or {}),
        "delivery_channel": delivery_channel,
        "delivery_target": delivery_target,
    }
    notification_result = topic_radar_notify(
        build_notification_payload(
            notification_payload,
            channel=notification_channel,
            target=notification_target,
            notify_on=notify_on,
            notification_options=notification_options,
        ),
        channel=notification_channel,
        target=notification_target,
        runs_root=source.run_root,
    )

    return {
        "run_status": result.get("run_status"),
        "skip_reason": None,
        "publish_source": {
            "kind": source.source_kind,
            "path": _relative_path(source.source_path),
            "run_root": _relative_path(source.run_root),
        },
        "publish_record": record,
        "delivery_result": result,
        "notification_result": notification_result,
        "errors": deepcopy(result.get("errors") or []),
    }
