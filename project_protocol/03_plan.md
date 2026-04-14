# OpenClaw 下一阶段执行计划

## 1. 计划定位
本文档用于在阶段十历史基线之上，明确区分三类内容：
- 哪些能力属于阶段十已经完成的历史基线；
- 哪些能力属于本轮已经落地并已由实现与测试核对的新增事实；
- 哪些事项仍然保留为后续补齐或增强方向。

本文档不把阶段十历史材料改写为本轮新增能力证明，也不把尚未核实的后续目标提前写成既成事实。

## 2. 当前事实分层
### 2.1 阶段十已完成基线
当前仓库已经具备以下历史基线事实：
- 已有统一编排主入口 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)；
- 已有 ingest、score、write、deliver 主链路；
- 已有最小真实来源接入路径；
- 已有原项目既有报告撰写接入路径；
- 已有 `archive_only` 本地留档与阶段十演示材料包；
- 已有 `entry_options` 与 `entry_resolution` 作为内部统一入口口径。

### 2.2 本轮新增完成事实
基于当前实现状态，以下下一阶段能力已经从计划项转化为已完成事实：
- [`OrchestratorExecutionMode`](clawradar/orchestrator.py:31) 已正式补齐 `crawl_only`、`topics_only`、`write_only`、`deliver_only`、`resume` 与 `full_pipeline` 的统一执行模式矩阵；
- 统一编排已正式支持双输入收口：`real_source`、`user_topic`、`inline_topic_cards` 等输入方式通过 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 汇入同一后续主链路，其中用户主题输入由 [`load_user_topic_payload()`](clawradar/topics.py:196) 规范化；
- 抓取与评分之间的显式选题阶段已经落地，当前链路已稳定产出 `crawl_results`、`topic_cards`、`normalized_events`、`scored_events`、`content_bundles`、`delivery_receipt`、`score_results`、`delivery_result` 与 `run_summary` 等结构化结果；
- [`_resolve_resume_target()`](clawradar/orchestrator.py:703) 已按现有工件推断恢复起点，[`_build_write_payload()`](clawradar/orchestrator.py:714) 已负责把 `write_only` / `resume` 所需写作输入统一收口；
- [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 已完成 `write_only`、`resume`、双输入分支、阶段跳过原因与最终结果收口；
- 自动化测试 [`ClawRadarAutomationTestCase`](tests/test_openclaw_p0_automation.py:17) 已新增覆盖 `crawl_only`、`topics_only`、`user_topic`、`inline_topic_cards`、`write_only`、`resume`，本轮定向验证结果为 20 项通过。

### 2.3 仍待后续补齐事项
以下内容仍保留为后续工作，不得写成本轮已完成事实：
- 面向真实使用者的统一总启动门面，当前优先定位为由 skill 承接的外层调用载体；但本轮仅确认这一收口方向，不等于 skill 资产、调用说明与使用文档已经全部落地完成；
- ClawRadar 当前对外仍以顶层统一编排核心 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 为主，外层 skill 只是调用门面，而不是新增平行顶层入口；包装脚本只保留为后续可选增强，不写成本轮既成事实；
- 本次最小交付范围以 skill 资产、项目文档、协议同步为主；如包装脚本、额外入口封装、独立运行壳层、附加演示包等，仍属于后续可选补齐项；
- 标准阶段工件的对外协议说明、目录约定与回放示例仍需继续文档化，当前实现已具备结果对象与继续执行基础，但对外运行手册尚未最终定型；
- 双输入模式、分阶段模式与继续执行能力的演示材料仍需形成新的阶段性说明包，不能继续复用 [`project_protocol/stage10/`](project_protocol/stage10/) 作为这些新增能力的证明；
- 更易用的 preset 体系、错误说明、运行摘要增强、主题预设策略等体验层事项仍保留为后续增强；
- 轻量页面入口、更多来源扩展、更丰富交付方式、历史运行管理与批量调度能力仍属于后续阶段，不是本轮收口范围。

## 3. 已完成能力与后续事项总览
| 项目 | 当前状态 | 依据 | 后续动作 |
|---|---|---|---|
| 统一编排核心 | 已完成基线 | [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) | 继续作为唯一主编排核心 |
| 双输入模式收口 | 本轮已完成 | [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)、[`load_user_topic_payload()`](clawradar/topics.py:196) | 继续补充对外使用说明 |
| 显式选题阶段 | 本轮已完成 | [`build_topic_cards()`](clawradar/topics.py:273)、[`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) | 继续完善对外工件说明 |
| 分阶段执行矩阵 | 本轮已完成主要模式 | [`OrchestratorExecutionMode`](clawradar/orchestrator.py:31) | 继续补齐面向使用者的调用文档 |
| 基于工件继续执行 | 本轮已完成基础能力 | [`_resolve_resume_target()`](clawradar/orchestrator.py:703)、[`_build_write_payload()`](clawradar/orchestrator.py:714) | 继续补齐运行目录与回放示例 |
| 阶段十历史材料 | 已完成历史基线 | [`project_protocol/stage10/README.md`](project_protocol/stage10/README.md)、[`project_protocol/stage10/evidence_manifest.md`](project_protocol/stage10/evidence_manifest.md) | 仅作为历史基线，不承担本轮新增能力证明 |
| skill 外层调用载体 | 本轮计划收口方向已确认 | [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md)、[`project_protocol/02_constraints.md`](project_protocol/02_constraints.md) | 作为统一总启动门面的外层载体，MVP 直接调用 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) |
| 本次最小交付范围 | 本轮计划已明确 | [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md)、[`project_protocol/02_constraints.md`](project_protocol/02_constraints.md) | 以 skill 资产、项目文档、协议同步为主，不把包装脚本写成已完成事实 |
| 产品化总启动门面 | 仍待后续 | [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md)、[`project_protocol/02_constraints.md`](project_protocol/02_constraints.md) | 后续继续收口 |

## 4. 当前运行形态结论
### 4.1 已完成的统一主链路
当前统一主链路已可表达为：
1. 抓取或接入候选材料；
2. 形成 `crawl_results`；
3. 输出 `topic_cards` 作为显式选题结果；
4. 执行评分并输出 `scored_events` / `score_results`；
5. 对 `publish_ready` 结果组织写作并输出 `content_bundles`；
6. 执行交付并输出 `delivery_receipt` / `delivery_result`；
7. 通过 `run_summary`、`stage_statuses`、`event_statuses` 收口本次运行结果。

### 4.2 已完成的继续执行语义
当前实现已支持以下继续执行语义：
- 已有 `topic_cards` 或 `normalized_events` 时，可从 score 继续；
- 已有 `scored_events` 时，可从 write 继续；
- 已有 `content_bundles` 时，可直接继续到 deliver；
- `write_only` 会在写作完成后提前收口，不再自动进入交付。

### 4.3 仍待继续产品化的部分
当前尚未完成的重点，不是主链路能力本身，而是对外使用面的继续收口：
- 由 skill 作为统一总启动门面的外层调用载体，并形成唯一推荐启动方式与最小参数说明；
- MVP 阶段先收口为 skill 直接调用 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)，不额外制造包装脚本或平行顶层入口；
- 基于运行目录自动恢复、重放与核对的成套文档；
- 双输入与分阶段运行的新增演示/验收材料包。

## 5. 后续推进顺序
### 5.1 P0 剩余事项
- 补齐 skill 资产，使其可作为统一总启动门面的外层调用载体；
- 补齐 skill 调用 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 的最小使用说明与项目文档；
- 同步更新协议文档，明确 MVP 最小方案、边界与未完成事项；
- 补齐双输入模式、分阶段模式与继续执行的运行示例；
- 补齐标准阶段工件与运行目录的对外文档。

### 5.2 P1 增强事项
- preset 配置体系；
- 更易用的错误说明与运行摘要；
- 从中间工件继续执行的增强体验；
- 主题输入到抓取策略的预设与抽象。

### 5.3 P2 扩展事项
- 轻量页面入口；
- 更多来源扩展；
- 更丰富的交付方式；
- 历史运行管理与批量调度能力。

## 6. 当前完成判断
截至本轮，以下事项已可判定为完成：
- 双输入模式中的 `real_source` 与 `user_topic` 已统一进入主链路；
- 显式选题阶段已经成立，不再只有评分结果；
- 用户已经可以运行 `crawl_only`、`topics_only`、`score_only`、`write_only`、`deliver_only`、`resume` 与全流程模式；
- 系统已经能够基于阶段工件继续执行；
- OpenClaw 继续保持主系统地位，BettaFish 继续作为被调用输入与写作能力层。

以下事项仍保留为后续完成标准：
- 形成唯一推荐、面向真实使用者的总启动门面，并完成 skill 资产与使用说明的真实落地；
- 如需提升外层封装体验，再评估是否追加包装脚本；当前该项仍是后续可选增强，不属于本轮已完成事实；
- 形成新增能力对应的成套演示、说明与验收材料；
- 将运行目录、工件协议与回放方式进一步对外收口并稳定化。
