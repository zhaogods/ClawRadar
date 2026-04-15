---
name: openclaw-topic-radar
description: 调用当前仓库的 ClawRadar 统一入口来运行舆情选题、评分、写作和归档交付流程。适用于 user_topic、real_source 或已有中间工件继续执行。
---

# ClawRadar Topic Radar

当用户希望在当前仓库里触发、继续执行或检查 ClawRadar 统一工作流时，使用本 skill。

它只做一件事：收口到当前仓库真实入口，而不是再造一套平行编排。

说明：

- Skill 名称仍保留为 `openclaw-topic-radar`，用于兼容旧引用；
- 但当前项目主名称已经是 `ClawRadar`。

真实入口：

- Python API: `from clawradar.orchestrator import topic_radar_orchestrate`
- CLI launcher: `python run_openclaw_deliverable.py`
- Skill 脚本入口: `skills/openclaw-topic-radar/scripts/run_topic_radar.py`

## 何时使用

适用于下面几类请求：

- “围绕某个主题跑一轮舆情选题/评分/交付”
- “从真实来源抓热点再继续评分”
- “拿已有 `topic_cards` / `normalized_events` / `scored_events` 继续执行”
- “用最小参数调用当前仓库的 Topic Radar 流程”

不适用于：

- 重新实现 crawl / score / write / deliver 顶层编排
- 把 `radar_engines/` 当成单独主入口来绕开 `clawradar/`

## 默认原则

- 默认执行模式：`full_pipeline`
- 默认写作执行器：`external_writer`
- 默认交付方式：`archive_only`
- 默认交付目标：`archive://clawradar`
- 默认失败策略：`degrade.* = fail`

如果信息不足，优先做最小补齐，不先追问。

## 推荐做法

### 1. 优先选输入模式

- 用户只给主题、公司、关键词：用 `user_topic`
- 需要先抓真实热点：用 `real_source`
- 用户已经有中间工件：直接传完整 payload，避免重复推断

输入模式细节见：

- [references/modes.md](./references/modes.md)

最小 payload 示例见：

- [references/payloads.md](./references/payloads.md)

### 2. 优先使用 Skill 自带脚本

需要稳定执行时，优先运行：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --input-mode user_topic --topic "OpenAI 企业级智能体平台" --company "OpenAI" --keywords 智能体 企业服务
```

如果上游已经准备好了完整 JSON payload，则直接传文件：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --payload-file payload.json --execution-mode full_pipeline
```

如果上游已经有中间工件，则直接传对应文件继续执行：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --topic-cards-file topic_cards.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --scored-events-file scored_events.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --content-bundle-file content_bundle.json --execution-mode deliver_only
```

### 3. 正式交付仍以统一入口为准

无论是 skill、脚本还是手工 Python 调用，都必须收口到：

```python
from clawradar.orchestrator import topic_radar_orchestrate
```

不要在 skill 里手工拼另一套 stage 编排。

## 输出与回报

优先回报这些字段：

- `run_status`
- `final_stage`
- `decision_status`
- `output_root`
- `entry_resolution`
- `run_summary`
- `errors`

输出目录默认落在仓库根目录 `outputs/` 下。

## 依赖边界

- `user_topic` 和纯 inline payload 可以只依赖顶层 `clawradar/`
- `real_source` 依赖 `radar_engines` 中的真实来源能力
- `external_writer` 依赖 `radar_engines.ReportEngine`

如果 `real_source` 或 `external_writer` 不可用，应明确说明是运行环境问题，而不是 skill 入口问题。

## 7. 调用后最少汇报字段

调用完成后，至少回报：

- `run_status`
- `final_stage`
- `decision_status`
- `output_root`
- `entry_resolution`
- `run_summary`

如果是分阶段调用，再补充对应工件：

- `crawl_only`：`crawl_results`
- `topics_only`：`topic_cards`
- `score_only`：`scored_events` / `score_results`
- `write_only`：`content_bundles`
- `deliver_only`：`delivery_result` / `delivery_receipt`
- `resume`：说明本次从哪一阶段恢复

## 8. 行为约束

- 不把本 skill 叙述成新的顶层主入口；
- 不把 `project_protocol/stage10/` 历史材料改写为本轮新增能力证明；
- 不把尚未实现的能力写成已完成事实；
- 对外说明时始终保持：skill 负责组织调用，真正统一入口仍是 `topic_radar_orchestrate()`，正式 launcher 只是它的外层门面。
