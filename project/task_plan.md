# ClawRadar 剥壳任务计划

## 当前目标

先保持 `MindSpider`、`QueryEngine`、`MediaEngine`、`ReportEngine` 四个核心引擎整体保留，停止继续做大规模目录删除，转入“边界固化 + 输入能力增强”的下一阶段。

## 当前阶段

- phase: 3
- name: 边界固化与 P1 规划
- status: in_progress

## 阶段列表

| 阶段 | 名称 | 状态 | 说明 |
|---|---|---|---|
| 1 | 删除旧平台外壳 | complete | 已删除 `ForumEngine`、`InsightEngine`、`SingleEngineApp`、`SentimentAnalysisModel`、旧 tests、旧 templates、旧入口脚本和旧报告脚本。 |
| 2 | 文档对齐与 P0 修复 | complete | 已对齐 `README.md`，完成 `real_source` / `user_topic` P0 多源融合增强，并补充定向测试。 |
| 3 | 边界固化与 P1 规划 | in_progress | 识别四引擎最小运行边界、清点主线真实依赖、确定下一轮增强顺序与落点。 |
| 4 | 输入层 P1 增强 | pending | 在不裁四引擎的前提下，补统一去重、聚类、多样性排序、补搜和二跳补证据。 |
| 5 | ReportEngine 依赖收缩评估 | pending | 梳理 `external_writer` 对 `ReportEngine` 的最小依赖图，只做评估，不直接删内部模块。 |
| 6 | 下一轮精细瘦身决策 | pending | 基于运行依赖图，决定哪些兼容层可以后续移出、哪些必须继续保留。 |

## 下一阶段主目标

下一阶段重点不是“再删文件”，而是完成三件事：

1. 固化四引擎当前运行边界，明确什么是主线真实依赖。
2. 继续增强 `real_source` / `user_topic`，把 P0 提升到 P1 可用级。
3. 为后续精细瘦身建立依赖图，而不是凭目录名继续做静态删除。

## 下一阶段执行顺序

### A. 四引擎边界固化

- 产出四引擎最小运行边界清单。
- 标记哪些模块属于：
  - 主线直接调用
  - 引擎内部间接依赖
  - 纯兼容保留
  - 历史文档或演示残留

### B. 输入层 P1 增强

- 给 `real_source` 增加跨源去重和候选多样性排序。
- 给 `user_topic` 增加补搜、结果不足时的再次召回策略。
- 评估是否引入热点候选的二跳补证据。
- 把 P0 的定向测试扩展为更完整的输入层回归测试。

### C. ReportEngine 依赖评估

- 梳理 `clawradar/writing.py` 到 `ReportEngine.agent.create_agent()` 的最小依赖链。
- 识别 `static/`、模板、chart repair、状态管理中哪些是实际运行依赖。
- 暂不删除内部模块，只沉淀依赖图和可移出清单。

## 当前范围

允许保留：

- `MindSpider`
- `QueryEngine`
- `MediaEngine`
- `ReportEngine`
- `radar_engines/config.py`
- `radar_engines/utils/`
- `radar_engines/static/`

当前不再保留的旧平台外壳：

- `ForumEngine`
- `InsightEngine`
- `SingleEngineApp`
- `SentimentAnalysisModel`
- 旧 Streamlit 报告目录
- 旧 tests
- 旧入口脚本

## 约束

- 不做四引擎内部子功能裁剪。
- 不删除共享基础设施。
- 不把历史文档里的旧名称当成当前结构。
- `project/reports/` 仅保留本地，不再纳入版本控制。
- 下一阶段所有删除决策都必须建立在“运行依赖已确认”的前提上。

## 2026-04-21 临时验证：ReportEngine 章节列表结构错位

- status: complete
- 目标：先基于缺陷报告规划验证，再判断当前修复是否已解决问题。
- 已完成：
  1. 阅读 `project/reports/report_engine_list_structure_bug_report.md`
  2. 阅读修复相关文件：`radar_engines/ReportEngine/nodes/chapter_generation_node.py`、`radar_engines/ReportEngine/ir/validator.py`、`radar_engines/ReportEngine/prompts/prompts.py`
  3. 运行 `python -m unittest tests.test_report_engine_chapter_structure -v`
  4. 运行 `python -m py_compile` 校验本次改动文件
- 结论：当前修复已在代码和定向回归测试层面验证通过。
- 注意：直接运行单测会因 `ReportEngine` 绝对导入约定失败，需带 `PYTHONPATH=F:/02_code/ClawRadar/radar_engines` 执行。

