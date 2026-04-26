import unittest
from pathlib import Path
from types import SimpleNamespace

from radar_engines.ReportEngine.agent import ReportAgent
from radar_engines.ReportEngine.core.template_parser import TemplateSection
from radar_engines.ReportEngine.ir.validator import IRValidator
from radar_engines.ReportEngine.nodes.chapter_generation_node import ChapterGenerationNode
from radar_engines.ReportEngine.nodes.document_layout_node import DocumentLayoutNode


class _DummyStorage:
    pass


class ReportEngineChapterStructureTestCase(unittest.TestCase):
    def setUp(self):
        self.node = ChapterGenerationNode(
            llm_client=None,
            validator=IRValidator(),
            storage=_DummyStorage(),
            error_log_dir=Path(__file__).parent / "fixtures" / "tmp_error_logs",
        )
        self.validator = IRValidator()

    def test_sanitize_lifts_misplaced_heading_out_of_list_item(self):
        chapter = {
            "chapterId": "chapter-1",
            "title": "测试章节",
            "anchor": "chapter-1",
            "order": 1,
            "blocks": [
                {
                    "type": "list",
                    "listType": "bullet",
                    "items": [
                        [
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "技术依赖风险", "marks": []}],
                            },
                            {
                                "type": "heading",
                                "level": 3,
                                "text": "6.1.2 应用风险",
                                "anchor": "section-6-1-2",
                            },
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "应用风险体现在业务落地。", "marks": []}],
                            },
                            {
                                "type": "list",
                                "listType": "bullet",
                                "items": [
                                    [
                                        {
                                            "type": "paragraph",
                                            "inlines": [{"text": "过度依赖", "marks": []}],
                                        }
                                    ]
                                ],
                            },
                        ]
                    ],
                }
            ],
        }

        self.node._sanitize_chapter_blocks(chapter)

        self.assertEqual(len(chapter["blocks"]), 4)
        self.assertEqual(chapter["blocks"][0]["type"], "list")
        self.assertEqual(len(chapter["blocks"][0]["items"]), 1)
        self.assertEqual(len(chapter["blocks"][0]["items"][0]), 1)
        self.assertEqual(chapter["blocks"][0]["items"][0][0]["type"], "paragraph")
        self.assertEqual(chapter["blocks"][1]["type"], "heading")
        self.assertEqual(chapter["blocks"][1]["text"], "6.1.2 应用风险")
        self.assertEqual(chapter["blocks"][2]["type"], "paragraph")
        self.assertEqual(chapter["blocks"][3]["type"], "list")

    def test_sanitize_lifts_following_list_after_heading(self):
        chapter = {
            "chapterId": "chapter-1",
            "title": "测试章节",
            "anchor": "chapter-1",
            "order": 1,
            "blocks": [
                {
                    "type": "list",
                    "listType": "bullet",
                    "items": [
                        [
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "技术依赖风险", "marks": []}],
                            },
                            {
                                "type": "heading",
                                "level": 3,
                                "text": "6.2.3 开发者生态繁荣与技术创新",
                                "anchor": "section-6-2-3",
                            },
                        ],
                        [
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "这一项原本也被错误留在旧列表里", "marks": []}],
                            }
                        ],
                    ],
                }
            ],
        }

        self.node._sanitize_chapter_blocks(chapter)

        self.assertEqual(len(chapter["blocks"]), 3)
        self.assertEqual(chapter["blocks"][0]["type"], "list")
        self.assertEqual(len(chapter["blocks"][0]["items"]), 1)
        self.assertEqual(chapter["blocks"][1]["type"], "heading")
        self.assertEqual(chapter["blocks"][2]["type"], "paragraph")
        self.assertEqual(
            chapter["blocks"][2]["inlines"][0]["text"],
            "这一项原本也被错误留在旧列表里",
        )

    def test_validator_rejects_heading_inside_list_item(self):
        chapter = {
            "chapterId": "chapter-1",
            "title": "测试章节",
            "anchor": "chapter-1",
            "order": 1,
            "blocks": [
                {
                    "type": "list",
                    "listType": "bullet",
                    "items": [
                        [
                            {
                                "type": "heading",
                                "level": 3,
                                "text": "6.1.2 应用风险",
                                "anchor": "section-6-1-2",
                            }
                        ]
                    ],
                }
            ],
        }

        ok, errors = self.validator.validate_chapter(chapter)

        self.assertFalse(ok)
        self.assertTrue(any("不能为 heading" in error for error in errors))

    def test_normal_valid_list_items_remain_unchanged(self):
        chapter = {
            "chapterId": "chapter-1",
            "title": "测试章节",
            "anchor": "chapter-1",
            "order": 1,
            "blocks": [
                {
                    "type": "list",
                    "listType": "bullet",
                    "items": [
                        [
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "第一项", "marks": []}],
                            }
                        ],
                        [
                            {
                                "type": "paragraph",
                                "inlines": [{"text": "第二项", "marks": []}],
                            }
                        ],
                    ],
                }
            ],
        }

        original = {
            "type": "list",
            "listType": "bullet",
            "items": [
                [
                    {
                        "type": "paragraph",
                        "inlines": [{"text": "第一项", "marks": []}],
                    }
                ],
                [
                    {
                        "type": "paragraph",
                        "inlines": [{"text": "第二项", "marks": []}],
                    }
                ],
            ],
        }

        self.node._sanitize_chapter_blocks(chapter)

        self.assertEqual(chapter["blocks"][0], original)
