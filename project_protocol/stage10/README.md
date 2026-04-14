# 阶段十历史演示包说明

## 1. 目录用途
[`project_protocol/stage10/`](project_protocol/stage10/) 用于集中留存阶段十形成的历史演示、真实运行结果快照、验收核对材料与本地复现说明。

本目录的定位始终是历史基线证据包，不是本轮新增能力或后续产品化目标已经全部完成的证明包。

## 2. 当前文件集合
- 统一入口输入样本：[`project_protocol/stage10/generated/demo_input.json`](project_protocol/stage10/generated/demo_input.json)
- 统一入口真实结果：[`project_protocol/stage10/generated/demo_result.json`](project_protocol/stage10/generated/demo_result.json)
- 本地留档目录：[`project_protocol/stage10/demo_runs/`](project_protocol/stage10/demo_runs/)
- 证据清单：[`project_protocol/stage10/evidence_manifest.md`](project_protocol/stage10/evidence_manifest.md)
- 本地复现说明：[`project_protocol/stage10/local_reproduction.md`](project_protocol/stage10/local_reproduction.md)
- 验收核对清单：[`project_protocol/stage10/acceptance_checklist.md`](project_protocol/stage10/acceptance_checklist.md)

## 3. 阶段十已成立的历史基线
阶段十材料真实证明了以下历史事实：
- 统一编排主链路已经存在，当前 ClawRadar 顶层核心入口是 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)
- 基于准真实样本可以完成真实本地运行并产出结果快照与本地留档
- `archive_only` 本地留档路径已经成立
- 阶段十所需的演示与验收收口材料已经形成

## 4. 与本轮实现状态的关系
在阶段十之后，当前代码与测试又向前推进了一步。基于本轮已核对事实，仓库当前状态还包括：
- [`OrchestratorExecutionMode`](clawradar/orchestrator.py:31) 已包含 `crawl_only`、`topics_only`、`score_only`、`write_only`、`deliver_only`、`resume` 与 `full_pipeline`
- 双输入模式中的 `real_source` 与 `user_topic` 已统一纳入 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 的同一主链路
- 抓取与评分之间已经形成显式选题阶段，并产出 `topic_cards`
- 基于工件继续执行的基础能力已经通过 [`_resolve_resume_target()`](clawradar/orchestrator.py:703) 与 [`_build_write_payload()`](clawradar/orchestrator.py:714) 在统一编排中落地
- 自动化测试 [`ClawRadarAutomationTestCase`](tests/test_openclaw_p0_automation.py:17) 已新增覆盖 `crawl_only`、`topics_only`、`user_topic`、`inline_topic_cards`、`write_only`、`resume`，并完成 20 项定向通过验证

以上内容用于说明“阶段十之后仓库状态已经前进到哪里”，不是说本目录中的阶段十文件本身已经变成这些新增能力的历史证明。

## 5. 本目录没有承担的证明职责
本目录中的历史材料，不自动等同于以下内容已经由阶段十材料证明：
- 面向真实使用者的总启动门面
- 双输入模式的完整说明与验收材料
- 显式选题阶段的新增证明材料
- 全流程运行、分阶段运行与 `resume` 的新增演示材料
- 标准阶段工件、运行目录与回放说明的完整产品化文档

这些内容应分别以当前代码事实、当前测试事实以及 [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md)、[`project_protocol/02_constraints.md`](project_protocol/02_constraints.md)、[`project_protocol/03_plan.md`](project_protocol/03_plan.md)、[`project_protocol/04_changelog.md`](project_protocol/04_changelog.md)、[`project_protocol/05_decisionlog.md`](project_protocol/05_decisionlog.md) 的最新口径为准。

## 6. 阶段十材料的继续价值
虽然本目录不承担本轮新增能力证明，但它仍继续提供以下价值：
- 作为统一编排历史基线成立的证据
- 作为 `archive_only` 最小交付与本地留档成立的证据
- 作为历史阶段验收收口的复盘材料
- 作为后续新增阶段说明材料的对照基线

## 7. 边界说明
- 本目录不把真实来源在线抓取、原项目外部写作实跑、真实外部交付实跑写成阶段十演示事实
- 本目录也不把双输入模式、显式选题阶段、`write_only`、`resume`、新增测试覆盖写成阶段十已证明事实
- 本目录只补充“与本轮实现状态的关系”，不回写为本轮新增能力的证据包
