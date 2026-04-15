---
name: openclaw-topic-radar
description: 使用当前仓库的 ClawRadar 统一入口运行选题、评分、写作与归档交付。适用于 user_topic、real_source 或已有中间工件继续执行，禁止用额外 agent 搜索替代 skill 自己的 real_source。
---

# ClawRadar Topic Radar

调用当前仓库的 ClawRadar 正式工作流，并把所有执行收口到真实入口，不再临时拼接一套平行编排。

这个 skill 的目标只有一个：

- 用当前仓库里的正式入口完成运行、恢复、交付和回报。

它不是：

- 一个新的顶层主入口；
- 一个“先用 agent 或 web 搜索取数，再把结果塞回仓库”的替代流程；
- 一个绕开 `clawradar/` 直接调用 `radar_engines/` 各模块的自由编排器。

真实入口固定为：

- Python API：`from clawradar.orchestrator import topic_radar_orchestrate`
- 正式 launcher：`python run_openclaw_deliverable.py`
- Skill 包装脚本：`python skills/openclaw-topic-radar/scripts/run_topic_radar.py`

Skill 名称仍保留 `openclaw-topic-radar`，仅用于兼容旧引用；项目当前统一主名是 `ClawRadar`。

## 何时使用

适用于：

- 围绕一个主题跑一轮完整的舆情选题、评分、写作和交付；
- 从真实来源抓热点，再进入统一主链路；
- 从 `topic_cards`、`normalized_events`、`scored_events`、`content_bundle` 等中间工件继续执行；
- 用最小参数对当前仓库进行一次可回放的正式运行。

不适用于：

- 自己重新实现 crawl、score、write、deliver 的顶层串联；
- 把 `radar_engines/` 当成单独主入口；
- 先让 agent / web 搜索 / 其他脚本手工抓取真实数据，再伪装成 skill 输出。

## 输入规范

本 skill 只接受并组织下列输入形态：

1. `user_topic`
2. `real_source`
3. `inline_candidates`
4. `inline_normalized`
5. `inline_topic_cards`
6. 已有 `scored_events`
7. 已有 `content_bundle` / `content_bundles`

模式选择规则：

- 只有主题、公司、关键词时：使用 `user_topic`
- 明确要求真实抓取时：使用 `real_source`
- 已有中间工件时：直接从对应工件恢复，不回退到更早阶段

参考：

- [references/modes.md](./references/modes.md)
- [references/payloads.md](./references/payloads.md)

## 默认运行规范

默认值如下：

- `execution_mode = full_pipeline`
- `write.executor = external_writer`
- `delivery.target_mode = archive_only`
- `delivery.target = archive://clawradar`
- `degrade.input_unavailable = fail`
- `degrade.write_unavailable = fail`
- `degrade.delivery_unavailable = fail`

如果用户没有特别说明，先按以上默认值补齐，而不是追问一串参数。

## 安装与预检

### 最小前提

- Python 3.10+
- 在仓库根目录内运行，或通过 `--repo-root` / `CLAWRADAR_REPO_ROOT` 显式指定仓库

### 不同能力的依赖边界

- 仅跑顶层 `clawradar/` 和 inline 工件：依赖较少
- `real_source`：依赖 `radar_engines` 的真实来源能力和网络访问
- `external_writer`：依赖 `radar_engines.ReportEngine` 及其配置

### 推荐安装

完整能力优先安装：

```bash
python -m pip install -r radar_engines/requirements.txt
```

若只想先跑 `real_source` 的最小依赖，可先安装：

```bash
python -m pip install httpx sqlalchemy loguru pydantic pydantic-settings python-dotenv
```

### 推荐预检

skill 包装脚本支持预检：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --input-mode real_source --source-ids weibo --check-only
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --input-mode user_topic --topic "OpenAI 企业级智能体平台" --write-executor external_writer --check-only
```

预检只检查这次运行真正会触发的能力，不会对不会执行到的阶段误报依赖缺失。

### 环境配置

- `real_source` / `external_writer` 所需配置优先从仓库根目录 `.env` 或 `radar_engines/.env` 读取
- 如果某能力不可用，要明确报告“运行环境未满足”，不要把它描述成 skill 入口失效

## 运行方式

### 1. 优先使用 skill 包装脚本

默认应直接运行：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --input-mode user_topic --topic "OpenAI 企业级智能体平台" --company "OpenAI" --keywords 智能体 企业服务
```

真实抓取必须由 skill 自己触发：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --input-mode real_source --source-ids weibo --limit 5
```

如果用户已经有完整 JSON payload：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --payload-file payload.json --execution-mode full_pipeline
```

如果用户已经有中间工件：

```bash
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --topic-cards-file topic_cards.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --scored-events-file scored_events.json --execution-mode resume
python skills/openclaw-topic-radar/scripts/run_topic_radar.py --content-bundle-file content_bundle.json --execution-mode deliver_only
```

### 2. 需要稳定落地时的建议

- 首次跑 `real_source` 时先执行 `--check-only`
- 环境尚未补齐时，不要硬跑 `external_writer`，可以显式切到 `--write-executor openclaw_builtin`
- 需要保存测试输出时，使用 `--runs-root`

### 3. 正式收口

无论从 skill、脚本还是上层调用进入，最终都必须收口到：

```python
from clawradar.orchestrator import topic_radar_orchestrate
```

不要在 skill 文案、执行说明或实现里暗示还有另一套“更底层但更正确”的 stage 编排。

## 输出规范

优先汇报这些字段：

- `run_status`
- `final_stage`
- `decision_status`
- `output_root`
- `entry_resolution`
- `run_summary`
- `errors`

必要时补充：

- `crawl_only`：`crawl_results`
- `topics_only`：`topic_cards`
- `score_only`：`scored_events` / `score_results`
- `write_only`：`content_bundles`
- `deliver_only`：`delivery_result` / `delivery_receipt`
- `resume`：明确从哪一阶段恢复

输出目录默认在仓库根目录 `outputs/` 下，也可以通过 `--runs-root` 覆盖。

## 规范化要求

对外说明时，必须保持以下口径一致：

- skill 负责组织调用，不负责定义新的业务协议
- 真正统一入口是 `topic_radar_orchestrate()`
- `real_source` 是 skill 触发后由仓库内部能力完成，不是 agent 预抓取
- `external_writer` 和 `real_source` 的失败都应优先归因为运行环境或依赖边界，而不是 skill 概念本身

## 强约束

必须遵守：

- 不把本 skill 叙述成新的顶层主入口
- 不手工拼接另一套 crawl / score / write / deliver 编排
- 不把 `project_protocol/stage10/` 历史材料改写为本轮新增能力证明
- 不把尚未实现的能力写成已完成事实
- 不在用户要求真实抓取时先用 agent 搜索、web 搜索或其他脚本代替 `real_source`
- 如果需要真实来源数据，必须由 skill 脚本或统一入口自己触发 `real_source`

明确禁止：

- “先搜一轮微博/网页，再把结果包装成 `topic_candidates` 继续跑”
- “先用 agent 搜索确认热点，再说 skill 已完成真实抓取”
- “遇到 `real_source` 失败时，悄悄改成手工搜索补数据”

允许的例外只有诊断：

- 可以在 skill 失败后为了定位原因去检查依赖、配置或网络
- 但这种诊断不能替代 skill 本身的真实抓取结果
