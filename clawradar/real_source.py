"""阶段七：统一入口 real_source 适配，复用 MindSpider BroadTopicExtraction 热点采集。"""

from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib import import_module
from typing import Any, Dict, List, Sequence, Tuple

DEFAULT_REAL_SOURCE_PROVIDER = "mindspider_broad_topic_today_news"
DEFAULT_REAL_SOURCE_IDS: Tuple[str, ...] = ("weibo",)
DEFAULT_REAL_SOURCE_LIMIT = 5
DEFAULT_TOPIC_DRIVEN_PROVIDER = "topic_driven_news_search"
DEFAULT_TOPIC_DRIVEN_LIMIT = 5


class RealSourceUnavailableError(RuntimeError):
    """真实来源不可用。"""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_source_ids(raw_value: Any) -> List[str]:
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
        source_ids = [str(item).strip().lower() for item in raw_value if str(item).strip()]
    elif raw_value is None:
        source_ids = []
    else:
        source_ids = [segment.strip().lower() for segment in str(raw_value).split(",") if segment.strip()]

    if not source_ids:
        return list(DEFAULT_REAL_SOURCE_IDS)

    deduplicated: List[str] = []
    seen = set()
    for source_id in source_ids:
        if source_id in seen:
            continue
        seen.add(source_id)
        deduplicated.append(source_id)
    return deduplicated


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return resolved if resolved > 0 else default


