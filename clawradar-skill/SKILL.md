---
name: 追踪雷达助手
description: 使用 ClawRadar 官方仓库运行选题发现、评分、写作与交付流程。适用于 user_topic、real_source 或从中间工件恢复执行；数据必须由 Skill 自己通过仓库流程抓取，不允许由 agent 手工搜索替代 real_source。
---

# 追踪雷达助手

## 作用

这个 Skill 用来指导 Claude 在本地已克隆的 ClawRadar 仓库中运行正式工作流，而不是临时拼接一套平行流程。

它适合做三类事情：

- 从 `user_topic` 启动一轮完整流程
- 从 `real_source` 启动真实来源抓取并继续下游处理
- 从 `topic_cards`、`normalized_events`、`scored_events`、`content_bundle` 等中间工件恢复执行

它不适合做这些事：

- 在仓库之外重新实现一套 crawl / score / write / deliver 编排
- 用网页搜索、手工摘录、其他脚本抓来的数据冒充 `real_source`
- 把 `radar_engines/` 当作与顶层工作流并列的用户主入口

## 官方仓库

ClawRadar 官方仓库地址：

`https://github.com/zhaogods/ClawRadar`

本 Skill 依赖完整仓库。只保存或上传单独的 `Skill.md` 并不能让本地工作流运行起来。

## 名称与唤醒词

这个 Skill 的正式中文名是：

`追踪雷达助手`

可接受的近似唤醒词包括：

- `追踪雷达助手`
- `追踪雷达`
- `雷达助手`
- `选题雷达助手`
- `舆情追踪助手`
- `ClawRadar`

当用户明确要求使用这些名称之一时，应视为要求调用本 Skill 对应的工作流约束，而不是切换成普通 agent 自由搜索模式。

## 唯一事实来源

始终以仓库里的正式入口为准：

- Python API：`from clawradar.orchestrator import topic_radar_orchestrate`
- 推荐 CLI 入口：`python run_openclaw_deliverable.py`

如果未来仓库里出现其他辅助脚本，它们也只是便利封装，不是新的事实来源。

## 安装

### 1. 克隆整个仓库

必须克隆整个项目，不能只拷贝 skill 文件夹。

```bash
git clone https://github.com/zhaogods/ClawRadar.git
cd ClawRadar
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. 安装依赖

完整安装：

```bash
python -m pip install -r radar_engines/requirements.txt
python -m pip install pytest
```

如果当前只做顶层协议调试或部分本地测试，也至少需要保证仓库能正常导入 `clawradar/` 主流程代码。

### 4. 环境配置

如果要跑 `real_source` 或 `external_writer`，通常还需要配置运行环境，例如：

- 仓库根目录 `.env`
- `radar_engines/.env`
- 对应模型、接口或外部服务所需的凭证

如果这些条件未满足，应明确报告“环境未就绪”或“依赖未满足”，不要把问题描述成 Skill 定义本身失效。

## 仓库内维护约定

在当前仓库里，`clawradar-skill/` 现在只保留这一份 `SKILL.md`，作为单文件 Skill 的维护副本。

不要把这个目录误解为可独立运行的最小发行包。真正的运行能力来自整个 ClawRadar 仓库。

## 什么时候使用

在这些场景下使用本 Skill：

- 用户要围绕某个主题运行正式选题雷达流程
- 用户要从真实来源抓取候选事件
- 用户已经有中间工件，希望从中途恢复执行
- 用户要先检查环境是否具备执行条件

在这些场景下不要使用本 Skill：

- 只是普通写作、翻译、泛研究、头脑风暴
- 用户要做与 ClawRadar 仓库无关的自动化
- 仓库还没 clone 到本地
- 用户想让 Claude 先手工搜资料，再伪装成 `real_source`

## 输入选择规则

### 使用 `user_topic`

当用户提供的是主题、公司、赛道、摘要、关键词等提示信息，而不是现成事件列表时，优先走 `user_topic`。

### 使用 `real_source`

当用户明确要求从真实来源抓取时，必须由仓库自己的 `real_source` 链路执行。不能用手工网页搜索结果替代。

### 使用恢复模式

如果用户已经有中间工件，则优先从最接近目标阶段的工件恢复，例如：

- 有 `topic_cards`：从选题卡继续
- 有 `normalized_events`：从标准化结果继续
- 有 `scored_events`：从评分结果继续
- 有 `content_bundle`：直接做交付

不要为了“看起来完整”而回退重跑更早阶段。

## 推荐执行规则

1. 默认优先使用 `run_openclaw_deliverable.py`
2. 只有在用户明确要求 Python 级调用时，才直接使用 API
3. 遇到现成工件时优先恢复，而不是重建
4. 遇到缺失依赖时先报告环境问题
5. 遇到 `real_source` 失败时，不要悄悄换成人工搜索补数据
6. 所有对结果的描述都必须和仓库真实执行结果一致
7. 输出目录固定使用仓库根目录下的默认 `outputs/`

## 数据抓取硬约束

一旦用户明确要求使用本 Skill，数据获取必须遵守以下规则：

- 如果任务需要抓取真实数据，必须由 ClawRadar 仓库自己的 `real_source` 或 `user_topic -> real_source` 链路完成
- agent 不得先自行网页搜索、浏览、摘录、整理，再把结果伪装成仓库输入
- agent 不得先抓微博、新闻、论坛、网页内容，再手工改写成 `topic_candidates`、`normalized_events` 或其他中间工件冒充 Skill 输出
- 如果真实抓取所需依赖、网络或凭证不可用，应明确报告环境未就绪，而不是改走“agent 代抓取”

只允许以下两类例外：

- 用户明确提供了现成中间工件，并要求从这些工件恢复执行
- 为了诊断失败原因而检查配置、依赖或网络，但这种诊断不能替代真实抓取本身

## 常用命令

### 从 `user_topic` 启动完整流程

```bash
python run_openclaw_deliverable.py --input-mode user_topic --topic "OpenAI 企业级智能体平台" --company "OpenAI" --keywords 智能体 企业服务
```

### 从 `real_source` 启动完整流程

```bash
python run_openclaw_deliverable.py --input-mode real_source --source-ids weibo --limit 5
```

### 从评分结果恢复

```bash
python run_openclaw_deliverable.py --scored-events-file scored_events.json --execution-mode resume
```

### 只执行交付阶段

```bash
python run_openclaw_deliverable.py --content-bundle-file content_bundle.json --execution-mode deliver_only
```

### Python API 调用

```python
from clawradar.orchestrator import topic_radar_orchestrate

