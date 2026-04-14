# ClawRadar 一天交付版发现记录

## 核心结论
- 当前项目的正确主线不是重做 BettaFish 平台，而是以 `clawradar/` 为主编排核心，复用 BettaFish 的真实爬取与报告撰写能力。
- `project_protocol/01_requirements.md:20` 已要求统一总启动门面、双输入、全流程与分阶段执行、结构化工件。
- `project_protocol/02_constraints.md:15`、`project_protocol/02_constraints.md:21` 已要求 OpenClaw 保持主系统地位，而真实采集层与报告撰写层只能作为被调用能力。
- `project_protocol/stage10/local_reproduction.md:47` 到 `project_protocol/stage10/local_reproduction.md:61` 明确：阶段十并没有证明真实来源在线抓取、`external_writer` 实跑或真实外部交付实跑。
- 因此，如果目标是“1 天内可交付且不是 MVP”，必须优先补齐三件事：
  1. 统一入口；
  2. 真实来源实跑；
  3. BettaFish 报告撰写能力实跑。

## 当前代码中最适合承接一天交付版的部分
- 统一编排核心：`clawradar/orchestrator.py:1251`
- 真实来源适配：`clawradar/real_source.py`
- 选题阶段：`clawradar/topics.py:219`、`clawradar/topics.py:264`
- 评分阶段：`clawradar/scoring.py:326`
- 写作阶段：`clawradar/writing.py`
- 交付阶段：`clawradar/delivery.py`
- BettaFish 报告引擎：`BettaFish/ReportEngine/agent.py:173`

## 当前与一天交付目标的真实差距
### 1. 统一入口缺口
- 早期阶段当前只有统一函数入口 `topic_radar_orchestrate()` 和 demo 脚本 `scripts/run_real_source_demo.py`。
- 当时缺少正式、唯一推荐、面向使用者的启动门面；现已补齐 `run_openclaw_deliverable.py` 作为正式 launcher，`scripts/run_real_source_demo.py` 仅保留为历史 demo 脚本。

### 2. 真实抓取缺口
- 代码已存在 `real_source` 适配能力，但阶段十材料没有证明真实在线抓取已作为正式交付路径跑通。
- `user_topic` 目前更像输入桥接，不足以单独证明“围绕主题抓真实信息”已经完成。

### 3. 真实写作缺口
- `clawradar/writing.py` 默认内置写作能力仍偏占位；若要达到正式交付，默认正式路径应切到复用 BettaFish ReportEngine 的真实写作执行。

### 4. 文档与验收缺口
- 当前协议文档区分了基线、已完成事实与后续事项，但用户手册、运行手册、交付说明并未真正收口到“1 天交付版”。

## 一天交付版的合理边界
- 是“单机/受控环境正式交付版”，不是平台化 SaaS。
- 要求真实信息、完整流程、统一入口、可复跑、可留档、可说明。
- 不要求在 1 天内补齐平台级监控、权限、批量调度、多租户与完整运营后台。

## 建议的正式交付默认口径
- 默认入口：一个新的统一 CLI/启动脚本/正式 skill，其职责只是把用户参数收口到 `entry_options` 并调用 `topic_radar_orchestrate()`。
- 默认输入：`real_source` 优先；`user_topic` 则必须驱动真实抓取，不再停留在占位候选。
- 默认写作：`external_writer` / BettaFish ReportEngine 优先；`openclaw_builtin` 只保留为降级路径。
- 默认交付：`archive_only` + 可追溯回执，外发渠道可作为可选能力。

## 已落地的正式收口进展
- `clawradar/orchestrator.py` 的默认值已经切到 `external_writer + archive_only`，正式全链路默认不再落回 builtin + feishu 组合。
- `clawradar/topics.py` 的 `load_user_topic_payload()` 已改为委托 `real_source.py`，`user_topic` 正式语义变成“主题驱动真实抓取”。
- `clawradar/real_source.py` 已同时支持 source-driven 与 topic-driven 两类真实输入，并记录 provider、query、candidate_count 等上下文。
- 根目录已新增 `run_openclaw_deliverable.py`，作为面向交付使用的唯一正式 launcher；统一主入口仍然是 `topic_radar_orchestrate()`。
- 自动化测试已开始围绕新默认值与新 `user_topic` 语义收口，文档仍需同步更新。
- 当前真实环境下 `external_writer` 失败不是编排逻辑问题，而是运行环境缺少 `sniffio`：`openai` 包本身导入即失败，因此 ReportEngine 还未真正启动就中断。
- `BettaFish/requirements.txt` 原先只声明了 `openai>=1.3.0` 与 `httpx==0.28.1`，未显式列出 `sniffio`/`distro`/`jiter`；现已补齐这几个关键运行依赖。
- `ReportEngine/__init__.py` 与 `ReportEngine/renderers/__init__.py` 原先在包导入阶段就会级联加载重依赖模块，导致 HTML-only 路径也可能被 PDF/Matplotlib 缺依赖拖死；现已改为惰性导出，OpenClaw 的 external_writer 默认 HTML 写作链路不再被这类可选依赖阻塞。
- 经本地验证，external_writer + archive_only 默认链路已经可以完成一次 smoke 级全流程执行。
- 正式 launcher 双路径验收已完成：
  - `real_source` 路径完成到 `deliver`，生成 `delivery_receipt`，并按统一 run 目录结构生成 archive-only 留档；当前默认输出根目录已统一为项目根目录 `outputs/`。
  - `user_topic` 路径完成到 `deliver`，`user_topic_provider` 记录为 `anspire_search`，archive 路径目录名中保留真实 URL 痕迹，证明已走真实抓取而非 `user_topic://...` 占位来源。
- 这意味着“一天内正式可交付版本”的收口条件已满足：统一入口、真实来源输入、BettaFish ReportEngine 真实写作、archive-only 交付留档、自动化测试与正式验收均已成立。
- 目录规范化收尾阶段最后残留的旧路径文案位于 `BettaFish/ReportEngine/scripts/export_to_pdf.py` 与 `BettaFish/ReportEngine/scripts/generate_all_blocks_demo.py`；现已统一改为 `outputs/final_reports/...`，README 中相关表述已同步一致。
- 另有一个未被仓库其他代码引用的遗留脚本 `BettaFish/export_pdf.py`，原先写死了 macOS 本地绝对路径与旧 `final_reports/...` 目录；现已改为基于脚本所在目录自动定位项目根，并从 `outputs/final_reports/ir` 自动发现最新 IR、输出到 `outputs/final_reports/pdf`。
- BettaFish 根级日志路径此前仍与新的 `outputs/` 体系分离：`app.py`、`ForumEngine/monitor.py`、`utils/forum_reader.py` 默认还在读写 `logs/`。现已统一切换到 `outputs/logs`，与 Docker 挂载和 ReportEngine 其余路径口径保持一致；本轮未迁移历史日志，只是停止继续产出新的根级日志目录。
- README 中的目录树与运行说明也已同步：`outputs/logs/` 现在被明确标注为主运行日志、`forum.log` 与 ReportEngine 日志的统一落点，避免再把根级 `logs/` 误读为正式默认目录。
- `BettaFish/.gitignore` 也已补齐到当前目录规范：新增 `outputs/final_reports/` 忽略规则，并将旧根级 `final_reports/` 明确标注为历史兼容目录，避免忽略规则与实际输出结构继续漂移。
