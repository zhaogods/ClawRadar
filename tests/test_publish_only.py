import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from clawradar.publish_only import publish_existing_output


class PublishOnlyTestCase(unittest.TestCase):
    def _workspace_tmpdir(self, name):
        workspace_tmp_root = Path(__file__).resolve().parents[1] / ".tmp" / "test_runs"
        workspace_tmp_root.mkdir(parents=True, exist_ok=True)
        run_root = workspace_tmp_root / f"{name}{self.id().replace('.', '-') }"
        if run_root.exists():
            shutil.rmtree(run_root)
        run_root.mkdir(parents=True, exist_ok=True)
        return run_root

    def _write_content_bundles(self, run_root: Path, *, event_id: str = "evt-publish-001") -> Path:
        content_bundles_path = run_root / "stages" / "write" / "content_bundles.json"
        content_bundles_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "event_id": event_id,
                "title": {"text": "Publish Draft"},
                "summary": {"text": "Summary for publish-only"},
                "draft": {"body_markdown": "Draft body"},
                "evidence_pack": {},
            }
        ]
        content_bundles_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return content_bundles_path

    def _write_payload_snapshot(self, run_root: Path, *, event_id: str = "evt-publish-001") -> Path:
        payload_snapshot_path = run_root / "evt-archive" / "deliver" / "2026-04-20T12-00-00Z" / "payload_snapshot.json"
        payload_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "request_id": "req-snapshot",
            "trigger_source": "manual",
            "decision_status": "publish_ready",
            "event_id": event_id,
            "normalized_events": [],
            "timeline": [],
            "evidence_pack": {},
            "scorecard": {"decision_status": "publish_ready"},
            "content_bundle": {
                "event_id": event_id,
                "title": {"text": "Snapshot Draft"},
                "summary": {"text": "Summary from payload snapshot"},
                "draft": {"body_markdown": "Snapshot body"},
                "evidence_pack": {},
            },
        }
        payload_snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload_snapshot_path

    def _write_modern_output_run(self, runs_root: Path) -> Path:
        mode_root = runs_root / "user_topic"
        run_root = mode_root / "20260420_0332"
        debug_root = run_root / "debug"
        reports_root = run_root / "reports"
        debug_root.mkdir(parents=True, exist_ok=True)
        reports_root.mkdir(parents=True, exist_ok=True)

        old_report = reports_root / "final_report_old.html"
        new_report = reports_root / "final_report_new.html"
        old_report.write_text("old report", encoding="utf-8")
        new_report.write_text("new report", encoding="utf-8")
        os.utime(old_report, (1_700_000_000, 1_700_000_000))
        os.utime(new_report, (1_800_000_000, 1_800_000_000))

        content_bundles = [
            {
                "event_id": "evt-modern-old",
                "title": {"text": "Older Modern Report"},
                "summary": {"text": "Older summary"},
                "draft": {"body_markdown": "Older body"},
                "evidence_pack": {},
                "writer_receipt": {
                    "report_filepath": str(old_report),
                    "report_relative_path": "outputs/user_topic/20260420_0332/reports/final_report_old.html",
                },
            },
            {
                "event_id": "evt-modern-new",
                "title": {"text": "Latest Modern Report"},
                "summary": {"text": "Latest summary"},
                "draft": {"body_markdown": "Latest body"},
                "evidence_pack": {},
                "writer_receipt": {
                    "report_filepath": str(new_report),
                    "report_relative_path": "outputs/user_topic/20260420_0332/reports/final_report_new.html",
                },
            },
        ]
        (debug_root / "content_bundles.json").write_text(json.dumps(content_bundles, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_root / "summary.json").write_text(
            json.dumps({"request_id": "req-user-topic-001", "run_id": "20260420_0332", "status": "completed"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (mode_root / "latest.json").write_text(
            json.dumps({"mode": "user_topic", "latest_run": "20260420_0332", "status": "completed"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return run_root

    def test_publish_only_uses_latest_content_bundles_file(self):
        runs_root = self._workspace_tmpdir("publish-only-")
        older_run = runs_root / "req-old" / "run-old"
        newer_run = runs_root / "req-new" / "run-new"
        self._write_content_bundles(older_run, event_id="evt-old")
        latest_file = self._write_content_bundles(newer_run, event_id="evt-new")

        fake_result = {
            "run_status": "completed",
            "request_id": "req-new",
            "event_id": "evt-new",
            "delivery_receipt": {
                "events": [
                    {
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result) as mocked_deliver:
            result = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["publish_source"]["kind"], "content_bundles")
        self.assertEqual(Path(result["publish_source"]["path"]).name, latest_file.name)
        delivered_payload = mocked_deliver.call_args.args[0]
        self.assertEqual(delivered_payload["content_bundle"]["event_id"], "evt-new")
        self.assertTrue((newer_run / "publish" / "records.jsonl").exists())

    def test_publish_only_skips_when_same_content_already_published(self):
        runs_root = self._workspace_tmpdir("publish-only-")
        run_root = runs_root / "req-new" / "run-new"
        self._write_content_bundles(run_root, event_id="evt-new")

        fake_result = {
            "run_status": "completed",
            "request_id": "req-new",
            "event_id": "evt-new",
            "delivery_receipt": {
                "events": [
                    {
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result):
            first = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )
        self.assertEqual(first["run_status"], "completed")

        with patch("clawradar.publish_only.topic_radar_deliver", side_effect=AssertionError("should skip duplicate publish")):
            second = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        self.assertEqual(second["run_status"], "skipped")
        self.assertEqual(second["skip_reason"], "already_published")

    def test_publish_only_accepts_explicit_payload_snapshot_file(self):
        runs_root = self._workspace_tmpdir("publish-only-")
        run_root = runs_root / "req-snapshot" / "run-snapshot"
        payload_snapshot = self._write_payload_snapshot(run_root, event_id="evt-snapshot")

        fake_result = {
            "run_status": "completed",
            "request_id": "req-snapshot",
            "event_id": "evt-snapshot",
            "delivery_receipt": {
                "events": [
                    {
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result) as mocked_deliver:
            result = publish_existing_output(
                publish_file=payload_snapshot,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["publish_source"]["kind"], "payload_snapshot")
        delivered_payload = mocked_deliver.call_args.args[0]
        self.assertEqual(delivered_payload["content_bundle"]["event_id"], "evt-snapshot")
        self.assertTrue((run_root / "publish" / "records.jsonl").exists())

    def test_publish_only_prefers_mode_latest_pointer_and_latest_bundle_in_modern_outputs(self):
        runs_root = self._workspace_tmpdir("publish-only-modern-")
        modern_run = self._write_modern_output_run(runs_root)
        legacy_file = self._write_content_bundles(runs_root / "req-legacy" / "run-legacy", event_id="evt-legacy")
        os.utime(legacy_file, (1_900_000_000, 1_900_000_000))

        fake_result = {
            "run_status": "completed",
            "request_id": "req-user-topic-001",
            "event_id": "evt-modern-new",
            "delivery_receipt": {
                "events": [
                    {
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result) as mocked_deliver:
            result = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        delivered_payload = mocked_deliver.call_args.args[0]
        self.assertEqual(result["run_status"], "completed")
        self.assertTrue(result["publish_source"]["path"].endswith("outputs/user_topic/20260420_0332/debug/content_bundles.json"))
        self.assertTrue(result["publish_source"]["run_root"].endswith("outputs/user_topic/20260420_0332"))
        self.assertEqual(delivered_payload["request_id"], "req-user-topic-001")
        self.assertEqual(delivered_payload["content_bundle"]["event_id"], "evt-modern-new")
        self.assertTrue((modern_run / "publish" / "records.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
