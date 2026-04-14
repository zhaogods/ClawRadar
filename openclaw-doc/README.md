# OpenClaw 说明文档

## 1. 概述

### 1.1 OpenClaw 是什么

根据已确认信息，OpenClaw 是适用于任何操作系统的 AI 智能体 Gateway 网关。它通过单个 Gateway 进程连接聊天应用与智能体，并将 Gateway 作为会话、路由和渠道连接的唯一事实来源。

### 1.2 适用场景

已确认的典型使用场景包括：

- 通过 WhatsApp、Telegram、Discord、iMessage 等聊天应用与智能体交互
- 支持本地部署或远程部署
- 适合个人助手类场景
- 适合多智能体隔离场景
- 支持通过浏览器控制界面进行管理

### 1.3 信息边界说明

本文仅基于已提供的官方中文文档调研结果整理，不包含额外网页调研、推断性结论或未明确披露的实现细节。文中会明确区分“已确认信息”与“未明确说明”。

## 2. 官方文档导航

以下为当前已确认的官方中文文档入口：

- 首页：<https://docs.openclaw.ai/zh-CN>
- 安装：<https://docs.openclaw.ai/zh-CN/install>
- 聊天渠道：<https://docs.openclaw.ai/zh-CN/channels>
- 工具：<https://docs.openclaw.ai/zh-CN/tools>
- 模型提供商目录：<https://docs.openclaw.ai/zh-CN/providers>
- CLI 参考：<https://docs.openclaw.ai/zh-CN/cli>
- 配置向导：<https://docs.openclaw.ai/zh-CN/cli/configure>
- 配置命令：<https://docs.openclaw.ai/zh-CN/cli/config>
- 模型命令：<https://docs.openclaw.ai/zh-CN/cli/models>
- 单次智能体调用：<https://docs.openclaw.ai/zh-CN/cli/agent>
- 多智能体管理：<https://docs.openclaw.ai/zh-CN/cli/agents>

建议项目成员优先按“安装 → 配置 → 渠道接入 → 工具与模型 → 多智能体管理”的顺序阅读。

## 3. 核心功能

### 3.1 多聊天渠道接入

已确认信息：

- 支持多聊天渠道接入
- 支持大量渠道与插件扩展
- WeChat 插件通过腾讯 iLink Bot 二维码登录
- WeChat 插件仅支持私聊
- Telegram 是最快的渠道设置方式之一
- WhatsApp 需要二维码配对，并且会存储更多状态

### 3.2 多智能体路由与会话隔离

已确认信息：

- 支持多智能体路由
- 支持按工作区隔离会话
- 支持按发送者隔离会话
- 支持智能体身份定制
- 默认情况下，OpenClaw 使用内置 Pi 二进制，以 RPC 模式运行，并按发送者创建独立会话

### 3.3 工具系统

已确认信息显示，OpenClaw 的工具系统覆盖以下类别：

- 文件系统
- 运行时
- 会话
- 记忆
- Web
- UI
- 自动化
- 消息
- 节点

其中：

- 浏览器工具支持打开页面、截图、快照、交互、上传、导出 PDF
- 节点工具支持通知、摄像头、录屏、定位、Canvas 展示与 A2UI 推送

### 3.4 模型与提供商接入

已确认信息：

- 支持多个 LLM 提供商
- 支持默认模型配置
- 支持图像模型配置
- 支持模型别名
- 支持回退链
- 支持认证配置
- 支持模型扫描发现

### 3.5 运维与管理能力

已确认信息：

- 支持安装
- 支持启动、停止、重启
- 支持状态检测
- 支持 daemon
- 支持健康检查
- 支持日志查看
- 支持安全审计
- 支持 Web 控制界面
- 支持设备与节点配对审批

## 4. 安装与快速开始

### 4.1 安装方式

#### 安装脚本

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

#### 包管理器安装

```bash
npm install -g openclaw@latest
pnpm add -g openclaw@latest
bun add -g openclaw@latest
```

#### 源码安装

```bash
pnpm install && pnpm ui:build && pnpm build
```

### 4.2 快速开始流程

已确认的快速开始流程如下：

1. 安装 OpenClaw
2. 执行 `openclaw onboard --install-daemon`
3. 执行 `openclaw channels login`
4. 执行 `openclaw gateway --port 18789`

### 4.3 安装验证

可使用以下命令验证安装与运行状态：

```bash
openclaw --version
openclaw doctor
openclaw gateway status
```

### 4.4 仪表板地址

默认仪表板地址为：<http://127.0.0.1:18789/>

### 4.5 单次智能体调用

`openclaw agent` 用于一次性智能体调用。

已确认限制与行为：

- 至少需要 `--to`、`--session-id` 或 `--agent` 之一
- 支持 `--deliver`
- 支持 `--local`
- `--channel`、`--reply-channel`、`--reply-account` 仅影响回复投递，不影响会话路由

## 5. 配置方法

### 5.1 配置文件位置

已确认配置文件位置：

```text
~/.openclaw/openclaw.json
```

### 5.2 配置入口

支持以下配置入口：

- `openclaw configure`
- `openclaw config`
- Web 控制界面

### 5.3 `configure` 的主要分区

已确认 `configure` 包含以下主要分区：

- workspace
- model
- web
- gateway
- daemon
- channels
- plugins
- skills
- health

### 5.4 `config` 命令能力

已确认 `openclaw config` 支持：

- `get`
- `set`
- `unset`
- `file`
- `schema`
- `validate`

### 5.5 配置路径与值格式

已确认信息：

- 路径支持点路径和数组索引
- 值按 JSON5 解析
- `--strict-json` 可强制 JSON5
- 支持普通值
- 支持 SecretRef 构建器
- 支持 `secrets.providers.<alias>` 构建器
- 支持 `--batch-json`
- 支持 `--batch-file`

