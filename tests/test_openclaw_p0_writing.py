import json
import unittest
from pathlib import Path
from unittest.mock import patch

from clawradar.writing import WriteExecutor, WriteOperation, build_write_rejection, topic_radar_write


class ClawRadarWritingTestCase(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _load_fixture(self, filename):
        return json.loads((self.fixtures_dir / filename).read_text(encoding="utf-8"))

    def test_publish_ready_input_generates_structured_content_bundle(self):
        payload = self._load_fixture("openclaw_p0_write_publish_ready_input.json")

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

    def test_non_publish_ready_input_is_rejected_with_clear_failure_structure(self):
        payload = self._load_fixture("openclaw_p0_write_need_more_evidence_input.json")

        result = topic_radar_write(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["decision_status"], "need_more_evidence")
        self.assertEqual(result["content_bundles"], [])
        self.assertEqual(result["errors"][0]["code"], "decision_not_publish_ready")

    def test_rewrite_and_summary_regeneration_can_be_called_independently(self):
        payload = self._load_fixture("openclaw_p0_write_publish_ready_input.json")
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
        payload = self._load_fixture("openclaw_p0_write_publish_ready_input.json")
        payload["operation"] = WriteOperation.REWRITE.value

        result = build_write_rejection(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "content_bundle_required")

    def test_external_writer_success_returns_writer_receipt_and_artifacts(self):
        payload = self._load_fixture("openclaw_p0_write_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>阶段八外部写作成功。</p></body></html>",
            "report_id": "report-stage8-001",
            "report_filepath": "/tmp/final_report.html",
            "report_relative_path": "outputs/final_reports/final_report.html",
            "ir_filepath": "/tmp/report_ir.json",
            "ir_relative_path": "outputs/final_reports/ir/report_ir.json",
            "state_filepath": "/tmp/report_state.json",
            "state_relative_path": "outputs/final_reports/report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            result = topic_radar_write(payload, executor=WriteExecutor.EXTERNAL_WRITER.value)

        self.assertEqual(result["run_status"], "succeeded")
        self.assertEqual(result["executor"], "external_writer")
        self.assertEqual(len(result["content_bundles"]), 1)
        self.assertEqual(len(result["write_requests"]), 1)
        self.assertEqual(len(result["writer_receipts"]), 1)
        bundle = result["content_bundles"][0]
        self.assertIn("writer_receipt", bundle)
        self.assertIn("report_artifacts", bundle)
        self.assertEqual(bundle["writer_receipt"]["report_id"], "report-stage8-001")
        self.assertEqual(bundle["report_artifacts"]["state_relative_path"], "outputs/final_reports/report_state.json")


if __name__ == "__main__":
    unittest.main()
