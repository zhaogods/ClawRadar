import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
                "summary": {
                    "text": "Summary for publish-only",
                    "channel_variants": {"wechat": "WeChat summary for publish-only"},
                },
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
                "summary": {
                    "text": "Summary from payload snapshot",
                    "channel_variants": {"wechat": "WeChat summary from payload snapshot"},
                },
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
                "summary": {
                    "text": "Older summary",
                    "channel_variants": {"wechat": "Older WeChat summary"},
                },
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
                "summary": {
                    "text": "Latest summary",
                    "channel_variants": {"wechat": "Latest WeChat summary"},
                },
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
        self.assertEqual(
            delivered_payload["content_bundle"]["summary"]["channel_variants"]["wechat"],
            "WeChat summary for publish-only",
        )
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

    def test_publish_only_republishes_when_wechat_summary_variant_changes(self):
        runs_root = self._workspace_tmpdir("publish-only-")
        run_root = runs_root / "req-new" / "run-new"
        content_bundles_path = self._write_content_bundles(run_root, event_id="evt-new")

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

        payload = json.loads(content_bundles_path.read_text(encoding="utf-8"))
        payload[0]["summary"]["channel_variants"]["wechat"] = "Updated WeChat summary for publish-only"
        content_bundles_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result) as mocked_deliver:
            second = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        self.assertEqual(second["run_status"], "completed")
        self.assertEqual(second["publish_record"]["summary_wechat"], "Updated WeChat summary for publish-only")
        delivered_payload = mocked_deliver.call_args.args[0]
        self.assertEqual(
            delivered_payload["content_bundle"]["summary"]["channel_variants"]["wechat"],
            "Updated WeChat summary for publish-only",
        )

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
        self.assertEqual(result["publish_record"]["summary_text"], "Summary from payload snapshot")
        self.assertEqual(result["publish_record"]["summary_wechat"], "WeChat summary from payload snapshot")
        delivered_payload = mocked_deliver.call_args.args[0]
        self.assertEqual(delivered_payload["content_bundle"]["event_id"], "evt-snapshot")
        self.assertEqual(
            delivered_payload["content_bundle"]["summary"]["channel_variants"]["wechat"],
            "WeChat summary from payload snapshot",
        )
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
        self.assertEqual(
            delivered_payload["content_bundle"]["summary"]["channel_variants"]["wechat"],
            "Latest WeChat summary",
        )
        self.assertTrue((modern_run / "publish" / "records.jsonl").exists())

    def test_publish_only_triggers_notification_when_configured(self):
        runs_root = self._workspace_tmpdir("publish-only-notify-")
        run_root = runs_root / "req-new" / "run-new"
        self._write_content_bundles(run_root, event_id="evt-new")

        fake_result = {
            "run_status": "completed",
            "request_id": "req-new",
            "event_id": "evt-new",
            "delivery_receipt": {
                "delivery_channel": "wechat",
                "delivery_target": "wechat://draft-box/openclaw-review",
                "events": [
                    {
                        "status": "delivered",
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }
        fake_notification_result = {
            "run_status": "completed",
            "notification_receipt": {
                "notification_channel": "pushplus",
                "notification_target": "pushplus://default",
                "notification_reason": "publish_succeeded",
            },
            "errors": [],
            "skip_reason": None,
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result), patch(
            "clawradar.publish_only.topic_radar_notify", return_value=fake_notification_result
        ) as mocked_notify:
            result = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
                notification_channel="pushplus",
                notification_target="pushplus://default",
                notification_options={"pushplus": {"token": "token-123"}},
                notify_on=["publish_succeeded"],
            )

        notify_payload = mocked_notify.call_args.args[0]
        self.assertEqual(result["notification_result"], fake_notification_result)
        self.assertEqual(mocked_notify.call_args.kwargs["channel"], "pushplus")
        self.assertEqual(mocked_notify.call_args.kwargs["target"], "pushplus://default")
        self.assertEqual(mocked_notify.call_args.kwargs["runs_root"], run_root)
        self.assertEqual(notify_payload["notification_channel"], "pushplus")
        self.assertEqual(notify_payload["notification_target"], "pushplus://default")
        self.assertEqual(notify_payload["notify_on"], ["publish_succeeded"])
        self.assertEqual(notify_payload["notification_reason"], "publish_succeeded")
        self.assertEqual(notify_payload["output_root"], run_root.as_posix())
        self.assertEqual(notify_payload["output_context"]["output_root"], run_root.as_posix())
        self.assertEqual(notify_payload["entry_options"]["notification"]["channel"], "pushplus")
        self.assertEqual(notify_payload["entry_options"]["notification"]["target"], "pushplus://default")
        self.assertEqual(notify_payload["entry_options"]["notification"]["notify_on"], ["publish_succeeded"])
        self.assertNotIn("token", notify_payload["entry_options"]["notification"].get("pushplus", {}))
        self.assertEqual(notify_payload["delivery_channel"], "wechat")
        self.assertEqual(notify_payload["delivery_target"], "wechat://draft-box/openclaw-review")

    def test_publish_only_skips_notification_when_not_configured(self):
        runs_root = self._workspace_tmpdir("publish-only-notify-skip-")
        run_root = runs_root / "req-new" / "run-new"
        self._write_content_bundles(run_root, event_id="evt-new")

        fake_result = {
            "run_status": "completed",
            "request_id": "req-new",
            "event_id": "evt-new",
            "delivery_receipt": {
                "events": [
                    {
                        "status": "delivered",
                        "message_path": "wechat_delivery_message.json",
                        "payload_path": "payload_snapshot.json",
                        "archive_path": "archive",
                        "failure_info": None,
                    }
                ]
            },
            "errors": [],
        }

        with patch("clawradar.publish_only.topic_radar_deliver", return_value=fake_result), patch(
            "clawradar.publish_only.topic_radar_notify", return_value={"run_status": "skipped"}
        ) as mocked_notify:
            result = publish_existing_output(
                runs_root=runs_root,
                delivery_channel="wechat",
                delivery_target="wechat://draft-box/openclaw-review",
            )

        mocked_notify.assert_called_once()
        notify_payload = mocked_notify.call_args.args[0]
        self.assertEqual(mocked_notify.call_args.kwargs["channel"], None)
        self.assertEqual(mocked_notify.call_args.kwargs["target"], None)
        self.assertEqual(notify_payload["notification_channel"], "")
        self.assertEqual(notify_payload["notification_target"], "")
        self.assertEqual(notify_payload["notify_on"], [])
        self.assertEqual(result["notification_result"]["run_status"], "skipped")

    def test_pushplus_notifier_builds_request_and_summary(self):
        from clawradar.notifiers.pushplus.service import send_pushplus_notification

        payload = {
            "request_id": "req-notify-001",
            "run_status": "completed",
            "final_stage": "deliver",
            "decision_status": "publish_ready",
            "notification_reason": "publish_succeeded",
            "delivery_channel": "wechat",
            "delivery_target": "wechat://draft-box/openclaw-review",
            "output_root": "F:/outputs/user_topic/20260420_0332",
            "delivery_receipt": {
                "events": [
                    {"status": "delivered", "failure_info": None},
                    {"status": "failed", "failure_info": {"message": "quota exceeded"}},
                ]
            },
        }
        response = Mock()
        response.json.return_value = {"code": 200, "msg": "ok", "data": "msg-id-1"}
        response.raise_for_status.return_value = None

        with patch("clawradar.notifiers.pushplus.service.requests.post", return_value=response) as mocked_post:
            result = send_pushplus_notification(
                payload,
                notification_target="pushplus://channel/ops-room",
                options={"pushplus": {"token": "token-123"}},
            )

        request_body = mocked_post.call_args.kwargs["json"]
        self.assertEqual(request_body["token"], "token-123")
        self.assertEqual(request_body["channel"], "ops-room")
        self.assertEqual(request_body["template"], "markdown")
        self.assertIn("ClawRadar 通知", request_body["title"])
        self.assertIn("**请求 ID**：req-notify-001", request_body["content"])
        self.assertIn("**失败交付数**：1", request_body["content"])
        self.assertIn("**首个错误**：quota exceeded", request_body["content"])
        self.assertEqual(result["channel"], "pushplus")
        self.assertEqual(result["metadata"]["pushplus_channel"], "ops-room")
        self.assertEqual(result["metadata"]["provider_code"], 200)
        self.assertEqual(result["metadata"]["provider_data"], "msg-id-1")

    def test_pushplus_notifier_loads_token_from_local_env_file(self):
        from clawradar.notifiers.pushplus.service import send_pushplus_notification

        payload = {
            "request_id": "req-notify-003",
            "run_status": "completed",
            "final_stage": "deliver",
            "decision_status": "publish_ready",
            "notification_reason": "publish_succeeded",
        }
        response = Mock()
        response.json.return_value = {"code": 200, "msg": "ok", "data": "msg-id-2"}
        response.raise_for_status.return_value = None

        with patch("clawradar.notifiers.pushplus.service.PUSHPLUS_ENV_FILE") as mocked_env_path, patch(
            "clawradar.notifiers.pushplus.service.dotenv_values", return_value={"PUSHPLUS_TOKEN": "env-token-123"}
        ), patch("clawradar.notifiers.pushplus.service.requests.post", return_value=response) as mocked_post:
            mocked_env_path.exists.return_value = True
            result = send_pushplus_notification(
                payload,
                notification_target="pushplus://default",
                options={},
            )

        request_body = mocked_post.call_args.kwargs["json"]
        self.assertEqual(request_body["token"], "env-token-123")
        self.assertEqual(result["metadata"]["provider_data"], "msg-id-2")

    def test_pushplus_notifier_raises_when_provider_returns_failure(self):
        from clawradar.notifiers.pushplus.service import PushPlusNotificationError, send_pushplus_notification

        payload = {
            "request_id": "req-notify-002",
            "run_status": "failed",
            "final_stage": "write",
            "decision_status": "need_more_evidence",
            "notification_reason": "run_failed",
        }
        response = Mock()
        response.json.return_value = {"code": 500, "msg": "rate limited"}
        response.raise_for_status.return_value = None

        with patch("clawradar.notifiers.pushplus.service.requests.post", return_value=response):
            with self.assertRaises(PushPlusNotificationError) as ctx:
                send_pushplus_notification(
                    payload,
                    notification_target="pushplus://default",
                    options={"pushplus": {"token": "token-123"}},
                )



if __name__ == "__main__":
    unittest.main()
