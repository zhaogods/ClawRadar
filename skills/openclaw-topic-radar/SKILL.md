---
name: openclaw-topic-radar
description: 用最小参数调用当前仓库的 OpenClaw Topic Radar 统一入口，支持 user_topic、real_source、inline_topic_cards 与分阶段执行。
---

# OpenClaw Topic Radar Deliverable Skill

当调用方希望从 OpenClaw / Roo 侧以最小参数触发、继续执行或核对当前项目的 Topic Radar 流程时，使用本 skill。

## 1. 角色定位

本 skill 只是当前项目的外层调用门面，负责：

- 帮调用方选择最合适的输入模式；
- 组装最小可运行 `payload`；
- 直接调用统一入口；
- 用最小字段回报结果。

本 skill **不创建新的平行顶层编排**、**不绕开统一入口直接拼阶段函数**；面向正式交付时，推荐直接调用仓库根目录的 `run_openclaw_deliverable.py`，其内部仍然收口到同一个统一入口。

当前项目真实统一入口是：

- `topic_radar_orchestrate()`
- 位置：`clawradar/orchestrator.py`
- 推荐导入：`from clawradar.orchestrator import topic_radar_orchestrate`

## 2. 正式交付调用原则

### 2.1 统一入口原则

始终优先直接导入并调用 `topic_radar_orchestrate()`。

不要：

- 新增 `run_skill.py`、`launcher.py`、`main_skill.py` 一类包装脚本；
- 分别手工调用 crawl / topics / score / write / deliver 形成另一套顶层编排；
- 把 stage10 历史材料写成“本 skill 已被证明”的证据。

### 2.2 默认推荐执行方式

正式交付默认推荐：

- `execution_mode="full_pipeline"`
- `entry_options.delivery.target_mode="archive_only"`
- `entry_options.delivery.target="archive://openclaw_p0"`
- `entry_options.write.executor="external_writer"`

这样最适合单机/受控环境正式交付：既能走统一入口全链路，又能默认复用真实写作与本地留档回执。

## 3. 推荐输入模式

### 3.1 `user_topic`

当用户只给了“主题 / 公司 / 关键词 / 赛道”而没有结构化候选事件时，优先使用 `user_topic`。

适合：

- “帮我跟进 OpenAI 最近企业级智能体动态”
- “围绕 Manus / 智能体协作做一轮选题”
- “先按这个主题出候选，再决定值不值得写”

最小示例：

```json
{
  "request_id": "req-user-topic-demo",
  "trigger_source": "manual",
  "user_topic": {
    "topic": "OpenAI 企业级智能体平台",
    "company": "OpenAI",
    "keywords": ["智能体", "企业服务"]
  },
  "entry_options": {
    "input": {
      "mode": "user_topic"
    },
    "write": {
      "executor": "external_writer"
    },
    "delivery": {
      "target_mode": "archive_only",
      "target": "archive://openclaw_p0"
    }
  }
}
```

### 3.2 `real_source`

当调用方已经具备真实来源配置，希望先抓取候选，再走统一主链路时，使用 `real_source`。

适合：

- 定时扫描来源；
- 热点发现；
- 需要先形成 `crawl_results`。

最小示例：

```json
{
  "request_id": "req-real-source-demo",
  "trigger_source": "manual",
  "entry_options": {
    "input": {
      "mode": "real_source"
    },
    "write": {
      "executor": "external_writer"
    },
    "delivery": {
      "target_mode": "archive_only",
      "target": "archive://openclaw_p0"
    }
  }
}
```

### 3.3 `inline_topic_cards`

当上游已经准备好了 `topic_cards`，希望跳过 crawl / topics，直接继续评分或下游阶段时，使用 `inline_topic_cards`。

适合：

- 人工确认后的选题卡继续评分；
- 复用已有选题工件；
- 配合 `score_only`、`write_only`、`resume`。

最小示例：

```json
{
  "request_id": "req-inline-topic-cards-demo",
  "trigger_source": "manual",
  "topic_cards": [
    {
      "event_id": "evt-demo-001",
      "topic_title": "OpenAI 企业级智能体平台",
      "summary": "围绕企业级智能体协作与审计能力形成的选题卡。"
    }
  ],
  "entry_options": {
    "input": {
      "mode": "inline_topic_cards"
    }
  }
}
```

