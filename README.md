# ClawRadar

ClawRadar 是一条面向真实来源热点发现、结构化评分、内容生成与归档/发布的开源流水线。

当前仓库将顶层统一流程保留在 `clawradar/`，并复用 `radar_engines/` 中保留下来的能力层。

## 这个仓库能做什么

- 从真实来源或用户给定主题中接收候选事件。
- 对事件做标准化处理并生成评分结果。
- 生成或重写内容包。
- 通过适配器归档或发布到支持的渠道。
- 保留可回放、可审计、可排障的运行产物。

## 主入口

- CLI 启动器：`run_openclaw_deliverable.py`
- Python API：`clawradar.orchestrator.topic_radar_orchestrate()`
- 既有产物回放发布：`--publish-only`

## 快速开始

### 环境准备

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
```

### 运行 real_source 流程

```bash
python run_openclaw_deliverable.py --input-mode real_source --source-ids weibo --limit 5
```

### 运行 user_topic 流程

```bash
python run_openclaw_deliverable.py --input-mode user_topic --topic "AI 智能体治理" --company "OpenAI" --keywords 治理 审计
```

### 回放既有输出并重新发布

```bash
python run_openclaw_deliverable.py --publish-only --delivery-channel wechat --delivery-target wechat://draft-box/openclaw-review --publish-file outputs/<mode>/<run_id>/debug/content_bundles.json
```

### 运行测试

```bash
python -m pytest tests
```

## 支持的输入模式

- `real_source`：从真实来源链路拉取候选事件。
- `user_topic`：根据用户给定的主题、公司、关键词等构造候选事件。
- `inline_candidates`、`inline_normalized`、`inline_topic_cards`：接收已经准备好的 inline 载荷。

## 默认执行行为

- 写作执行器默认是 `external_writer`。
- 交付目标默认是 `archive_only`。
- 输入、写作、交付三个阶段的 degrade 策略默认都是 `fail`。
- `publish-only` 是正式支持的回放发布路径，可在不重跑上游阶段的情况下复用既有生成结果。

## 输出结构

一次运行会写入：

```text
outputs/<mode>/<run_id>/
```

其中 `run_id` 使用北京时间生成，格式为 `YYYYMMDD_HHMM`。

每次运行目录中的主要产物包括：

- `summary.json`：运行总览与阶段结果。
- `reports/`：最终面向人阅读的报告产物。
- `recovery/`：按事件归档的回放与交付快照。
- `debug/`：诊断用的中间产物与阶段追踪信息。

每个输入模式目录下还会保留：

- `outputs/<mode>/latest.json`：指向该模式最近一次运行结果的指针文件。

`publish-only` 可以直接回放已有的 `debug/content_bundles.json` 或 `payload_snapshot.json`，同时兼容部分旧路径产物。

## 版本迭代

这个项目经历过几轮针对顶层主流程的收敛。整体目标一直是：让主链路更容易运行、更容易审计、更容易回放，同时避免把整套旧平台结构重新带回根流程。

### V1

第一个可用的顶层版本明确建立了 `clawradar/` 这一统一编排层，并把主流程拆成清晰的四个阶段：

- ingest
- score
- write
- deliver

这一版的意义在于把原先分散在旧脚本和引擎内部路径中的调用关系，收敛成一条明确的统一入口流程。

### V2

第二轮迭代的重点是让一次运行结束后更容易理解结果、检查状态和定位产物。

主要变化包括：

- 统一输出到 `outputs/<mode>/<run_id>/`
- 将最终产物、恢复快照、调试信息分开存放
- 为每个输入模式增加 `outputs/<mode>/latest.json` 便于快速定位最近一次运行
- 将 `summary.json` 固定为运行级总入口

当前顶层工作流的输出布局就是围绕这一版建立的。

### V2.1 微信发布图片修复

这一轮迭代重点处理的是微信草稿发布中的报告视觉还原问题。

主要变化包括：

- 优化从报告到微信草稿的转换链路，让图表和视觉内容尽可能被保留下来
- 降低富文本报告在发布过程中退化成纯文本或纯表格的概率
- 让最终草稿更接近原始 HTML 报告的阅读体验

这次修复的目标不只是“让图片出现”，而是让微信端看到的内容结构更接近生成报告本身。

### V2.2 微信草稿长度约束与发布修复

这一轮迭代重点解决的是：在微信网页端看起来没有超限，但调用微信草稿 API 时仍被拒绝的问题。

主要变化包括：

- 将标题、作者、摘要三类约束在写作、归一化、交付链路中统一起来
- 修正微信草稿请求体的发送方式，显式使用 UTF-8 JSON 正文
- 保留 `45003` 和 `45004` 场景下的重试与审计元数据
- 降低“本地看起来可发布，但真正创建草稿时失败”的概率

这一版之后，微信相关的生成约束与发布约束在端到端路径上更加一致。

## 测试

主测试命令：

```bash
python -m pytest tests
```

如果只想先验证顶层编排主流程，可以先跑：

```bash
python -m pytest tests/test_clawradar_automation.py
```

## 许可证

GPL-2.0

