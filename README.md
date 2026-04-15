<div align="center">

# ClawRadar

**面向真实来源热点发现、结构化评分、内容生成与归档交付的开源舆情流水线**

**一个用于热点发现、证据组织、内容生成与归档交付的开源舆情工作流。**

**An open-source public-opinion workflow for trend discovery, evidence structuring, content generation, and archived delivery.**

![License](https://img.shields.io/badge/license-GPL--2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)

</div>

ClawRadar 是一个开源 Python 项目，聚焦舆情选题、评分、写作和交付。当前仓库包含两层结构：

- 顶层 `clawradar/`：更聚焦的 P0 交付管线，提供统一入口、结构化契约、测试夹具和正式 launcher。
- `radar_engines/`：保留的原始能力层，包含 `MindSpider`、`QueryEngine`、`MediaEngine`、`InsightEngine`、`ReportEngine` 等模块，供顶层流程复用。

这个仓库更接近“可编排的舆情流水线”而不是单一脚本。核心目标是把候选事件从输入接入，一路处理到评分、成稿和归档交付。

## 项目描述

ClawRadar 试图把“舆情发现 -> 证据组织 -> 评分决策 -> 写作产出 -> 归档交付”收敛到同一条可复用链路里。它既可以作为独立命令行流程运行，也可以作为上层系统调用的协议化组件使用。

当前顶层实现主要面向 P0 交付场景，强调：

- 统一入口，而不是分散脚本
- 结构化中间产物，而不是仅返回文本
- 可归档、可回放、可审计的运行结果
- 与 `radar_engines/` 能力层复用，而不是重复造轮子

## 致谢

本项目的能力层整理与兼容保留，参考并受益于开源项目 [BettaFish](https://github.com/666ghj/BettaFish)。感谢原项目作者与贡献者。

## 当前实现重点

顶层 `clawradar` 已经把主流程收敛到了一个统一入口：

```python
from clawradar.orchestrator import topic_radar_orchestrate
```

围绕这个入口，项目已经实现了以下能力：

- 输入适配：支持 `inline_candidates`、`inline_normalized`、`inline_topic_cards`、`real_source`、`user_topic` 五类输入模式。
- 标准化 ingest：把上游候选事件收敛成统一的 `normalized_events` 结构。
- 选题与抓取桥接：支持从真实来源加载候选事件，或从用户主题派生抓取请求。
- 结构化评分：生成时间线、事实点、风险标记、维度分和最终决策。
- 写作阶段：支持内置写作，也支持委托 `ReportEngine` 作为外部 writer。
- 交付阶段：支持飞书消息格式和本地归档快照。
- 编排与产物管理：每次运行都会生成 `meta/`、`stages/`、`events/` 等输出目录。

## 仓库结构

```text
ClawRadar/
├─ clawradar/                   # 顶层 P0 管线
│  ├─ contracts.py              # ingest 契约与标准化
│  ├─ topics.py                 # 选题卡片、user_topic 适配
│  ├─ real_source.py            # real_source 适配，复用 MindSpider / 搜索能力
│  ├─ scoring.py                # 评分与决策
│  ├─ writing.py                # 写作与外部 writer 适配
│  ├─ delivery.py               # 交付与归档
│  └─ orchestrator.py           # 统一编排入口
├─ run_openclaw_deliverable.py  # 正式推荐 launcher
├─ scripts/
│  └─ run_real_source_demo.py   # real_source 演示脚本
├─ tests/                       # 顶层 P0 测试
├─ radar_engines/               # 原始多引擎能力层
│  ├─ MindSpider/               # 热点采集与爬取
│  ├─ QueryEngine/
│  ├─ MediaEngine/
│  ├─ InsightEngine/
│  ├─ ReportEngine/
│  └─ ...
├─ skills/                      # 相关 skill 定义
└─ outputs/                     # 运行输出目录
```

## 主流程

顶层流程由 `topic_radar_orchestrate()` 负责串联。按职责可以理解为：

1. 接收输入并解析 `entry_options`
2. 根据输入模式决定是否走 `real_source` / `user_topic` 适配
3. 生成候选事件并做 ingest 标准化
4. 对候选事件进行评分，得出 `publish_ready`、`watchlist`、`need_more_evidence` 等结论
5. 对可发布事件生成内容包
6. 执行交付或归档
7. 输出统一的 `run_summary`、阶段状态和事件状态

默认情况下，正式 launcher 使用的策略是：

- `write.executor = external_writer`
- `delivery.target_mode = archive_only`
- `delivery.target = archive://openclaw_p0`
- `degrade.* = fail`

这意味着它优先走正式交付路径，但不会默认直接向外部渠道推送。

## 快速开始

### 1. 环境建议

仓库顶层代码使用了 Python 3.10+ 语法，建议直接使用 Python 3.10 或 3.11。

如果你只想跑顶层契约测试，最小依赖很少；如果你要启用 `real_source`、外部写作或完整的引擎能力，建议安装 `radar_engines/requirements.txt` 中的依赖。

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r radar_engines/requirements.txt
pip install pytest
```

### 2. 最小 Python 调用

```python
from clawradar.orchestrator import topic_radar_orchestrate

payload = {
    "request_id": "req-minimal-001",
    "trigger_source": "manual",
    "topic_candidates": [
        {
            "event_id": "evt-minimal-001",
            "event_title": "OpenAI 发布企业级智能体平台更新",
            "event_time": "2026-04-09T08:00:00Z",
            "source_url": "https://example.com/openai-update"
        }
    ]
}

result = topic_radar_orchestrate(payload)
print(result["run_status"], result["final_stage"], result["decision_status"])
```

### 3. 正式 launcher

从命令行运行时，优先使用根目录的 `run_openclaw_deliverable.py`：

```bash
python run_openclaw_deliverable.py --input-mode real_source --source-ids weibo --limit 5
python run_openclaw_deliverable.py --input-mode user_topic --topic "AI 智能体治理" --company "OpenAI" --keywords 治理 审计
```

### 4. real_source 演示

```bash
python scripts/run_real_source_demo.py
```

这个脚本会关闭写作和交付，只保留真实来源加载和评分，便于本地验证输入适配链路。

## 输入模式

统一入口当前最重要的两种外部输入模式如下：

- `real_source`：从 `MindSpider` 等真实来源拉取热点候选事件，再进入统一主链路。
- `user_topic`：用户只给主题、公司、关键词等提示词，系统先构造主题上下文，再委托真实来源层做候选发现。

此外也支持直接给：

- `topic_candidates`
- `normalized_events`
- `topic_cards`

这使得项目既可以作为完整流水线运行，也可以作为中间协议层嵌入其他系统。

## 输出结果

一次运行通常会在 `outputs/<request_id>/<run_slug>/` 下生成结果。典型目录包括：

- `meta/`：`run_summary.json`、`entry_resolution.json`、`artifact_summary.json`、`errors.json`
- `stages/`：各阶段的中间结果快照
- `events/`：按事件维度归档的评分卡、payload 快照、交付产物
- `reports/`：最终报告、IR、中间章节和日志

这套输出结构适合做审计、回放和单事件重试。

## 测试

顶层 `tests/` 已覆盖 ingest、评分、写作、交付和 orchestrator 自动化主路径。建议先跑这组测试确认协议稳定：

```bash
python -m pytest tests
```

从现有测试可以看出，当前顶层 P0 重点验证的是：

- 统一入口的行为一致性
- `publish_ready` / `need_more_evidence` 等状态路由
- 写作与交付阶段的协议稳定性
- 归档产物是否完整落盘

## `radar_engines` 的定位

`radar_engines/` 不是顶层入口的替代品，而是被复用的能力层和兼容层。当前顶层流程至少会复用其中两类能力：

- `MindSpider`：真实来源热点采集
- `ReportEngine`：外部 writer 生成报告

如果你只是要接入统一编排，不需要直接从 `radar_engines/` 启动整套旧系统；如果你要扩展采集、搜索、报告渲染或多智能体分析，再进入该目录阅读原始模块会更合适。

## 适合从哪里开始读

如果你第一次接手这个项目，推荐按下面顺序阅读：

1. `run_openclaw_deliverable.py`
2. `clawradar/orchestrator.py`
3. `clawradar/contracts.py`
4. `clawradar/scoring.py`
5. `clawradar/writing.py`
6. `clawradar/delivery.py`
7. `tests/test_openclaw_p0_automation.py`

这样能先看清入口和协议，再看阶段能力，最后用测试理解真实约束。

## 注意事项

- 当前仓库里同时保留了新旧两层实现，阅读时不要把 `clawradar/` 和 `radar_engines/` 当成两套并列入口。
- `real_source` 和 `external_writer` 依赖 `radar_engines/` 中的模块以及对应运行环境，不是纯标准库能力。
- 项目里有一些历史文档和兼容文件，可能存在编码或命名风格不一致的情况；以顶层 `clawradar/` 和 `tests/` 的真实实现为准。

## 开源协议

本仓库根目录已采用 [GPL-2.0](./LICENSE) 开源协议。

这与 `radar_engines/` 目录中已有的许可证口径保持一致，便于仓库作为一个整体对外发布。

如果你后续准备拆分子模块、二次分发或引入新的第三方组件，仍然建议逐目录核对：

- 根目录 [LICENSE](./LICENSE)
- [radar_engines/LICENSE](./radar_engines/LICENSE)
- 各子目录附带的第三方许可证文件
