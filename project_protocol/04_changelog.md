# 变更记录

## 1. 本轮变更定位
本轮仅回写“可由 skill 调用项目”的最小可行方案中，**已经真实落地且可由当前仓库文件核对**的文档与资产事实；不新增设计，不把未实现事项提前写成已完成事实。

本轮事实依据限定为当前仓库中已存在的以下文件：
- 正式 skill 资产 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)；
- 根级说明页 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md)；
- 项目使用文档 [`使用.md`](使用.md)；
- 协议计划层 [`project_protocol/03_plan.md`](project_protocol/03_plan.md)；
- 协议决策层 [`project_protocol/05_decisionlog.md`](project_protocol/05_decisionlog.md)。

## 2. 本轮已完成且已落地的事实
### 2.1 已新增正式 skill 资产
- 已新增正式 skill 资产 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)；
- 该文件已把 skill 定位为当前项目的**外层调用门面**，用于以最小参数组织调用统一入口 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)；
- 该文件已明确 skill **不创建新的平行顶层编排**、**不绕开统一入口直接拼阶段函数**、**不引入新的包装脚本**。

### 2.2 已更新旧根级 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md) 的定位
- 根级 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md) 已改为旧版 skill 草案保留页；
- 该文件已明确正式 skill 入口收口到 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)；
- 该文件已说明保留根级 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md) 的目的，是避免继续误用旧草案中的过期路径、过期模式说明与旧入口假设。

### 2.3 已更新 [`使用.md`](使用.md) 以对齐 skill 调用口径
- [`使用.md`](使用.md) 已明确当前项目真实统一入口仍是 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)；
- [`使用.md`](使用.md) 已明确 skill 只是统一总启动门面的外层调用载体，不应新造平行顶层入口；
- [`使用.md`](使用.md) 已补充与 skill 对齐的最小调用方式、输入模式说明与推荐执行方式，口径与正式 skill 资产一致。

### 2.4 已更新计划层与决策层协议文件
- [`project_protocol/03_plan.md`](project_protocol/03_plan.md) 已补写本轮最小方案的计划层口径，明确 skill 是统一总启动门面的外层载体，且本次最小交付范围以 skill 资产、项目文档、协议同步为主；
- [`project_protocol/05_decisionlog.md`](project_protocol/05_decisionlog.md) 已补写对应决策依据，明确 skill 继续收口到 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)，且 [`project_protocol/04_changelog.md`](project_protocol/04_changelog.md) 应在真实落地后再回写事实；
- 上述两份协议文件均已明确：本轮最小方案以 skill 直接调用统一入口为准，而不是扩写新的外层编排实现。

## 3. 本轮未发生且不得越界写成已完成的事项
- 本轮**未新增 Python 包装脚本**；当前仓库中可核对的正式方案仍是由 skill 直接调用统一入口，而不是新增 `run_skill.py`、`launcher.py`、`main_skill.py` 一类壳层；
- 本轮**未新增平行顶层入口**；当前统一入口仍是 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)，skill 只是外层调用门面，不是新的主编排；
- 本轮**未将阶段十材料改写为本轮 skill 方案证明**；[`project_protocol/stage10/`](project_protocol/stage10/) 仍只应被视为历史基线材料；
- 本轮**未把 [`project_protocol/01_requirements.md`](project_protocol/01_requirements.md) 与 [`project_protocol/02_constraints.md`](project_protocol/02_constraints.md) 写成发生了新的已完成变更**；
- 本轮**未回写未落地的附加增强项**，包括但不限于新增演示包、额外运行壳层、更多入口封装或新的证明材料。

## 4. 各已落地文件的事实摘要
### 4.1 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)
- 已作为正式 skill 资产落地；
- 已给出输入模式、执行模式、最小取参原则与推荐调用模板；
- 已把直接调用 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) 作为当前 MVP 正式口径。

### 4.2 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md)
- 已转为旧版根目录 skill 说明页；
- 已把正式 skill 路径指向 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)。

### 4.3 [`使用.md`](使用.md)
- 已与正式 skill 资产统一术语与调用方式；
- 已明确“不新增包装脚本”“不新造平行顶层入口”的边界；
- 已把 skill 调用视为对统一入口的外层组织，而非替代统一入口。

### 4.4 [`project_protocol/03_plan.md`](project_protocol/03_plan.md) 与 [`project_protocol/05_decisionlog.md`](project_protocol/05_decisionlog.md)
- 已承接本轮最小方案的计划层与决策层口径；
- 已把“skill 作为外层调用载体、继续收口到统一入口、MVP 不先做包装脚本、阶段十材料不承担 skill 方案证明”写成当前协议事实边界。

## 5. 口径提醒
- [`project_protocol/04_changelog.md`](project_protocol/04_changelog.md) 本次只回写当前仓库已落地、可核对的事实，不承担新增设计说明；
- 若后续再新增包装脚本、演示材料、验收包或新的外层入口文档，应在真实落地后另行回写，不得提前记账；
- 当前正式 skill 路径应以 [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md) 为准，根级 [`openclaw-doc/compat/SKILL.md`](openclaw-doc/compat/SKILL.md) 仅作兼容说明页。
