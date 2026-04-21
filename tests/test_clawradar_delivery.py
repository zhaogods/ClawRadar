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

    def test_wechat_channel_uses_channel_specific_message_file(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
                return "wechat-media-id"

        try:
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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

        archived_payload = json.loads(Path(result["delivery_receipt"]["events"][0]["payload_path"]).read_text(encoding="utf-8"))
        wechat_options = archived_payload["entry_options"]["delivery"]["wechat"]
        self.assertNotIn("appid", wechat_options)
        self.assertNotIn("secret", wechat_options)
        self.assertNotIn("WECHAT_APPID", archived_payload)
        self.assertNotIn("WECHAT_SECRET", archived_payload)

    def test_wechat_channel_simplifies_report_html_for_wechat_draft(self):
        payload = self._load_fixture("clawradar_deliver_publish_ready_input.json")
        payload["delivery_channel"] = "wechat"
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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
        payload["delivery_target"] = "wechat://draft-box/openclaw-review"
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
            with patch("clawradar.publishers.wechat.service._load_wechat_publisher_class", return_value=FakePublisher):
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


if __name__ == "__main__":
    unittest.main()