class ReportEngineDocumentLayoutTestCase(unittest.TestCase):
    def setUp(self):
        self.node = DocumentLayoutNode(llm_client=None)

    def test_parse_response_normalizes_summary_pack_fields(self):
        result = self.node._parse_response(
            """
            {
              "title": "测试报告",
              "tocPlan": [{"chapterId": "S1", "display": "一、概览", "description": "概览章节"}],
              "hero": {"summary": "Hero摘要。"},
              "summaryPack": {
                "generic": "  通用摘要。  ",
                "short": "",
                "wechat": " 微信摘要。 ",
                "sourceHint": " subtitle "
              }
            }
            """
        )

        self.assertEqual(result["summaryPack"]["generic"], "通用摘要。")
        self.assertEqual(result["summaryPack"]["short"], "通用摘要。")
        self.assertEqual(result["summaryPack"]["wechat"], "微信摘要。")
        self.assertEqual(result["summaryPack"]["sourceHint"], "subtitle")

    def test_parse_response_falls_back_to_hero_summary_when_summary_pack_missing_or_invalid(self):
        result = self.node._parse_response(
            """
            {
              "title": "测试报告",
              "tocPlan": [{"chapterId": "S1", "display": "一、概览", "description": "概览章节"}],
              "hero": {"summary": "Hero摘要。"},
              "summaryPack": {
                "generic": {"bad": true},
                "short": [],
                "wechat": "",
                "sourceHint": ""
              }
            }
            """
        )


class ReportEngineAgentMetadataTestCase(unittest.TestCase):
    def test_generate_report_returns_summary_pack_in_report_metadata(self):
        agent = object.__new__(ReportAgent)
        agent._CONTENT_SPARSE_MIN_ATTEMPTS = 3
        agent._STRUCTURAL_RETRY_ATTEMPTS = 2
        agent.config = SimpleNamespace(CHAPTER_JSON_MAX_ATTEMPTS=1)
        agent.state = SimpleNamespace(
            metadata=SimpleNamespace(query="", template_used="", generation_time=0),
            mark_processing=lambda: None,
            mark_completed=lambda: None,
            mark_failed=lambda message: None,
            html_content="",
            task_id="",
            query="",
        )
        agent.chapter_storage = SimpleNamespace(
            start_session=lambda report_id, manifest_meta: Path("F:/02_code/ClawRadar/.tmp/report-agent-test")
        )
        agent.document_composer = SimpleNamespace(
            build_document=lambda report_id, manifest_meta, chapters: {"meta": manifest_meta, "chapters": chapters}
        )
        agent.renderer = SimpleNamespace(render=lambda document_ir: "<html><body>report</body></html>")
        agent._save_report = lambda html_report, document_ir, report_id: {}
        agent._persist_planning_artifacts = lambda run_dir, layout_design, word_plan, template_overview: None
        agent._should_retry_inappropriate_content_error = lambda error: False
        agent._normalize_reports = lambda reports: {"query_engine": "Q", "media_engine": "M", "insight_engine": "I"}
        agent._slice_template = lambda template_markdown: [
            TemplateSection(title="概览", slug="overview", order=10, depth=1, raw_title="# 概览", chapter_id="S1")
        ]
        agent._build_template_overview = lambda template_text, sections: {
            "title": "模板标题",
            "chapters": [section.to_dict() for section in sections],
        }
        agent._build_generation_context = lambda query, normalized_reports, forum_logs, template_result, layout_design, chapter_targets, word_plan, template_overview: {
            "theme_tokens": {"accent": "#123456"}
        }
        agent._run_stage_with_retry = lambda stage_name, fn, expected_keys=None, postprocess=None: fn()
        agent._select_template = lambda query, reports, forum_logs, custom_template: {
            "template_name": "custom",
            "template_content": "# 概览",
            "selection_reason": "unit-test",
        }
        agent.document_layout_node = SimpleNamespace(
            run=lambda sections, template_markdown, reports, forum_logs, query, template_overview: {
                "title": "测试报告",
                "subtitle": "副标题",
                "tagline": "标签线",
                "tocTitle": "目录",
                "tocPlan": [{"chapterId": "S1", "display": "一、概览", "description": "概览章节"}],
                "hero": {"summary": "Hero摘要。"},
                "summaryPack": {
                    "generic": "通用摘要。",
                    "short": "短摘要。",
                    "wechat": "微信摘要。",
                    "sourceHint": "hero.summary",
                },
                "themeTokens": {"accent": "#abcdef"},
                "layoutNotes": ["note"],
            }
        )
        agent.word_budget_node = SimpleNamespace(
            run=lambda sections, layout_design, normalized_reports, forum_logs, query, template_overview: {
                "totalWords": 1000,
                "globalGuidelines": ["guide"],
                "chapters": [{"chapterId": "S1", "targetWords": 1000}],
            }
        )
        agent.chapter_generation_node = SimpleNamespace(
            run=lambda section, generation_context, run_dir, stream_callback=None: {
                "chapterId": section.chapter_id,
                "title": section.title,
                "anchor": section.slug,
                "order": section.order,
                "blocks": [],
            }
        )

        result = agent.generate_report(
            query="测试主题",
            reports=["Q", "M", "I"],
            forum_logs="",
            custom_template="",
            save_report=False,
        )

        self.assertEqual(result["report_title"], "测试报告")
        self.assertEqual(result["report_metadata"]["summaryPack"]["generic"], "通用摘要。")
        self.assertEqual(result["report_metadata"]["summaryPack"]["wechat"], "微信摘要。")
        self.assertEqual(result["report_metadata"]["hero"]["summary"], "Hero摘要。")
        self.assertEqual(result["report_metadata"]["toc"]["customEntries"][0]["chapterId"], "S1")
        self.assertEqual(result["report_metadata"]["themeTokens"]["accent"], "#abcdef")


if __name__ == "__main__":
    unittest.main()