### 5.6 已确认示例配置项

已明确出现的示例配置项包括：

- `channels.whatsapp.allowFrom`
- `channels.whatsapp.groups`
- `messages.groupChat.mentionPatterns`

### 5.7 配置生效注意事项

编辑配置后需要重启 Gateway。

## 6. 模型、工具与多智能体配置

### 6.1 Gateway 与运行模式

已确认信息：

- Gateway 相关配置项：`gateway.mode`
- `setup` / `onboard` 支持 `--mode <local|remote>`
- `gateway` 支持 `--bind <loopback|tailnet|lan|auto|custom>`
- 智能体运行可通过 Gateway
- 也可使用 `--local` 本地嵌入执行
- Gateway 请求失败时会回退到嵌入式智能体

### 6.2 多智能体命令

已确认的多智能体命令包括：

- `agents list`
- `agents add`
- `agents bind`
- `agents unbind`
- `agents delete`

创建并绑定智能体的已确认示例形式：

```bash
agents add [name] --workspace <dir> --model <id> --bind <channel[:accountId]>
```

### 6.3 工具权限与工具画像

已确认工具相关配置包括：

- `tools.allow`
- `tools.deny`
- `tools.profile`
- `agents.list[].tools.profile`
- `tools.byProvider`
- `agents.list[].tools.byProvider`

已确认 profile 包括：

- `minimal`
- `coding`
- `messaging`
- `full`

### 6.4 工具组

已确认工具组包括：

- `group:fs`
- `group:runtime`
- `group:sessions`
- `group:memory`
- `group:web`
- `group:ui`
- `group:automation`
- `group:messaging`
- `group:nodes`
- `group:openclaw`

### 6.5 Web / 浏览器相关配置

已确认配置项包括：

- `tools.web.search.maxResults`
- `tools.web.search.enabled`
- `tools.web.fetch.enabled`
- `browser.enabled`
- `browser.defaultProfile`

### 6.6 模型配置与认证

已确认能力包括：

- `agents.defaults.model.primary`
- `agents.defaults.imageModel.primary`
- `models aliases`
- `models fallbacks`
- `models image-fallbacks`
- `models scan`
- `models auth add|setup-token|paste-token`
- `models auth order get|set|clear`

### 6.7 Secret / Provider 来源

已确认支持的 Secret/provider 来源：

- env
- file
- exec

### 6.8 MCP 状态说明

已确认信息边界如下：

- 在当前已访问页面中，未见 MCP 独立专章
- 未见 MCP 的明确配置步骤
- 未见 MCP 的配置示例

因此，关于 MCP 的完整定义、入口与配置方式，本文统一标记为“未明确说明”。

## 7. 最佳实践与注意事项

### 7.1 渠道接入建议

- Telegram 是较快的接入路径之一，适合优先验证渠道链路
- WhatsApp 需要二维码配对，并会存储更多状态，部署前应考虑状态管理
- WeChat 插件仅支持私聊，规划群聊场景时不可假设其支持群会话

### 7.2 会话与访问控制建议

- 默认按发送者创建独立会话，适合降低串话风险
- 建议优先配置访问控制白名单
- 建议优先配置群组 @ 提及规则

### 7.3 配置安全与校验

- `configure` 会校验 token、password 与 `gateway.auth.mode` 的一致性
- token SecretRef 无法解析时，会阻止 daemon 安装
- 推荐使用 `config validate`
- 推荐结合 `--dry-run` 进行检查
- 不支持 SecretRef 的配置表面会拒绝写入
- `--allow-exec` 仅可用于 dry-run

### 7.4 模型调用成本与风险

- `models status --probe` 会产生真实调用成本
- 同时存在速率限制风险

### 7.5 渠道差异说明

- 群组、媒体、reaction 支持因渠道而异
- BlueBubbles 编辑功能在 macOS 26 Tahoe 上损坏
- 不同渠道能力不能在未验证前默认等同

### 7.6 路由与投递边界

需要特别注意：`agent` 中的 `--channel`、`--reply-channel`、`--reply-account` 仅影响回复投递，不影响会话路由。

## 8. 已确认信息与未明确说明

### 8.1 已确认信息

以下内容在提供的事实来源中已明确给出：

- OpenClaw 的定位是 AI 智能体 Gateway 网关
- Gateway 是会话、路由和渠道连接的唯一事实来源
- 支持多渠道接入、多智能体路由、工具系统、模型提供商接入、Web 控制界面与运维能力
- 已给出安装方式、快速开始命令、配置入口、关键配置项、模型与工具相关命令
- 已给出若干最佳实践和限制说明

### 8.2 未明确说明

以下内容在当前事实来源中未被明确说明，使用时不得自行补充细节：

- MCP 的完整定义、专门入口、配置步骤与示例
- `/platforms` 页面细节
- Gateway 专章下更细的部署、安全、故障排查全文
- 各渠道单页逐项参数说明
- 控制界面具体菜单层级与字段级 UI 说明
- Docker / Kubernetes / VPS 等部署路径完整细节

## 9. 面向项目成员的速读结论

如果团队只需快速建立整体认识，可按以下顺序理解 OpenClaw：

1. 它本质上是一个连接聊天渠道与智能体的 Gateway
2. Gateway 是会话、路由、渠道连接的统一中心
3. 使用上先完成安装、onboard、渠道登录与 Gateway 启动
4. 再通过配置文件、`configure`、`config` 或 Web 控制界面完成模型、工具和渠道配置
5. 如果进入多角色协作场景，再使用多智能体命令进行工作区、模型和渠道绑定
6. 对于 MCP、细粒度部署、安全细节和 UI 菜单说明，当前资料中均未明确说明，应避免主观扩展
