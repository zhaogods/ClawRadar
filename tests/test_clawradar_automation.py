import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clawradar.contracts import normalize_ingest_payload
from clawradar.orchestrator import OrchestratorErrorCode, OrchestratorTriggerSource, topic_radar_orchestrate
from clawradar.real_source import RealSourceUnavailableError
from clawradar.scoring import ScoreDecisionStatus
from clawradar.writing import WriteErrorCode, WriteExecutor, WriteOperation, WriteRunStatus


class ClawRadarAutomationTestCase(unittest.TestCase):
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

    def _build_publish_ready_pipeline_payload(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")
        payload["delivery_channel"] = "feishu"
        payload["delivery_target"] = "feishu://openclaw/p0-review"
        payload["entry_options"] = {
            "write": {"executor": "openclaw_builtin"},
            "delivery": {
                "target_mode": "feishu",
                "channel": "feishu",
                "target": payload["delivery_target"],
            },
        }
        return payload

    def _build_non_publish_ready_pipeline_payload(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["request_id"] = "req-stage5-need-more-evidence"
        payload["topic_candidates"][0]["company"] = ""
        payload["topic_candidates"][0]["initial_tags"] = []
        payload["topic_candidates"][0]["fact_candidates"] = [
            deepcopy(payload["topic_candidates"][0]["fact_candidates"][0])
        ]
        return payload

    def _build_two_event_pipeline_payload(self):
        payload = self._build_publish_ready_pipeline_payload()
        second_event = deepcopy(payload["topic_candidates"][0])
        second_event["event_id"] = "evt-stage5-002"
        second_event["event_title"] = "OpenAI 发布智能体安全治理控制台"
        second_event["event_time"] = "2026-04-09T09:30:00Z"
        second_event["source_url"] = "https://example.com/openai-agent-security-console"
        second_event["raw_excerpt"] = "平台新增审计、权限控制与智能体安全治理控制台。"
        second_event["timeline_candidates"] = [
            {
                "timestamp": "2026-04-09T09:00:00Z",
                "label": "preview",
                "summary": "发布前预告披露将上线智能体安全治理能力",
                "source_url": "https://example.com/openai-agent-security-preview",
                "source_type": "blog",
            },
            {
                "timestamp": "2026-04-09T09:45:00Z",
                "label": "customer_feedback",
                "summary": "首批客户确认治理控制台已进入试用",
                "source_url": "https://example.com/openai-agent-security-customer",
                "source_type": "interview",
            },
        ]
        second_event["fact_candidates"] = [
            {
                "fact_id": "fact-stage5-201",
                "claim": "治理控制台支持权限与审计日志",
                "source_url": "https://example.com/openai-agent-security-console",
                "confidence": 0.94,
                "citation_excerpt": "管理员可集中管理权限与审计日志。",
            },
            {
                "fact_id": "fact-stage5-202",
                "claim": "控制台提供多智能体运行治理能力",
                "source_url": "https://example.com/openai-agent-security-governance",
                "confidence": 0.9,
                "citation_excerpt": "支持跨智能体运行状态与权限治理。",
            },
            {
                "fact_id": "fact-stage5-203",
                "claim": "已有企业客户开始试用治理控制台",
                "source_url": "https://example.com/openai-agent-security-customer",
                "confidence": 0.88,
                "citation_excerpt": "合作客户确认已进入试用阶段。",
            },
        ]
        payload["topic_candidates"].append(second_event)
        return payload

    def _build_real_source_adapter_payload(self):
        return {
            "request_id": "req-stage7-real-source",
            "trigger_source": OrchestratorTriggerSource.MANUAL.value,
            "topic_candidates": [
                {
                    "event_id": "real-source-weibo-123",
                    "event_title": "AI 公司发布新模型并进入微博热搜",
                    "company": "AI公司",
                    "event_time": "2026-04-10T08:00:00Z",
                    "source_url": "https://example.com/weibo/123",
                    "source_type": "mindspider:weibo",
                    "raw_excerpt": "微博热搜显示 AI 公司发布新模型并引发广泛讨论。",
                    "initial_tags": ["real_source", "微博热搜"],
                    "confidence": 0.72,
                    "timeline_candidates": [
                        {
                            "timestamp": "2026-04-10T08:05:00Z",
                            "label": "real_source_collected",
                            "summary": "MindSpider 从微博热搜采集到该事件。",
                            "source_url": "https://example.com/weibo/123",
                            "source_type": "mindspider:weibo",
                        }
                    ],
                    "fact_candidates": [
                        {
                            "fact_id": "real-source-weibo-123-fact-1",
                            "claim": "AI 公司发布新模型并进入微博热搜",
                            "source_url": "https://example.com/weibo/123",
                            "confidence": 0.72,
                            "citation_excerpt": "微博热搜显示 AI 公司发布新模型并引发广泛讨论。",
                        },
                        {
                            "fact_id": "real-source-weibo-123-fact-2",
                            "claim": "该话题来自微博热搜榜单，当前榜单位置为第1位",
                            "source_url": "https://example.com/weibo/123",
                            "confidence": 0.68,
                            "citation_excerpt": "该话题来自微博热搜榜单，当前榜单位置为第1位",
                        },
                    ],
                    "source_metadata": {
                        "provider": "mindspider_broad_topic_today_news",
                        "source_id": "weibo",
                        "source_name": "微博热搜",
                        "rank": 1,
                        "item_id": "123",
                        "collected_at": "2026-04-10T08:05:00Z",
                        "upstream_timestamp": "2026-04-10T08:05:00Z",
                    },
                    "source_snapshot": {
                        "id": "123",
                        "title": "AI 公司发布新模型并进入微博热搜",
                        "url": "https://example.com/weibo/123",
                        "rank": 1,
                    },
                }
            ],
            "real_source_context": {
                "provider": "mindspider_broad_topic_today_news",
                "requested_source_ids": ["weibo"],
                "applied_source_ids": ["weibo"],
                "failed_sources": [],
                "candidate_count": 1,
                "collected_at": "2026-04-10T08:05:00Z",
            },
        }

    def _archive_slug(self, delivery_time):
        return delivery_time.replace(":", "-").replace(".", "-")

    def _run_output_root(self, result):
        return Path(result["output_root"])

    def _archive_dir(self, result, event_id, delivery_time):
        return self._run_output_root(result) / "recovery" / event_id / "deliver" / self._archive_slug(delivery_time)

    def _build_deliver_only_replay_payload(self, orchestration_result):
        replay_payload = deepcopy(orchestration_result["stage_results"]["deliver"])
        replay_payload["delivery_target"] = orchestration_result["delivery_receipt"]["delivery_target"]
        return replay_payload

    def test_manual_full_pipeline_runs_all_stages_and_backfills_statuses(self):
        payload = self._build_publish_ready_pipeline_payload()

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(payload, runs_root=Path(tmpdir))

        self.assertEqual(result["trigger_source"], OrchestratorTriggerSource.MANUAL.value)
        self.assertEqual(result["trigger_context"]["source"], OrchestratorTriggerSource.MANUAL.value)
        self.assertFalse(result["trigger_context"]["is_single_event_rerun"])
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "succeeded")
        self.assertEqual(result["processed_event_ids"], ["evt-stage2-001"])
        self.assertEqual(result["event_statuses"][0]["event_id"], "evt-stage2-001")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "delivered")

    def test_defaults_use_external_writer_and_archive_only(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>默认正式路径调用外部写作。</p></body></html>",
            "report_id": "report-defaults-001",
            "report_filepath": "/tmp/default_report.html",
            "report_relative_path": "outputs/reports/default_report.html",
            "ir_filepath": "/tmp/default_report_ir.json",
            "ir_relative_path": "outputs/reports/ir/default_report_ir.json",
            "state_filepath": "/tmp/default_report_state.json",
            "state_relative_path": "outputs/reports/default_report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        tmpdir = self._workspace_tmpdir("automation-")
        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            result = topic_radar_orchestrate(payload, runs_root=Path(tmpdir))
        self.assertTrue(self._run_output_root(result).exists())
        self.assertTrue((self._run_output_root(result) / "summary.json").exists())

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["entry_resolution"]["write"]["requested_executor"], "external_writer")
        self.assertEqual(result["entry_resolution"]["write"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertEqual(result["entry_resolution"]["delivery"]["target_mode"], "archive_only")
        self.assertEqual(result["entry_resolution"]["delivery"]["channel"], "archive_only")
        self.assertEqual(result["entry_resolution"]["delivery"]["target"], "archive://clawradar")
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_target"], "archive://clawradar")
        self.assertEqual(result["content_bundles"][0]["writer_receipt"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertEqual(result["content_bundles"][0]["writer_receipt"]["report_id"], "report-defaults-001")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "archived")
        self.assertEqual(result["event_statuses"][0]["artifact_summary"]["delivery_receipt_status"], "archived")
        self.assertEqual(result["artifact_summary"]["delivered_count"], 0)
        self.assertTrue(result["delivery_receipt"]["events"][0]["archive_path"])

    def test_formal_launcher_builds_deliverable_defaults(self):
        module_path = Path(__file__).resolve().parents[1] / "run_openclaw_deliverable.py"
        spec = importlib.util.spec_from_file_location("run_openclaw_deliverable", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        args = SimpleNamespace(
            input_mode="user_topic",
            topic="AI 智能体安全治理",
            company="OpenAI",
            track="企业智能体",
            summary="聚焦审计、权限与治理能力。",
            keywords=["治理", "审计"],
            source_ids=["weibo"],
            limit=3,
            request_id="req-launcher-smoke",
            trigger_source="manual",
            execution_mode="full_pipeline",
            runs_root="",
        )

        payload = module._build_payload(args)

        self.assertEqual(payload["entry_options"]["input"]["mode"], "user_topic")
        self.assertEqual(payload["entry_options"]["write"]["executor"], "external_writer")
        self.assertEqual(payload["entry_options"]["delivery"]["target_mode"], "archive_only")
        self.assertEqual(payload["entry_options"]["delivery"]["target"], "archive://clawradar")
        self.assertEqual(payload["entry_options"]["degrade"]["input_unavailable"], "fail")
        self.assertEqual(payload["entry_options"]["degrade"]["write_unavailable"], "fail")
        self.assertEqual(payload["entry_options"]["degrade"]["delivery_unavailable"], "fail")
        self.assertEqual(payload["user_topic"]["topic"], "AI 智能体安全治理")
        self.assertEqual(payload["user_topic"]["keywords"], ["治理", "审计"])
        self.assertNotIn("source_ids", payload["entry_options"]["input"])

        real_source_args = SimpleNamespace(
            input_mode="real_source",
            topic="",
            company="",
            track="",
            summary="",
            keywords=[],
            source_ids=["weibo", "zhihu"],
            limit=5,
            request_id="req-launcher-real-source",
            trigger_source="manual",
            execution_mode="full_pipeline",
            runs_root="",
        )
        real_source_payload = module._build_payload(real_source_args)
        self.assertEqual(real_source_payload["entry_options"]["input"]["source_ids"], ["weibo", "zhihu"])
        self.assertNotIn("user_topic", real_source_payload)
        self.assertEqual(real_source_payload["entry_options"]["write"]["executor"], "external_writer")
        self.assertEqual(real_source_payload["entry_options"]["delivery"]["target_mode"], "archive_only")

    def test_formal_launcher_publish_only_routes_to_publish_existing_output(self):
        module_path = Path(__file__).resolve().parents[1] / "run_openclaw_deliverable.py"
        spec = importlib.util.spec_from_file_location("run_openclaw_deliverable", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        args = SimpleNamespace(
            publish_only=True,
            publish_file="outputs/sample/stages/write/content_bundles.json",
            delivery_channel="wechat",
            delivery_target="wechat://draft-box/openclaw-review",
            target_event_id="evt-stage2-001",
            force_republish=True,
            runs_root="",
        )

        with patch.object(module, "_parse_args", return_value=args):
            with patch.object(module, "publish_existing_output", return_value={"run_status": "completed"}) as mocked_publish:
                with patch.object(module, "topic_radar_orchestrate", side_effect=AssertionError("should not orchestrate when publish_only is enabled")):
                    with patch("builtins.print"):
                        module.main()

        mocked_kwargs = mocked_publish.call_args.kwargs
        self.assertEqual(mocked_kwargs["publish_file"], Path("outputs/sample/stages/write/content_bundles.json"))
        self.assertEqual(mocked_kwargs["delivery_channel"], "wechat")
        self.assertEqual(mocked_kwargs["delivery_target"], "wechat://draft-box/openclaw-review")
        self.assertEqual(mocked_kwargs["target_event_id"], "evt-stage2-001")
        self.assertEqual(mocked_kwargs["force_republish"], True)

    def test_full_pipeline_persists_traceable_archive_and_audit_recovery_objects(self):
        payload = self._build_publish_ready_pipeline_payload()
        delivery_time = "2026-04-09T13:00:00Z"
        event_id = payload["topic_candidates"][0]["event_id"]

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(
            payload,
            delivery_time=delivery_time,
            runs_root=Path(tmpdir),
        )
        archive_dir = self._archive_dir(result, event_id, delivery_time)

        self.assertEqual([item["event_id"] for item in result["normalized_events"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["scored_events"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["content_bundles"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["delivery_receipt"]["events"]], [event_id])
        self.assertEqual(result["artifact_summary"]["normalized_event_count"], 1)
        self.assertEqual(result["artifact_summary"]["scored_event_count"], 1)
        self.assertEqual(result["artifact_summary"]["content_bundle_count"], 1)
        self.assertEqual(result["artifact_summary"]["delivered_count"], 1)
        self.assertTrue(result["event_statuses"][0]["artifact_summary"]["has_content_bundle"])
        self.assertEqual(result["event_statuses"][0]["artifact_summary"]["delivery_receipt_status"], "delivered")

        event_receipt = result["delivery_receipt"]["events"][0]
        scorecard_path = Path(event_receipt["scorecard_path"])
        payload_path = Path(event_receipt["payload_path"])
        message_path = Path(event_receipt["message_path"])
        self.assertEqual(Path(event_receipt["archive_path"]), archive_dir)
        self.assertEqual(scorecard_path, archive_dir / "scorecard.json")
        self.assertEqual(payload_path, archive_dir / "payload_snapshot.json")
        self.assertEqual(message_path, archive_dir / "feishu_message.json")
        self.assertTrue(scorecard_path.exists())
        self.assertTrue(payload_path.exists())
        self.assertTrue(message_path.exists())

        archived_scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        archived_payload = json.loads(payload_path.read_text(encoding="utf-8"))
        archived_message = json.loads(message_path.read_text(encoding="utf-8"))
        self.assertEqual(archived_scorecard["event_id"], event_id)
        self.assertEqual(archived_scorecard["scorecard"], result["scored_events"][0]["scorecard"])
        self.assertEqual(archived_payload["scorecard_path"], event_receipt["scorecard_path"])
        self.assertEqual(archived_payload["request_id"], result["request_id"])
        self.assertEqual(archived_payload["event_id"], event_id)
        self.assertEqual(archived_payload["delivery_request"]["delivery_target"], payload["delivery_target"])
        self.assertEqual(archived_payload["scorecard"], result["scored_events"][0]["scorecard"])
        self.assertEqual(
            archived_payload["content_bundle"],
            result["stage_results"]["deliver"]["content_bundle"],
        )
        self.assertEqual(archived_message["metadata"]["event_id"], event_id)

        self.assertEqual(result["stage_results"]["write"]["content_bundles"][0], result["content_bundles"][0])
        self.assertEqual(
            result["stage_results"]["deliver"]["content_bundle"],
            archived_payload["content_bundle"],
        )
        self.assertEqual(result["stage_results"]["deliver"]["delivery_receipt"], result["delivery_receipt"])

    def test_archive_only_defaults_persist_traceable_archive_and_status(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")
        delivery_time = "2026-04-09T13:00:00Z"
        event_id = payload["topic_candidates"][0]["event_id"]
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>archive_only 默认路径保留可追溯留档。</p></body></html>",
            "report_id": "report-archive-default-001",
            "report_filepath": "/tmp/archive_default_report.html",
            "report_relative_path": "outputs/reports/archive_default_report.html",
            "ir_filepath": "/tmp/archive_default_report_ir.json",
            "ir_relative_path": "outputs/reports/ir/archive_default_report_ir.json",
            "state_filepath": "/tmp/archive_default_report_state.json",
            "state_relative_path": "outputs/reports/archive_default_report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        tmpdir = self._workspace_tmpdir("automation-")
        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            result = topic_radar_orchestrate(
                payload,
                delivery_time=delivery_time,
                runs_root=Path(tmpdir),
            )
        archive_dir = self._archive_dir(result, event_id, delivery_time)

        self.assertEqual([item["event_id"] for item in result["normalized_events"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["scored_events"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["content_bundles"]], [event_id])
        self.assertEqual([item["event_id"] for item in result["delivery_receipt"]["events"]], [event_id])
        self.assertEqual(result["artifact_summary"]["normalized_event_count"], 1)
        self.assertEqual(result["artifact_summary"]["scored_event_count"], 1)
        self.assertEqual(result["artifact_summary"]["content_bundle_count"], 1)
        self.assertEqual(result["artifact_summary"]["delivered_count"], 0)
        self.assertTrue(result["event_statuses"][0]["artifact_summary"]["has_content_bundle"])
        self.assertEqual(result["event_statuses"][0]["artifact_summary"]["delivery_receipt_status"], "archived")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "archived")
        self.assertEqual(result["content_bundles"][0]["writer_receipt"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertEqual(result["content_bundles"][0]["writer_receipt"]["report_id"], "report-archive-default-001")

        event_receipt = result["delivery_receipt"]["events"][0]
        scorecard_path = Path(event_receipt["scorecard_path"])
        payload_path = Path(event_receipt["payload_path"])
        message_path = Path(event_receipt["message_path"])
        self.assertEqual(Path(event_receipt["archive_path"]), archive_dir)
        self.assertEqual(scorecard_path, archive_dir / "scorecard.json")
        self.assertEqual(payload_path, archive_dir / "payload_snapshot.json")
        self.assertEqual(message_path, archive_dir / "feishu_message.json")
        self.assertEqual(event_receipt["status"], "archived")
        self.assertTrue(scorecard_path.exists())
        self.assertTrue(payload_path.exists())
        self.assertTrue(message_path.exists())

        archived_scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
        archived_payload = json.loads(payload_path.read_text(encoding="utf-8"))
        archived_message = json.loads(message_path.read_text(encoding="utf-8"))
        self.assertEqual(archived_scorecard["event_id"], event_id)
        self.assertEqual(archived_scorecard["scorecard"], result["scored_events"][0]["scorecard"])
        self.assertEqual(archived_payload["scorecard_path"], event_receipt["scorecard_path"])
        self.assertEqual(archived_payload["request_id"], result["request_id"])
        self.assertEqual(archived_payload["event_id"], event_id)
        self.assertEqual(archived_payload["delivery_request"]["delivery_channel"], "archive_only")
        self.assertEqual(archived_payload["delivery_request"]["delivery_target"], "archive://clawradar")
        self.assertEqual(archived_payload["scorecard"], result["scored_events"][0]["scorecard"])
        self.assertEqual(
            archived_payload["content_bundle"],
            result["stage_results"]["deliver"]["content_bundle"],
        )
        self.assertEqual(archived_message["metadata"]["event_id"], event_id)
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_target"], "archive://clawradar")

        self.assertEqual(result["stage_results"]["write"]["content_bundles"][0], result["content_bundles"][0])
        self.assertEqual(
            result["stage_results"]["deliver"]["content_bundle"],
            archived_payload["content_bundle"],
        )
        self.assertEqual(result["stage_results"]["deliver"]["delivery_receipt"], result["delivery_receipt"])

    def test_deliver_only_replay_reuses_existing_artifacts_without_reexecuting_upstream_stages(self):
        payload = self._build_publish_ready_pipeline_payload()
        first_delivery_time = "2026-04-09T13:10:00Z"
        second_delivery_time = "2026-04-09T13:11:00Z"

        tmpdir = self._workspace_tmpdir("automation-")
        first_result = topic_radar_orchestrate(
            payload,
            delivery_time=first_delivery_time,
            runs_root=Path(tmpdir),
        )
        replay_payload = self._build_deliver_only_replay_payload(first_result)
        replay_result = topic_radar_orchestrate(
            replay_payload,
            execution_mode="deliver_only",
            delivery_time=second_delivery_time,
            runs_root=Path(tmpdir),
        )

        self.assertEqual(replay_result["run_status"], "completed")
        self.assertEqual(replay_result["final_stage"], "deliver")
        self.assertEqual(replay_result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(replay_result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(replay_result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(replay_result["stage_statuses"]["deliver"]["status"], "succeeded")
        self.assertIsNone(replay_result["stage_results"]["ingest"])
        self.assertIsNone(replay_result["stage_results"]["score"])
        self.assertIsNone(replay_result["stage_results"]["write"])
        self.assertEqual(
            replay_result["content_bundles"],
            [first_result["stage_results"]["deliver"]["content_bundle"]],
        )
        self.assertEqual(replay_result["delivery_receipt"]["events"][0]["event_id"], first_result["processed_event_ids"][0])
        self.assertEqual(
            replay_result["stage_results"]["deliver"]["content_bundle"],
            first_result["stage_results"]["deliver"]["content_bundle"],
        )
        self.assertEqual(
            replay_result["stage_results"]["deliver"]["scorecard"],
            first_result["stage_results"]["deliver"]["scorecard"],
        )

        first_payload_path = Path(first_result["delivery_receipt"]["events"][0]["payload_path"])
        replay_payload_path = Path(replay_result["delivery_receipt"]["events"][0]["payload_path"])
        self.assertNotEqual(first_payload_path, replay_payload_path)
        self.assertTrue(replay_payload_path.exists())

        replay_snapshot = json.loads(replay_payload_path.read_text(encoding="utf-8"))
        self.assertEqual(
            replay_snapshot["content_bundle"],
            first_result["stage_results"]["deliver"]["content_bundle"],
        )
        self.assertEqual(replay_snapshot["scorecard"], first_result["scored_events"][0]["scorecard"])

    def test_crawl_only_returns_crawl_artifact_and_skips_downstream(self):
        payload = self._build_publish_ready_pipeline_payload()

        result = topic_radar_orchestrate(payload, execution_mode="crawl_only")

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "crawl")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["crawl_results"]["input_mode"], "inline_candidates")
        self.assertEqual(result["artifact_summary"]["crawl_candidate_count"], 1)
        self.assertEqual(result["processed_event_ids"], [payload["topic_candidates"][0]["event_id"]])
        self.assertEqual(result["topic_cards"], [])
        self.assertEqual(result["normalized_events"], [])
        self.assertEqual(result["scored_events"], [])
        self.assertEqual(result["content_bundles"], [])

    def test_topics_only_builds_topic_cards_and_stops_before_score(self):
        payload = self._build_publish_ready_pipeline_payload()

        result = topic_radar_orchestrate(payload, execution_mode="topics_only")

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "topics")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["artifact_summary"]["topic_card_count"], 1)
        self.assertEqual(result["topic_cards"][0]["event_id"], payload["topic_candidates"][0]["event_id"])
        self.assertEqual(result["stage_results"]["topics"]["normalized_events"][0]["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_entry_options_user_topic_builds_candidates_into_shared_pipeline(self):
        payload = {
            "request_id": "req-stage11-user-topic",
            "trigger_source": OrchestratorTriggerSource.MANUAL.value,
            "entry_options": {
                "input": {
                    "mode": "user_topic",
                    "topic": "AI 智能体安全治理",
                    "company": "OpenAI",
                    "track": "企业智能体",
                    "keywords": ["治理", "审计"],
                },
                "write": {"enabled": False},
            },
        }
        user_topic_payload = {
            "request_id": payload["request_id"],
            "trigger_source": payload["trigger_source"],
            "topic_candidates": [
                {
                    "event_id": "user-topic-tavily-news-https-example-com-openai-agent-governance",
                    "event_title": "OpenAI 发布智能体治理与审计更新",
                    "company": "OpenAI",
                    "event_time": "2026-04-10T08:00:00Z",
                    "source_url": "https://example.com/openai-agent-governance",
                    "source_type": "tavily:news",
                    "raw_excerpt": "报道提到 OpenAI 推出治理、审计与权限控制更新。",
                    "initial_tags": ["AI 智能体安全治理", "OpenAI", "企业智能体", "治理", "审计"],
                    "confidence": 0.62,
                    "timeline_candidates": [
                        {
                            "timestamp": "2026-04-10T08:05:00Z",
                            "label": "user_topic_search_collected",
                            "summary": "围绕主题检索到相关文章。",
                            "source_url": "https://example.com/openai-agent-governance",
                            "source_type": "tavily:news",
                        }
                    ],
                    "fact_candidates": [
                        {
                            "fact_id": "user-topic-tavily-fact-1",
                            "claim": "OpenAI 发布智能体治理与审计更新",
                            "source_url": "https://example.com/openai-agent-governance",
                            "confidence": 0.66,
                            "citation_excerpt": "报道提到 OpenAI 推出治理、审计与权限控制更新。",
                        }
                    ],
                    "source_metadata": {
                        "provider": "tavily_news",
                        "input_mode": "user_topic",
                        "query": "AI 智能体安全治理 OpenAI 企业智能体 治理 审计 最新新闻",
                        "rank": 1,
                        "source_name": "Tavily News",
                        "collected_at": "2026-04-10T08:05:00Z",
                        "topic": "AI 智能体安全治理",
                        "company": "OpenAI",
                        "track": "企业智能体",
                        "keywords": ["治理", "审计"],
                    },
                    "source_snapshot": {
                        "title": "OpenAI 发布智能体治理与审计更新",
                        "url": "https://example.com/openai-agent-governance",
                        "provider": "tavily_news",
                        "source_type": "tavily:news",
                        "source_name": "Tavily News",
                    },
                }
            ],
            "user_topic_context": {
                "topic": "AI 智能体安全治理",
                "company": "OpenAI",
                "track": "企业智能体",
                "summary": "",
                "keywords": ["治理", "审计"],
                "requested_at": "2026-04-10T08:00:00Z",
                "input_mode": "user_topic",
                "provider": "tavily_news",
                "query": "AI 智能体安全治理 OpenAI 企业智能体 治理 审计 最新新闻",
                "requested_source_ids": ["topic_query"],
                "applied_source_ids": ["tavily_news"],
                "failed_sources": [],
                "candidate_count": 1,
                "collected_at": "2026-04-10T08:05:00Z",
            },
        }

        with patch(
            "clawradar.orchestrator.load_user_topic_payload",
            return_value=(deepcopy(user_topic_payload), deepcopy(user_topic_payload["user_topic_context"])),
        ):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["entry_resolution"]["input"]["requested_mode"], "user_topic")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "user_topic")
        self.assertTrue(result["entry_resolution"]["input"]["user_topic_loaded"])
        self.assertEqual(result["entry_resolution"]["input"]["user_topic_provider"], "tavily_news")
        self.assertEqual(result["entry_resolution"]["input"]["user_topic_candidate_count"], 1)
        self.assertEqual(result["crawl_results"]["input_mode"], "user_topic")
        self.assertEqual(result["artifact_summary"]["crawl_candidate_count"], 1)
        self.assertEqual(result["artifact_summary"]["topic_card_count"], 1)
        self.assertEqual(result["crawl_results"]["user_topic_context"]["provider"], "tavily_news")
        self.assertEqual(result["crawl_results"]["user_topic_context"]["applied_source_ids"], ["tavily_news"])
        self.assertEqual(result["topic_cards"][0]["source_type"], "tavily:news")
        self.assertEqual(result["topic_cards"][0]["source_url"], "https://example.com/openai-agent-governance")
        self.assertTrue(result["topic_cards"][0]["event_id"].startswith("user-topic-tavily-news-"))
        self.assertEqual(result["stage_results"]["score"]["scored_events"][0]["trace"]["source_type"], "tavily:news")

    def test_entry_options_inline_topic_cards_scores_without_reingest(self):
        payload = self._build_publish_ready_pipeline_payload()
        topics_result = topic_radar_orchestrate(payload, execution_mode="topics_only")
        replay_payload = {
            "request_id": payload["request_id"],
            "trigger_source": payload["trigger_source"],
            "topic_cards": deepcopy(topics_result["topic_cards"]),
            "entry_options": {
                "input": {"mode": "inline_topic_cards"},
                "write": {"enabled": False},
            },
        }

        result = topic_radar_orchestrate(replay_payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "succeeded")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "inline_topic_cards")
        self.assertIsNone(result["stage_results"]["ingest"])
        self.assertEqual(result["topic_cards"][0]["event_id"], payload["topic_candidates"][0]["event_id"])
        self.assertEqual(result["scored_events"][0]["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_write_only_reuses_existing_scored_events_and_stops_before_delivery(self):
        payload = self._build_publish_ready_pipeline_payload()
        score_result = topic_radar_orchestrate(payload, execution_mode="score_only")
        write_payload = {
            "request_id": score_result["request_id"],
            "trigger_source": score_result["trigger_source"],
            "scored_events": deepcopy(score_result["scored_events"]),
            "entry_options": {
                "write": {"executor": "openclaw_builtin"},
            },
        }

        result = topic_radar_orchestrate(write_payload, execution_mode="write_only")

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "write")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertIsNone(result["stage_results"]["score"])
        self.assertEqual(result["content_bundles"][0]["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_resume_from_scored_events_restarts_at_write_and_delivers(self):
        payload = self._build_publish_ready_pipeline_payload()
        score_result = topic_radar_orchestrate(payload, execution_mode="score_only")
        resume_payload = {
            "request_id": score_result["request_id"],
            "trigger_source": score_result["trigger_source"],
            "scored_events": deepcopy(score_result["scored_events"]),
            "delivery_channel": "feishu",
            "delivery_target": "feishu://openclaw/p0-review",
            "entry_options": {
                "input": {"mode": "inline_normalized"},
                "write": {"executor": "openclaw_builtin"},
                "delivery": {
                    "target_mode": "feishu",
                    "channel": "feishu",
                    "target": "feishu://openclaw/p0-review",
                },
                "degrade": {"input_unavailable": "fallback_inline_normalized"},
            },
        }

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(
            resume_payload,
            execution_mode="resume",
            runs_root=Path(tmpdir),
        )

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "succeeded")
        self.assertEqual(result["content_bundles"][0]["event_id"], payload["topic_candidates"][0]["event_id"])
        self.assertEqual(result["delivery_receipt"]["events"][0]["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_resume_from_content_bundles_restarts_at_deliver(self):
        payload = self._build_publish_ready_pipeline_payload()
        score_result = topic_radar_orchestrate(payload, execution_mode="score_only")
        write_result = topic_radar_orchestrate(
            {
                "request_id": score_result["request_id"],
                "trigger_source": score_result["trigger_source"],
                "scored_events": deepcopy(score_result["scored_events"]),
                "entry_options": {
                    "write": {"executor": "openclaw_builtin"},
                },
            },
            execution_mode="write_only",
        )
        resume_payload = {
            "request_id": write_result["request_id"],
            "trigger_source": write_result["trigger_source"],
            "scored_events": deepcopy(write_result["scored_events"]),
            "content_bundles": deepcopy(write_result["content_bundles"]),
            "delivery_channel": "feishu",
            "delivery_target": "feishu://openclaw/p0-review",
            "entry_options": {
                "input": {"mode": "inline_normalized"},
                "write": {"executor": "openclaw_builtin"},
                "delivery": {
                    "target_mode": "feishu",
                    "channel": "feishu",
                    "target": "feishu://openclaw/p0-review",
                },
                "degrade": {"input_unavailable": "fallback_inline_normalized"},
            },
        }

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(
            resume_payload,
            execution_mode="resume",
            runs_root=Path(tmpdir),
        )

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["stage_statuses"]["crawl"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["topics"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "succeeded")
        self.assertEqual(result["content_bundles"][0]["event_id"], payload["topic_candidates"][0]["event_id"])
        self.assertEqual(result["delivery_receipt"]["events"][0]["event_id"], payload["topic_candidates"][0]["event_id"])

    def test_cron_score_only_preserves_trigger_source(self):
        payload = self._load_fixture("clawradar_score_need_more_evidence_input.json")

        result = topic_radar_orchestrate(payload, execution_mode="score_only")

        self.assertEqual(result["trigger_source"], OrchestratorTriggerSource.CRON.value)
        self.assertEqual(result["trigger_context"]["target_event_ids"], [])
        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")

    def test_single_event_rerun_filters_only_target_event_without_cross_talk(self):
        payload = self._build_two_event_pipeline_payload()
        original_payload = deepcopy(payload)
        payload["target_event_id"] = "evt-stage5-002"

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(payload, runs_root=Path(tmpdir))

        self.assertEqual(result["trigger_source"], OrchestratorTriggerSource.SINGLE_EVENT_RERUN.value)
        self.assertTrue(result["trigger_context"]["is_single_event_rerun"])
        self.assertEqual(result["requested_event_ids"], ["evt-stage5-002"])
        self.assertEqual(result["processed_event_ids"], ["evt-stage5-002"])
        self.assertEqual([item["event_id"] for item in result["normalized_events"]], ["evt-stage5-002"])
        self.assertEqual([item["event_id"] for item in result["scored_events"]], ["evt-stage5-002"])
        self.assertEqual([item["event_id"] for item in result["content_bundles"]], ["evt-stage5-002"])
        self.assertEqual([item["event_id"] for item in result["event_statuses"]], ["evt-stage5-002"])
        self.assertEqual(len(original_payload["topic_candidates"]), 2)

    def test_ingest_rejection_marks_downstream_stages_as_skipped(self):
        payload = self._load_fixture("clawradar_minimal_input.json")
        del payload["topic_candidates"][0]["source_url"]

        result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "rejected")
        self.assertEqual(result["final_stage"], "ingest")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "failed")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["event_id"], "evt-stage1-001")
        self.assertEqual(result["event_statuses"][0]["ingest_status"], "rejected")
        self.assertEqual(result["event_statuses"][0]["score_status"], "skipped")

    def test_score_failure_stops_write_and_deliver(self):
        payload = self._build_publish_ready_pipeline_payload()

        with patch("clawradar.orchestrator.score_topic_candidates", side_effect=RuntimeError("score crashed")):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "failed")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["score_status"], "failed")
        self.assertEqual(result["event_statuses"][0]["write_status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "skipped")

    def test_non_publish_ready_skips_write_and_deliver(self):
        payload = self._build_non_publish_ready_pipeline_payload()

        result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["decision_status"], ScoreDecisionStatus.NEED_MORE_EVIDENCE.value)
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["decision_status"], ScoreDecisionStatus.NEED_MORE_EVIDENCE.value)
        self.assertEqual(result["event_statuses"][0]["write_status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "skipped")

    def test_write_failure_marks_publish_ready_event_and_skips_deliver(self):
        payload = self._build_publish_ready_pipeline_payload()
        failing_write_result = {
            "request_id": payload["request_id"],
            "trigger_source": payload["trigger_source"],
            "run_status": WriteRunStatus.FAILED.value,
            "decision_status": ScoreDecisionStatus.PUBLISH_READY.value,
            "operation": WriteOperation.GENERATE.value,
            "content_bundles": [],
            "errors": [
                {
                    "code": "writer_unavailable",
                    "message": "writer unavailable",
                    "missing_fields": [],
                }
            ],
        }

        with patch("clawradar.orchestrator.topic_radar_write", return_value=failing_write_result):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["final_stage"], "write")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "failed")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["event_statuses"][0]["write_status"], "failed")
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "skipped")

    def test_delivery_failure_is_written_back_to_result(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["simulate_delivery_failure"] = True

        tmpdir = self._workspace_tmpdir("automation-")
        result = topic_radar_orchestrate(payload, runs_root=Path(tmpdir))

        self.assertEqual(result["run_status"], "delivery_failed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "failed")
        self.assertEqual(result["artifact_summary"]["delivery_failed_count"], 1)
        self.assertEqual(result["delivery_receipt"]["failed_count"], 1)
        self.assertEqual(result["event_statuses"][0]["deliver_status"], "failed")
        self.assertTrue(result["event_statuses"][0]["errors"])

    def test_entry_options_input_mode_overrides_legacy_fields_and_records_resolution(self):
        payload = self._build_publish_ready_pipeline_payload()
        normalized_payload = normalize_ingest_payload(payload)
        payload["normalized_events"] = normalized_payload["normalized_events"]
        payload["entry_options"] = {
            "input": {"mode": "inline_normalized"},
            "write": {"enabled": False},
        }

        result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "skipped")
        self.assertIsNone(result["stage_results"]["ingest"])
        self.assertEqual(result["entry_resolution"]["input"]["requested_mode"], "inline_normalized")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "inline_normalized")
        self.assertEqual(result["entry_resolution"]["input"]["selection_source"], "entry_options")
        self.assertFalse(result["entry_resolution"]["degrade"]["fallback_triggered"])

    def test_entry_options_write_disabled_stops_after_score(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"enabled": False},
        }

        result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "skipped")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "skipped")
        self.assertEqual(result["entry_resolution"]["write"]["enabled"], False)
        self.assertEqual(result["content_bundles"], [])
        self.assertIsNone(result["delivery_receipt"])

    def test_entry_options_archive_only_delivery_does_not_call_feishu_delivery(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "openclaw_builtin"},
            "delivery": {
                "target_mode": "archive_only",
                "target": "archive://openclaw-p0-tests",
            }
        }
        delivery_time = "2026-04-09T13:30:00Z"
        event_id = payload["topic_candidates"][0]["event_id"]

        tmpdir = self._workspace_tmpdir("automation-")
        with patch("clawradar.orchestrator.topic_radar_deliver", side_effect=AssertionError("should not call topic_radar_deliver")):
            result = topic_radar_orchestrate(
                payload,
                delivery_time=delivery_time,
                runs_root=Path(tmpdir),
            )

        archive_dir = self._archive_dir(result, event_id, delivery_time)
        event_receipt = result["delivery_receipt"]["events"][0]

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["stage_statuses"]["deliver"]["status"], "succeeded")
        self.assertEqual(result["entry_resolution"]["delivery"]["target_mode"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_target"], "archive://openclaw-p0-tests")
        self.assertEqual(result["delivery_receipt"]["archive_root"], (self._run_output_root(result) / "recovery").resolve().as_posix())
        self.assertEqual(event_receipt["status"], "archived")
        self.assertTrue(event_receipt["archive_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}"))
        self.assertTrue(event_receipt["scorecard_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/scorecard.json"))
        self.assertTrue(event_receipt["payload_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/payload_snapshot.json"))
        self.assertTrue(event_receipt["message_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/feishu_message.json"))
        self.assertTrue(Path(event_receipt["scorecard_path"]).exists())
        self.assertTrue(Path(event_receipt["payload_path"]).exists())
        self.assertTrue(Path(event_receipt["message_path"]).exists())

        archived_scorecard = json.loads(Path(event_receipt["scorecard_path"]).read_text(encoding="utf-8"))
        archived_payload = json.loads(Path(event_receipt["payload_path"]).read_text(encoding="utf-8"))
        self.assertEqual(archived_scorecard["event_id"], event_id)
        self.assertEqual(archived_payload["scorecard_path"], event_receipt["scorecard_path"])
        self.assertEqual(archived_payload["delivery_request"]["delivery_channel"], "archive_only")
        self.assertEqual(archived_payload["delivery_request"]["delivery_target"], "archive://openclaw-p0-tests")
        self.assertEqual(archived_payload["delivery_request"]["delivery_time"], delivery_time)

    def test_entry_options_real_source_success_enters_existing_chain(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "input": {"mode": "real_source"},
            "write": {"enabled": False},
        }
        adapter_payload = self._build_real_source_adapter_payload()

        with patch(
            "clawradar.orchestrator.load_real_source_payload",
            return_value=(adapter_payload, deepcopy(adapter_payload["real_source_context"])),
        ):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["stage_statuses"]["ingest"]["status"], "succeeded")
        self.assertEqual(result["stage_statuses"]["score"]["status"], "succeeded")
        self.assertEqual(result["entry_resolution"]["input"]["requested_mode"], "real_source")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "real_source")
        self.assertTrue(result["entry_resolution"]["input"]["real_source_loaded"])
        self.assertEqual(result["entry_resolution"]["input"]["real_source_provider"], "mindspider_broad_topic_today_news")
        self.assertEqual(result["entry_resolution"]["input"]["real_source_candidate_count"], 1)
        self.assertEqual(result["entry_resolution"]["input"]["real_source_applied_source_ids"], ["weibo"])
        self.assertFalse(result["entry_resolution"]["degrade"]["fallback_triggered"])
        self.assertEqual(result["normalized_events"][0]["event_id"], "real-source-weibo-123")
        self.assertEqual(result["normalized_events"][0]["source_metadata"]["source_id"], "weibo")
        self.assertEqual(result["stage_results"]["ingest"]["real_source_context"]["provider"], "mindspider_broad_topic_today_news")
        self.assertEqual(result["stage_results"]["score"]["real_source_context"]["applied_source_ids"], ["weibo"])

    def test_entry_options_real_source_falls_back_by_strategy(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "input": {"mode": "real_source"},
            "write": {"enabled": False},
            "degrade": {"input_unavailable": "fallback_inline_candidates"},
        }

        with patch(
            "clawradar.orchestrator.load_real_source_payload",
            side_effect=RealSourceUnavailableError("MindSpider unavailable"),
        ):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "score")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "inline_candidates")
        self.assertFalse(result["entry_resolution"]["input"]["real_source_loaded"])
        self.assertTrue(result["entry_resolution"]["degrade"]["fallback_triggered"])
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["category"], "input")
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["requested"], "real_source")
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["applied"], "inline_candidates")

    def test_entry_options_real_source_without_degrade_fails_explicitly(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "input": {"mode": "real_source"},
        }

        with patch(
            "clawradar.orchestrator.load_real_source_payload",
            side_effect=RealSourceUnavailableError("MindSpider unavailable"),
        ):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["final_stage"], "orchestrator")
        self.assertEqual(result["errors"][0]["code"], OrchestratorErrorCode.INPUT_MODE_UNAVAILABLE.value)
        self.assertIn("MindSpider unavailable", result["errors"][0]["message"])
        self.assertEqual(result["entry_resolution"]["input"]["requested_mode"], "real_source")
        self.assertEqual(result["entry_resolution"]["input"]["effective_mode"], "real_source")
        self.assertFalse(result["entry_resolution"]["input"]["real_source_loaded"])

    def test_entry_options_external_writer_succeeds_when_writer_returns_artifacts(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "external_writer"},
            "delivery": {"enabled": False},
        }
        fake_result = {
            "html_content": "<html><body><h1>综合报告</h1><p>阶段八外部写作成功。</p></body></html>",
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

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "write")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "succeeded")
        self.assertEqual(result["entry_resolution"]["write"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertFalse(result["entry_resolution"]["degrade"]["fallback_triggered"])
        self.assertEqual(result["stage_results"]["write"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertEqual(len(result["stage_results"]["write"]["writer_receipts"]), 1)
        self.assertEqual(result["content_bundles"][0]["writer_receipt"]["report_id"], "report-stage8-001")
        self.assertEqual(
            result["content_bundles"][0]["report_artifacts"]["state_relative_path"],
            "outputs/reports/report_state.json",
        )

    def test_entry_options_external_writer_falls_back_to_builtin(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "external_writer"},
            "delivery": {"enabled": False},
            "degrade": {"write_unavailable": "fallback_openclaw_builtin"},
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                raise RuntimeError("writer boom")

        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "write")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "succeeded")
        self.assertEqual(result["entry_resolution"]["write"]["executor"], WriteExecutor.OPENCLAW_BUILTIN.value)
        self.assertTrue(result["entry_resolution"]["degrade"]["fallback_triggered"])
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["category"], "write")
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["requested"], "external_writer")
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["applied"], "openclaw_builtin")
        self.assertEqual(result["stage_results"]["write"]["executor"], WriteExecutor.OPENCLAW_BUILTIN.value)
        self.assertEqual(result["content_bundles"][0]["event_id"], "evt-stage2-001")

    def test_entry_options_external_writer_without_degrade_fails_explicitly(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "external_writer"},
            "delivery": {"enabled": False},
        }

        with patch(
            "clawradar.writing._get_report_engine_agent_factory",
            side_effect=ImportError("ReportEngine unavailable"),
        ):
            result = topic_radar_orchestrate(payload)

        self.assertEqual(result["run_status"], "failed")
        self.assertEqual(result["final_stage"], "write")
        self.assertEqual(result["stage_statuses"]["write"]["status"], "failed")
        self.assertEqual(result["errors"][0]["code"], WriteErrorCode.WRITER_UNAVAILABLE.value)
        self.assertEqual(result["entry_resolution"]["write"]["requested_executor"], "external_writer")
        self.assertEqual(result["entry_resolution"]["write"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)
        self.assertEqual(result["stage_results"]["write"]["executor"], WriteExecutor.EXTERNAL_WRITER.value)

    def test_entry_options_delivery_unavailable_falls_back_to_archive_only(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "openclaw_builtin"},
            "delivery": {
                "target_mode": "feishu",
                "channel": "webhook",
                "target": "webhook://openclaw/p0-review",
            },
            "degrade": {"delivery_unavailable": "archive_only"},
        }
        delivery_time = "2026-04-09T13:35:00Z"
        event_id = payload["topic_candidates"][0]["event_id"]

        tmpdir = self._workspace_tmpdir("automation-")
        with patch("clawradar.orchestrator.topic_radar_deliver", side_effect=AssertionError("should fallback before topic_radar_deliver")):
            result = topic_radar_orchestrate(
                payload,
                delivery_time=delivery_time,
                runs_root=Path(tmpdir),
            )

        archive_dir = self._archive_dir(result, event_id, delivery_time)
        event_receipt = result["delivery_receipt"]["events"][0]

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["entry_resolution"]["delivery"]["target_mode"], "archive_only")
        self.assertEqual(result["entry_resolution"]["delivery"]["channel"], "archive_only")
        self.assertTrue(result["entry_resolution"]["degrade"]["fallback_triggered"])
        self.assertEqual(result["entry_resolution"]["degrade"]["fallbacks"][0]["category"], "delivery")
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_target"], "webhook://openclaw/p0-review")
        self.assertEqual(event_receipt["status"], "archived")
        self.assertTrue(event_receipt["archive_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}"))
        self.assertTrue(event_receipt["scorecard_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/scorecard.json"))
        self.assertTrue(event_receipt["payload_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/payload_snapshot.json"))
        self.assertTrue(event_receipt["message_path"].endswith(f"{event_id}/deliver/{self._archive_slug(delivery_time)}/feishu_message.json"))
        self.assertTrue(Path(event_receipt["scorecard_path"]).exists())
        self.assertTrue(Path(event_receipt["payload_path"]).exists())
        self.assertTrue(Path(event_receipt["message_path"]).exists())

        archived_scorecard = json.loads(Path(event_receipt["scorecard_path"]).read_text(encoding="utf-8"))
        archived_payload = json.loads(Path(event_receipt["payload_path"]).read_text(encoding="utf-8"))
        self.assertEqual(archived_scorecard["event_id"], event_id)
        self.assertEqual(archived_payload["scorecard_path"], event_receipt["scorecard_path"])
        self.assertEqual(archived_payload["delivery_request"]["delivery_channel"], "archive_only")
        self.assertEqual(archived_payload["delivery_request"]["delivery_target"], "webhook://openclaw/p0-review")
        self.assertEqual(archived_payload["delivery_request"]["delivery_time"], delivery_time)

    def test_entry_options_wechat_reaches_delivery_stage(self):
        payload = self._build_publish_ready_pipeline_payload()
        payload["entry_options"] = {
            "write": {"executor": "openclaw_builtin"},
            "delivery": {
                "target_mode": "wechat",
                "target": "wechat://draft-box/openclaw-review",
            },
        }

        fake_deliver_result = {
            "request_id": payload["request_id"],
            "trigger_source": payload["trigger_source"],
            "event_id": payload["topic_candidates"][0]["event_id"],
            "run_status": "completed",
            "decision_status": "publish_ready",
            "normalized_events": [],
            "timeline": [],
            "evidence_pack": {},
            "scorecard": {},
            "content_bundle": {},
            "delivery_receipt": {
                "delivery_time": "2026-04-09T13:40:00Z",
                "delivery_channel": "wechat",
                "delivery_target": "wechat://draft-box/openclaw-review",
                "archive_root": ".tmp/test_runs",
                "failed_count": 0,
                "events": [
                    {
                        "request_id": payload["request_id"],
                        "event_id": payload["topic_candidates"][0]["event_id"],
                        "decision_status": "publish_ready",
                        "delivery_time": "2026-04-09T13:40:00Z",
                        "delivery_channel": "wechat",
                        "delivery_target": "wechat://draft-box/openclaw-review",
                        "archive_path": "archive-path",
                        "scorecard_path": "scorecard-path",
                        "payload_path": "payload-path",
                        "message_path": "wechat_delivery_message.json",
                        "status": "delivered",
                        "failure_info": None,
                    }
                ],
            },
            "errors": [],
        }

        with patch("clawradar.orchestrator.topic_radar_deliver", return_value=fake_deliver_result) as mocked_deliver:
            result = topic_radar_orchestrate(payload, delivery_time="2026-04-09T13:40:00Z")

        self.assertEqual(result["run_status"], "completed")
        self.assertEqual(result["final_stage"], "deliver")
        self.assertEqual(result["entry_resolution"]["delivery"]["target_mode"], "wechat")
        self.assertEqual(result["entry_resolution"]["delivery"]["channel"], "wechat")
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "wechat")

        mocked_args, mocked_kwargs = mocked_deliver.call_args
        delivered_payload = mocked_args[0]
        self.assertEqual(delivered_payload["delivery_channel"], "wechat")
        self.assertEqual(delivered_payload["delivery_target"], "wechat://draft-box/openclaw-review")
        self.assertEqual(mocked_kwargs["channel"], "wechat")
        self.assertEqual(mocked_kwargs["target"], "wechat://draft-box/openclaw-review")


    def test_missing_delivery_channel_defaults_to_archive_only_without_external_delivery(self):
        payload = self._load_fixture("clawradar_score_publish_ready_input.json")
        fake_result = {
            "html_content": "<html><body><h1>default local archive</h1><p>delivery channel absent.</p></body></html>",
            "report_id": "report-default-local-001",
            "report_filepath": "/tmp/default_local_report.html",
            "report_relative_path": "outputs/reports/default_local_report.html",
            "ir_filepath": "/tmp/default_local_report_ir.json",
            "ir_relative_path": "outputs/reports/ir/default_local_report_ir.json",
            "state_filepath": "/tmp/default_local_report_state.json",
            "state_relative_path": "outputs/reports/default_local_report_state.json",
        }

        class FakeAgent:
            def generate_report(self, **kwargs):
                self.kwargs = kwargs
                return fake_result

        tmpdir = self._workspace_tmpdir("automation-default-local-")
        with patch("clawradar.writing._get_report_engine_agent_factory", return_value=lambda: FakeAgent()):
            with patch("clawradar.orchestrator.topic_radar_deliver", side_effect=AssertionError("should remain local when delivery channel is absent")):
                result = topic_radar_orchestrate(payload, runs_root=Path(tmpdir))

        self.assertEqual(result["entry_resolution"]["delivery"]["target_mode"], "archive_only")
        self.assertEqual(result["entry_resolution"]["delivery"]["channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_channel"], "archive_only")
        self.assertEqual(result["delivery_receipt"]["delivery_target"], "archive://clawradar")
        self.assertEqual(result["delivery_receipt"]["events"][0]["status"], "archived")

if __name__ == "__main__":
    unittest.main()
