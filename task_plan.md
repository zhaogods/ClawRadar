# ClawRadar 一天内正式可交付版本计划

## 目标
在现有协议与代码基线上，用 **1 天** 收口出一个“可正式交付、但范围受控”的版本：必须能获取真实信息、复用 radar_engines 的真实爬取系统与报告撰写能力、具备统一入口、跑通完整流程，并形成可验收的运行说明与留档结果。

## 当前阶段
- phase: 4
- name: 正式实现与验收
- status: complete

## 阶段列表
| 阶段 | 名称 | 状态 | 说明 |
|---|---|---|---|
| 1 | 协议重读与目标重定义 | complete | 已重读 `project_protocol/`，确认阶段十只是历史基线，不足以证明真实抓取与真实写作实跑 |
| 2 | 现状与一天内可交付边界收口 | complete | 已确认应以 clawradar 为主线，复用 radar_engines 爬取与 ReportEngine，交付对象为单机/受控环境正式版本 |
| 3 | 收口一天交付方案 | complete | 已明确默认值切换、user_topic 真抓取、正式 launcher、测试与文档收口的实施顺序 |
| 4 | 正式实现与验收 | complete | 已完成默认值切换、user_topic 真抓取、正式 launcher、测试/文档收口，并补齐 external_writer 默认链路的关键运行依赖 |

## 一天交付版定义
- 不是 MVP demo，也不是阶段十那种准真实样本复现。
- 是“单机/受控环境可正式交付版本”：
  - 能通过统一入口发起任务；
  - 能使用真实来源抓取或围绕用户主题抓取真实信息；
  - 能输出显式选题、评分、写作、交付留档全链路结果；
  - 写作阶段优先复用 radar_engines 报告撰写能力，而不是只靠 OpenClaw 内置拼稿；
  - 最终产物、运行目录、工件、失败信息、使用方式都可说明、可验收、可复跑。
- 本次不追求多用户平台化、权限系统、监控平台、批量调度、云端长期运行。

## 必须完成项
1. 统一入口：提供唯一推荐入口，外层参数收口到 `topic_radar_orchestrate()`。
2. 真实输入：打通 `real_source` 实跑，或在 `user_topic` 模式下真正触发抓取而不是仅构造占位候选。
3. 完整流程：crawl -> topics -> score -> write -> deliver 可从统一入口完整执行。
4. 真实写作：写作阶段复用 radar_engines 报告撰写能力，不以 `openclaw_builtin` 占位稿作为正式交付默认值。
5. 标准工件：`crawl_results`、`topic_cards`、`scored_events`、`content_bundles`、`delivery_receipt`、`run_summary` 都能稳定产出。
6. 运行说明：提供最小但正式的使用说明、输入说明、输出说明、失败说明与验收方式。
7. 验证：至少补齐一条真实输入实跑路径的验收脚本/测试/演示材料。

## 明确不纳入一天范围
- 多用户 Web 平台重构
- 平台级权限系统
- Prometheus/Sentry/完整可观测性体系
- 大规模调度与任务队列平台
- 多交付渠道全面接入
- 全面重写 radar_engines 主系统

## 关键协议依据
- `project_protocol/01_requirements.md` 要求统一总启动门面、双输入、全流程与分阶段运行、结构化工件。
- `project_protocol/02_constraints.md` 要求 OpenClaw 继续为主系统，radar_engines 仅作为被调用输入/写作能力层，且不得制造平行顶层入口。
- `project_protocol/stage10/local_reproduction.md` 明确阶段十并未证明真实来源在线抓取、`external_writer` 实跑或真实外部交付实跑。
- 因此一天交付版必须优先补上“真实抓取 + 真实写作 + 统一入口”这三个缺口。

## 一天实施顺序
1. 统一入口封装
2. 真实来源链路打通
3. 真实写作链路切到 radar_engines ReportEngine
4. 补齐一条默认完整流程配置
5. 补齐使用文档与验收样例
6. 跑真实验收并留档

## 遇到的错误
| 错误 | 尝试次数 | 解决方案 |
|---|---:|---|
| 误把上一轮 skill/MVP 收口方向当作当前目标 | 1 | 按用户新要求重读协议，改为“1 天正式交付版”口径 |
| 阶段十材料容易被误读为已覆盖真实抓取/真实写作 | 1 | 以 `stage10/local_reproduction.md` 的真实性边界重新收口目标 |
| 会话压缩后规划文件与已修改代码未同步 | 1 | 先运行 session-catchup、核对 `git diff --stat`，再把阶段状态改为实现与验收进行中 |
