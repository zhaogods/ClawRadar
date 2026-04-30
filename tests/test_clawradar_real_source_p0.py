import unittest
from types import SimpleNamespace
from unittest.mock import patch

from clawradar import real_source
from clawradar.real_source import load_real_source_payload


class ClawRadarRealSourceP0TestCase(unittest.TestCase):
    def tearDown(self):
        real_source._load_settings.cache_clear()

    def test_load_real_source_payload_round_robin_merges_multiple_sources(self):
        payload = {
            "request_id": "req-stage7-real-source",
            "trigger_source": "manual",
            "entry_options": {
                "input": {
                    "mode": "real_source",
                    "source_ids": ["weibo", "zhihu"],
                    "limit": 4,
                }
            },
        }
        mock_results = [
            {
                "source": "weibo",
                "status": "success",
                "timestamp": "2026-04-10T08:05:00",
                "data": {
                    "items": [
                        {"id": "w1", "title": "weibo-1", "url": "https://example.com/weibo/1", "rank": 1},
                        {"id": "w2", "title": "weibo-2", "url": "https://example.com/weibo/2", "rank": 2},
                        {"id": "w3", "title": "weibo-3", "url": "https://example.com/weibo/3", "rank": 3},
                    ]
                },
            },
            {
                "source": "zhihu",
                "status": "success",
                "timestamp": "2026-04-10T08:06:00",
                "data": {
                    "items": [
                        {"id": "z1", "title": "zhihu-1", "url": "https://example.com/zhihu/1", "rank": 1},
                        {"id": "z2", "title": "zhihu-2", "url": "https://example.com/zhihu/2", "rank": 2},
                    ]
                },
            },
        ]

        with patch(
            "clawradar.real_source._collect_mindspider_news",
            return_value=(mock_results, {"weibo": "Weibo", "zhihu": "Zhihu"}, "https://newsnow.busiyi.world", []),
        ):
            result, context = load_real_source_payload(payload)

        self.assertEqual(context["applied_source_ids"], ["weibo", "zhihu"])
        self.assertEqual(context["candidate_count"], 4)
        self.assertEqual(
            [item["source_metadata"]["source_id"] for item in result["topic_candidates"]],
            ["weibo", "zhihu", "weibo", "zhihu"],
        )

    def test_search_topic_news_merges_multiple_providers(self):
        context = {
            "topic": "AI agent governance",
            "company": "OpenAI",
            "track": "enterprise ai",
            "keywords": ["audit", "policy"],
        }
        settings = SimpleNamespace(
            TAVILY_API_KEY="t-key",
            BOCHA_WEB_SEARCH_API_KEY="b-key",
            ANSPIRE_API_KEY="a-key",
        )

        tavily_items = [
            {"title": "A", "url": "https://example.com/a", "content": "A", "provider": "tavily_news", "source_type": "tavily:news", "source_name": "Tavily News"},
            {"title": "B", "url": "https://example.com/shared", "content": "B", "provider": "tavily_news", "source_type": "tavily:news", "source_name": "Tavily News"},
        ]
        bocha_items = [
            {"title": "C", "url": "https://example.com/c", "content": "C", "provider": "bocha_search", "source_type": "bocha:web", "source_name": "Bocha Search"},
            {"title": "D", "url": "https://example.com/shared", "content": "D", "provider": "bocha_search", "source_type": "bocha:web", "source_name": "Bocha Search"},
        ]
        anspire_items = [
            {"title": "E", "url": "https://example.com/e", "content": "E", "provider": "anspire_search", "source_type": "anspire:web", "source_name": "Anspire Search"},
        ]

        with patch("clawradar.real_source._load_settings", return_value=settings), \
             patch("clawradar.real_source._search_with_tavily", return_value=tavily_items), \
             patch("clawradar.real_source._search_with_bocha", return_value=bocha_items), \
             patch("clawradar.real_source._search_with_anspire", return_value=anspire_items):
            items, query, failed_sources, applied_source_ids, enrichment_items = real_source._search_topic_news(context, limit=4)

        self.assertIn("latest news", query)
        self.assertEqual(applied_source_ids, ["tavily_news", "bocha_search", "anspire_search"])
        self.assertEqual(
            [item["url"] for item in items],
            [
                "https://example.com/a",
                "https://example.com/c",
                "https://example.com/e",
                "https://example.com/shared",
            ],
        )
        self.assertEqual(failed_sources, [])

    def test_load_topic_driven_payload_records_multiple_applied_source_ids(self):
        payload = {
            "request_id": "req-stage7-user-topic",
            "trigger_source": "manual",
            "entry_options": {"input": {"mode": "user_topic", "topic": "AI governance", "limit": 3}},
        }

        with patch(
            "clawradar.real_source._search_topic_news",
            return_value=(
                [
                    {"title": "A", "url": "https://example.com/a", "content": "A", "provider": "tavily_news", "source_type": "tavily:news", "source_name": "Tavily News"},
                    {"title": "B", "url": "https://example.com/b", "content": "B", "provider": "bocha_search", "source_type": "bocha:web", "source_name": "Bocha Search"},
                ],
                "AI governance latest news",
                [],
                ["tavily_news", "bocha_search"],
                [],
            ),
        ):
            result, context = load_real_source_payload(payload)

        self.assertEqual(context["applied_source_ids"], ["tavily_news", "bocha_search"])
        self.assertEqual(context["provider"], "tavily_news")
        self.assertEqual(result["user_topic_context"]["applied_source_ids"], ["tavily_news", "bocha_search"])


if __name__ == "__main__":
    unittest.main()