payload = {
    "request_id": "req-demo-001",
    "trigger_source": "manual",
    "entry_options": {
        "input": {
            "mode": "user_topic",
            "topic": "OpenAI 企业级智能体平台",
            "company": "OpenAI",
            "keywords": ["智能体", "企业服务"],
        }
    },
    "user_topic": {
        "topic": "OpenAI 企业级智能体平台",
        "company": "OpenAI",
        "keywords": ["智能体", "企业服务"],
    },
}

result = topic_radar_orchestrate(payload)
print(result.get("run_status"), result.get("final_stage"))
```

## 执行前检查

正式运行前，至少确认以下条件：

- 当前目录确实是 ClawRadar 仓库根目录
- 存在 `clawradar/` 目录
- 存在 `run_openclaw_deliverable.py`
- 默认输出会写入仓库根目录下的 `outputs/`
- 依赖已经安装
- 需要外部能力时，环境变量和凭证已经配置

如果用户第一次跑 `real_source` 或 `external_writer`，优先建议先做环境检查，再做正式执行。

## 输出汇报要求

向用户汇报结果时，优先给这些字段：

- `run_status`
- `final_stage`
- `decision_status`
- `output_root`
- `entry_resolution`
- `run_summary`
- `errors`

如果是恢复执行，还要额外说明：

- 从哪个工件进入
- 跳过了哪些阶段
- 当前是否产出了新的交付物

## 示例提示词

- “用 `user_topic` 跑一轮 OpenAI 企业级智能体平台选题。”
- “从 `scored_events.json` 继续执行，不要重跑前面的阶段。”
- “先检查本地环境能不能跑 `real_source`，能跑再正式执行。”
- “输入是现成 `content_bundle.json`，只做 deliver_only。”
- “不要手工搜网页，直接按仓库的 `real_source` 流程来。”

## 严格边界

必须遵守：

- 不要声称 `real_source` 已成功，除非仓库确实执行成功
- 不要把手工搜索结果包装成仓库原生输出
- 不要把 agent 自己抓到的数据包装成 Skill 的抓取结果
- 不要编造不存在的阶段、工件、保障或能力
- 不要把环境问题误报成 Skill 失效
- 不要把 `radar_engines/` 说成默认的最终用户入口

## 维护说明

这份文件是当前仓库中“追踪雷达助手” Skill 的唯一维护文档，目标是：

- 元数据清晰
- 工作流单一明确
- 触发条件明确
- 安装步骤可直接执行
- 使用边界清楚

如果以后确实需要扩展，可以继续补充内容；但默认应保持单文件、低歧义、可直接执行。
