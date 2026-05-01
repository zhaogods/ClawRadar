"""ClawRadar real_source adapters for source-driven and user-topic ingestion."""

from __future__ import annotations

import asyncio
import io
import re
import sys as _sys
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from importlib import import_module
from typing import Any, Dict, List, Sequence, Tuple

DEFAULT_REAL_SOURCE_PROVIDER = "mindspider_broad_topic_today_news"
DEFAULT_REAL_SOURCE_IDS: Tuple[str, ...] = ("weibo", "zhihu", "36kr")
DEFAULT_REAL_SOURCE_LIMIT = 10
DEFAULT_TOPIC_DRIVEN_PROVIDER = "topic_driven_news_search"
DEFAULT_TOPIC_DRIVEN_LIMIT = 10


class RealSourceUnavailableError(RuntimeError):
    """Raised when real-source fetching cannot produce usable candidates."""


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
        except Exception as exc:  # pragma: no cover
            import_errors.append(f"{module_name}: {exc}")

    raise RealSourceUnavailableError(f"{capability_label} unavailable: " + " | ".join(import_errors))


@lru_cache(maxsize=1)
def _load_settings():
    module = _load_first_available_module(
        (
            "radar_engines.config",
            "config",
            "ClawRadar.config",
            "BettaFish.config",
        ),
        capability_label="ClawRadar settings",
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


def _load_deep_sentiment_module():
    return _load_first_available_module(
        (
            "radar_engines.MindSpider.DeepSentimentCrawling.main",
        ),
        capability_label="MindSpider DeepSentimentCrawling",
    )


def _run_deep_sentiment_crawling(
    platforms: List[str] | None = None,
    max_keywords: int = 50,
    max_notes: int = 50,
    test_mode: bool = False,
    login_type: str = "auto",
    server_mode: bool | None = None,
) -> Dict[str, Any]:
    """Run MindSpider DeepSentimentCrawling on selected social media platforms.

    Returns a dict with crawl statistics and content summaries per platform.
    """
    if platforms is None:
        platforms = ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]

    module = _load_deep_sentiment_module()
    crawler_class = getattr(module, "DeepSentimentCrawling", None)
    if crawler_class is None:
        raise RealSourceUnavailableError("MindSpider DeepSentimentCrawling class not found")

    crawler = crawler_class(server_mode=server_mode)

    # Wrap stdout/stderr with UTF-8 to survive emoji print() on GBK Windows consoles
    _old_stdout = _sys.stdout
    _old_stderr = _sys.stderr
    try:
        if hasattr(_old_stdout, "buffer") and _old_stdout.buffer is not None:
            _sys.stdout = io.TextIOWrapper(
                _old_stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        if hasattr(_old_stderr, "buffer") and _old_stderr.buffer is not None:
            _sys.stderr = io.TextIOWrapper(
                _old_stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        crawl_return = crawler.run_daily_crawling(
            target_date=None,  # Use today
            platforms=list(platforms),
            max_keywords_per_platform=int(max_keywords),
            max_notes_per_platform=int(max_notes),
            login_type=login_type,
        )
    except Exception as exc:
        raise RealSourceUnavailableError(f"DeepSentimentCrawling failed: {exc}") from exc
    finally:
        # Detach wrappers from underlying buffers so GC won't close them
        _new_stdout = _sys.stdout
        _new_stderr = _sys.stderr
        _sys.stdout = _old_stdout
        _sys.stderr = _old_stderr
        for _w in (_new_stdout, _new_stderr):
            try:
                _w.detach()
            except Exception:
                pass

    # run_daily_crawling may return bool or {"success": bool, "error": str}
    if isinstance(crawl_return, dict):
        is_success = bool(crawl_return.get("success"))
        error_msg = str(crawl_return.get("error") or "").strip()
    else:
        is_success = bool(crawl_return)
        error_msg = "" if is_success else "crawling returned False"

    summary = crawler.get_crawl_summary() if hasattr(crawler, "get_crawl_summary") else {}
    return {
        "success": is_success,
        "error": error_msg if not is_success else None,
        "platforms_attempted": list(platforms),
        "params": {
            "max_keywords": max_keywords,
            "max_notes": max_notes,
            "test_mode": test_mode,
        },
        "summary": summary,
    }


def _settings_value(name: str) -> Any:
    return getattr(_load_settings(), name, None)


def _collect_mindspider_news(
    source_ids: Sequence[str],
    *,
    persist: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], str, List[str]]:
    module = _load_mindspider_module()
    collector_class = getattr(module, "NewsCollector", None)
    if collector_class is None:
        raise RealSourceUnavailableError("MindSpider BroadTopicExtraction missing NewsCollector")

    source_names = dict(getattr(module, "SOURCE_NAMES", {}) or {})
    base_url = str(getattr(module, "BASE_URL", "https://newsnow.busiyi.world")).rstrip("/")

    collector = collector_class.__new__(collector_class)
    collector.supported_sources = list(source_names.keys())

    # Enable database persistence when configured
    extracted_keywords: List[str] = []
    if persist:
        try:
            settings = _load_settings()
            db_config = {
                "db_dialect": getattr(settings, "DB_DIALECT", "mysql"),
                "db_host": getattr(settings, "DB_HOST", "127.0.0.1"),
                "db_port": int(getattr(settings, "DB_PORT", 3306)),
                "db_user": getattr(settings, "DB_USER", "root"),
                "db_password": getattr(settings, "DB_PASSWORD", ""),
                "db_name": getattr(settings, "DB_NAME", "mindspider"),
                "db_charset": getattr(settings, "DB_CHARSET", "utf8mb4"),
            }
            DatabaseManager = getattr(module, "DatabaseManager", None)
            if DatabaseManager is not None:
                db = DatabaseManager()
                collector.db_manager = db
        except Exception:
            collector.db_manager = None
    else:
        collector.db_manager = None

    try:
        results = asyncio.run(collector.get_popular_news(list(source_ids)))
    except Exception as exc:
        raise RealSourceUnavailableError(f"MindSpider hot news collection failed: {exc}") from exc

    if not isinstance(results, list):
        raise RealSourceUnavailableError("MindSpider hot news collection returned an invalid payload")

    # Persist collected news to database and extract keywords if DB was enabled
    if persist and collector.db_manager is not None:
        try:
            asyncio.run(collector.collect_and_save_news(list(source_ids)))
        except Exception:
            pass

    # Extract keywords & save to daily_topics so DeepSentimentCrawling can read them
    if persist:
        try:
            topic_module = _load_first_available_module(
                (
                    "MindSpider.BroadTopicExtraction.topic_extractor",
                    "radar_engines.MindSpider.BroadTopicExtraction.topic_extractor",
                ),
                capability_label="MindSpider TopicExtractor",
            )
            TopicExtractor = getattr(topic_module, "TopicExtractor", None)
            if TopicExtractor is not None:
                extractor = TopicExtractor()
                news_items = []
                for result in results:
                    items = result.get("data", {}).get("items", []) if isinstance(result.get("data"), dict) else []
                    news_items.extend(items)
                if news_items:
                    ai_result = extractor.extract_keywords_and_summary(news_items)
                    # extract_keywords_and_summary returns Tuple[List[str], str]
                    if isinstance(ai_result, (tuple, list)) and len(ai_result) >= 2:
                        extracted_keywords = list(ai_result[0] or [])
                        ai_summary = str(ai_result[1] or "")
                    else:
                        extracted_keywords = []
                        ai_summary = ""
                    if extracted_keywords and collector.db_manager is not None:
                        collector.db_manager.save_daily_topics(extracted_keywords, ai_summary)
        except Exception:
            pass

    # Log historical crawl statistics when persistence is active
    if persist and collector.db_manager is not None:
        try:
            stats = collector.db_manager.show_statistics()
            if stats:
                logger = getattr(module, "logger", None)
                if logger:
                    logger.info(f"📊 历史爬取统计: {stats}")
            recent = collector.db_manager.show_recent_data(days=3)
            if recent is not None:
                logger = getattr(module, "logger", None)
                if logger:
                    logger.info(f"📅 最近3天数据量: {recent}")
        except Exception:
            pass

    # Close DB connection after all operations complete
    close_method = getattr(collector, "close", None)
    if callable(close_method):
        try:
            close_method()
        except Exception:
            pass

    return results, source_names, base_url, extracted_keywords


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
    ranking_claim = f"This topic came from the {source_name} trending list"
    if rank_text:
        ranking_claim = f"{ranking_claim}, current rank #{rank_text}"

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
    raw_excerpt = str(item.get("desc") or item.get("digest") or item.get("content") or item.get("hot") or title).strip()

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
                "summary": f"ClawRadar collected this candidate from MindSpider {source_name} trending feed",
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


def _dedupe_candidates_by_source_url(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    seen_keys = set()
    for candidate in candidates:
        source_url = str(candidate.get("source_url") or "").strip().lower()
        event_id = str(candidate.get("event_id") or "").strip().lower()
        dedupe_key = source_url or event_id
        if not dedupe_key or dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduplicated.append(candidate)
    return deduplicated


def _round_robin_take(grouped_items: Sequence[Sequence[Dict[str, Any]]], *, limit: int, key_field: str) -> List[Dict[str, Any]]:
    buckets: List[List[Dict[str, Any]]] = [list(items) for items in grouped_items if items]
    merged: List[Dict[str, Any]] = []
    seen_keys = set()

    while buckets and len(merged) < limit:
        next_buckets: List[List[Dict[str, Any]]] = []
        for bucket in buckets:
            while bucket and len(merged) < limit:
                candidate = bucket.pop(0)
                key = str(candidate.get(key_field) or "").strip().lower()
                if not key:
                    key = str(candidate.get("event_id") or "").strip().lower()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(candidate)
                break
            if bucket:
                next_buckets.append(bucket)
            if len(merged) >= limit:
                break
        buckets = next_buckets

    return merged


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

    persist = bool(input_options.get("persist") or payload.get("persist"))

    results, source_names, base_url, extracted_keywords = _collect_mindspider_news(
        requested_source_ids, persist=persist,
    )

    grouped_candidates: List[List[Dict[str, Any]]] = []
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
                    "error": str(result.get("error") or "unknown error").strip() or "unknown error",
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
                    "error": "MindSpider returned invalid items payload",
                }
            )
            continue

        source_candidates: List[Dict[str, Any]] = []
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
            if candidate is not None:
                source_candidates.append(candidate)

        source_candidates = _dedupe_candidates_by_source_url(source_candidates)
        if not source_candidates:
            failed_sources.append(
                {
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": "empty",
                    "error": "MindSpider returned no usable news items",
                }
            )
            continue

        grouped_candidates.append(source_candidates)
        if source_id not in applied_source_ids:
            applied_source_ids.append(source_id)

    topic_candidates = _round_robin_take(grouped_candidates, limit=candidate_limit, key_field="source_url")
    if not topic_candidates:
        raise RealSourceUnavailableError("MindSpider returned no usable topic candidates")

    context = {
        "provider": DEFAULT_REAL_SOURCE_PROVIDER,
        "requested_source_ids": list(requested_source_ids),
        "applied_source_ids": applied_source_ids,
        "failed_sources": failed_sources,
        "candidate_count": len(topic_candidates),
        "collected_at": collected_at,
        "extracted_keywords": extracted_keywords,
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
    return " ".join([*deduplicated, "latest news"]).strip()


def _normalize_search_item(
    item: Any,
    *,
    provider: str,
    source_type: str,
    source_name: str,
    time_window: str = "week",
    time_weight: float = 1.0,
) -> Dict[str, Any] | None:
    """Normalize a search result item to the common dict format."""
    title = str(getattr(item, "title", "") or getattr(item, "name", "") or "").strip()
    url = str(getattr(item, "url", "") or "").strip()
    if not title or not url:
        return None
    return {
        "title": title,
        "url": url,
        "content": str(getattr(item, "content", "") or getattr(item, "snippet", "") or "").strip(),
        "published_at": str(getattr(item, "published_date", "") or getattr(item, "date_last_crawled", "") or "").strip(),
        "provider": provider,
        "source_type": source_type,
        "source_name": source_name,
        "time_window": time_window,
        "time_weight": time_weight,
    }


# Time decay weights: 24h = 1.0, week = 0.7, month = 0.4
_TIME_WINDOW_WEIGHTS = {"24h": 1.0, "week": 0.7, "month": 0.4}


def _search_with_tavily(query: str) -> List[Dict[str, Any]]:
    search_module = _load_query_engine_search_module()
    api_key = _settings_value("TAVILY_API_KEY")
    client = search_module.TavilyNewsAgency(api_key=api_key)

    items: List[Dict[str, Any]] = []

    # Multi-window search: 24h, week
    windows = [
        ("24h", lambda: client.search_news_last_24_hours(query)),
        ("week", lambda: client.search_news_last_week(query)),
    ]
    for window_name, search_fn in windows:
        try:
            response = search_fn()
            for item in response.results:
                norm = _normalize_search_item(
                    item,
                    provider="tavily_news",
                    source_type=f"tavily:news:{window_name}",
                    source_name="Tavily News",
                    time_window=window_name,
                    time_weight=_TIME_WINDOW_WEIGHTS.get(window_name, 0.7),
                )
                if norm:
                    items.append(norm)
        except Exception:
            pass

    # Image search
    try:
        img_response = client.search_images_for_news(query)
        for item in img_response.results:
            title = str(getattr(item, "title", "") or "").strip()
            img_url = str(getattr(item, "url", "") or "").strip()
            if title and img_url:
                items.append({
                    "title": title,
                    "url": img_url,
                    "content": str(getattr(item, "description", "") or "").strip(),
                    "published_at": "",
                    "provider": "tavily_news",
                    "source_type": "tavily:image",
                    "source_name": "Tavily Images",
                    "time_window": "week",
                    "time_weight": 0.5,
                    "is_image": True,
                })
    except Exception:
        pass

    return items


def _search_with_bocha(query: str) -> List[Dict[str, Any]]:
    search_module = _load_media_engine_search_module()
    api_key = _settings_value("BOCHA_WEB_SEARCH_API_KEY")
    client = search_module.BochaMultimodalSearch(api_key=api_key)

    items: List[Dict[str, Any]] = []

    # Multi-window search: 24h, week
    windows = [
        ("24h", lambda: client.search_last_24_hours(query)),
        ("week", lambda: client.search_last_week(query)),
    ]
    for window_name, search_fn in windows:
        try:
            response = search_fn()
            for item in response.webpages:
                norm = _normalize_search_item(
                    item,
                    provider="bocha_search",
                    source_type=f"bocha:web:{window_name}",
                    source_name="Bocha Search",
                    time_window=window_name,
                    time_weight=_TIME_WINDOW_WEIGHTS.get(window_name, 0.7),
                )
                if norm:
                    items.append(norm)
        except Exception:
            pass

    # Structured data search (stock, weather, encyclopedia)
    try:
        struct_response = client.search_for_structured_data(query)
        for item in struct_response.webpages:
            norm = _normalize_search_item(
                item,
                provider="bocha_search",
                source_type="bocha:structured",
                source_name="Bocha Structured",
                time_window="week",
                time_weight=0.8,
            )
            if norm:
                norm["is_structured"] = True
                items.append(norm)
    except Exception:
        pass

    return items


def _search_with_anspire(query: str, limit: int) -> List[Dict[str, Any]]:
    search_module = _load_media_engine_search_module()
    api_key = _settings_value("ANSPIRE_API_KEY")
    client = search_module.AnspireAISearch(api_key=api_key)

    items: List[Dict[str, Any]] = []

    # Multi-window search: 24h, week
    windows = [
        ("24h", lambda: client.search_last_24_hours(query, max_results=max(limit // 2, 3)),
         ),
        ("week", lambda: client.search_last_week(query, max_results=limit),
         ),
    ]
    for window_name, search_fn in windows:
        try:
            response = search_fn()
            for item in response.webpages:
                norm = _normalize_search_item(
                    item,
                    provider="anspire_search",
                    source_type=f"anspire:web:{window_name}",
                    source_name="Anspire Search",
                    time_window=window_name,
                    time_weight=_TIME_WINDOW_WEIGHTS.get(window_name, 0.7),
                )
                if norm:
                    items.append(norm)
        except Exception:
            pass

    return items


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
            "claim": f"This candidate was found through {source_name} using query '{query}' at rank #{rank}.",
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
    time_weight = float(item.get("time_weight") or 1.0)
    base_confidence = 0.62
    adjusted_confidence = min(0.85, base_confidence * time_weight + 0.10)
    if item.get("is_structured"):
        adjusted_confidence = max(adjusted_confidence, 0.68)
    if item.get("is_image"):
        adjusted_confidence = max(adjusted_confidence, 0.55)

    return {
        "event_id": event_id,
        "event_title": title,
        "company": str(context.get("company") or "").strip(),
        "event_time": event_time,
        "source_url": source_url,
        "source_type": source_type,
        "raw_excerpt": raw_excerpt,
        "initial_tags": list(dict.fromkeys(initial_tags)),
        "confidence": round(adjusted_confidence, 3),
        "image_urls": [source_url] if item.get("is_image") else [],
        "structured_data": item.get("is_structured") or False,
        "time_weight": time_weight,
        "time_window": str(item.get("time_window") or ""),
        "timeline_candidates": [
            {
                "timestamp": collected_at,
                "label": "user_topic_search_collected",
                "summary": f"ClawRadar searched topic '{context.get('topic')}' via {source_name} and found this candidate",
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


def _dedupe_search_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    seen_urls = set()
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        normalized_url = url.lower()
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduplicated.append(item)
    return deduplicated


def _merge_provider_search_results(provider_results: Sequence[Tuple[str, Sequence[Dict[str, Any]]]], *, limit: int) -> List[Dict[str, Any]]:
    grouped_items = [_dedupe_search_items(items) for _, items in provider_results if items]
    return _round_robin_take(grouped_items, limit=limit, key_field="url")


def _build_search_enrichment_stats(
    items: Sequence[Dict[str, Any]],
    *,
    enrichment_items: Sequence[Dict[str, Any]] = (),
    extra_queries: Sequence[str] = (),
    applied_source_ids: Sequence[str] = (),
    failed_sources: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "total_items": len(items),
        "enrichment_items": len(enrichment_items),
        "extra_queries_used": len(list(extra_queries)),
        "providers": {},
    }
    all_items = list(items) + list(enrichment_items)
    for provider in applied_source_ids:
        provider_items = [it for it in all_items if it.get("provider") == provider]
        window_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        image_count = 0
        struct_count = 0
        for it in provider_items:
            tw = str(it.get("time_window") or "unknown")
            window_counts[tw] = window_counts.get(tw, 0) + 1
            st = str(it.get("source_type") or "unknown")
            type_counts[st] = type_counts.get(st, 0) + 1
            if it.get("is_image"):
                image_count += 1
            if it.get("is_structured"):
                struct_count += 1
        stats["providers"][provider] = {
            "total": len(provider_items),
            "by_time_window": window_counts,
            "by_source_type": type_counts,
            "image_results": image_count,
            "structured_data_results": struct_count,
        }
    stats["failed_sources"] = list(failed_sources)
    return stats


def _search_topic_news(
    context: Dict[str, Any],
    *,
    limit: int,
    extra_queries: Sequence[str] = (),
) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
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
    provider_results: List[Tuple[str, List[Dict[str, Any]]]] = []
    applied_source_ids: List[str] = []

    # Primary search with main query
    for provider_name, loader in provider_attempts:
        try:
            items = _dedupe_search_items(loader(query))[:limit]
        except Exception as exc:
            failed_sources.append(
                {
                    "source_id": provider_name,
                    "source_name": provider_name,
                    "status": "error",
                    "error": str(exc).strip() or "unknown error",
                }
            )
            continue

        if not items:
            failed_sources.append(
                {
                    "source_id": provider_name,
                    "source_name": provider_name,
                    "status": "empty",
                    "error": "search returned no results",
                }
            )
            continue

        provider_results.append((provider_name, items))
        applied_source_ids.append(provider_name)

    # Supplementary search with BroadTopic extracted keywords
    enrichment_items: List[Dict[str, Any]] = []
    for extra_query in list(extra_queries)[:5]:  # Cap at 5 extra queries
        combined = f"{extra_query} {context.get('topic', '')}".strip()
        if not combined:
            continue
        for provider_name, loader in provider_attempts:
            try:
                extra = _dedupe_search_items(loader(combined))[: max(3, limit // 3)]
                for item in extra:
                    item["source_type"] = f"{item.get('source_type', 'search')}:enriched"
                    item["source_name"] = f"{item.get('source_name', 'Search')} (关键词补充)"
                    item["time_weight"] = float(item.get("time_weight") or 0.7) * 0.8
                    enrichment_items.append(item)
            except Exception:
                pass

    merged_items = _merge_provider_search_results(provider_results, limit=limit)
    # Append enrichment items after merged results
    seen_urls = {str(item.get("url") or "").strip().lower() for item in merged_items}
    for enriched in enrichment_items:
        url = str(enriched.get("url") or "").strip().lower()
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged_items.append(enriched)

    if not merged_items:
        raise RealSourceUnavailableError("user_topic real fetch returned no usable search results")

    return merged_items, query, failed_sources, applied_source_ids, list(enrichment_items)


def _load_topic_driven_payload(payload: Dict[str, Any], input_options: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    context = _resolve_user_topic_context(payload, input_options)
    if not context["topic"]:
        raise RealSourceUnavailableError("user_topic mode requires topic")

    candidate_limit = _coerce_positive_int(
        input_options.get("limit") or payload.get("user_topic_limit"),
        default=DEFAULT_TOPIC_DRIVEN_LIMIT,
    )
    collected_at = _utc_timestamp()
    extra_queries = list(
        dict.fromkeys(
            [
                q
                for q in (
                    list(context.get("extracted_keywords") or [])
                    + list(context.get("keywords") or [])
                )
                if isinstance(q, str) and q.strip()
            ]
        )
    )
    search_items, query, failed_sources, applied_source_ids, enrichment_items = _search_topic_news(
        context, limit=candidate_limit, extra_queries=extra_queries,
    )

    topic_candidates: List[Dict[str, Any]] = []
    for rank, item in enumerate(search_items, start=1):
        candidate = _map_topic_search_item_to_candidate(
            item,
            context=context,
            rank=rank,
            query=query,
            collected_at=collected_at,
        )
        if candidate is not None:
            topic_candidates.append(candidate)

    if not topic_candidates:
        raise RealSourceUnavailableError("user_topic real fetch returned no usable topic candidates")

    resolved_context = {
        **context,
        "provider": applied_source_ids[0] if applied_source_ids else DEFAULT_TOPIC_DRIVEN_PROVIDER,
        "query": query,
        "requested_source_ids": ["topic_query"],
        "applied_source_ids": applied_source_ids,
        "failed_sources": failed_sources,
        "candidate_count": len(topic_candidates),
        "collected_at": collected_at,
        "enrichment_keywords": extra_queries,
        "enrichment_candidates": len(enrichment_items),
        "search_enrichment": _build_search_enrichment_stats(
            search_items,
            enrichment_items=enrichment_items,
            extra_queries=extra_queries,
            applied_source_ids=applied_source_ids,
            failed_sources=failed_sources,
        ),
    }

    return {
        "request_id": str(payload.get("request_id") or "").strip(),
        "trigger_source": str(payload.get("trigger_source") or "").strip(),
        "topic_candidates": topic_candidates,
        "user_topic_context": deepcopy(resolved_context),
    }, resolved_context


def load_real_source_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load source-driven or topic-driven candidates into ingest-compatible payloads."""

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
