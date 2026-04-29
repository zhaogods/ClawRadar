"""阶段三：ClawRadar 可调用内容生成能力。"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from copy import deepcopy
from enum import Enum
from html import unescape
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .scoring import ScoreDecisionStatus, ScoreRunStatus, ScoreValidationError, validate_score_payload

MAX_WECHAT_TITLE_CHARS = 64
MAX_WECHAT_TITLE_UTF8_BYTES = MAX_WECHAT_TITLE_CHARS * 4
MAX_WECHAT_AUTHOR_CHARS = 8
MAX_WECHAT_DIGEST_TEXT_UNITS = 120
MAX_WECHAT_DIGEST_UTF8_BYTES = MAX_WECHAT_DIGEST_TEXT_UNITS * 4



class WriteRunStatus(str, Enum):
    """阶段三 write 执行状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WriteOperation(str, Enum):
    """阶段三写作操作类型。"""

    GENERATE = "generate"
    REWRITE = "rewrite"
    REGENERATE_SUMMARY = "regenerate_summary"


class WriteExecutor(str, Enum):
    """阶段八写作执行器类型。"""

    CLAWRADAR_BUILTIN = "clawradar_builtin"
    EXTERNAL_WRITER = "external_writer"


class WriteErrorCode(str, Enum):
    """阶段三错误码。"""

    INVALID_INPUT = "invalid_input"
    DECISION_NOT_PUBLISH_READY = "decision_not_publish_ready"
    CONTENT_BUNDLE_REQUIRED = "content_bundle_required"
    WRITER_UNAVAILABLE = "writer_unavailable"
    EXTERNAL_WRITER_FAILED = "external_writer_failed"
    INVALID_WRITER_OUTPUT = "invalid_writer_output"


WRITE_REQUIRED_FIELDS: Tuple[str, ...] = (
    "request_id",
    "trigger_source",
    "scored_events",
)

MAX_TITLE_TEXT_CHARS = MAX_WECHAT_TITLE_CHARS
TITLE_FALLBACK_TEXT = "ClawRadar Report"
TITLE_COMPANY_SUFFIXES: Tuple[str, ...] = (
    "集团股份有限公司",
    "股份有限公司",
    "控股有限公司",
    "有限公司",
    "集团公司",
    "集团",
    "控股",
    "公司",
)


def _build_title_constraints() -> Dict[str, Any]:
    return {
        "channel": "wechat_draft",
        "max_chars": MAX_TITLE_TEXT_CHARS,
        "max_utf8_bytes": MAX_WECHAT_TITLE_UTF8_BYTES,
        "rewrite_when_over_limit": True,
        "allow_truncate_as_business_fallback": False,
        "require_semantic_completeness": True,
    }


def _build_summary_constraints() -> Dict[str, Any]:
    return {
        "channel": "wechat_draft",
        "max_chars": MAX_WECHAT_DIGEST_TEXT_UNITS,
        "max_text_units": MAX_WECHAT_DIGEST_TEXT_UNITS,
        "max_utf8_bytes": MAX_WECHAT_DIGEST_UTF8_BYTES,
        "rewrite_when_over_limit": True,
        "allow_truncate_as_business_fallback": False,
        "require_semantic_completeness": True,
        "require_plain_text": True,
    }


def _normalize_summary_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n：:｜|丨/／,，;；。！？!?-—–_")


def _summary_candidates(text: Any) -> List[str]:
    base = _normalize_summary_text(text)
    if not base:
        return []
    candidates: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        normalized = _normalize_summary_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    add(base)
    for separator in ("；", "。", "，", ":", "："):
        if separator in base:
            add(base.split(separator, 1)[0])
    return candidates


def _regenerate_wechat_summary(
    event_title: str,
    top_fact_claim: str,
    uncertainty_text: str,
    *,
    rewrite_feedback: Optional[Dict[str, Any]] = None,
    fallback: str = "ClawRadar 摘要",
) -> str:
    max_bytes = MAX_WECHAT_DIGEST_UTF8_BYTES
    max_chars = MAX_WECHAT_DIGEST_TEXT_UNITS
    if isinstance(rewrite_feedback, dict):
        try:
            feedback_max_bytes = int(rewrite_feedback.get("maxUtf8Bytes") or 0)
        except (TypeError, ValueError):
            feedback_max_bytes = 0
        if feedback_max_bytes > 0:
            max_bytes = min(max_bytes, feedback_max_bytes)
        try:
            feedback_max_chars = int(
                rewrite_feedback.get("maxChars") or rewrite_feedback.get("maxTextUnits") or 0
            )
        except (TypeError, ValueError):
            feedback_max_chars = 0
        if feedback_max_chars > 0:
            max_chars = min(max_chars, feedback_max_chars)
    candidate_groups = [
        f"{event_title}，核心事实是{top_fact_claim}。",
        f"{event_title}，核心事实是{top_fact_claim}，{uncertainty_text}。",
        f"{event_title}。",
        top_fact_claim,
        fallback,
    ]
    for group in candidate_groups:
        for candidate in _summary_candidates(group):
            if _utf8_length(candidate) <= max_bytes and len(candidate) <= max_chars:
                return candidate
    normalized_fallback = _normalize_summary_text(fallback) or "ClawRadar 摘要"
    return _truncate_text_units(
        _truncate_utf8(normalized_fallback, max_bytes, "ClawRadar 摘要"),
        max_chars,
        "ClawRadar 摘要",
    )


def _utf8_length(text: str) -> int:
    return len(str(text or "").encode("utf-8"))


def _text_unit_length(text: Any) -> int:
    return len(str(text or ""))


