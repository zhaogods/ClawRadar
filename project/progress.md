# ClawRadar 剥壳进度日志

## 2026-04-19

- 已确认四引擎整体保留策略：`MindSpider`、`QueryEngine`、`MediaEngine`、`ReportEngine` 继续完整保留，不做内部子功能裁剪。
- 已完成旧平台外壳删除，`radar_engines` 当前只保留四个核心引擎与共享基础设施。
- 已完成 `README.md` 对齐，明确 `clawradar/` 与 `radar_engines/` 的边界关系。
- 已完成 `real_source` / `user_topic` P0 增强：
  - `real_source` 默认源扩展为 `weibo + zhihu + 36kr`
  - `real_source` 默认上限提升为 `10`
  - `real_source` 改为多源轮转合并
  - `user_topic` 改为 Tavily / Bocha / Anspire 多 Provider 融合
  - `user_topic_context.applied_source_ids` 记录全部实际参与 Provider
- 已新增 `tests/test_clawradar_real_source_p0.py`，并通过 `python -m unittest tests.test_clawradar_real_source_p0 -v` 验证 3 个 P0 定向测试全部通过。
- 已修正 `project/reports/` 误推送问题：远端已移除，`.gitignore` 已增加 `project/reports/`，本地目录继续保留。

## 2026-04-19 下一阶段规划

- 已将任务阶段推进到 phase 3：`边界固化与 P1 规划`。
- 下一阶段不再继续做大规模目录删除。
- 下一阶段主目标调整为：
  - 固化四引擎最小运行边界
  - 增强 `real_source` / `user_topic` 的 P1 能力
  - 评估 `ReportEngine` 最小依赖图
  - 为后续精细瘦身建立依赖依据
## 2026-04-21 WeChat Image Planning

- Reviewed current WeChat image pipeline and confirmed that real `<img>` upload already works, while `canvas` charts are not handled because the publish path does not execute report-page JavaScript.
- Inspected `ReportEngine` renderers and found two useful upstream facts:
  - chart widgets are emitted as `canvas + chart-fallback` in `html_renderer.py`
  - static chart export capability already exists in `renderers/chart_to_svg.py`
- Recorded image strategy options and a preferred implementation order: keep `fallback_table` default, retain `<img>` upload, then explore static chart generation via `chart_to_svg.py` before considering headless-browser screenshots.

## 2026-04-21 ReportEngine Chapter Structure Validation

- Read `project/reports/report_engine_list_structure_bug_report.md` and aligned the expected fix points with current code in `chapter_generation_node.py`, `validator.py`, `prompts.py`, and `tests/test_report_engine_chapter_structure.py`.
- First test run failed with `ModuleNotFoundError: No module named 'ReportEngine'` because the package currently expects `PYTHONPATH` to include `radar_engines/`.
- Re-ran with `PYTHONPATH=F:/02_code/ClawRadar/radar_engines` and `python -m unittest tests.test_report_engine_chapter_structure -v`; all 4 tests passed.
- Ran `python -m py_compile` on the modified ReportEngine files and the new test file; compilation passed.
- Verification conclusion: the list-item/heading boundary fix is implemented and passes targeted regression checks, but direct test execution currently depends on the repo's existing import-path convention.

## 2026-04-24 Structured Summary Handoff

