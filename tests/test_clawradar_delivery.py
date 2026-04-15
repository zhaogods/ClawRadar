import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from clawradar.delivery import (
    build_delivery_rejection,
    build_feishu_delivery_message,
    topic_radar_deliver,
)


class ClawRadarDeliveryTestCase(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _load_fixture(self, filename):
        return json.loads((self.fixtures_dir / filename).read_text(encoding="utf-8"))

    def _assert_protocol_fields(self, result):
        self.assertEqual(
            set(result.keys()),
            {
                "request_id",
                "trigger_source",
                "event_id",
                "run_status",
                "decision_status",
                "normalized_events",
                "timeline",
                "evidence_pack",
                "scorecard",
                "content_bundle",
                "delivery_receipt",
                "errors",
            },
        )
        self.assertNotIn("content_bundles", result)
        self.assertNotIn("evidence_packet", result)

    def test_deliver_publish_ready_payload_returns_protocol_fields_and_full_archive_snapshot(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = topic_radar_deliver(
                payload,
                delivery_time="2026-04-09T12:00:00Z",
                runs_root=Path(tmpdir),
            )

            self._assert_protocol_fields(result)
            self.assertEqual(result["run_status"], "completed")
            self.assertEqual(result["decision_status"], "publish_ready")
            self.assertEqual(result["request_id"], payload["request_id"])
            self.assertEqual(result["event_id"], payload["content_bundle"]["event_id"])
            self.assertEqual(result["normalized_events"], payload["normalized_events"])
            self.assertEqual(result["timeline"], payload["timeline"])
            self.assertEqual(result["evidence_pack"], payload["evidence_pack"])
            self.assertEqual(result["scorecard"], payload["scorecard"])
            self.assertEqual(result["content_bundle"], payload["content_bundle"])
            self.assertEqual(result["errors"], [])

            receipt = result["delivery_receipt"]
            self.assertEqual(receipt["delivery_channel"], "feishu")
            self.assertEqual(receipt["delivery_target"], payload["delivery_target"])
            self.assertEqual(receipt["failed_count"], 0)
            self.assertEqual(len(receipt["events"]), 1)

            event_receipt = receipt["events"][0]
            self.assertEqual(event_receipt["request_id"], payload["request_id"])
            self.assertEqual(event_receipt["event_id"], payload["content_bundle"]["event_id"])
            self.assertEqual(event_receipt["decision_status"], "publish_ready")
            self.assertEqual(event_receipt["status"], "delivered")
            self.assertIsNone(event_receipt["failure_info"])

            archive_dir = Path(tmpdir) / "req-stage4-001" / "evt-stage4-001" / "deliver" / "2026-04-09T12-00-00Z"
            payload_path = archive_dir / "payload_snapshot.json"
            message_path = archive_dir / "feishu_message.json"
            self.assertTrue(payload_path.exists())
            self.assertTrue(message_path.exists())

            archived_payload = json.loads(payload_path.read_text(encoding="utf-8"))
            archived_message = json.loads(message_path.read_text(encoding="utf-8"))
            self.assertEqual(archived_payload["request_id"], payload["request_id"])
            self.assertEqual(archived_payload["event_id"], payload["content_bundle"]["event_id"])
            self.assertEqual(archived_payload["decision_status"], payload["decision_status"])
            self.assertEqual(archived_payload["normalized_events"], payload["normalized_events"])
            self.assertEqual(archived_payload["timeline"], payload["timeline"])
            self.assertEqual(archived_payload["evidence_pack"], payload["evidence_pack"])
            self.assertEqual(archived_payload["scorecard"], payload["scorecard"])
            self.assertEqual(archived_payload["content_bundle"], payload["content_bundle"])
            self.assertEqual(archived_payload["delivery_request"]["delivery_channel"], "feishu")
            self.assertEqual(archived_payload["delivery_request"]["delivery_target"], payload["delivery_target"])
            self.assertEqual(archived_payload["delivery_request"]["delivery_time"], "2026-04-09T12:00:00Z")
            self.assertNotIn("content_bundles", archived_payload)
            self.assertNotIn("evidence_packet", archived_payload["content_bundle"])

            self.assertEqual(archived_message["channel"], "feishu")
            self.assertEqual(archived_message["template_id"], "clawradar_feishu_summary_v1")
            self.assertEqual(archived_message["metadata"]["request_id"], payload["request_id"])
            self.assertEqual(archived_message["metadata"]["event_id"], payload["content_bundle"]["event_id"])
            self.assertIn("不确定性提示", archived_message["body_markdown"])

    def test_deliver_rejects_non_publish_ready_payload_without_crossing_stage_boundary(self):
        payload = self._load_fixture("clawradar_deliver_need_more_evidence_input.json")

        result = topic_radar_deliver(payload, delivery_time="2026-04-09T12:05:00Z")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["decision_status"], "need_more_evidence")
        self.assertEqual(result["normalized_events"], payload["normalized_events"])
        self.assertEqual(result["timeline"], payload["timeline"])
        self.assertEqual(result["evidence_pack"], payload["evidence_pack"])
        self.assertEqual(result["scorecard"], payload["scorecard"])
        self.assertEqual(result["content_bundle"], payload["content_bundle"])
        self.assertEqual(result["errors"][0]["code"], "decision_not_publish_ready")
        self.assertEqual(result["delivery_receipt"]["events"][0]["failure_info"]["code"], "decision_not_publish_ready")
        self.assertEqual(result["delivery_receipt"]["events"][0]["decision_status"], "need_more_evidence")
        self.assertIsNone(result["delivery_receipt"]["events"][0]["archive_path"])

    def test_deliver_failure_still_preserves_local_archive_and_upstream_scorecard(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["simulate_delivery_failure"] = True
        expected_scorecard = deepcopy(payload["scorecard"])
        expected_evidence_pack = deepcopy(payload["evidence_pack"])
        expected_content_bundle = deepcopy(payload["content_bundle"])

        with tempfile.TemporaryDirectory() as tmpdir:
            result = topic_radar_deliver(
                payload,
                delivery_time="2026-04-09T12:10:00Z",
                runs_root=Path(tmpdir),
            )

            self._assert_protocol_fields(result)
            self.assertEqual(result["run_status"], "delivery_failed")
            self.assertEqual(result["decision_status"], "publish_ready")
            self.assertEqual(result["scorecard"], expected_scorecard)
            self.assertEqual(result["evidence_pack"], expected_evidence_pack)
            self.assertEqual(result["content_bundle"], expected_content_bundle)
            self.assertEqual(result["delivery_receipt"]["failed_count"], 1)
            self.assertEqual(result["errors"][0]["code"], "delivery_channel_unavailable")

            event_receipt = result["delivery_receipt"]["events"][0]
            self.assertEqual(event_receipt["status"], "failed")
            self.assertEqual(event_receipt["failure_info"]["code"], "delivery_channel_unavailable")
            self.assertIsNotNone(event_receipt["archive_path"])
            self.assertIsNotNone(event_receipt["payload_path"])

            payload_path = Path(tmpdir) / "req-stage4-001" / "evt-stage4-001" / "deliver" / "2026-04-09T12-10-00Z" / "payload_snapshot.json"
            archived_payload = json.loads(payload_path.read_text(encoding="utf-8"))
            self.assertEqual(archived_payload["decision_status"], "publish_ready")
            self.assertEqual(archived_payload["scorecard"], expected_scorecard)
            self.assertEqual(archived_payload["evidence_pack"], expected_evidence_pack)
            self.assertEqual(archived_payload["content_bundle"], expected_content_bundle)

    def test_deliver_rerun_keeps_upstream_structured_artifacts_unchanged(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        expected_structured_artifacts = {
            "normalized_events": deepcopy(payload["normalized_events"]),
            "timeline": deepcopy(payload["timeline"]),
            "evidence_pack": deepcopy(payload["evidence_pack"]),
            "scorecard": deepcopy(payload["scorecard"]),
            "content_bundle": deepcopy(payload["content_bundle"]),
            "decision_status": payload["decision_status"],
            "request_id": payload["request_id"],
            "event_id": payload["content_bundle"]["event_id"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            first_result = topic_radar_deliver(
                payload,
                delivery_time="2026-04-09T12:15:00Z",
                runs_root=Path(tmpdir),
            )
            second_result = topic_radar_deliver(
                payload,
                delivery_time="2026-04-09T12:16:00Z",
                runs_root=Path(tmpdir),
            )

            first_payload_path = Path(tmpdir) / "req-stage4-001" / "evt-stage4-001" / "deliver" / "2026-04-09T12-15-00Z" / "payload_snapshot.json"
            second_payload_path = Path(tmpdir) / "req-stage4-001" / "evt-stage4-001" / "deliver" / "2026-04-09T12-16-00Z" / "payload_snapshot.json"
            first_snapshot = json.loads(first_payload_path.read_text(encoding="utf-8"))
            second_snapshot = json.loads(second_payload_path.read_text(encoding="utf-8"))

        for result in (first_result, second_result):
            self._assert_protocol_fields(result)
            self.assertEqual(result["run_status"], "completed")
            self.assertEqual(result["decision_status"], expected_structured_artifacts["decision_status"])
            self.assertEqual(result["request_id"], expected_structured_artifacts["request_id"])
            self.assertEqual(result["event_id"], expected_structured_artifacts["event_id"])
            self.assertEqual(result["normalized_events"], expected_structured_artifacts["normalized_events"])
            self.assertEqual(result["timeline"], expected_structured_artifacts["timeline"])
            self.assertEqual(result["evidence_pack"], expected_structured_artifacts["evidence_pack"])
            self.assertEqual(result["scorecard"], expected_structured_artifacts["scorecard"])
            self.assertEqual(result["content_bundle"], expected_structured_artifacts["content_bundle"])

        for field in expected_structured_artifacts:
            self.assertEqual(first_snapshot[field], expected_structured_artifacts[field])
            self.assertEqual(second_snapshot[field], expected_structured_artifacts[field])

        self.assertEqual(payload["decision_status"], "publish_ready")
        self.assertEqual(payload["scorecard"], expected_structured_artifacts["scorecard"])
        self.assertEqual(payload["content_bundle"], expected_structured_artifacts["content_bundle"])

    def test_feishu_message_template_and_rejection_structure_are_protocol_stable(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        message = build_feishu_delivery_message(
            payload,
            payload["content_bundle"],
            delivery_target=payload["delivery_target"],
        )

        self.assertEqual(message["channel"], "feishu")
        self.assertEqual(message["template_id"], "clawradar_feishu_summary_v1")
        self.assertIn(payload["request_id"], message["body_markdown"])
        self.assertIn(payload["content_bundle"]["event_id"], message["body_markdown"])

        invalid_payload = deepcopy(payload)
        del invalid_payload["delivery_target"]
        rejection = build_delivery_rejection(invalid_payload)

        self._assert_protocol_fields(rejection)
        self.assertEqual(rejection["run_status"], "delivery_failed")
        self.assertEqual(rejection["request_id"], payload["request_id"])
        self.assertEqual(rejection["event_id"], payload["content_bundle"]["event_id"])
        self.assertEqual(rejection["decision_status"], "publish_ready")
        self.assertEqual(rejection["content_bundle"], payload["content_bundle"])
        self.assertEqual(rejection["errors"][0]["code"], "delivery_target_required")
        self.assertEqual(rejection["delivery_receipt"]["events"][0]["failure_info"]["code"], "delivery_target_required")


if __name__ == "__main__":
    unittest.main()