def _truncate_text_units(text: str, max_units: int, fallback: str = "") -> str:
    value = str(text or "").strip()
    if not value:
        value = fallback.strip()
    if not value:
        return ""
    if _text_unit_length(value) <= max_units:
        return value
    truncated = value[:max_units].rstrip()
    return truncated or _truncate_utf8(fallback.strip(), max_units, "")


def _normalize_title_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n：:｜|丨/／,，;；。！？!?-—–_")


def _strip_title_suffixes(text: str) -> str:
    suffixes = (
        "深度观察报告",
        "深度观察",
        "分析报告",
        "观察报告",
        "专题报告",
        "舆情洞察报告",
        "热点追踪",
        "情况说明",
        "详细说明",
        "重大更新说明",
        "报告标题",
        "超长版本",
    )
    current = _normalize_title_text(text)
    while current:
        updated = current
        for suffix in suffixes:
            if updated.endswith(suffix) and len(updated) > len(suffix) + 2:
                updated = _normalize_title_text(updated[: -len(suffix)])
                break
        if updated == current:
            return current
        current = updated
    return ""


def _title_candidates(text: Any, *, company: str = "") -> List[str]:
    base = _normalize_title_text(text)
    company_text = _normalize_title_text(company)
    if not base:
        return []

    seeds = [base]
    without_brackets = _normalize_title_text(
        re.sub(r"（[^）]{0,30}）|\([^)]{0,30}\)|【[^】]{0,30}】|\[[^\]]{0,30}\]", "", base)
    )
    if without_brackets and without_brackets != base:
        seeds.append(without_brackets)
    if company_text and company_text not in base:
        seeds.append(f"{company_text}：{base}")
        if without_brackets and without_brackets != base:
            seeds.append(f"{company_text}：{without_brackets}")

    candidates: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        normalized = _normalize_title_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    split_pattern = r"[：:｜|丨/／—\-–,，;；。！？!?]\s*"
    leading_prefixes = ("关于", "聚焦", "发布", "推出", "上线", "披露", "回应", "宣布", "升级", "更新")

    for seed in seeds:
        normalized = _normalize_title_text(seed)
        add(normalized)
        no_ascii_tail = _normalize_title_text(
            re.sub(r"(?:报告标题)?(?:超长版本)?[0-9A-Za-z]{4,}$", "", normalized)
        )
        trimmed = _strip_title_suffixes(no_ascii_tail or normalized)
        add(trimmed)
        core_source = trimmed or no_ascii_tail or normalized
        if company_text:
            without_company = _normalize_title_text(
                re.sub(
                    rf"^{re.escape(company_text)}(?:[：:｜|丨/／—\-–,，;；。！？!?]\s*)?",
                    "",
                    core_source,
                )
            )
            add(without_company)
            core_source = without_company or core_source
        add(no_ascii_tail)
        for prefix in leading_prefixes:
            if core_source.startswith(prefix) and len(core_source) > len(prefix) + 4:
                core_source = _normalize_title_text(core_source[len(prefix):])
                add(core_source)
        segments = [_normalize_title_text(part) for part in re.split(split_pattern, core_source or normalized) if _normalize_title_text(part)]
        if segments:
            add(segments[0])

    return candidates


def _strip_company_suffixes(text: str) -> str:
    current = _normalize_title_text(text)
    while current:
        updated = current
        for suffix in TITLE_COMPANY_SUFFIXES:
            if updated.endswith(suffix) and len(updated) > len(suffix) + 1:
                updated = _normalize_title_text(updated[: -len(suffix)])
                break
        if updated == current:
            return current
        current = updated
    return ""


def _iter_regenerated_title_candidates(text: Any, *, company: str = "", fallback: str = TITLE_FALLBACK_TEXT) -> List[str]:
    candidates: List[str] = []
    seen = set()

    def add_candidate(value: Any) -> None:
        normalized = _normalize_title_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    for candidate in _title_candidates(text, company=company):
        add_candidate(candidate)

    normalized_company = _normalize_title_text(company)
    stripped_company = _strip_company_suffixes(normalized_company)
    for company_candidate in (stripped_company, normalized_company):
        add_candidate(company_candidate)
        if company_candidate:
            add_candidate(f"{company_candidate}事件观察")
            add_candidate(f"{company_candidate}舆情观察")

    add_candidate(fallback)
    return candidates


def _regenerate_title(
    text: str,
    *,
    max_chars: int = MAX_TITLE_TEXT_CHARS,
    company: str = "",
    fallback: str = TITLE_FALLBACK_TEXT,
) -> str:
    candidates = _iter_regenerated_title_candidates(text, company=company, fallback=fallback)
    for candidate in candidates:
        if len(candidate) <= max_chars:
            return candidate
    safe_fallback = _normalize_title_text(fallback) or TITLE_FALLBACK_TEXT
    return safe_fallback[:max_chars].rstrip() or TITLE_FALLBACK_TEXT


class WriteValidationError(ValueError):
    """write 输入校验失败。"""

    def __init__(self, *, code: WriteErrorCode, missing_fields: List[str], message: str):
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


def _truncate_utf8(text: str, max_bytes: int, fallback: str = "") -> str:
    value = str(text or "").strip()
    if not value:
        value = fallback.strip()
    if not value:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return fallback.strip()[:max_bytes]


def _normalize_write_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "scored_events" in payload:
        return payload
    try:
        return validate_score_payload(payload)
    except ScoreValidationError as exc:
        raise WriteValidationError(
            code=WriteErrorCode.INVALID_INPUT,
            missing_fields=list(exc.missing_fields),
            message="write payload missing required fields",
        ) from exc


