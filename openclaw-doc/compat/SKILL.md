---
name: openclaw-workflow-legacy
description: 旧版根目录 skill 草案保留页；正式 skill 请使用 skills/openclaw-topic-radar/SKILL.md。
---

# 根目录旧版 Skill 说明

本文件不再作为当前项目的正式 skill 入口。

正式 skill 资产已收口到：

- [`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)

保留本文件的目的只有两个：

1. 说明仓库里为什么同时存在根目录 [`SKILL.md`](SKILL.md) 与正式 skill 目录；
2. 避免继续误用旧草案中的过期路径、过期模式说明与旧入口假设。

## 为什么不继续复用根目录 [`SKILL.md`](SKILL.md)

旧版根目录草案存在以下问题：

- 假定工作目录仍是旧路径；
- 没有覆盖当前已成立的 `user_topic`、`inline_topic_cards`、`crawl_only`、`topics_only`、`write_only`、`resume`；
- 容易让调用方误以为 skill 可以绕开统一入口自行拼装流程；
- 不符合正式 skill 资产应放在 `skills/<skill-name>/SKILL.md` 下的收口方式。

## 当前正式口径

当前项目真实统一入口仍是 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)。

正式 skill 只负责外层组织调用，**不创建新的平行顶层编排**、**不引入新的包装脚本**、**不替代统一入口本身**。

如需实际调用说明，请优先阅读：

- 正式 skill：[`skills/openclaw-topic-radar/SKILL.md`](skills/openclaw-topic-radar/SKILL.md)
- 项目使用文档：[`使用.md`](使用.md)