## 2026-04-23 微信标题长度根因修复专项

- status: in_progress
- 目标：解决微信推送标题过长问题，修复策略以提示词约束和写作产物约束为主，代码校验为辅，微信渠道裁切仅保留为最终兜底。
- 需覆盖链路：
  - 默认内建写作链路：`clawradar/writing.py` 生成/改写 content_bundle 时就产出可直接用于微信的标题，不再靠截断修短。
  - 外部写作链路：`radar_engines/ReportEngine` 在文档布局阶段直接产出微信安全标题，再由 `clawradar/writing.py` 做校验与包装。
  - 渠道交付链路：`clawradar/publishers/wechat/service.py` 和 `third_party/wechat_publisher/publisher.py` 仅做校验、告警、最终兜底。
- 拟修改文件与职责：
  - `radar_engines/ReportEngine/prompts/prompts.py`：在 `SYSTEM_PROMPT_DOCUMENT_LAYOUT` 中加入微信标题长度、语义完整性、禁止靠截断达标等规则。
  - `radar_engines/ReportEngine/nodes/document_layout_node.py`：在解析后补充标题长度/完整性校验与告警，必要时回退到可解释的短标题。
  - `radar_engines/ReportEngine/agent.py`：把微信标题约束透传到布局阶段的上下文与 manifest，确保外部写作链路拿到同一套约束。
  - `clawradar/writing.py`：把当前 `_constrain_title()` 从主路径降级为校验/兜底，新增显式标题校验与修复决策，不再把截断当成默认生成方式。
  - `clawradar/publishers/wechat/service.py`：只负责透传 `content_bundle.title.text` 到微信草稿接口，遇到超限仅记录校验结果，不在此层做主路径截断。
  - `third_party/wechat_publisher/publisher.py`：保留 `upload_draft()` 内的 `_truncate_utf8()` 作为微信 API 最终边界兜底。
  - `tests/test_clawradar_writing.py` / `tests/test_clawradar_delivery.py`：补充上游直出合规标题、超限标题触发校验/兜底、渠道层不再承担主路径裁切的回归测试。
- 实施顺序：
  1. 先补 `ReportEngine` 提示词与布局上下文约束。
  2. 再调整 `clawradar/writing.py` 的标题生成/校验策略。
  3. 然后收紧微信服务层和第三方 publisher 的职责边界。
  4. 最后补齐回归测试，验证上游直出合规标题、兜底仅在最后一级生效。
- 风险提示：
  - 需要同时覆盖 `clawradar_builtin` 与 `external_writer`，避免只修外部写作链路。
  - 任何新增校验都不能把语义完整的标题再次机械截断成断裂字符串。
  - 若上游无法生成合规标题，应明确记录为写作校验失败或降级，而不是默默缩短后继续发布。

## 2026-04-24 WeChat 45004 描述长度修复与 third_party 迁移评估

- status: in_progress
- 目标：修复微信草稿发布 `errcode=45004 / description size out of limit`，并把 `third_party/wechat_publisher` 当前依赖事实与后续内迁删除步骤固化到计划中。
- 已知事实：
  1. `clawradar/publishers/wechat/service.py` 当前仅在 `45003` 时做标题重试；`digest` 只做了 `summary_text[:120]` 字符截断，与微信字节限制口径不一致。
  2. `third_party/wechat_publisher/publisher.py` 仍是当前微信发布主链路的底层实现，负责 access_token、封面上传、草稿上传、字段截断和结构化错误。
  3. 若要删除 `third_party/wechat_publisher`，需要先把 `WeChatPublisher`、`WeChatDraftUploadError`、上传逻辑和相关测试迁入 `clawradar/publishers/wechat/`，当前不能直接删除。
- 本阶段执行顺序：
  1. 统一 `digest` 的字节级截断口径，避免服务层和底层实现不一致。
  2. 为 `45004 description size out of limit` 增加一次安全摘要重试，并把尝试历史写入 `publish_attempts`。
  3. 补充定向测试，覆盖摘要超限重试成功/失败和最终传给 publisher 的 digest 字节数。
  4. 单独保留后续迁移阶段：把 `third_party/wechat_publisher` 内迁到渠道目录后再删除旧目录。
- 最新验证：
  1. `summary.channel_variants.wechat` 已通过 `publish_only`、archive-only 与 deliver-only replay 定向测试验证，当前不会在编排、归档、重放链路中丢失。
  4. `publish_only` 的审计记录已显式保存 `summary_text` 与 `summary_wechat`，当前可以直接从 `records.jsonl` 追溯去重与重放使用的摘要值。

