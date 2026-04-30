import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from clawradar import real_source
from clawradar.contracts import normalize_ingest_payload
from clawradar.real_source import RealSourceUnavailableError, load_real_source_payload


class ClawRadarContractsTestCase(unittest.TestCase):
    def _build_minimal_payload(self):
        return {
            "request_id": "req-stage1-minimal",
            "trigger_source": "manual",
            "topic_candidates": [
                {
                    "event_id": "evt-stage1-001",
                    "event_title": "OpenAI 发布企业级模型治理更新",
                    "company": "OpenAI",
                    "event_time": "2026-04-09T08:30:00Z",
                    "source_url": "https://example.com/openai-governance-update",
                    "source_type": "news",
                    "raw_excerpt": "OpenAI 发布企业级模型治理更新并披露审计能力。",
                    "initial_tags": ["AI", "治理"],
                    "confidence": 0.93,
                    "timeline_candidates": [
                        {
                            "timestamp": "2026-04-09T08:00:00Z",
                            "label": "announcement",
                            "summary": "官方预告企业级模型治理能力即将上线。",
                            "source_url": "https://example.com/openai-governance-preview",
                            "source_type": "blog",
                        }
                    ],
                    "fact_candidates": [
                        {
                            "fact_id": "fact-stage1-001",
                            "claim": "OpenAI 发布企业级模型治理更新",
                            "source_url": "https://example.com/openai-governance-update",
                            "confidence": 0.93,
                            "citation_excerpt": "OpenAI 发布企业级模型治理更新并披露审计能力。",
                        },
                        {
                            "fact_id": "fact-stage1-002",
                            "claim": "更新包含审计能力",
                            "source_url": "https://example.com/openai-governance-update",
                            "confidence": 0.88,
                            "citation_excerpt": "披露审计能力。",
                        },
                    ],
                }
            ],
        }

    def _build_real_source_payload(self):
        return {
            "request_id": "req-stage7-real-source",
            "trigger_source": "manual",
            "topic_candidates": [
                {
                    "event_id": "real-source-weibo-123",
                    "event_title": "AI 公司发布新模型并进入微博热搜",
                    "company": "AI公司",
                    "event_time": "2026-04-10T08:00:00Z",
                    "source_url": "https://example.com/weibo/123",
                    "source_type": "mindspider:weibo",
                    "raw_excerpt": "微博热搜显示 AI 公司发布新模型并引发广泛讨论。",
                    "initial_tags": ["real_source", "微博热搜"],
                    "confidence": 0.72,
                    "timeline_candidates": [
                        {
                            "timestamp": "2026-04-10T08:05:00Z",
                            "label": "real_source_collected",
                            "summary": "MindSpider 从微博热搜采集到该事件。",
                            "source_url": "https://example.com/weibo/123",
                            "source_type": "mindspider:weibo",
                        }
                    ],
                    "fact_candidates": [
                        {
                            "fact_id": "real-source-weibo-123-fact-1",
                            "claim": "AI 公司发布新模型并进入微博热搜",
                            "source_url": "https://example.com/weibo/123",
                            "confidence": 0.72,
                            "citation_excerpt": "微博热搜显示 AI 公司发布新模型并引发广泛讨论。",
                        },
                        {
                            "fact_id": "real-source-weibo-123-fact-2",
                            "claim": "该话题来自微博热搜榜单，当前榜单位置为第1位",
                            "source_url": "https://example.com/weibo/123",
                            "confidence": 0.68,
                            "citation_excerpt": "该话题来自微博热搜榜单，当前榜单位置为第1位",
                        },
                    ],
                    "source_metadata": {
                        "provider": "mindspider_broad_topic_today_news",
                        "source_id": "weibo",
                        "source_name": "微博热搜",
                        "rank": 1,
                        "item_id": "123",
                        "collected_at": "2026-04-10T08:05:00Z",
                        "upstream_timestamp": "2026-04-10T08:05:00Z",
                    },
                    "source_snapshot": {
                        "id": "123",
                        "title": "AI 公司发布新模型并进入微博热搜",
                        "url": "https://example.com/weibo/123",
                        "rank": 1,
                    },
                }
            ],
            "real_source_context": {
                "provider": "mindspider_broad_topic_today_news",
                "requested_source_ids": ["weibo"],
                "applied_source_ids": ["weibo"],
                "failed_sources": [],
                "candidate_count": 1,
                "collected_at": "2026-04-10T08:05:00Z",
            },
        }

    def test_minimal_valid_payload_is_accepted(self):
        payload = self._build_minimal_payload()

        result = normalize_ingest_payload(payload)

        self.assertEqual(result["run_status"], "accepted")
        self.assertEqual(result["decision_status"], "accepted")
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 0)
        self.assertEqual(len(result["normalized_events"]), 1)

    def test_missing_required_field_is_rejected_with_missing_fields(self):
        payload = self._build_minimal_payload()
        del payload["topic_candidates"][0]["event_id"]

        from clawradar.contracts import build_ingest_rejection

        result = build_ingest_rejection(payload)

        self.assertEqual(result["run_status"], "rejected")
        self.assertEqual(result["decision_status"], "rejected")
        self.assertEqual(result["normalized_events"], [])
        self.assertEqual(result["errors"][0]["code"], "missing_required_fields")
        self.assertIn("topic_candidates[0].event_id", result["errors"][0]["missing_fields"])

    def test_normalized_result_stably_traces_request_and_event_ids(self):
        payload = self._build_minimal_payload()

        result = normalize_ingest_payload(payload)
        normalized_event = result["normalized_events"][0]

        self.assertEqual(
            sorted(result.keys()),
            [
                "accepted_count",
                "decision_status",
                "errors",
                "normalized_events",
                "rejected_count",
                "request_id",
                "run_status",
                "trigger_source",
            ],
        )
        self.assertEqual(result["request_id"], payload["request_id"])
        self.assertEqual(normalized_event["request_id"], payload["request_id"])
        self.assertEqual(normalized_event["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_normalize_ingest_payload_preserves_real_source_fields(self):
        payload = self._build_real_source_payload()

        result = normalize_ingest_payload(payload)

        self.assertEqual(result["real_source_context"]["provider"], "mindspider_broad_topic_today_news")
        normalized_event = result["normalized_events"][0]
        self.assertEqual(normalized_event["source_metadata"]["source_id"], "weibo")
        self.assertEqual(normalized_event["source_snapshot"]["id"], "123")


class clawradarRealSourceAdapterTestCase(unittest.TestCase):
    def tearDown(self):
        real_source._load_settings.cache_clear()

    def _build_input_payload(self):
        return {
            "request_id": "req-stage7-real-source",
            "trigger_source": "manual",
            "entry_options": {
                "input": {
                    "mode": "real_source",
                    "source_ids": ["weibo"],
                    "limit": 2,
                }
            },
        }

    def test_load_real_source_payload_maps_mindspider_items_to_ingest_candidates(self):
        payload = self._build_input_payload()
        mock_results = [
            {
                "source": "weibo",
                "status": "success",
                "timestamp": "2026-04-10T08:05:00",
                "data": {
                    "items": [
                        {
                            "id": "123",
                            "title": "AI 公司发布新模型并进入微博热搜",
                            "url": "https://example.com/weibo/123",
                            "rank": 1,
                            "desc": "微博热搜显示 AI 公司发布新模型并引发广泛讨论。",
                        }
                    ]
                },
            }
        ]

        with patch("clawradar.real_source._collect_mindspider_news", return_value=(mock_results, {"weibo": "微博热搜"}, "https://newsnow.busiyi.world", [])):
            result, context = load_real_source_payload(payload)

        self.assertEqual(result["request_id"], "req-stage7-real-source")
        self.assertEqual(result["trigger_source"], "manual")
        self.assertEqual(context["provider"], "mindspider_broad_topic_today_news")
        self.assertEqual(context["requested_source_ids"], ["weibo"])
        self.assertEqual(context["applied_source_ids"], ["weibo"])
        self.assertEqual(context["candidate_count"], 1)
        candidate = result["topic_candidates"][0]
        self.assertEqual(candidate["event_id"], "real-source-weibo-123")
        self.assertEqual(candidate["event_title"], "AI 公司发布新模型并进入微博热搜")
        self.assertEqual(candidate["source_url"], "https://example.com/weibo/123")
        self.assertEqual(candidate["source_metadata"]["source_name"], "微博热搜")
        self.assertEqual(candidate["source_snapshot"]["rank"], 1)
        self.assertEqual(len(candidate["fact_candidates"]), 2)

    def test_load_real_source_payload_raises_when_no_candidate_available(self):
        payload = self._build_input_payload()
        mock_results = [
            {
                "source": "weibo",
                "status": "timeout",
                "error": "请求超时",
                "timestamp": "2026-04-10T08:05:00",
            }
        ]

        with patch("clawradar.real_source._collect_mindspider_news", return_value=(mock_results, {"weibo": "微博热搜"}, "https://newsnow.busiyi.world", [])):
            with self.assertRaises(RealSourceUnavailableError):
                load_real_source_payload(payload)


    def test_load_settings_prefers_repo_local_config_module(self):
        wrong_module = SimpleNamespace(settings=SimpleNamespace())
        expected_settings = SimpleNamespace(TAVILY_API_KEY="configured")
        right_module = SimpleNamespace(settings=expected_settings)

        def fake_import(module_name):
            if module_name == "radar_engines.config":
                return right_module
            if module_name == "config":
                return wrong_module
            raise ModuleNotFoundError(module_name)

        with patch("clawradar.real_source.import_module", side_effect=fake_import):
            real_source._load_settings.cache_clear()
            settings = real_source._load_settings()

        self.assertIs(settings, expected_settings)

    def test_search_topic_news_without_known_api_key_attrs_fails_gracefully(self):
        context = {
            "topic": "OpenAI 企业级智能体平台",
            "company": "OpenAI",
            "track": "企业服务",
            "keywords": ["智能体"],
        }

        with patch("clawradar.real_source._load_settings", return_value=SimpleNamespace()):
            with self.assertRaises(RealSourceUnavailableError) as exc_info:
                real_source._search_topic_news(context, limit=3)

        self.assertIn("no search provider configured", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