def _normalize_event_time(raw_value: Any, *, fallback: str) -> str:
    if isinstance(raw_value, (int, float)):
        timestamp_value = float(raw_value)
        if timestamp_value > 10_000_000_000:
            timestamp_value /= 1000.0
        return datetime.fromtimestamp(timestamp_value, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    normalized = str(raw_value or "").strip()
    return normalized or fallback


def _sanitize_identifier(value: Any, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def _load_first_available_module(module_names: Sequence[str], *, capability_label: str):
    import_errors: List[str] = []
    for module_name in module_names:
        try:
            return import_module(module_name)
        except Exception as exc:  # pragma: no cover - exercised via adapter error path
            import_errors.append(f"{module_name}: {exc}")

    raise RealSourceUnavailableError(
        f"{capability_label} 不可用: " + " | ".join(import_errors)
    )


@lru_cache(maxsize=1)
def _load_settings():
    module = _load_first_available_module(
        (
            "radar_engines.config",
            "config",
            "ClawRadar.config",
            "BettaFish.config",
        ),
        capability_label="OpenClaw settings",
    )
    return module.settings



def _load_mindspider_module():
    return _load_first_available_module(
        (
            "MindSpider.BroadTopicExtraction.get_today_news",
            "radar_engines.MindSpider.BroadTopicExtraction.get_today_news",
            "BettaFish.MindSpider.BroadTopicExtraction.get_today_news",
        ),
        capability_label="MindSpider BroadTopicExtraction",
    )



def _load_query_engine_search_module():
    return _load_first_available_module(
        (
            "QueryEngine.tools.search",
            "radar_engines.QueryEngine.tools.search",
            "BettaFish.QueryEngine.tools.search",
        ),
        capability_label="QueryEngine search",
    )



def _load_media_engine_search_module():
    return _load_first_available_module(
        (
            "MediaEngine.tools.search",
            "radar_engines.MediaEngine.tools.search",
            "BettaFish.MediaEngine.tools.search",
        ),
        capability_label="MediaEngine search",
    )


def _settings_value(name: str) -> Any:
    return getattr(_load_settings(), name, None)


def _collect_mindspider_news(source_ids: Sequence[str]) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
    module = _load_mindspider_module()
    collector_class = getattr(module, "NewsCollector", None)
    if collector_class is None:
        raise RealSourceUnavailableError("MindSpider BroadTopicExtraction 缺少 NewsCollector")

    source_names = dict(getattr(module, "SOURCE_NAMES", {}) or {})
    base_url = str(getattr(module, "BASE_URL", "https://newsnow.busiyi.world")).rstrip("/")

    collector = collector_class.__new__(collector_class)
    collector.db_manager = None
    collector.supported_sources = list(source_names.keys())

    try:
        results = asyncio.run(collector.get_popular_news(list(source_ids)))
    except Exception as exc:
        raise RealSourceUnavailableError(f"MindSpider 热点采集失败: {exc}") from exc
    finally:
        close_method = getattr(collector, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass

    if not isinstance(results, list):
        raise RealSourceUnavailableError("MindSpider 热点采集结果格式无效")

    return results, source_names, base_url


def _build_fact_candidates(
    *,
    event_id: str,
    title: str,
    raw_excerpt: str,
    source_name: str,
    source_url: str,
    rank: Any,
) -> List[Dict[str, Any]]:
    rank_text = str(rank).strip()
    ranking_claim = f"该话题来自{source_name}热点榜单"
    if rank_text:
        ranking_claim = f"{ranking_claim}，当前榜单位置为第{rank_text}位"

    return [
        {
            "fact_id": f"{event_id}-fact-1",
            "claim": title,
            "source_url": source_url,
            "confidence": 0.72,
            "citation_excerpt": raw_excerpt or title,
        },
        {
            "fact_id": f"{event_id}-fact-2",
            "claim": ranking_claim,
            "source_url": source_url,
            "confidence": 0.68,
            "citation_excerpt": ranking_claim,
        },
    ]


def _map_news_item_to_candidate(
    item: Dict[str, Any],
    *,
    source_id: str,
    source_name: str,
    rank: int,
    base_url: str,
    collected_at: str,
    result_timestamp: str,
) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    title = str(item.get("title") or "").strip()
    if not title:
        return None

    item_identifier = item.get("id") or item.get("news_id") or f"rank-{rank}"
    event_id = f"real-source-{source_id}-{_sanitize_identifier(item_identifier, fallback=f'rank-{rank}') }"
    source_url = str(item.get("url") or "").strip() or f"{base_url}/api/s?id={source_id}&latest"
    event_time = _normalize_event_time(
        item.get("event_time") or item.get("publish_time") or item.get("ctime") or item.get("timestamp") or result_timestamp,
        fallback=collected_at,
    )
    raw_excerpt = str(
        item.get("desc")
        or item.get("digest")
        or item.get("content")
        or item.get("hot")
        or title
    ).strip()

    return {
        "event_id": event_id,
        "event_title": title,
        "company": str(item.get("company") or "").strip(),
        "event_time": event_time,
        "source_url": source_url,
        "source_type": f"mindspider:{source_id}",
        "raw_excerpt": raw_excerpt,
        "initial_tags": ["real_source", source_name],
        "confidence": 0.68,
        "timeline_candidates": [
            {
                "timestamp": collected_at,
                "label": "real_source_collected",
                "summary": f"OpenClaw 通过 MindSpider 的 {source_name} 热点采集接入该候选事件",
                "source_url": source_url,
                "source_type": f"mindspider:{source_id}",
            }
        ],
        "fact_candidates": _build_fact_candidates(
            event_id=event_id,
            title=title,
            raw_excerpt=raw_excerpt,
            source_name=source_name,
            source_url=source_url,
            rank=item.get("rank") or rank,
        ),
        "source_metadata": {
            "provider": DEFAULT_REAL_SOURCE_PROVIDER,
            "source_id": source_id,
            "source_name": source_name,
            "rank": item.get("rank") or rank,
            "item_id": str(item_identifier),
            "collected_at": collected_at,
            "upstream_timestamp": result_timestamp,
        },
        "source_snapshot": deepcopy(item),
    }


def _load_source_driven_payload(payload: Dict[str, Any], input_options: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    requested_source_ids = _normalize_source_ids(
        input_options.get("source_ids")
        or input_options.get("sources")
        or payload.get("real_source_ids")
    )
    candidate_limit = _coerce_positive_int(
        input_options.get("limit") or payload.get("real_source_limit"),
        default=DEFAULT_REAL_SOURCE_LIMIT,
    )
    collected_at = _utc_timestamp()

    results, source_names, base_url = _collect_mindspider_news(requested_source_ids)

    topic_candidates: List[Dict[str, Any]] = []
    applied_source_ids: List[str] = []
    failed_sources: List[Dict[str, Any]] = []

    for result in results:
        source_id = str(result.get("source") or "unknown").strip().lower() or "unknown"
        status = str(result.get("status") or "error").strip().lower()
        source_name = source_names.get(source_id, source_id)
        result_timestamp = _normalize_event_time(result.get("timestamp"), fallback=collected_at)

        if status != "success":
            failed_sources.append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": status,
                    "error": str(result.get("error") or "未知错误").strip() or "未知错误",
                }
            )
            continue

        items = result.get("data", {}).get("items") if isinstance(result.get("data"), dict) else []
        if not isinstance(items, list):
            failed_sources.append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": "invalid_payload",
                    "error": "MindSpider 返回 items 结构无效",
                }
            )
            continue

        if source_id not in applied_source_ids:
            applied_source_ids.append(source_id)

        for rank, item in enumerate(items, start=1):
            candidate = _map_news_item_to_candidate(
                item,
                source_id=source_id,
                source_name=source_name,
                rank=rank,
                base_url=base_url,
                collected_at=collected_at,
                result_timestamp=result_timestamp,
            )
            if candidate is None:
                continue
            topic_candidates.append(candidate)
            if len(topic_candidates) >= candidate_limit:
                break

        if len(topic_candidates) >= candidate_limit:
            break

    if not topic_candidates:
        raise RealSourceUnavailableError("MindSpider 未返回可用热点候选事件")

    context = {
        "provider": DEFAULT_REAL_SOURCE_PROVIDER,
        "requested_source_ids": list(requested_source_ids),
        "applied_source_ids": applied_source_ids,
        "failed_sources": failed_sources,
        "candidate_count": len(topic_candidates),
        "collected_at": collected_at,
    }

    return {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "topic_candidates": topic_candidates,
        "real_source_context": deepcopy(context),
    }, context



