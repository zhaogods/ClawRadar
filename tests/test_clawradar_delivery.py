import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from clawradar.delivery import (
    build_delivery_rejection,
    build_feishu_delivery_message,
    topic_radar_deliver,
)
from clawradar.writing import MAX_WECHAT_DIGEST_TEXT_UNITS, MAX_WECHAT_DIGEST_UTF8_BYTES
from clawradar.publishers.wechat.publisher import WeChatDraftUploadError, WeChatPublisher


class ClawRadarDeliveryTestCase(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _load_fixture(self, filename):
        return json.loads((self.fixtures_dir / filename).read_text(encoding="utf-8"))


    def _workspace_tmpdir(self, name):
        workspace_tmp_root = Path(__file__).resolve().parents[1] / '.tmp' / 'test_runs'
        workspace_tmp_root.mkdir(parents=True, exist_ok=True)
        run_root = workspace_tmp_root / f"{name}{self.id().split('.')[-1]}"
        run_root.mkdir(parents=True, exist_ok=True)
        return run_root

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

        tmpdir = self._workspace_tmpdir("delivery-")
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

        tmpdir = self._workspace_tmpdir("delivery-")
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

        tmpdir = self._workspace_tmpdir("delivery-")
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

    def test_wechat_publisher_class_available_from_channel_package(self):
        from clawradar.publishers.wechat.publisher import WeChatPublisher as PublisherClass

        self.assertEqual(PublisherClass.__name__, "WeChatPublisher")
        publisher = PublisherClass("wx-test-appid", "wx-test-secret")
        for method_name in (
            "get_access_token",
            "upload_image",
            "upload_default_cover",
            "upload_draft",
        ):
            self.assertTrue(callable(getattr(publisher, method_name, None)))

    def test_wechat_channel_uses_channel_specific_message_file(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["entry_options"] = {
            "delivery": {
                "wechat": {
                    "appid": "payload-should-not-be-used",
                    "secret": "payload-should-not-be-used",
                }
            }
        }
        tmpdir = self._workspace_tmpdir("delivery-wechat-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")
        payload["content_bundle"]["title"]["text"] = "企业级安全治理平台发布"

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret
                FakePublisher.last_init = {"appid": appid, "secret": secret}

            def get_access_token(self):
                return "token-123"

            def _markdown_to_html(self, markdown_text):
                return f"<section>{markdown_text}</section>"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-09T12:00:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "wechat")
        self.assertEqual(result["delivery_receipt"]["events"][0]["message_path"].endswith("wechat_delivery_message.json"), True)
        self.assertEqual(result["delivery_receipt"]["events"][0]["status"], "delivered")
        self.assertEqual(result["delivery_receipt"]["events"][0]["failure_info"], None)
        self.assertEqual(FakePublisher.last_init, {"appid": "wx-test-appid", "secret": "wx-test-secret"})
        self.assertEqual(FakePublisher.last_upload["title"], "企业级安全治理平台发布")
        self.assertLessEqual(len(FakePublisher.last_upload["title"]), 64)

        archived_payload = json.loads(Path(result["delivery_receipt"]["events"][0]["payload_path"]).read_text(encoding="utf-8"))
        wechat_options = archived_payload["entry_options"]["delivery"]["wechat"]
        self.assertNotIn("appid", wechat_options)
        self.assertNotIn("secret", wechat_options)
        self.assertNotIn("WECHAT_APPID", archived_payload)
        self.assertNotIn("WECHAT_SECRET", archived_payload)

    def test_wechat_channel_normalizes_title_author_and_digest_before_upload(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["author"] = "超长作者名甲乙丙丁戊己庚辛壬癸作者"
        payload["content_bundle"]["title"]["text"] = "这是一个超过六十四个字符的微信公众号标题用于验证发布前归一化是否生效并确保新限制已正确放宽到平台最新规则"
        payload["content_bundle"]["summary"] = {
            "version": 1,
            "text": "摘" * 150,
            "channel_variants": {"wechat": "微" * 150},
            "source_refs": [],
            "uncertainty_markers": [],
        }

        tmpdir = self._workspace_tmpdir("delivery-wechat-normalize-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                FakePublisher.cover_title = title
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-26T16:00:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(FakePublisher.cover_title, FakePublisher.last_upload["title"])
        self.assertLessEqual(len(FakePublisher.last_upload["title"]), 64)
        self.assertLessEqual(len(FakePublisher.last_upload["author"]), 8)
        self.assertLessEqual(len(FakePublisher.last_upload["digest"]), 120)
        self.assertEqual(FakePublisher.last_upload["digest"], "微" * 120)

        event_receipt = result["delivery_receipt"]["events"][0]
        self.assertEqual(event_receipt["message_metadata"]["author"], FakePublisher.last_upload["author"])
        self.assertEqual(event_receipt["message_metadata"]["final_attempted_title"], FakePublisher.last_upload["title"])
        self.assertEqual(event_receipt["message_metadata"]["final_attempted_digest"], FakePublisher.last_upload["digest"])

    def test_wechat_channel_reports_token_failure_in_chinese(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        tmpdir = self._workspace_tmpdir("delivery-wechat-token-failure-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret
                self.last_error_message = "获取微信 access_token 失败：errcode=40164，errmsg=invalid ip not in whitelist。"

            def get_access_token(self):
                return None

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-09T12:11:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["errors"][0]["code"], "delivery_channel_unavailable")
        self.assertIn("获取微信 access_token 失败", result["errors"][0]["message"])
        self.assertIn("40164", result["errors"][0]["message"])
        self.assertIn("invalid ip not in whitelist", result["errors"][0]["message"])
        self.assertNotIn("IP 白名单", result["errors"][0]["message"])
        self.assertIn("获取微信 access_token 失败", result["delivery_receipt"]["events"][0]["failure_info"]["message"])
        self.assertIn("invalid ip not in whitelist", result["delivery_receipt"]["events"][0]["failure_info"]["message"])


    def test_wechat_channel_prefers_report_html_over_dirty_draft_markdown_with_tables_and_lists(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["content_bundle"]["draft"]["body_markdown"] = "Dirty prefix // Chart.js - embedded bundle"
        tmpdir = self._workspace_tmpdir("delivery-wechat-html-")
        report_path = Path(tmpdir) / "report.html"
        report_path.write_text(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <script>console.log('Chart.js bootstrap');</script>
</head>
<body>
  <main>
    <section class="hero-section-combined">
      <div class="hero-header">
        <h1>Hermes Agent Report</h1>
        <button type="button">Drop me</button>
      </div>
      <div class="hero-body">
        <p>This is the publishable article body.</p>
        <div class="chart-card"><canvas id="chart-1"></canvas></div>
        <ul><li>First item</li><li>Second item</li></ul>
        <table>
          <tr><th>Key</th><th>Value</th></tr>
          <tr><td>A</td><td>B</td></tr>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
            """.strip(),
            encoding="utf-8",
        )
        payload["content_bundle"]["writer_receipt"] = {
            "report_filepath": str(report_path),
        }

        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-09T12:10:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "wechat")
        self.assertIn("This is the publishable article body.", FakePublisher.last_upload["content"])
        self.assertIn("Hermes Agent Report", FakePublisher.last_upload["content"])
        self.assertIn("First item", FakePublisher.last_upload["content"])
        self.assertIn("Key", FakePublisher.last_upload["content"])
        self.assertNotIn("Chart.js", FakePublisher.last_upload["content"])
        self.assertNotIn("Drop me", FakePublisher.last_upload["content"])
        self.assertNotIn("canvas", FakePublisher.last_upload["content"].lower())

    def test_wechat_channel_placeholder_mode_replaces_visual_media(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["delivery_options"] = {"report_image_mode": "placeholder"}
        tmpdir = self._workspace_tmpdir("delivery-wechat-placeholder-")
        report_path = Path(tmpdir) / "report.html"
        report_path.write_text(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<body>
  <main>
    <section>
      <h1>Visual Report</h1>
      <p>Body text.</p>
      <img src="https://example.com/demo.png" alt="Demo Image" />
      <canvas id="chart-1"></canvas>
    </section>
  </main>
</body>
</html>
            """.strip(),
            encoding="utf-8",
        )
        payload["content_bundle"]["writer_receipt"] = {"report_filepath": str(report_path)}

        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-09T12:12:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self.assertIn("Image omitted", FakePublisher.last_upload["content"])
        self.assertIn("Chart omitted", FakePublisher.last_upload["content"])
        self.assertNotIn("<canvas", FakePublisher.last_upload["content"].lower())

    def test_wechat_channel_upload_mode_keeps_uploaded_img(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["delivery_options"] = {"report_image_mode": "upload"}
        tmpdir = self._workspace_tmpdir("delivery-wechat-upload-")
        image_path = Path(tmpdir) / "chart.png"
        image_path.write_bytes(b"fake-image")
        report_path = Path(tmpdir) / "report.html"
        report_path.write_text(
            f"""
<!DOCTYPE html>
<html lang="zh-CN">
<body>
  <main>
    <section>
      <h1>Upload Report</h1>
      <p>Body text.</p>
      <img src="{image_path}" alt="Uploaded Image" />
    </section>
  </main>
</body>
</html>
            """.strip(),
            encoding="utf-8",
        )
        payload["content_bundle"]["writer_receipt"] = {"report_filepath": str(report_path)}

        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret
                self.access_token = "token-123"

            def get_access_token(self):
                return self.access_token

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                with patch("clawradar.publishers.wechat.image_handler.upload_wechat_article_image", return_value="https://mmbiz.qpic.cn/test-image"):
                    from clawradar.publishers.wechat import service as wechat_service
                    wechat_service._channel_env.cache_clear()
                    topic_radar_deliver(
                        payload,
                        channel="wechat",
                        target=payload["delivery_target"],
                        delivery_time="2026-04-09T12:14:00Z",
                        runs_root=Path(tmpdir),
                    )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self.assertIn("https://mmbiz.qpic.cn/test-image", FakePublisher.last_upload["content"])
        self.assertIn("<img", FakePublisher.last_upload["content"].lower())
        self.assertNotIn("Image omitted", FakePublisher.last_upload["content"])

    def test_wechat_channel_upload_mode_renders_chart_payload_as_img(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["delivery_options"] = {"report_image_mode": "upload"}
        tmpdir = self._workspace_tmpdir("delivery-wechat-chart-upload-")
        report_path = Path(tmpdir) / "report.html"
        report_path.write_text(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<body>
  <main>
    <section>
      <h1>Chart Upload Report</h1>
      <div class="chart-card">
        <div class="chart-container">
          <canvas id="chart-1" data-config-id="chart-config-1"></canvas>
        </div>
        <script id="chart-config-1" type="application/json">{"widgetType":"chart.js/bar","data":{"labels":["Jan","Feb"],"datasets":[{"label":"Series A","data":[10,12]},{"label":"Series B","data":[15,18]}]},"options":{"plugins":{"title":{"display":true,"text":"Chart Summary"}}}}</script>
        <div class="chart-fallback" data-prebuilt="true">
          <table>
            <caption>Chart Summary</caption>
            <thead>
              <tr><th>Category</th><th>Series A</th><th>Series B</th></tr>
            </thead>
            <tbody>
              <tr><td>Jan</td><td>10</td><td>15</td></tr>
              <tr><td>Feb</td><td>12</td><td>18</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </main>
</body>
</html>
            """.strip(),
            encoding="utf-8",
        )
        payload["content_bundle"]["writer_receipt"] = {"report_filepath": str(report_path)}

        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret
                self.access_token = "token-123"

            def get_access_token(self):
                return self.access_token

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                with patch("clawradar.publishers.wechat.image_handler.render_chart_container_to_png", return_value=Path(tmpdir) / "chart.png"):
                    with patch("clawradar.publishers.wechat.image_handler.upload_wechat_article_image", return_value="https://mmbiz.qpic.cn/chart-real-image"):
                        from clawradar.publishers.wechat import service as wechat_service
                        wechat_service._channel_env.cache_clear()
                        topic_radar_deliver(
                            payload,
                            channel="wechat",
                            target=payload["delivery_target"],
                            delivery_time="2026-04-09T12:15:00Z",
                            runs_root=Path(tmpdir),
                        )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self.assertIn("https://mmbiz.qpic.cn/chart-real-image", FakePublisher.last_upload["content"])
        self.assertIn("<img", FakePublisher.last_upload["content"].lower())
        self.assertNotIn("<table", FakePublisher.last_upload["content"].lower())
        self.assertIn("Chart Summary", FakePublisher.last_upload["content"])

    def test_wechat_channel_prefers_report_html_over_dirty_draft_markdown(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["content_bundle"]["draft"]["body_markdown"] = "Dirty prefix // Chart.js - embedded bundle"
        tmpdir = self._workspace_tmpdir("delivery-wechat-html-")
        report_path = Path(tmpdir) / "report.html"
        report_path.write_text(
            """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <script>console.log('Chart.js bootstrap');</script>
</head>
<body>
  <main>
    <section>
      <h1>Hermes Agent Report</h1>
      <p>This is the publishable article body.</p>
      <button type="button">Drop me</button>
    </section>
  </main>
</body>
</html>
            """.strip(),
            encoding="utf-8",
        )
        payload["content_bundle"]["writer_receipt"] = {
            "report_filepath": str(report_path),
        }

        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-09T12:10:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "wechat")
        self.assertIn("This is the publishable article body.", FakePublisher.last_upload["content"])
        self.assertNotIn("Chart.js", FakePublisher.last_upload["content"])
        self.assertNotIn("Drop me", FakePublisher.last_upload["content"])

    def test_wechat_delivery_prefers_channel_specific_summary_variant(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["content_bundle"]["summary"] = {
            "version": 1,
            "text": "通用摘要文本。",
            "channel_variants": {"wechat": "微信专用摘要文本。"},
            "source_refs": [],
            "uncertainty_markers": [],
        }

        tmpdir = self._workspace_tmpdir("delivery-wechat-summary-variant-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-24T12:25:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(FakePublisher.last_upload["digest"], "微信专用摘要文本。")

    def test_wechat_delivery_retries_title_once_on_45003_and_succeeds(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["normalized_events"][0]["company"] = "OpenAI"
        payload["content_bundle"]["title"]["text"] = "AI大模型调用量逆转，算力涨价谁买单：面向企业落地的深度观察报告——围绕模型、算力、采购与治理的超长标题扩展说明，用于验证45003重试是否真正触发"
        tmpdir = self._workspace_tmpdir("delivery-wechat-45003-retry-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            last_error_message = None
            last_error_details = None
            upload_titles = []

            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                title = kwargs["title"]
                FakePublisher.upload_titles.append(title)
                if len(FakePublisher.upload_titles) == 1:
                    attempted_title = title[:64]
                    FakePublisher.last_error_message = "创建微信草稿失败：errcode=45003，errmsg=title size out of limit。"
                    FakePublisher.last_error_details = {
                        "errcode": "45003",
                        "errmsg": "title size out of limit",
                        "attempted_title": attempted_title,
                        "attempted_title_utf8_bytes": len(attempted_title.encode("utf-8")),
                    }
                    raise WeChatDraftUploadError(
                        errcode="45003",
                        errmsg="title size out of limit",
                        attempted_title=attempted_title,
                        attempted_title_utf8_bytes=len(attempted_title.encode("utf-8")),
                    )
                FakePublisher.last_error_message = None
                FakePublisher.last_error_details = None
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-24T12:10:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(len(FakePublisher.upload_titles), 2)
        self.assertLess(len(FakePublisher.upload_titles[1].encode("utf-8")), len(FakePublisher.upload_titles[0].encode("utf-8")))
        self.assertEqual(FakePublisher.last_upload["title"], FakePublisher.upload_titles[1])

        message_path = Path(result["delivery_receipt"]["events"][0]["message_path"])
        message_payload = json.loads(message_path.read_text(encoding="utf-8"))
        publish_attempts = message_payload["metadata"]["publish_attempts"]
        self.assertEqual(len(publish_attempts), 2)
        self.assertEqual(publish_attempts[0]["stage"], "failed")
        self.assertEqual(publish_attempts[0]["errcode"], "45003")
        self.assertEqual(publish_attempts[1]["stage"], "succeeded")
        self.assertEqual(message_payload["metadata"]["final_attempted_title"], FakePublisher.upload_titles[1])
        self.assertEqual(
            message_payload["metadata"]["final_attempted_title_utf8_bytes"],
            len(FakePublisher.upload_titles[1].encode("utf-8")),
        )

    def test_wechat_delivery_reports_attempted_titles_when_45003_retry_still_fails(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["normalized_events"][0]["company"] = "OpenAI"
        payload["content_bundle"]["title"]["text"] = "AI大模型调用量逆转，算力涨价谁买单：面向企业落地的深度观察报告——围绕模型、算力、采购与治理的超长标题扩展说明，用于验证45003失败后仍会保留重试痕迹"

        tmpdir = self._workspace_tmpdir("delivery-wechat-45003-fail-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            last_error_message = None
            last_error_details = None
            upload_titles = []

            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                title = kwargs["title"]
                FakePublisher.upload_titles.append(title)
                attempted_title = title[:64]
                FakePublisher.last_error_message = "创建微信草稿失败：errcode=45003，errmsg=title size out of limit。"
                FakePublisher.last_error_details = {
                    "errcode": "45003",
                    "errmsg": "title size out of limit",
                    "attempted_title": attempted_title,
                    "attempted_title_utf8_bytes": len(attempted_title.encode("utf-8")),
                }
                raise WeChatDraftUploadError(
                    errcode="45003",
                    errmsg="title size out of limit",
                    attempted_title=attempted_title,
                    attempted_title_utf8_bytes=len(attempted_title.encode("utf-8")),
                )

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-24T12:20:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["errors"][0]["code"], "delivery_channel_unavailable")
        self.assertEqual(len(FakePublisher.upload_titles), 2)

        failure_info = result["delivery_receipt"]["events"][0]["failure_info"]
        self.assertEqual(failure_info["code"], "delivery_channel_unavailable")
        self.assertIn("details", failure_info)
        self.assertEqual(failure_info["details"]["errcode"], "45003")
        self.assertEqual(failure_info["details"]["errmsg"], "title size out of limit")
        self.assertEqual(len(failure_info["details"]["publish_attempts"]), 2)
        self.assertEqual(failure_info["details"]["publish_attempts"][0]["stage"], "failed")
        self.assertEqual(failure_info["details"]["publish_attempts"][1]["stage"], "failed")
        self.assertLess(
            failure_info["details"]["publish_attempts"][1]["requested_title_utf8_bytes"],
            failure_info["details"]["publish_attempts"][0]["requested_title_utf8_bytes"],
        )
        self.assertEqual(result["errors"][0]["details"]["errcode"], "45003")

    def test_wechat_delivery_retries_digest_once_on_45004_and_succeeds(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["normalized_events"][0]["company"] = "OpenAI"
        payload["content_bundle"]["title"]["text"] = "AI算力涨价潮：供需关系重构与行业阵痛"
        payload["content_bundle"]["summary"] = {
            "version": 1,
            "text": "中" * 150,
            "channel_variants": {"wechat": "中" * 150},
            "source_refs": [],
            "uncertainty_markers": [],
        }

        tmpdir = self._workspace_tmpdir("delivery-wechat-45004-retry-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            last_error_message = None
            last_error_details = None
            upload_digests = []
            upload_titles = []

            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                digest = kwargs["digest"]
                title = kwargs["title"]
                FakePublisher.upload_digests.append(digest)
                FakePublisher.upload_titles.append(title)
                if len(FakePublisher.upload_digests) == 1:
                    FakePublisher.last_error_message = "创建微信草稿失败：errcode=45004，errmsg=description size out of limit。"
                    FakePublisher.last_error_details = {
                        "errcode": "45004",
                        "errmsg": "description size out of limit",
                        "attempted_title": title,
                        "attempted_title_utf8_bytes": len(title.encode("utf-8")),
                    }
                    raise WeChatDraftUploadError(
                        errcode="45004",
                        errmsg="description size out of limit",
                        attempted_title=title,
                        attempted_title_utf8_bytes=len(title.encode("utf-8")),
                    )
                FakePublisher.last_error_message = None
                FakePublisher.last_error_details = None
                FakePublisher.last_upload = kwargs
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-24T12:30:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(len(FakePublisher.upload_digests), 2)
        self.assertLess(
            len(FakePublisher.upload_digests[1].encode("utf-8")),
            len(FakePublisher.upload_digests[0].encode("utf-8")),
        )
        self.assertLessEqual(len(FakePublisher.upload_digests[1].encode("utf-8")), MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(
            len(FakePublisher.upload_digests[1]),
            MAX_WECHAT_DIGEST_TEXT_UNITS,
        )
        self.assertEqual(FakePublisher.last_upload["digest"], FakePublisher.upload_digests[1])
        self.assertLessEqual(len(FakePublisher.last_upload["digest"].encode("utf-8")), MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(
            len(FakePublisher.last_upload["digest"]),
            MAX_WECHAT_DIGEST_TEXT_UNITS,
        )
        self.assertNotIn("请直接重写一个更短且语义完整的微信公众号摘要", FakePublisher.upload_digests[1])

        message_path = Path(result["delivery_receipt"]["events"][0]["message_path"])
        message_payload = json.loads(message_path.read_text(encoding="utf-8"))
        publish_attempts = message_payload["metadata"]["publish_attempts"]
        self.assertEqual(len(publish_attempts), 2)
        self.assertEqual(publish_attempts[0]["stage"], "failed")
        self.assertEqual(publish_attempts[0]["errcode"], "45004")
        self.assertEqual(publish_attempts[1]["stage"], "succeeded")
        self.assertLess(publish_attempts[1]["digest_utf8_bytes"], publish_attempts[0]["digest_utf8_bytes"])
        self.assertLessEqual(publish_attempts[1]["digest_chars"], MAX_WECHAT_DIGEST_TEXT_UNITS)
        event_receipt = result["delivery_receipt"]["events"][0]
        self.assertEqual(event_receipt["message_metadata"]["final_attempted_digest"], FakePublisher.upload_digests[1])
        self.assertEqual(
            event_receipt["message_metadata"]["final_attempted_digest_utf8_bytes"],
            len(FakePublisher.upload_digests[1].encode("utf-8")),
        )
        self.assertLessEqual(event_receipt["message_metadata"]["final_attempted_digest_utf8_bytes"], MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(event_receipt["message_metadata"]["final_attempted_digest_chars"], MAX_WECHAT_DIGEST_TEXT_UNITS)
        self.assertNotIn(
            "请直接重写一个更短且语义完整的微信公众号摘要",
            event_receipt["message_metadata"]["final_attempted_digest"],
        )
        self.assertEqual(
            event_receipt["message_metadata"]["publish_attempts"][1]["requested_digest"],
            FakePublisher.upload_digests[1],
        )

    def test_wechat_delivery_reports_failed_digests_when_45004_retry_still_fails(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/clawradar-review"
        payload["normalized_events"][0]["company"] = "OpenAI"
        payload["content_bundle"]["title"]["text"] = "AI算力涨价潮：供需关系重构与行业阵痛"
        payload["content_bundle"]["summary"] = {
            "version": 1,
            "text": "中" * 150,
            "channel_variants": {"wechat": "中" * 150},
            "source_refs": [],
            "uncertainty_markers": [],
        }

        tmpdir = self._workspace_tmpdir("delivery-wechat-45004-fail-")
        channel_env = Path("clawradar/publishers/wechat/.env")
        original_env = channel_env.read_text(encoding="utf-8") if channel_env.exists() else None
        channel_env.write_text("WECHAT_APPID=wx-test-appid\nWECHAT_SECRET=wx-test-secret\nWECHAT_AUTHOR=ClawRadar\n", encoding="utf-8")

        class FakePublisher:
            last_error_message = None
            last_error_details = None
            upload_digests = []
            upload_titles = []

            def __init__(self, appid, secret):
                self.appid = appid
                self.secret = secret

            def get_access_token(self):
                return "token-123"

            def upload_default_cover(self, title=""):
                return "cover-media-id"

            def upload_draft(self, **kwargs):
                digest = kwargs["digest"]
                title = kwargs["title"]
                FakePublisher.upload_digests.append(digest)
                FakePublisher.upload_titles.append(title)
                FakePublisher.last_error_message = "创建微信草稿失败：errcode=45004，errmsg=description size out of limit。"
                FakePublisher.last_error_details = {
                    "errcode": "45004",
                    "errmsg": "description size out of limit",
                    "attempted_title": title,
                    "attempted_title_utf8_bytes": len(title.encode("utf-8")),
                }
                raise WeChatDraftUploadError(
                    errcode="45004",
                    errmsg="description size out of limit",
                    attempted_title=title,
                    attempted_title_utf8_bytes=len(title.encode("utf-8")),
                )

        try:
            with patch("clawradar.publishers.wechat.service.WeChatPublisher", new=FakePublisher):
                from clawradar.publishers.wechat import service as wechat_service
                wechat_service._channel_env.cache_clear()
                result = topic_radar_deliver(
                    payload,
                    channel="wechat",
                    target=payload["delivery_target"],
                    delivery_time="2026-04-24T12:40:00Z",
                    runs_root=Path(tmpdir),
                )
        finally:
            from clawradar.publishers.wechat import service as wechat_service
            wechat_service._channel_env.cache_clear()
            if original_env is None:
                if channel_env.exists():
                    channel_env.unlink()
            else:
                channel_env.write_text(original_env, encoding="utf-8")

        self._assert_protocol_fields(result)
        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["errors"][0]["code"], "delivery_channel_unavailable")
        self.assertEqual(len(FakePublisher.upload_digests), 2)

        failure_info = result["delivery_receipt"]["events"][0]["failure_info"]
        self.assertEqual(failure_info["code"], "delivery_channel_unavailable")
        self.assertIn("details", failure_info)
        self.assertEqual(failure_info["details"]["errcode"], "45004")
        self.assertEqual(failure_info["details"]["errmsg"], "description size out of limit")
        self.assertEqual(len(failure_info["details"]["publish_attempts"]), 2)
        self.assertEqual(failure_info["details"]["publish_attempts"][0]["stage"], "failed")
        self.assertEqual(failure_info["details"]["publish_attempts"][1]["stage"], "failed")
        self.assertLess(
            failure_info["details"]["publish_attempts"][1]["digest_utf8_bytes"],
            failure_info["details"]["publish_attempts"][0]["digest_utf8_bytes"],
        )
        self.assertLessEqual(failure_info["details"]["publish_attempts"][1]["digest_utf8_bytes"], MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(len(FakePublisher.upload_digests[1]), MAX_WECHAT_DIGEST_TEXT_UNITS)
        self.assertEqual(
            failure_info["details"]["final_attempted_digest"],
            FakePublisher.upload_digests[1],
        )
        self.assertEqual(
            failure_info["details"]["final_attempted_digest_utf8_bytes"],
            len(FakePublisher.upload_digests[1].encode("utf-8")),
        )
        self.assertLessEqual(failure_info["details"]["final_attempted_digest_utf8_bytes"], MAX_WECHAT_DIGEST_UTF8_BYTES)
        self.assertLessEqual(failure_info["details"]["final_attempted_digest_chars"], MAX_WECHAT_DIGEST_TEXT_UNITS)
        self.assertEqual(result["delivery_receipt"]["events"][0]["message_metadata"]["final_attempted_digest"], FakePublisher.upload_digests[1])
        self.assertEqual(result["errors"][0]["details"]["errcode"], "45004")

    def test_wechat_publisher_sends_utf8_json_body_without_unicode_escapes(self):
        publisher = WeChatPublisher("wx-test-appid", "wx-test-secret")
        publisher.access_token = "token-123"
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"media_id": "wechat-media-id"}

        def fake_post(url, params=None, data=None, headers=None, timeout=None, **kwargs):
            captured["url"] = url
            captured["params"] = params
            captured["data"] = data
            captured["headers"] = headers
            captured["timeout"] = timeout
            captured["extra_kwargs"] = kwargs
            return FakeResponse()

        with patch("clawradar.publishers.wechat.publisher.requests.post", side_effect=fake_post):
            media_id = publisher.upload_draft(
                title="中文标题甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黄宇宙洪荒日月盈昃",
                content="<p>正文</p>",
                author="作者甲乙丙丁戊己庚辛壬癸",
                digest="摘要甲乙丙丁戊己庚辛壬癸",
                thumb_media_id="thumb-media-id",
            )

        self.assertEqual(media_id, "wechat-media-id")
        self.assertNotIn("json", captured["extra_kwargs"])
        self.assertIsInstance(captured["data"], bytes)
        body_text = captured["data"].decode("utf-8")
        self.assertIn("中文标题", body_text)
        self.assertIn("作者甲乙", body_text)
        self.assertIn("摘要甲乙", body_text)
        self.assertNotIn("\\u", body_text)
        self.assertEqual(captured["headers"], {"Content-Type": "application/json; charset=utf-8"})
        self.assertEqual(captured["timeout"], 30)

        article = json.loads(body_text)["articles"][0]
        self.assertLessEqual(len(article["title"]), 64)
        self.assertLessEqual(len(article["author"]), 8)
        self.assertLessEqual(len(article["digest"]), 120)

    def test_wechat_publisher_reports_official_draft_error_without_permission_guess(self):
        publisher = WeChatPublisher("wx-test-appid", "wx-test-secret")
        publisher.access_token = "token-123"

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "errcode": 45003,
                    "errmsg": "title size out of limit",
                }

        with patch("clawradar.publishers.wechat.publisher.requests.post", return_value=FakeResponse()):
            with self.assertRaises(WeChatDraftUploadError) as context:
                publisher.upload_draft(
                    title="超长标题",
                    content="<p>body</p>",
                    author="ClawRadar",
                    digest="summary",
                    thumb_media_id="thumb-media-id",
                )

        error = context.exception
        self.assertEqual(error.errcode, "45003")
        self.assertEqual(error.errmsg, "title size out of limit")
        self.assertEqual(
            publisher.last_error_message,
            "创建微信草稿失败：errcode=45003，errmsg=title size out of limit。",
        )
        self.assertEqual(
            publisher.last_error_details,
            {
                "errcode": "45003",
                "errmsg": "title size out of limit",
                "attempted_title": "超长标题",
                "attempted_title_utf8_bytes": len("超长标题".encode("utf-8")),
                "attempted_digest": "summary",
                "attempted_digest_utf8_bytes": len("summary".encode("utf-8")),
                "attempted_digest_chars": 7,
                "attempted_digest_text_units": 7,
            },
        )