def _collect_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing_fields: List[str] = []
    for field in WRITE_REQUIRED_FIELDS:
        if field not in payload or _is_blank(payload.get(field)):
            missing_fields.append(field)

    scored_events = payload.get("scored_events")
    if not isinstance(scored_events, list) or not scored_events:
        missing_fields.append("scored_events")
        return missing_fields

    for index, event in enumerate(scored_events):
        if not isinstance(event, dict):
            missing_fields.append(f"scored_events[{index}]")
            continue
        for field in ("event_id", "event_title", "status", "timeline", "fact_points", "trace"):
            if field not in event or _is_blank(event.get(field)):
                missing_fields.append(f"scored_events[{index}].{field}")

    return missing_fields


def validate_write_payload(payload: Dict[str, Any], *, operation: str = WriteOperation.GENERATE.value) -> Dict[str, Any]:
    """校验并返回阶段三 write 可消费载荷。"""

    normalized_payload = _normalize_write_payload(payload)
    missing_fields = _collect_missing_fields(normalized_payload)
    if missing_fields:
        raise WriteValidationError(
            code=WriteErrorCode.INVALID_INPUT,
            missing_fields=missing_fields,
            message="write payload missing required fields",
        )

    if operation in (WriteOperation.REWRITE.value, WriteOperation.REGENERATE_SUMMARY.value) and not isinstance(
        normalized_payload.get("content_bundle"), dict
    ):
        raise WriteValidationError(
            code=WriteErrorCode.CONTENT_BUNDLE_REQUIRED,
            missing_fields=["content_bundle"],
            message="rewrite operations require existing content_bundle",
        )

    return normalized_payload


