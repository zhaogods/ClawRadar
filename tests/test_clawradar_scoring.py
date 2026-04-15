import json
import unittest
from pathlib import Path

from clawradar.scoring import build_score_rejection, score_topic_candidates


class ClawRadarScoringTestCase(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _load_fixture(self, filename):
        return json.loads((self.fixtures_dir / filename).read_text(encoding="utf-8"))

    def test_score_accepts_ingest_shape_and_returns_structured_publish_ready_result(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")

        result = score_topic_candidates(payload)

        self.assertEqual(result["run_status"], "succeeded")
        self.assertEqual(result["decision_status"], "publish_ready")
        self.assertEqual(result["decision_counts"]["publish_ready"], 1)
        self.assertEqual(len(result["scored_events"]), 1)

        scored_event = result["scored_events"][0]
        self.assertEqual(scored_event["status"], "publish_ready")
        self.assertGreaterEqual(scored_event["scorecard"]["total_score"], 75)
        self.assertGreaterEqual(len(scored_event["timeline"]), 3)
        self.assertGreaterEqual(len(scored_event["fact_points"]), 3)
        self.assertEqual(scored_event["trace"]["source_url"], payload["topic_candidates"][0]["source_url"])

    def test_score_supports_independent_normalized_input_and_routes_need_more_evidence(self):
        payload = self._load_fixture("clawradar_score_need_more_evidence_input.json")

        result = score_topic_candidates(payload)

        self.assertEqual(result["run_status"], "succeeded")
        self.assertEqual(result["decision_status"], "need_more_evidence")
        self.assertEqual(result["decision_counts"]["need_more_evidence"], 1)

        scored_event = result["scored_events"][0]
        self.assertEqual(scored_event["request_id"], payload["request_id"])
        self.assertEqual(scored_event["event_id"], payload["normalized_events"][0]["event_id"])
        self.assertEqual(scored_event["status"], "need_more_evidence")
        self.assertEqual(scored_event["timeline"][0]["source_url"], payload["normalized_events"][0]["source_url"])
        self.assertTrue(any(flag["code"] == "single_source_signal" for flag in scored_event["risk_flags"]))

    def test_score_rejection_preserves_missing_fields_for_invalid_payload(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")
        del payload["topic_candidates"][0]["event_id"]

        result = build_score_rejection(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["decision_status"], "need_more_evidence")
        self.assertEqual(result["scored_events"], [])
        self.assertEqual(result["errors"][0]["code"], "invalid_input")
        self.assertIn("normalized_events[0].event_id", result["errors"][0]["missing_fields"])


if __name__ == "__main__":
    unittest.main()