- 已在 `radar_engines/ReportEngine/prompts/prompts.py` 为 `SYSTEM_PROMPT_DOCUMENT_LAYOUT` 新增 `summaryPack` 输出契约，并把 `generic` / `short` / `wechat` / `sourceHint` 写入 `document_layout_output_schema`。
- 已在 `radar_engines/ReportEngine/nodes/document_layout_node.py` 增加 `summaryPack` 解析与标准化；当上游缺失时，会退回 `hero.summary` 生成最小可用摘要包，且保持纯文本。
- 已在 `radar_engines/ReportEngine/agent.py` 将 `summaryPack` 写入 `manifest_meta`，并通过 `report_metadata` 一并透传到 external writer 返回结果。
- 已在 `clawradar/writing.py` 新增对结构化摘要的优先消费：external_writer 现在优先使用 `report_metadata.summaryPack` 生成 `content_bundle.summary.text` 与 `summary.channel_variants.wechat`，HTML preview 仅保留给 `draft.body_markdown` 和最后兜底。
- 已在 `clawradar/publishers/wechat/service.py` 新增 `_resolve_summary_text()`；微信发布现在优先读取 `content_bundle.summary.channel_variants.wechat`，再退回 `summary.text`。
- 已新增回归测试：
  - `tests/test_clawradar_writing.py::test_external_writer_prefers_structured_summary_pack_and_exposes_wechat_variant`
  - `tests/test_clawradar_delivery.py::test_wechat_delivery_prefers_channel_specific_summary_variant`
  - `tests/test_report_engine_chapter_structure.py::ReportEngineDocumentLayoutTestCase`
  - `tests/test_report_engine_chapter_structure.py::ReportEngineAgentMetadataTestCase`
- 运行 `python -m unittest tests.test_clawradar_writing.ClawRadarWritingTestCase.test_external_writer_prefers_structured_summary_pack_and_exposes_wechat_variant tests.test_clawradar_writing.ClawRadarWritingTestCase.test_external_writer_preview_ignores_embedded_scripts_in_summary_and_draft tests.test_clawradar_delivery.ClawRadarDeliveryTestCase.test_wechat_delivery_prefers_channel_specific_summary_variant tests.test_clawradar_delivery.ClawRadarDeliveryTestCase.test_wechat_delivery_retries_digest_once_on_45004_and_succeeds tests.test_clawradar_delivery.ClawRadarDeliveryTestCase.test_wechat_delivery_reports_failed_digests_when_45004_retry_still_fails` 通过（5 tests）。
- 额外运行 `PYTHONPATH=F:/02_code/ClawRadar/radar_engines python -m unittest tests.test_report_engine_chapter_structure.ReportEngineDocumentLayoutTestCase tests.test_clawradar_writing.ClawRadarWritingTestCase.test_external_writer_prefers_structured_summary_pack_and_exposes_wechat_variant tests.test_clawradar_delivery.ClawRadarDeliveryTestCase.test_wechat_delivery_prefers_channel_specific_summary_variant` 通过（4 tests）。
- 额外运行 `PYTHONPATH=F:/02_code/ClawRadar/radar_engines python -m unittest tests.test_report_engine_chapter_structure.ReportEngineAgentMetadataTestCase` 通过（1 test），确认 `generate_report()` 返回的 `report_metadata.summaryPack` 与 `manifest_meta` 一致。
- 运行 `python -m py_compile` 校验本次修改文件通过。

## 2026-04-24 Summary Variant Persistence Verification

- 已为 `tests/test_publish_only.py` 的 content_bundles / payload_snapshot / modern output fixtures 补入 `summary.channel_variants.wechat`，并新增断言确认 publish-only 重放不会剥离该字段。
- 已为 `tests/test_clawradar_automation.py` 的 archive-only 与 deliver-only replay 场景补入 `summary.channel_variants.wechat` 透传断言，确认归档与重放链路都保留了微信摘要变体。
- 已修正 `deliver_only` 回放测试的前置条件：需要用 `external_writer` 生成含 `channel_variants` 的 content bundle，builtin writer 路径不适合验证该字段。

- 已补 `clawradar/publish_only.py:_content_hash()`：重复发布判重现在同时纳入 `summary.text` 与 `summary.channel_variants.wechat`，避免微信渠道摘要变体变更时仍被误判为旧内容。
- 已补 `publish_only` 审计记录：`records.jsonl` / `publish_record` 现在会显式保存 `summary_text` 与 `summary_wechat`，便于后续排查 publish-only 走的到底是哪份渠道摘要。
- 已在 `tests/test_publish_only.py` 增加对 `publish_record.summary_text` / `publish_record.summary_wechat` 的断言，覆盖 payload snapshot 与微信摘要变体变更重发场景。
- 运行 `python -m unittest tests.test_publish_only.PublishOnlyTestCase` 通过（5 tests）。