def _build_evidence_packet(scored_event: Dict[str, Any]) -> Dict[str, Any]:
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
                "uncertainty": "待补充交叉验证" if (fact.get("confidence") is not None and fact.get("confidence", 0) < 0.9) else "",
            }
        )

    timeline_support = []
    for item in scored_event.get("timeline", []):
        if not isinstance(item, dict):
            continue
        timeline_support.append(
            {
                "timestamp": str(item.get("timestamp") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "summary": str(item.get("summary") or "").strip(),
                "source_url": str(item.get("source_url") or "").strip(),
            }
        )

    risk_notes = []
    for flag in scored_event.get("risk_flags", []):
        if not isinstance(flag, dict):
            continue
        risk_notes.append(
            {
                "code": str(flag.get("code") or "").strip(),
                "severity": str(flag.get("severity") or "").strip(),
                "message": str(flag.get("message") or "").strip(),
            }
        )

    return {
        "core_claim": str(scored_event.get("event_title") or "").strip(),
        "source_support": source_support,
        "timeline_support": timeline_support,
        "risk_notes": risk_notes,
        "uncertainty_markers": [
            item["uncertainty"]
            for item in source_support
            if item.get("uncertainty")
        ]
        or ["当前结论基于已收集证据，仍需持续跟踪新增来源。"],
    }


def _build_title(scored_event: Dict[str, Any]) -> str:
    company = _normalize_title_text(scored_event.get("trace", {}).get("company") or "")
    event_title = _normalize_title_text(scored_event.get("event_title") or "")
    preferred_title = event_title
    if company and company not in event_title:
        preferred_title = f"{company}：{event_title}"
    return _regenerate_title(preferred_title, company=company, fallback=TITLE_FALLBACK_TEXT)


def _build_outline(scored_event: Dict[str, Any], evidence_packet: Dict[str, Any]) -> List[Dict[str, Any]]:
    tags = _to_string_list(scored_event.get("trace", {}).get("initial_tags"))
    focus = "、".join(tags[:3]) if tags else "行业影响"
    return [
        {
            "section_id": "lead",
            "heading": "事件概览",
            "purpose": "说明事件是什么、何时发生、为什么值得关注。",
            "evidence_refs": [item["fact_id"] for item in evidence_packet["source_support"][:2] if item.get("fact_id")],
        },
        {
            "section_id": "evidence",
            "heading": "证据与时间线",
            "purpose": "按时间线梳理关键来源与已确认事实。",
            "evidence_refs": [item["fact_id"] for item in evidence_packet["source_support"] if item.get("fact_id")],
        },
        {
            "section_id": "impact",
            "heading": f"{focus}影响判断",
            "purpose": "结合业务相关性说明潜在影响，并保留不确定性提示。",
            "evidence_refs": [item["code"] for item in evidence_packet["risk_notes"] if item.get("code")],
        },
    ]


def _build_draft(scored_event: Dict[str, Any], evidence_packet: Dict[str, Any], title: str, *, version_note: str = "初稿") -> Dict[str, Any]:
    trace = scored_event.get("trace", {})
    facts = evidence_packet["source_support"]
    top_fact = facts[0] if facts else {"claim": str(scored_event.get("event_title") or "").strip(), "source_url": "", "citation_excerpt": ""}
    second_fact = facts[1] if len(facts) > 1 else top_fact
    uncertainty = evidence_packet["uncertainty_markers"][0]
    company = str(trace.get("company") or "相关企业").strip() or "相关企业"
    body = (
        f"{version_note}：{title}\n\n"
        f"{company}相关事件已达到 publish_ready 门槛。当前可确认的核心信息是：{top_fact['claim']}"
        f"（来源：{top_fact['source_url']}）。\n\n"
        f"从现有证据看，事件推进节奏较快，时间线已覆盖检测、披露与市场反馈环节。"
        f"补充事实显示：{second_fact['claim']}（来源：{second_fact['source_url']}）。"
        f"若引用原文，可优先采用“{top_fact.get('citation_excerpt') or second_fact.get('citation_excerpt') or '暂无摘录'}”作为证据摘录。\n\n"
        f"影响判断上，该事件与业务相关性较高，但仍需同步提示：{uncertainty}"
    )
    return {
        "version": 1 if version_note == "初稿" else 2,
        "label": version_note,
        "body_markdown": body,
        "source_refs": [item["fact_id"] for item in facts if item.get("fact_id")],
        "uncertainty_markers": list(evidence_packet["uncertainty_markers"]),
    }


def _build_summary(
    scored_event: Dict[str, Any],
    evidence_packet: Dict[str, Any],
    *,
    regenerated: bool = False,
    rewrite_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    top_fact = evidence_packet["source_support"][0]
    prefix = "摘要重生" if regenerated else "摘要"
    event_title = str(scored_event.get("event_title") or "").strip()
    top_fact_claim = str(top_fact.get("claim") or "").strip()
    uncertainty_text = str(evidence_packet["uncertainty_markers"][0] or "").strip()
    generic_text = (
        f"{prefix}：{event_title}。"
        f"已确认事实包括“{top_fact_claim}”，来源为 {top_fact['source_url']}；"
        f"使用时需保留提示：{uncertainty_text}"
    )
    wechat_text = _regenerate_wechat_summary(
        event_title,
        top_fact_claim,
        uncertainty_text,
        rewrite_feedback=rewrite_feedback,
        fallback=event_title or top_fact_claim or "ClawRadar 摘要",
    )
    return {
        "version": 2 if regenerated else 1,
        "text": generic_text,
        "channel_variants": {
            "wechat": wechat_text,
        },
        "source_refs": [item["fact_id"] for item in evidence_packet["source_support"][:2] if item.get("fact_id")],
        "uncertainty_markers": list(evidence_packet["uncertainty_markers"]),
    }


def _build_content_bundle(scored_event: Dict[str, Any]) -> Dict[str, Any]:
    evidence_packet = _build_evidence_packet(scored_event)
    title = _build_title(scored_event)
    outline = _build_outline(scored_event, evidence_packet)
    draft = _build_draft(scored_event, evidence_packet, title)
    summary = _build_summary(scored_event, evidence_packet)
    return {
        "event_id": scored_event["event_id"],
        "content_status": "generated",
        "evidence_packet": evidence_packet,
        "title": {"text": title, "version": 1},
        "outline": outline,
        "draft": draft,
        "summary": summary,
    }


def _rewrite_content_bundle(content_bundle: Dict[str, Any], scored_event: Dict[str, Any]) -> Dict[str, Any]:
    evidence_packet = content_bundle["evidence_packet"]
    company = _normalize_title_text(scored_event.get("trace", {}).get("company") or "")
    title_text = _regenerate_title(
        str(content_bundle.get("title", {}).get("text") or _build_title(scored_event)).strip(),
        company=company,
        fallback=TITLE_FALLBACK_TEXT,
    )
    draft = _build_draft(scored_event, evidence_packet, title_text, version_note="改写稿")
    draft["version"] = int(content_bundle.get("draft", {}).get("version", 1)) + 1
    return {
        **content_bundle,
        "content_status": "rewritten",
        "title": {"text": title_text, "version": int(content_bundle.get("title", {}).get("version", 1)) + 1},
        "draft": draft,
    }


def _regenerate_summary(content_bundle: Dict[str, Any], scored_event: Dict[str, Any]) -> Dict[str, Any]:
    evidence_packet = content_bundle["evidence_packet"]
    summary_rewrite_feedback = (
        deepcopy(content_bundle.get("summary_rewrite_feedback"))
        if isinstance(content_bundle.get("summary_rewrite_feedback"), dict)
        else None
    )
    return {
        **content_bundle,
        "content_status": "summary_regenerated",
        "summary": _build_summary(scored_event, evidence_packet, regenerated=True, rewrite_feedback=summary_rewrite_feedback),
    }


def _select_publish_ready_events(scored_events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        event for event in scored_events if isinstance(event, dict) and event.get("status") == ScoreDecisionStatus.PUBLISH_READY.value
    ]


def _get_report_engine_agent_factory():
    import_errors: List[str] = []
    for module_name, package_name in (
        ("ReportEngine.agent", None),
        ("radar_engines.ReportEngine.agent", "radar_engines.ReportEngine"),
        ("BettaFish.ReportEngine.agent", "BettaFish.ReportEngine"),
    ):
        try:
            if package_name and "ReportEngine" not in sys.modules:
                sys.modules["ReportEngine"] = import_module(package_name)
            return import_module(module_name).create_agent
        except Exception as exc:
            import_errors.append(f"{module_name}: {exc}")

    raise RuntimeError("ReportEngine agent unavailable: " + " | ".join(import_errors))



def _build_report_engine_config_overrides(payload: Dict[str, Any]) -> Dict[str, Any]:
    output_context = payload.get("output_context") if isinstance(payload.get("output_context"), dict) else {}
    reports_root = output_context.get("reports_root")
    debug_root = output_context.get("debug_root")
    if not reports_root:
        return {}

    reports_root_path = Path(reports_root).resolve()
    debug_root_path = Path(debug_root).resolve() if debug_root else reports_root_path.parent / "debug"
    ir_root = debug_root_path / "ir"
    chapters_root = debug_root_path / "chapters"
    logs_root = debug_root_path / "logs"

    return {
        "OUTPUT_DIR": str(reports_root_path.as_posix()),
        "DOCUMENT_IR_OUTPUT_DIR": str(ir_root.as_posix()),
        "CHAPTER_OUTPUT_DIR": str(chapters_root.as_posix()),
        "LOG_FILE": str((logs_root / "report.log").as_posix()),
        "JSON_ERROR_LOG_DIR": str((logs_root / "json_repair_failures").as_posix()),
    }


def _default_port_for_scheme(scheme: str) -> int:
    normalized = str(scheme or "").strip().lower()
    if normalized in {"https", "wss"}:
        return 443
    if normalized.startswith("socks"):
        return 1080
    return 80


def _connection_target(label: str, raw_url: str) -> Optional[Tuple[str, str, int]]:
    parsed = urlparse(str(raw_url or "").strip())
    if not parsed.hostname:
        return None
    port = parsed.port or _default_port_for_scheme(parsed.scheme)
    return label, parsed.hostname, int(port)


def _iter_connectivity_targets(agent: Any) -> List[Tuple[str, str, int]]:
    targets: List[Tuple[str, str, int]] = []
    seen = set()
    llm_client = getattr(agent, "llm_client", None)
    if llm_client is None:
        return targets

    for env_name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        env_value = str(os.getenv(env_name) or "").strip()
        target = _connection_target(f"{env_name}={env_value}", env_value)
        if target is None or target[1:] in seen:
            continue
        seen.add(target[1:])
        targets.append(target)

    base_url = getattr(llm_client, "base_url", None)
    target = _connection_target(f"base_url={base_url}", str(base_url or "").strip())
    if target is not None and target[1:] not in seen:
        targets.append(target)

    return targets


def _assert_external_writer_connectivity(agent: Any, *, timeout_seconds: float = 3.0) -> None:
    for label, host, port in _iter_connectivity_targets(agent):
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                continue
        except OSError as exc:
            raise RuntimeError(
                f"external_writer connectivity preflight failed for {label}: {host}:{port} is unreachable ({exc})"
            ) from exc


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _html_to_text(html_content: str) -> str:
    without_scripts = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", html_content, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", without_scripts)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _content_status_for_operation(operation: str) -> str:
    if operation == WriteOperation.REWRITE.value:
        return "rewritten"
    if operation == WriteOperation.REGENERATE_SUMMARY.value:
        return "summary_regenerated"
    return "generated"


def _extract_report_preview(report_text: str, *, max_length: int = 1200) -> str:
    preview = report_text[:max_length].strip()
    if len(report_text) > max_length:
        preview += "..."
    return preview


def _extract_report_summary_pack(generation_result: Dict[str, Any]) -> Dict[str, str]:
    def clean_text(value: Any) -> str:
        if isinstance(value, dict):
            return ""
        if isinstance(value, list):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return re.sub(r"\s+", " ", str(value or "")).strip()

    metadata = generation_result.get("report_metadata") if isinstance(generation_result.get("report_metadata"), dict) else {}
    summary_pack = metadata.get("summaryPack") if isinstance(metadata.get("summaryPack"), dict) else {}
    if not summary_pack:
        summary_pack = generation_result.get("summaryPack") if isinstance(generation_result.get("summaryPack"), dict) else {}

    generic = clean_text(summary_pack.get("generic"))
    short = clean_text(summary_pack.get("short"))
    wechat = clean_text(summary_pack.get("wechat"))
    source_hint = clean_text(summary_pack.get("sourceHint"))

    if not generic:
        generic = clean_text((summary_pack or {}).get("summary"))
    if not short:
        short = generic
    if not wechat:
        wechat = short or generic

    if generic or short or wechat:
        return {
            "generic": generic,
            "short": short,
            "wechat": wechat,
            "sourceHint": source_hint,
        }
    return {}


def _build_external_writer_request(
    payload: Dict[str, Any],
    scored_event: Dict[str, Any],
    evidence_packet: Dict[str, Any],
    *,
    operation: str,
) -> Dict[str, Any]:
    report_profile = deepcopy(payload.get("report_profile")) if isinstance(payload.get("report_profile"), dict) else {}
    writing_brief = deepcopy(payload.get("writing_brief")) if isinstance(payload.get("writing_brief"), dict) else {}
    title_constraints = _build_title_constraints()
    summary_constraints = _build_summary_constraints()
    custom_template = str(
        report_profile.get("custom_template")
        or payload.get("custom_template")
        or ""
    ).strip()
    query = str(
        writing_brief.get("title")
        or writing_brief.get("query")
        or scored_event.get("event_title")
        or scored_event.get("event_id")
        or "ClawRadar Report"
    ).strip()
    existing_profile_constraints = (
        report_profile.get("title_constraints") if isinstance(report_profile.get("title_constraints"), dict) else {}
    )
    report_profile["title_constraints"] = {**existing_profile_constraints, **title_constraints}
    report_profile["summary_constraints"] = {
        **(
            report_profile.get("summary_constraints")
            if isinstance(report_profile.get("summary_constraints"), dict)
            else {}
        ),
        **summary_constraints,
    }
    writing_brief["title_constraints"] = deepcopy(title_constraints)
    writing_brief["summary_constraints"] = deepcopy(summary_constraints)
    writing_brief["title_instruction"] = "微信公众号标题超长时必须直接重写，不得依赖下游裁剪兜底。"
    writing_brief["summary_instruction"] = "微信公众号摘要超长时必须直接重写为更短的完整纯文本摘要，不得依赖下游截断兜底。"
    if operation == WriteOperation.REGENERATE_SUMMARY.value and isinstance(payload.get("content_bundle"), dict):
        existing_summary = payload["content_bundle"].get("summary") if isinstance(payload["content_bundle"].get("summary"), dict) else {}
        existing_channel_variants = existing_summary.get("channel_variants") if isinstance(existing_summary.get("channel_variants"), dict) else {}
        summary_rewrite_feedback = payload.get("summary_rewrite_feedback") if isinstance(payload.get("summary_rewrite_feedback"), dict) else {}
        if summary_rewrite_feedback:
            writing_brief["summary_rewrite_feedback"] = deepcopy(summary_rewrite_feedback)
            report_profile["summary_rewrite_feedback"] = deepcopy(summary_rewrite_feedback)
        if existing_summary:
            writing_brief["existing_summary"] = {
                "generic": str(existing_summary.get("text") or "").strip(),
                "wechat": str(existing_channel_variants.get("wechat") or existing_summary.get("text") or "").strip(),
            }
    return {
        "event_id": str(scored_event.get("event_id") or "").strip(),
        "query": query,
        "operation": operation,
        "timeline": deepcopy(scored_event.get("timeline") or []),
        "evidence_pack": deepcopy(evidence_packet),
        "scorecard": deepcopy(scored_event.get("scorecard") or {}),
        "writing_brief": writing_brief,
        "report_profile": report_profile,
        "custom_template": custom_template,
    }


def _build_external_writer_inputs(write_request: Dict[str, Any], scored_event: Dict[str, Any]) -> Tuple[List[str], str]:
    trace = scored_event.get("trace", {}) if isinstance(scored_event.get("trace"), dict) else {}
    reports = [
        "\n".join(
            [
                "# ClawRadar 选题与写作简报",
                f"事件标题：{str(scored_event.get('event_title') or '').strip()}",
                f"公司：{str(trace.get('company') or '').strip()}",
                f"操作类型：{write_request['operation']}",
                "## 评分卡",
                _json_dump(write_request["scorecard"]),
                "## 写作简报",
                _json_dump(write_request["writing_brief"]),
            ]
        ),
        "\n".join(
            [
                "# ClawRadar 证据与时间线",
                "## 时间线",
                _json_dump(write_request["timeline"]),
                "## 证据包",
                _json_dump(write_request["evidence_pack"]),
            ]
        ),
        "\n".join(
            [
                "# ClawRadar 风险与约束",
                "## 输出约束",
                _json_dump(write_request["report_profile"]),
                "## 风险标记",
                _json_dump(scored_event.get("risk_flags") or []),
            ]
        ),
    ]
    forum_logs = "\n".join(
        [
            f"request_id={str(scored_event.get('request_id') or '').strip()}",
            f"event_id={write_request['event_id']}",
            f"operation={write_request['operation']}",
            f"decision_status={str(scored_event.get('status') or '').strip()}",
        ]
    )
    return reports, forum_logs


def _build_external_writer_bundle(
    scored_event: Dict[str, Any],
    evidence_packet: Dict[str, Any],
    write_request: Dict[str, Any],
    generation_result: Dict[str, Any],
    *,
    operation: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    company = _normalize_title_text(scored_event.get("trace", {}).get("company") or "")
    title_text = _regenerate_title(
        str(
            generation_result.get("report_title")
            or write_request.get("query")
            or _build_title(scored_event)
        ).strip(),
        company=company,
        fallback=TITLE_FALLBACK_TEXT,
    )
    outline = _build_outline(scored_event, evidence_packet)
    report_text = _html_to_text(str(generation_result.get("html_content") or "").strip())
    report_preview = _extract_report_preview(report_text) or f"原项目 ReportEngine 已生成报告：{title_text}"
    report_summary_pack = _extract_report_summary_pack(generation_result)
    summary_text = report_summary_pack.get("generic") or f"原项目 ReportEngine 已生成报告：{report_preview[:180]}" + ("..." if len(report_preview) > 180 else "")
    wechat_summary_text = report_summary_pack.get("wechat") or summary_text
    summary_source_hint = report_summary_pack.get("sourceHint") or ""
    source_refs = [item["fact_id"] for item in evidence_packet["source_support"] if item.get("fact_id")]
    uncertainty_markers = list(evidence_packet["uncertainty_markers"])
    summary_rewrite_feedback = write_request.get("writing_brief", {}).get("summary_rewrite_feedback") if isinstance(write_request.get("writing_brief"), dict) else None
    if operation == WriteOperation.REGENERATE_SUMMARY.value:
        top_fact_claim = str((evidence_packet.get("source_support") or [{}])[0].get("claim") or "").strip()
        uncertainty_text = str((uncertainty_markers or [""])[0] or "").strip()
        if summary_text:
            summary_text = _normalize_summary_text(summary_text)
        if wechat_summary_text:
            wechat_summary_text = _regenerate_wechat_summary(
                title_text or write_request.get("query") or str(scored_event.get("event_title") or "").strip(),
                top_fact_claim,
                uncertainty_text,
                rewrite_feedback=summary_rewrite_feedback if isinstance(summary_rewrite_feedback, dict) else None,
                fallback=_normalize_summary_text(wechat_summary_text) or _normalize_summary_text(summary_text) or title_text,
            )
        if not summary_text:
            summary_text = _normalize_summary_text(wechat_summary_text) or title_text
        if not summary_source_hint:
            summary_source_hint = "summaryPack.wechat"
    writer_receipt = {
        "event_id": str(scored_event.get("event_id") or "").strip(),
        "executor": WriteExecutor.EXTERNAL_WRITER.value,
        "status": WriteRunStatus.SUCCEEDED.value,
        "operation": operation,
        "query": write_request["query"],
        "report_id": generation_result.get("report_id"),
        "report_filepath": generation_result.get("report_filepath"),
        "report_relative_path": generation_result.get("report_relative_path"),
        "ir_filepath": generation_result.get("ir_filepath"),
        "ir_relative_path": generation_result.get("ir_relative_path"),
        "state_filepath": generation_result.get("state_filepath"),
        "state_relative_path": generation_result.get("state_relative_path"),
        "failure_info": None,
    }
    bundle = {
        "event_id": str(scored_event.get("event_id") or "").strip(),
        "content_status": _content_status_for_operation(operation),
        "evidence_packet": evidence_packet,
        "title": {"text": title_text, "version": 1},
        "outline": outline,
        "draft": {
            "version": 1,
            "label": "原项目报告",
            "body_markdown": report_preview,
            "source_refs": source_refs,
            "uncertainty_markers": uncertainty_markers,
        },
        "summary": {
            "version": 1,
            "text": summary_text,
            "channel_variants": {
                "wechat": wechat_summary_text,
            },
            "source_hint": summary_source_hint,
            "source_refs": source_refs[:2],
            "uncertainty_markers": uncertainty_markers,
        },
        "writer_receipt": deepcopy(writer_receipt),
        "report_artifacts": {
            "report_id": generation_result.get("report_id"),
            "report_filepath": generation_result.get("report_filepath"),
            "report_relative_path": generation_result.get("report_relative_path"),
            "ir_filepath": generation_result.get("ir_filepath"),
            "ir_relative_path": generation_result.get("ir_relative_path"),
            "state_filepath": generation_result.get("state_filepath"),
            "state_relative_path": generation_result.get("state_relative_path"),
        },
    }
    return bundle, writer_receipt


def _is_retryable_external_writer_error(exc: Exception) -> bool:
    try:
        from radar_engines.ReportEngine.llms import is_retryable_stream_error
    except Exception:
        return False
    return is_retryable_stream_error(exc)


def _build_external_writer_failure(
    normalized_payload: Dict[str, Any],
    *,
    operation: str,
    code: WriteErrorCode,
    message: str,
    write_requests: List[Dict[str, Any]],
    writer_receipts: List[Dict[str, Any]],
    content_bundles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "request_id": str(normalized_payload.get("request_id") or "").strip(),
        "trigger_source": str(normalized_payload.get("trigger_source") or "").strip(),
        "run_status": WriteRunStatus.FAILED.value,
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "operation": operation,
        "executor": WriteExecutor.EXTERNAL_WRITER.value,
        "content_bundles": content_bundles or [],
        "errors": [
            {
                "code": code.value,
                "message": message,
                "missing_fields": [],
            }
        ],
        "write_requests": write_requests,
        "writer_receipts": writer_receipts,
    }


def _topic_radar_write_external(normalized_payload: Dict[str, Any], *, operation: str) -> Dict[str, Any]:
    publish_ready_events = _select_publish_ready_events(normalized_payload["scored_events"])
    if not publish_ready_events:
        return build_write_rejection(
            normalized_payload,
            code=WriteErrorCode.DECISION_NOT_PUBLISH_READY,
            message="write requires publish_ready scored_events",
        )

    try:
        agent_factory = _get_report_engine_agent_factory()
    except Exception as exc:
        write_requests = []
        writer_receipts = [
            {
                "event_id": str(event.get("event_id") or "").strip(),
                "executor": WriteExecutor.EXTERNAL_WRITER.value,
                "status": WriteRunStatus.FAILED.value,
                "operation": operation,
                "query": str(event.get("event_title") or event.get("event_id") or "").strip(),
                "failure_info": {
                    "code": WriteErrorCode.WRITER_UNAVAILABLE.value,
                    "message": str(exc),
                },
            }
            for event in publish_ready_events
        ]
        return _build_external_writer_failure(
            normalized_payload,
            operation=operation,
            code=WriteErrorCode.WRITER_UNAVAILABLE,
            message=str(exc),
            write_requests=write_requests,
            writer_receipts=writer_receipts,
        )

    content_bundles: List[Dict[str, Any]] = []
    write_requests: List[Dict[str, Any]] = []
    writer_receipts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    try:
        agent = agent_factory(config_overrides=_build_report_engine_config_overrides(normalized_payload))
    except TypeError:
        agent = agent_factory()
    except Exception as exc:
        writer_receipts = [
            {
                "event_id": str(event.get("event_id") or "").strip(),
                "executor": WriteExecutor.EXTERNAL_WRITER.value,
                "status": WriteRunStatus.FAILED.value,
                "operation": operation,
                "query": str(event.get("event_title") or event.get("event_id") or "").strip(),
                "failure_info": {
                    "code": WriteErrorCode.WRITER_UNAVAILABLE.value,
                    "message": str(exc),
                },
            }
            for event in publish_ready_events
        ]
        return _build_external_writer_failure(
            normalized_payload,
            operation=operation,
            code=WriteErrorCode.WRITER_UNAVAILABLE,
            message=str(exc),
            write_requests=write_requests,
            writer_receipts=writer_receipts,
        )

    try:
        _assert_external_writer_connectivity(agent)
    except Exception as exc:
        writer_receipts = [
            {
                "event_id": str(event.get("event_id") or "").strip(),
                "executor": WriteExecutor.EXTERNAL_WRITER.value,
                "status": WriteRunStatus.FAILED.value,
                "operation": operation,
                "query": str(event.get("event_title") or event.get("event_id") or "").strip(),
                "failure_info": {
                    "code": WriteErrorCode.WRITER_UNAVAILABLE.value,
                    "message": str(exc),
                },
            }
            for event in publish_ready_events
        ]
        return _build_external_writer_failure(
            normalized_payload,
            operation=operation,
            code=WriteErrorCode.WRITER_UNAVAILABLE,
            message=str(exc),
            write_requests=write_requests,
            writer_receipts=writer_receipts,
        )

    for scored_event in publish_ready_events:
        evidence_packet = _build_evidence_packet(scored_event)
        write_request = _build_external_writer_request(
            normalized_payload,
            scored_event,
            evidence_packet,
            operation=operation,
        )
        write_requests.append(write_request)
        reports, forum_logs = _build_external_writer_inputs(write_request, scored_event)

        generation_result = None
        last_generation_error: Optional[Exception] = None
        for generation_attempt in range(2):
            try:
                generation_result = agent.generate_report(
                    query=write_request["query"],
                    reports=reports,
                    forum_logs=forum_logs,
                    custom_template=write_request["custom_template"],
                    save_report=True,
                )
                last_generation_error = None
                break
            except Exception as exc:
                last_generation_error = exc
                should_retry = generation_attempt == 0 and _is_retryable_external_writer_error(exc)
                if should_retry:
                    continue
                writer_receipts.append(
                    {
                        "event_id": write_request["event_id"],
                        "executor": WriteExecutor.EXTERNAL_WRITER.value,
                        "status": WriteRunStatus.FAILED.value,
                        "operation": operation,
                        "query": write_request["query"],
                        "failure_info": {
                            "code": WriteErrorCode.EXTERNAL_WRITER_FAILED.value,
                            "message": str(exc),
                        },
                    }
                )
                errors.append(
                    {
                        "code": WriteErrorCode.EXTERNAL_WRITER_FAILED.value,
                        "message": str(exc),
                        "missing_fields": [],
                    }
                )
                break
        if last_generation_error is not None:
            continue

        if not isinstance(generation_result, dict) or _is_blank(generation_result.get("html_content")):
            writer_receipts.append(
                {
                    "event_id": write_request["event_id"],
                    "executor": WriteExecutor.EXTERNAL_WRITER.value,
                    "status": WriteRunStatus.FAILED.value,
                    "operation": operation,
                    "query": write_request["query"],
                    "failure_info": {
                        "code": WriteErrorCode.INVALID_WRITER_OUTPUT.value,
                        "message": "external writer returned empty html_content",
                    },
                }
            )
            errors.append(
                {
                    "code": WriteErrorCode.INVALID_WRITER_OUTPUT.value,
                    "message": "external writer returned empty html_content",
                    "missing_fields": ["html_content"],
                }
            )
            continue

        bundle, writer_receipt = _build_external_writer_bundle(
            scored_event,
            evidence_packet,
            write_request,
            generation_result,
            operation=operation,
        )
        content_bundles.append(bundle)
        writer_receipts.append(writer_receipt)

    run_status = WriteRunStatus.SUCCEEDED.value if not errors else WriteRunStatus.FAILED.value
    return {
        "request_id": str(normalized_payload.get("request_id") or "").strip(),
        "trigger_source": str(normalized_payload.get("trigger_source") or "").strip(),
        "run_status": run_status,
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "operation": operation,
        "executor": WriteExecutor.EXTERNAL_WRITER.value,
        "content_bundles": content_bundles,
        "errors": errors,
        "write_requests": write_requests,
        "writer_receipts": writer_receipts,
    }


def topic_radar_write(
    payload: Dict[str, Any],
    *,
    operation: str = WriteOperation.GENERATE.value,
    executor: str = WriteExecutor.CLAWRADAR_BUILTIN.value,
) -> Dict[str, Any]:
    """执行阶段三内容生成，支持 builtin 与 external_writer。"""

    normalized_payload = validate_write_payload(payload, operation=operation)
    publish_ready_events = _select_publish_ready_events(normalized_payload["scored_events"])
    if not publish_ready_events:
        return build_write_rejection(
            normalized_payload,
            code=WriteErrorCode.DECISION_NOT_PUBLISH_READY,
            message="write requires publish_ready scored_events",
        )

    if executor == WriteExecutor.EXTERNAL_WRITER.value:
        return _topic_radar_write_external(normalized_payload, operation=operation)

    content_bundles: List[Dict[str, Any]] = []
    existing_bundle = normalized_payload.get("content_bundle") if isinstance(normalized_payload.get("content_bundle"), dict) else None

    for scored_event in publish_ready_events:
        if operation == WriteOperation.REWRITE.value and existing_bundle is not None:
            bundle = _rewrite_content_bundle(existing_bundle, scored_event)
        elif operation == WriteOperation.REGENERATE_SUMMARY.value and existing_bundle is not None:
            bundle = _regenerate_summary(existing_bundle, scored_event)
        else:
            bundle = _build_content_bundle(scored_event)
        content_bundles.append(bundle)

    return {
        "request_id": str(normalized_payload["request_id"]).strip(),
        "trigger_source": str(normalized_payload["trigger_source"]).strip(),
        "run_status": WriteRunStatus.SUCCEEDED.value,
        "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
        "operation": operation,
        "executor": WriteExecutor.CLAWRADAR_BUILTIN.value,
        "content_bundles": content_bundles,
        "errors": [],
        "write_requests": [],
        "writer_receipts": [],
    }


def build_write_rejection(
    payload: Optional[Dict[str, Any]] = None,
    *,
    code: WriteErrorCode = WriteErrorCode.INVALID_INPUT,
    message: str = "write payload rejected",
) -> Dict[str, Any]:
    """返回阶段三 write 拒收结构。"""

    payload = payload or {}
    request_id = payload.get("request_id")
    trigger_source = payload.get("trigger_source")
    try:
        validate_write_payload(payload, operation=payload.get("operation", WriteOperation.GENERATE.value))
    except WriteValidationError as exc:
        return {
            "request_id": request_id,
            "trigger_source": trigger_source,
            "run_status": WriteRunStatus.FAILED.value,
            "decision_status": ScoreDecisionStatus.NEED_MORE_EVIDENCE.value,
            "operation": payload.get("operation", WriteOperation.GENERATE.value),
            "executor": payload.get("executor", WriteExecutor.CLAWRADAR_BUILTIN.value),
            "content_bundles": [],
            "errors": [exc.to_error_response()],
            "write_requests": [],
            "writer_receipts": [],
        }

    return {
        "request_id": request_id,
        "trigger_source": trigger_source,
        "run_status": WriteRunStatus.FAILED.value,
        "decision_status": payload.get("decision_status", ScoreDecisionStatus.NEED_MORE_EVIDENCE.value),
        "operation": payload.get("operation", WriteOperation.GENERATE.value),
        "executor": payload.get("executor", WriteExecutor.CLAWRADAR_BUILTIN.value),
        "content_bundles": [],
        "errors": [
            {
                "code": code.value,
                "message": message,
                "missing_fields": [],
            }
        ],
        "write_requests": [],
        "writer_receipts": [],
    }