def _normalize_topic_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [segment.strip() for segment in str(value).split(",") if segment.strip()]

    deduplicated: List[str] = []
    seen = set()
    for item in values:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduplicated.append(item)
    return deduplicated



def _first_non_blank(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""



def _resolve_user_topic_context(payload: Dict[str, Any], input_options: Dict[str, Any]) -> Dict[str, Any]:
    existing_context = payload.get("user_topic_context") if isinstance(payload.get("user_topic_context"), dict) else {}
    user_topic = payload.get("user_topic") if isinstance(payload.get("user_topic"), dict) else {}
    requested_at = str(existing_context.get("requested_at") or _utc_timestamp()).strip() or _utc_timestamp()
    return {
        "topic": _first_non_blank(
            existing_context.get("topic"),
            input_options.get("topic"),
            user_topic.get("topic"),
            payload.get("topic"),
            payload.get("user_topic_title"),
            payload.get("keyword"),
        ),
        "company": _first_non_blank(
            existing_context.get("company"),
            input_options.get("company"),
            user_topic.get("company"),
            payload.get("company"),
        ),
        "track": _first_non_blank(
            existing_context.get("track"),
            input_options.get("track"),
            user_topic.get("track"),
            payload.get("track"),
            payload.get("sector"),
        ),
        "summary": _first_non_blank(
            existing_context.get("summary"),
            input_options.get("summary"),
            user_topic.get("summary"),
            payload.get("summary"),
            payload.get("topic_summary"),
        ),
        "keywords": _normalize_topic_string_list(
            existing_context.get("keywords")
            or input_options.get("keywords")
            or user_topic.get("keywords")
            or payload.get("keywords")
            or payload.get("topic_keywords")
        ),
        "requested_at": requested_at,
        "input_mode": "user_topic",
    }



def _build_topic_search_query(context: Dict[str, Any]) -> str:
    tokens = [
        context.get("topic"),
        context.get("company"),
        context.get("track"),
        *list(context.get("keywords") or []),
    ]
    deduplicated: List[str] = []
    seen = set()
    for token in tokens:
        text = str(token or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduplicated.append(text)
    return " ".join([*deduplicated, "最新新闻"]).strip()



def _search_with_tavily(query: str) -> List[Dict[str, Any]]:
    search_module = _load_query_engine_search_module()
    client = search_module.TavilyNewsAgency(api_key=_settings_value("TAVILY_API_KEY"))
    response = client.search_news_last_week(query)
    return [
        {
            "title": item.title,
            "url": item.url,
            "content": item.content,
            "published_at": item.published_date,
            "provider": "tavily_news",
            "source_type": "tavily:news",
            "source_name": "Tavily News",
        }
        for item in response.results
        if str(item.title or "").strip() and str(item.url or "").strip()
    ]



def _search_with_bocha(query: str) -> List[Dict[str, Any]]:
    search_module = _load_media_engine_search_module()
    client = search_module.BochaMultimodalSearch(api_key=_settings_value("BOCHA_WEB_SEARCH_API_KEY"))
    response = client.search_last_week(query)
    return [
        {
            "title": item.name,
            "url": item.url,
            "content": item.snippet,
            "published_at": item.date_last_crawled,
            "provider": "bocha_search",
            "source_type": "bocha:web",
            "source_name": "Bocha Search",
        }
        for item in response.webpages
        if str(item.name or "").strip() and str(item.url or "").strip()
    ]



def _search_with_anspire(query: str, limit: int) -> List[Dict[str, Any]]:
    search_module = _load_media_engine_search_module()
    client = search_module.AnspireAISearch(api_key=_settings_value("ANSPIRE_API_KEY"))
    response = client.search_last_week(query, max_results=limit)
    return [
        {
            "title": item.name,
            "url": item.url,
            "content": item.snippet,
            "published_at": item.date_last_crawled,
            "provider": "anspire_search",
            "source_type": "anspire:web",
            "source_name": "Anspire Search",
        }
        for item in response.webpages
        if str(item.name or "").strip() and str(item.url or "").strip()
    ]



def _build_topic_fact_candidates(
    *,
    event_id: str,
    title: str,
    raw_excerpt: str,
    source_url: str,
    source_name: str,
    rank: int,
    query: str,
) -> List[Dict[str, Any]]:
    return [
        {
            "fact_id": f"{event_id}-fact-1",
            "claim": title,
            "source_url": source_url,
            "confidence": 0.66,
            "citation_excerpt": raw_excerpt or title,
        },
        {
            "fact_id": f"{event_id}-fact-2",
            "claim": f"该候选通过 {source_name} 的主题搜索得到，搜索查询为“{query}”，排序位置为第{rank}位。",
            "source_url": source_url,
            "confidence": 0.58,
            "citation_excerpt": raw_excerpt or query,
        },
    ]



def _map_topic_search_item_to_candidate(
    item: Dict[str, Any],
    *,
    context: Dict[str, Any],
    rank: int,
    query: str,
    collected_at: str,
) -> Dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    source_url = str(item.get("url") or "").strip()
    if not title or not source_url:
        return None

    event_id = f"user-topic-{_sanitize_identifier(item.get('provider') or 'search', fallback='search')}-{_sanitize_identifier(source_url, fallback=f'rank-{rank}') }"
    raw_excerpt = str(item.get("content") or context.get("summary") or title).strip()
    event_time = _normalize_event_time(item.get("published_at"), fallback=collected_at)
    tag_candidates = [
        context.get("topic"),
        context.get("company"),
        context.get("track"),
        *list(context.get("keywords") or []),
    ]
    initial_tags = [str(tag).strip() for tag in tag_candidates if str(tag or "").strip()]
    source_name = str(item.get("source_name") or item.get("provider") or "topic_search").strip()
    source_type = str(item.get("source_type") or "topic_search:web").strip()

    return {
        "event_id": event_id,
        "event_title": title,
        "company": str(context.get("company") or "").strip(),
        "event_time": event_time,
        "source_url": source_url,
        "source_type": source_type,
        "raw_excerpt": raw_excerpt,
        "initial_tags": list(dict.fromkeys(initial_tags)),
        "confidence": 0.62,
        "timeline_candidates": [
            {
                "timestamp": collected_at,
                "label": "user_topic_search_collected",
                "summary": f"OpenClaw 围绕主题“{context.get('topic')}”通过 {source_name} 检索到该候选事件",
                "source_url": source_url,
                "source_type": source_type,
            }
        ],
        "fact_candidates": _build_topic_fact_candidates(
            event_id=event_id,
            title=title,
            raw_excerpt=raw_excerpt,
            source_url=source_url,
            source_name=source_name,
            rank=rank,
            query=query,
        ),
        "source_metadata": {
            "provider": str(item.get("provider") or "topic_search").strip(),
            "input_mode": "user_topic",
            "query": query,
            "rank": rank,
            "source_name": source_name,
            "collected_at": collected_at,
            "topic": str(context.get("topic") or "").strip(),
            "company": str(context.get("company") or "").strip(),
            "track": str(context.get("track") or "").strip(),
            "keywords": list(context.get("keywords") or []),
        },
        "source_snapshot": deepcopy(item),
    }



def _search_topic_news(context: Dict[str, Any], *, limit: int) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, Any]]]:
    query = _build_topic_search_query(context)
    tavily_api_key = _settings_value("TAVILY_API_KEY")
    bocha_api_key = _settings_value("BOCHA_WEB_SEARCH_API_KEY")
    anspire_api_key = _settings_value("ANSPIRE_API_KEY")
    provider_attempts: List[Tuple[str, Any]] = []
    if tavily_api_key:
        provider_attempts.append(("tavily_news", _search_with_tavily))
    if bocha_api_key:
        provider_attempts.append(("bocha_search", _search_with_bocha))
    if anspire_api_key:
        provider_attempts.append(("anspire_search", lambda raw_query: _search_with_anspire(raw_query, limit)))

    if not provider_attempts:
        raise RealSourceUnavailableError("user_topic real fetch unavailable: no search provider configured")

    failed_sources: List[Dict[str, Any]] = []
    for provider_name, loader in provider_attempts:
        try:
            items = loader(query)
        except Exception as exc:
            failed_sources.append(
                {
                    "source_id": provider_name,
                    "source_name": provider_name,
                    "status": "error",
                    "error": str(exc).strip() or "未知错误",
                }
            )
            continue

        deduplicated: List[Dict[str, Any]] = []
        seen_urls = set()
        for item in items:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduplicated.append(item)
            if len(deduplicated) >= limit:
                break

        if deduplicated:
            return deduplicated, query, failed_sources

        failed_sources.append(
            {
                "source_id": provider_name,
                "source_name": provider_name,
                "status": "empty",
                "error": "搜索结果为空",
            }
        )

    raise RealSourceUnavailableError("user_topic real fetch returned no usable search results")



