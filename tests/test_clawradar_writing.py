import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clawradar.writing import (
    MAX_WECHAT_DIGEST_TEXT_UNITS,
    MAX_WECHAT_DIGEST_UTF8_BYTES,
    WriteExecutor,
    WriteOperation,
    build_write_rejection,
    topic_radar_write,
)


class ClawRadarWritingTestCase(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _load_fixture(self, filename):
        return json.loads((self.fixtures_dir / filename).read_text(encoding="utf-8"))

    def test_publish_ready_input_generates_structured_content_bundle(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")

        result = topic_radar_write(payload)

        self.assertEqual(result["run_status"], "succeeded")
        self.assertEqual(result["decision_status"], "publish_ready")
        self.assertEqual(result["operation"], "generate")
        self.assertEqual(len(result["content_bundles"]), 1)

        bundle = result["content_bundles"][0]
        self.assertEqual(bundle["content_status"], "generated")
        self.assertEqual(bundle["event_id"], payload["scored_events"][0]["event_id"])
        self.assertIn("evidence_packet", bundle)
        self.assertIn("title", bundle)
        self.assertIn("outline", bundle)
        self.assertIn("draft", bundle)
        self.assertIn("summary", bundle)
        self.assertGreaterEqual(len(bundle["evidence_packet"]["source_support"]), 3)
        self.assertTrue(bundle["summary"]["uncertainty_markers"])

    def test_builtin_writer_regenerates_overlong_title_instead_of_truncating_it(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        payload["scored_events"][0]["trace"]["company"] = "中国人工智能产业发展集团股份有限公司"
        payload["scored_events"][0]["event_title"] = "发布多智能体协同治理平台与企业级安全审计控制台重大更新说明，并披露行业落地进展与生态合作路线图以及更多补充说明，用于验证重写而非截断的超长标题版本"

        result = topic_radar_write(payload)

        title_text = result["content_bundles"][0]["title"]["text"]
        preferred_title = f"{payload['scored_events'][0]['trace']['company']}：{payload['scored_events'][0]['event_title']}"
        naive_truncation = preferred_title[:64]
        self.assertEqual(title_text, "多智能体协同治理平台与企业级安全审计控制台重大更新说明")
        self.assertLessEqual(len(title_text), 64)
        self.assertNotEqual(title_text, naive_truncation)
        self.assertNotIn("集团", title_text)
        self.assertFalse(title_text.endswith("路线图"))

    def test_non_publish_ready_input_is_rejected_with_clear_failure_structure(self):
        payload = self._load_fixture("clawradar_write_need_more_evidence_input.json")

        result = topic_radar_write(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["decision_status"], "need_more_evidence")
        self.assertEqual(result["content_bundles"], [])
        self.assertEqual(result["errors"][0]["code"], "decision_not_publish_ready")

    def test_rewrite_and_summary_regeneration_can_be_called_independently(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        generated = topic_radar_write(payload)
        bundle = generated["content_bundles"][0]

        rewrite_payload = dict(payload)
        rewrite_payload["content_bundle"] = bundle
        rewrite_result = topic_radar_write(rewrite_payload, operation=WriteOperation.REWRITE.value)

        self.assertEqual(rewrite_result["run_status"], "succeeded")
        self.assertEqual(rewrite_result["content_bundles"][0]["content_status"], "rewritten")
        self.assertNotEqual(
            rewrite_result["content_bundles"][0]["draft"]["body_markdown"],
            bundle["draft"]["body_markdown"],
        )

        summary_payload = dict(payload)
        summary_payload["content_bundle"] = bundle
        summary_result = topic_radar_write(summary_payload, operation=WriteOperation.REGENERATE_SUMMARY.value)

        self.assertEqual(summary_result["run_status"], "succeeded")
        self.assertEqual(summary_result["content_bundles"][0]["content_status"], "summary_regenerated")
        self.assertNotEqual(
            summary_result["content_bundles"][0]["summary"]["text"],
            bundle["summary"]["text"],
        )

    def test_rewrite_requires_existing_content_bundle(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        payload["operation"] = WriteOperation.REWRITE.value

        result = build_write_rejection(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "content_bundle_required")

    def test_external_writer_propagates_title_constraints_and_regenerates_overlong_title(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>阶段八外部写作成功。</p></body></html>",
            "report_title": "中国人工智能产业发展趋势深度观察报告标题超长版本1234567890ABCDEF以及更多补充说明，用于验证标题重写是否生效",
            "report_id": "report-stage8-001",
            "report_filepath": "/tmp/final_report.html",
            "report_relative_path": "outputs/reports/final_report.html",
            "ir_filepath": "/tmp/report_ir.json",
            "ir_relative_path": "outputs/reports/ir/report_ir.json",
            "state_filepath": "/tmp/report_state.json",
            "state_relative_path": "outputs/reports/report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()), patch(
            "clawradar.writing._assert_external_writer_connectivity"
        ):
            result = topic_radar_write(payload, executor=WriteExecutor.EXTERNAL_WRITER.value)

        self.assertEqual(result["run_status"], "succeeded")
        self.assertEqual(result["executor"], "external_writer")
        self.assertEqual(len(result["content_bundles"]), 1)
        self.assertEqual(len(result["write_requests"]), 1)
        self.assertEqual(len(result["writer_receipts"]), 1)
        bundle = result["content_bundles"][0]
        write_request = result["write_requests"][0]
        self.assertIn("writer_receipt", bundle)
        self.assertIn("report_artifacts", bundle)
        self.assertEqual(bundle["writer_receipt"]["report_id"], "report-stage8-001")
        self.assertEqual(bundle["report_artifacts"]["state_relative_path"], "outputs/reports/report_state.json")
        self.assertEqual(bundle["title"]["text"], "中国人工智能产业发展趋势深度观察报告标题超长版本1234567890ABCDEF以及更多补充说明，用于验证标题重写是否生效")
        self.assertLessEqual(len(bundle["title"]["text"]), 64)
        self.assertTrue(write_request["writing_brief"]["title_constraints"]["rewrite_when_over_limit"])
        self.assertFalse(write_request["writing_brief"]["title_constraints"]["allow_truncate_as_business_fallback"])
        self.assertIn("必须直接重写", write_request["writing_brief"]["title_instruction"])
        self.assertTrue(write_request["report_profile"]["title_constraints"]["require_semantic_completeness"])

    def test_external_writer_preview_ignores_embedded_scripts_in_summary_and_draft(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><script>var x='Chart.js - embedded bundle';</script><p>真正摘要内容。</p></body></html>",
            "report_title": "综合报告",
            "report_id": "report-stage8-002",
            "report_filepath": "/tmp/final_report.html",
            "report_relative_path": "outputs/reports/final_report.html",
            "ir_filepath": "/tmp/report_ir.json",
            "ir_relative_path": "outputs/reports/ir/report_ir.json",
            "state_filepath": "/tmp/report_state.json",
            "state_relative_path": "outputs/reports/report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()), patch(
            "clawradar.writing._assert_external_writer_connectivity"
        ):
            result = topic_radar_write(payload, executor=WriteExecutor.EXTERNAL_WRITER.value)

        bundle = result["content_bundles"][0]
        self.assertIn("综合报告", bundle["draft"]["body_markdown"])
        self.assertIn("真正摘要内容。", bundle["draft"]["body_markdown"])
        self.assertIn("真正摘要内容。", bundle["summary"]["text"])
        self.assertNotIn("Chart.js", bundle["draft"]["body_markdown"])
        self.assertNotIn("embedded bundle", bundle["draft"]["body_markdown"])
        self.assertNotIn("Chart.js", bundle["summary"]["text"])

    def test_external_writer_prefers_structured_summary_pack_and_exposes_wechat_variant(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>这是一段预览兜底文本。</p></body></html>",
            "report_title": "综合报告",
            "report_id": "report-stage8-003",
            "report_filepath": "/tmp/final_report.html",
            "report_relative_path": "outputs/reports/final_report.html",
            "ir_filepath": "/tmp/report_ir.json",
            "ir_relative_path": "outputs/reports/ir/report_ir.json",
            "state_filepath": "/tmp/report_state.json",
            "state_relative_path": "outputs/reports/report_state.json",
            "report_metadata": {
                "summaryPack": {
                    "generic": "通用结构化摘要。",
                    "short": "短摘要。",
                    "wechat": "微信渠道摘要。",
                    "sourceHint": "hero.summary",
                }
            },
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()), patch(
            "clawradar.writing._assert_external_writer_connectivity"
        ):
            result = topic_radar_write(payload, executor=WriteExecutor.EXTERNAL_WRITER.value)

        bundle = result["content_bundles"][0]
        self.assertEqual(bundle["summary"]["text"], "通用结构化摘要。")
        self.assertEqual(bundle["summary"]["channel_variants"]["wechat"], "微信渠道摘要。")
        self.assertEqual(bundle["summary"]["source_hint"], "hero.summary")

    def test_builtin_writer_regenerate_summary_produces_wechat_variant_within_limit_and_without_feedback_text(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        generated = topic_radar_write(payload)
        bundle = generated["content_bundles"][0]
        bundle["summary_rewrite_feedback"] = {
            "reason": "description size out of limit",
            "requiredAction": "请直接重写一个更短且语义完整的微信公众号摘要，不要截断上一版摘要。",
            "maxUtf8Bytes": MAX_WECHAT_DIGEST_UTF8_BYTES,
            "maxTextUnits": MAX_WECHAT_DIGEST_TEXT_UNITS,
        }

        summary_payload = dict(payload)
        summary_payload["content_bundle"] = bundle
        summary_result = topic_radar_write(summary_payload, operation=WriteOperation.REGENERATE_SUMMARY.value)

        summary = summary_result["content_bundles"][0]["summary"]
        wechat_summary = summary["channel_variants"]["wechat"]
        self.assertIn("channel_variants", summary)
        self.assertIn("wechat", summary["channel_variants"])
        self.assertLessEqual(len(wechat_summary.encode("utf-8")), MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(len(wechat_summary), MAX_WECHAT_DIGEST_TEXT_UNITS)
        self.assertNotEqual(wechat_summary, summary["text"])
        self.assertNotIn("请直接重写一个更短且语义完整的微信公众号摘要", wechat_summary)
        self.assertNotIn("description size out of limit", wechat_summary)

    def test_external_writer_regenerate_summary_propagates_summary_constraints_and_feedback(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")
        payload["content_bundle"] = {
            "event_id": payload["scored_events"][0]["event_id"],
            "content_status": "generated",
            "evidence_packet": {
                "source_support": [
                    {
                        "fact_id": "fact-1",
                        "claim": "平台包含多智能体任务编排能力",
                        "source_url": "https://example.com/fact",
                    }
                ],
                "uncertainty_markers": ["待补充交叉验证"],
            },
            "summary": {
                "text": "这是旧摘要。",
                "channel_variants": {"wechat": "这是旧微信摘要。"},
            },
        }
        payload["summary_rewrite_feedback"] = {
            "reason": "description size out of limit",
            "requiredAction": "请重写更短摘要。",
            "maxUtf8Bytes": MAX_WECHAT_DIGEST_UTF8_BYTES,
            "maxTextUnits": MAX_WECHAT_DIGEST_TEXT_UNITS,
        }
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>这是一段预览兜底文本。</p></body></html>",
            "report_title": "综合报告",
            "report_id": "report-stage8-004",
            "report_filepath": "/tmp/final_report.html",
            "report_relative_path": "outputs/reports/final_report.html",
            "ir_filepath": "/tmp/report_ir.json",
            "ir_relative_path": "outputs/reports/ir/report_ir.json",
            "state_filepath": "/tmp/report_state.json",
            "state_relative_path": "outputs/reports/report_state.json",
            "report_metadata": {
                "summaryPack": {
                    "generic": "通用结构化摘要。",
                    "short": "短摘要。",
                    "wechat": "这是一个需要再次缩短的微信公众号摘要版本，用于验证重写约束是否生效。",
                    "sourceHint": "hero.summary",
                }
            },
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                FakeAgent.last_kwargs = kwargs
                return fake_result

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()), patch(
            "clawradar.writing._assert_external_writer_connectivity"
        ):
            result = topic_radar_write(
                payload,
                operation=WriteOperation.REGENERATE_SUMMARY.value,
                executor=WriteExecutor.EXTERNAL_WRITER.value,
            )

        write_request = result["write_requests"][0]
        summary = result["content_bundles"][0]["summary"]
        self.assertTrue(write_request["writing_brief"]["summary_constraints"]["rewrite_when_over_limit"])
        self.assertFalse(write_request["writing_brief"]["summary_constraints"]["allow_truncate_as_business_fallback"])
        self.assertEqual(write_request["writing_brief"]["summary_constraints"]["max_text_units"], MAX_WECHAT_DIGEST_TEXT_UNITS)
        self.assertIn("summary_rewrite_feedback", write_request["writing_brief"])
        self.assertEqual(write_request["writing_brief"]["existing_summary"]["wechat"], "这是旧微信摘要。")
        self.assertLessEqual(len(summary["channel_variants"]["wechat"]), MAX_WECHAT_DIGEST_TEXT_UNITS)

    def test_external_writer_fails_fast_when_connectivity_preflight_fails(self):
        payload = self._load_fixture("clawradar_write_publish_ready_input.json")

        class FakeAgent:
            llm_client = SimpleNamespace(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

            def generate_report(self, **kwargs):
                raise AssertionError("generate_report should not run after fail-fast preflight")

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()), patch.dict(
            "os.environ",
            {"HTTPS_PROXY": "http://127.0.0.1:9"},
            clear=False,
        ), patch(
            "clawradar.writing.socket.create_connection",
            side_effect=ConnectionRefusedError("[WinError 10061] target actively refused connection"),
        ):
            result = topic_radar_write(payload, executor=WriteExecutor.EXTERNAL_WRITER.value)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["executor"], "external_writer")
        self.assertEqual(result["errors"][0]["code"], "writer_unavailable")
        self.assertIn("connectivity preflight failed", result["errors"][0]["message"])
        self.assertEqual(result["writer_receipts"][0]["failure_info"]["code"], "writer_unavailable")


if __name__ == "__main__":
    unittest.main()