## 4. 推荐执行模式

统一执行模式继续收口到 `topic_radar_orchestrate()`，推荐含义如下：

- `full_pipeline`：默认模式；从当前输入一路执行到可达的最下游阶段。
- `crawl_only`：只形成 `crawl_results`。
- `topics_only`：形成 `topic_cards` 后收口。
- `score_only`：输出 `scored_events` / `score_results` 后收口。
- `write_only`：基于已有 `scored_events` 组织写作，不自动继续交付。
- `deliver_only`：基于已有 `content_bundles` 只做交付。
- `resume`：依据已有工件自动判断从 score / write / deliver 哪一段继续。

推荐顺序：

1. 默认先用 `full_pipeline`；
2. 只看选题时用 `topics_only`；
3. 只看评分时用 `score_only`；
4. 从中间工件继续时优先用 `resume`；
5. 只有在调用方明确知道自己手里已有哪类工件时，再使用 `write_only` 或 `deliver_only`。

## 5. 信息不足时的最小取参原则

### 5.1 能不问就不问

优先由 skill 自动补齐：

- `trigger_source` 默认补成 `manual`；
- `request_id` 缺失时由 skill 生成临时请求号；
- 本地正式交付默认走 `archive_only`；
- 未指定写作执行器时默认 `external_writer`；
- 未指定交付目标时默认 `archive://openclaw_p0`；
- 未指定 `execution_mode` 时默认 `full_pipeline`。

### 5.2 只追问真正缺失的业务输入

只在下面几类信息缺失时向用户补问：

1. 三种输入来源至少要有一种：
   - `user_topic`
   - `real_source` 所需来源配置
   - `inline_topic_cards`
2. 若用户要求真实交付而不是本地留档，才追问交付目标；
3. 若用户要求 `write_only` / `deliver_only` / `resume`，才追问已有中间工件。

### 5.3 建议追问顺序

- 第一步：你想用 `user_topic`、`real_source` 还是已有 `topic_cards`？
- 第二步：默认按 `full_pipeline + archive_only` 跑，除非你明确要 `topics_only` / `score_only` / `write_only` / `deliver_only` / `resume`。
- 第三步：只有要真实交付时，再问目标通道与目标地址。

## 6. 推荐调用模板

推荐优先使用根目录正式 launcher；如果需要在 skill 内直接组装调用，也要保持同一套正式默认值：

```python
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(".").resolve()))
from clawradar.orchestrator import topic_radar_orchestrate

payload = {
    "request_id": "req-openclaw-topic-radar-demo",
    "trigger_source": "manual",
    "user_topic": {
        "topic": "OpenAI 企业级智能体平台",
        "company": "OpenAI",
        "keywords": ["智能体", "企业服务"],
    },
    "entry_options": {
        "input": {"mode": "user_topic"},
        "write": {"executor": "external_writer"},
        "delivery": {
            "target_mode": "archive_only",
            "target": "archive://openclaw_p0",
        },
        "degrade": {
            "input_unavailable": "fail",
            "write_unavailable": "fail",
            "delivery_unavailable": "fail",
        },
    },
}

result = topic_radar_orchestrate(payload, execution_mode="full_pipeline")
print(json.dumps({
    "run_status": result.get("run_status"),
    "final_stage": result.get("final_stage"),
    "decision_status": result.get("decision_status"),
    "entry_resolution": result.get("entry_resolution"),
    "run_summary": result.get("run_summary"),
}, ensure_ascii=False, indent=2))
```

正式 launcher 调用示例：

```bash
python run_openclaw_deliverable.py --input-mode real_source --source-ids weibo --limit 5
python run_openclaw_deliverable.py --input-mode user_topic --topic "OpenAI 企业级智能体平台" --company "OpenAI" --keywords 智能体 企业服务
```

正式输出目录现在统一收口到返回值里的 `output_root`。目录结构按 run 分层，大致包括：

- `meta/`
- `stages/crawl/`、`stages/topics/`、`stages/score/`、`stages/write/`、`stages/deliver/`
- `reports/final/`、`reports/ir/`、`reports/chapters/`、`reports/logs/`
- `events/<event_id>/deliver/<timestamp>/scorecard.json`

`--runs-root` 表示总输出根目录，不再等于最终 archive 目录本身；若不显式传入，默认使用项目根目录下的 `outputs/`。

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