def _load_topic_driven_payload(payload: Dict[str, Any], input_options: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    context = _resolve_user_topic_context(payload, input_options)
    if not context["topic"]:
        raise RealSourceUnavailableError("user_topic mode requires topic")

    candidate_limit = _coerce_positive_int(
        input_options.get("limit") or payload.get("user_topic_limit"),
        default=DEFAULT_TOPIC_DRIVEN_LIMIT,
    )
    collected_at = _utc_timestamp()
    search_items, query, failed_sources = _search_topic_news(context, limit=candidate_limit)

    topic_candidates: List[Dict[str, Any]] = []
    provider = ""
    applied_source_ids: List[str] = []
    for rank, item in enumerate(search_items, start=1):
        provider = str(item.get("provider") or provider or DEFAULT_TOPIC_DRIVEN_PROVIDER).strip()
        candidate = _map_topic_search_item_to_candidate(
            item,
            context=context,
            rank=rank,
            query=query,
            collected_at=collected_at,
        )
        if candidate is None:
            continue
        topic_candidates.append(candidate)
        if provider and provider not in applied_source_ids:
            applied_source_ids.append(provider)

    if not topic_candidates:
        raise RealSourceUnavailableError("user_topic real fetch returned no usable topic candidates")

    resolved_context = {
        **context,
        "provider": provider or DEFAULT_TOPIC_DRIVEN_PROVIDER,
        "query": query,
        "requested_source_ids": ["topic_query"],
        "applied_source_ids": applied_source_ids,
        "failed_sources": failed_sources,
        "candidate_count": len(topic_candidates),
        "collected_at": collected_at,
    }

    return {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "topic_candidates": topic_candidates,
        "user_topic_context": deepcopy(resolved_context),
    }, resolved_context



def load_real_source_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """加载真实来源或主题驱动抓取结果，并转换为既有 ingest 可消费载荷。"""

    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    input_options = entry_options.get("input") if isinstance(entry_options.get("input"), dict) else {}
    input_mode = str(input_options.get("mode") or "").strip().lower()

    if input_mode == "user_topic" or isinstance(payload.get("user_topic_context"), dict):
        return _load_topic_driven_payload(payload, input_options)
    return _load_source_driven_payload(payload, input_options)


__all__ = [
    "DEFAULT_REAL_SOURCE_PROVIDER",
    "DEFAULT_REAL_SOURCE_IDS",
    "DEFAULT_REAL_SOURCE_LIMIT",
    "RealSourceUnavailableError",
    "load_real_source_payload",
]
