# 阶段十历史证据清单

## 1. 证据链目标
本清单用于说明阶段十已经具备的历史演示与验收证据，且只记录已实际生成、可本地核对的产物，不把未运行内容写成既成事实。

本清单的定位始终是历史基线证据说明，不是本轮新增实现或后续产品化目标已经完成的证明。

## 2. 本次采用的最小证据链
- 统一入口：[`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)
- 输入样本：[`project_protocol/stage10/generated/demo_input.json`](project_protocol/stage10/generated/demo_input.json)
- 输入来源基底：[`tests/fixtures/openclaw_p0_score_publish_ready_input.json`](tests/fixtures/openclaw_p0_score_publish_ready_input.json)
- 写作执行：`entry_options.write.executor=openclaw_builtin`
- 交付模式：`entry_options.delivery.target_mode=archive_only`
- 留档根目录：[`project_protocol/stage10/demo_runs/`](project_protocol/stage10/demo_runs/)
- 统一结果快照：[`project_protocol/stage10/generated/demo_result.json`](project_protocol/stage10/generated/demo_result.json)

## 3. 已实际生成的核心证据
### 3.1 统一入口输入样本
- 文件：[`project_protocol/stage10/generated/demo_input.json`](project_protocol/stage10/generated/demo_input.json)
- 事实：该文件由历史阶段十真实运行前写出，记录 `request_id=req-stage10-demo-001`、`entry_options.delivery.target_mode=archive_only`、`entry_options.write.executor=openclaw_builtin` 等演示输入。

### 3.2 统一入口真实运行结果快照
- 文件：[`project_protocol/stage10/generated/demo_result.json`](project_protocol/stage10/generated/demo_result.json)
- 事实：该文件由统一入口真实执行后写出，结果显示：
  - `run_status=completed`
  - `final_stage=deliver`
  - `decision_status=publish_ready`
  - `entry_resolution.delivery.target_mode=archive_only`
  - `entry_resolution.delivery.target=archive://stage10-demo`
  - `stage_statuses.deliver.status=succeeded`
  - `event_statuses[0].deliver_status=archived`

### 3.3 本地留档快照
- 文件：[`project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/payload_snapshot.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/payload_snapshot.json)
- 事实：该快照真实保留 `normalized_events`、`timeline`、`evidence_pack`、`scorecard`、`content_bundle` 与 `delivery_request`，用于核对历史主链路产物与交付请求。

### 3.4 审核消息模板快照
- 文件：[`project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/feishu_message.json`](project_protocol/stage10/demo_runs/req-stage10-demo-001/evt-stage2-001/deliver/2026-04-12T06-46-00Z/feishu_message.json)
- 事实：该文件真实写出审核友好的摘要消息模板；虽然本次交付目标为 `archive_only`，但消息体快照仍被留档，证明阶段十历史最小交付面已形成可回放审核材料。

## 4. 该证据链实际证明了什么
- 已证明统一入口可以在本地稳定跑通 ingest → score → write → deliver 主链路。
- 已证明 `entry_options` 会被统一解析并写回 `entry_resolution`。
- 已证明 `archive_only` 不是名义语义，而会真实落地本地留档与可追溯回执。
- 已证明阶段十所需的历史演示包与历史验收留档已经形成。

## 5. 与本轮新增实现的关系说明
在阶段十之后，仓库当前实现又新增了若干已核对事实，包括：
- [`OrchestratorExecutionMode`](clawradar/orchestrator.py:31) 已包含 `write_only` 与 `resume`，并连同 `crawl_only`、`topics_only`、`score_only`、`deliver_only` 构成更完整的执行模式矩阵；
- [`_resolve_resume_target()`](clawradar/orchestrator.py:703) 与 [`_build_write_payload()`](clawradar/orchestrator.py:714) 已在统一编排中补齐工件恢复与写作输入收口；
- 双输入模式、显式选题阶段与新增分阶段执行场景已通过 [`ClawRadarAutomationTestCase`](tests/test_openclaw_p0_automation.py:17) 中新增用例核对；
- 定向自动化测试结果为 20 项通过。

这里记录这些关系，是为了避免把阶段十材料与当前仓库状态割裂；但这些新增事实仍然来自当前代码与测试，而不是来自本清单所列阶段十历史产物本身。

## 6. 该证据链没有自动证明的内容
以下内容不能仅凭本清单被写成“阶段十已经证明”或“阶段十材料已经覆盖”：
- 面向真实使用者的总启动门面
- 双输入模式的完整说明与验收材料
- 显式选题阶段的新增说明材料
- 全流程运行、分阶段运行与 `resume` 的新增演示材料
- 标准阶段工件、运行目录与回放说明的完整产品化文档

这些内容属于阶段十之后新增的实现事实或后续正式目标，应以当前代码、当前测试以及 [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md)、[`project_protocol/02_constraints.md`](project_protocol/02_constraints.md)、[`project_protocol/03_plan.md`](project_protocol/03_plan.md)、[`project_protocol/04_changelog.md`](project_protocol/04_changelog.md)、[`project_protocol/05_decisionlog.md`](project_protocol/05_decisionlog.md) 的最新口径为准。

## 7. 本次历史证据链没有声称的内容
- 阶段十历史演示没有把真实来源在线抓取写成已实跑；相关接入事实仍以 [`tests/test_openclaw_p0_automation.py`](tests/test_openclaw_p0_automation.py) 中相关用例与现有代码为依据。
- 阶段十历史演示没有把 `external_writer` 写成已实跑；相关接入事实仍以 [`clawradar/writing.py`](clawradar/writing.py) 与相关测试为依据。
- 阶段十历史演示没有把真实外部渠道外发写成已完成；本次交付明确是 `archive_only` 本地留档演示。
- 阶段十历史演示没有把 `write_only`、`resume`、`user_topic`、`inline_topic_cards`、新增 `topics` 阶段写成历史演示事实。

## 8. 阶段十历史收口判断
基于以上真实产物，阶段十已经具备统一入口真实运行、结果快照、本地留档、核对材料与复现说明的最小但足够历史证据链，因此它可以继续作为当前项目的历史基线。

同时必须明确：该历史基线不等于本轮新增的双输入模式、显式选题阶段、`write_only`、`resume`、新增测试覆盖已经由阶段十材料证明；这些内容只是在当前仓库状态中另行成立。
