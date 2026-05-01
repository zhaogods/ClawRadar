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

| 入口 | 说明 |
|------|------|
| `python start.py` | 交互式启动（推荐），中文菜单引导 |
| `python run_clawradar_deliverable.py` | CLI 启动器，适合脚本/定时任务 |
| `clawradar.orchestrator.topic_radar_orchestrate()` | Python API |

## 快速开始

### 1. Python 环境

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
playwright install chromium
```

### 2. 系统依赖

**所有平台必需**：

- Node.js — `pyexecjs` 执行 JS 签名脚本（如抖音 `douyin.js`），缺失会导致爬虫启动失败
  ```bash
  sudo apt install nodejs      # Linux
  # 或从 https://nodejs.org 下载安装（Windows/macOS）
  ```

**Linux 云服务器额外依赖**：

- Xvfb — 虚拟帧缓冲，使 Chrome 以非 headless 模式运行以绕过社媒平台反爬检测
  ```bash
  sudo apt install xvfb
  ```
- 中文字体 — 报告 PDF 渲染用
  ```bash
  sudo apt install fonts-noto-cjk fonts-wqy-zenhei
  ```

> 完整云服务器部署步骤见 [docs/cloud-deployment.md](docs/cloud-deployment.md)。

### 3. 交互式运行

```bash
python start.py
```

按中文提示逐项选择：运行模式 → 日志模式 → 输入来源 → 深爬配置（平台/登录方式/服务器模式）→ 写作/发布选项。

### 4. 命令行运行

**real_source 流程**：

```bash
python run_clawradar_deliverable.py --input-mode real_source --source-ids weibo --limit 5
```

**user_topic 流程**：

```bash
python run_clawradar_deliverable.py --input-mode user_topic --topic "AI 智能体治理" --company "OpenAI" --keywords 治理 审计
```

**回放既有输出并重新发布**：

```bash
python run_clawradar_deliverable.py --publish-only --delivery-channel wechat --delivery-target wechat://draft-box/clawradar-review --publish-file outputs/<mode>/<run_id>/debug/content_bundles.json
```

### 5. 运行测试

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

## 版本说明

版本迭代与更新记录已迁移到 `changes.md`，请查看该文件获取完整更新历史。

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

