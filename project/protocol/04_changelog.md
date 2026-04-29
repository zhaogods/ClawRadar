# 变更记录

## 1. 本轮变更定位
本轮回写的是当前仓库中已经真实落地、并且可以通过代码、目录结构和定向测试核对的事实；不写未实现方案，不提前记账。

## 2. 本轮已完成且已落地的事实
### 2.1 已完成 `radar_engines` 第一轮外壳剥离
- `radar_engines/` 已移除旧平台外壳目录：`ForumEngine`、`InsightEngine`、`SingleEngineApp`、`SentimentAnalysisModel`；
- 旧入口脚本、旧模板目录、旧测试目录与旧报告脚本已从当前运行边界剥离；
- 当前仓库在 `radar_engines/` 下只保留四个核心引擎：`MindSpider`、`QueryEngine`、`MediaEngine`、`ReportEngine`，以及共享基础设施 `config.py`、`utils/`、`static/`。

### 2.2 已完成项目文档对齐
- [`README.md`](README.md) 已重写为当前实际结构说明；
- 文档已明确 `clawradar/` 是统一编排主线，`radar_engines/` 是当前保留的能力层；
- 文档已明确现阶段四引擎整体保留，不做内部子功能裁剪。

### 2.3 已完成 `real_source` / `user_topic` 的 P0 增强
- [`clawradar/real_source.py`](clawradar/real_source.py) 已完成 `real_source` 默认源扩展与默认上限提升；
- `real_source` 已改为多来源轮转合并；
- `user_topic` 已改为 Tavily / Bocha / Anspire 多 Provider 融合；
- `user_topic_context.applied_source_ids` 已记录全部实际参与 Provider。

### 2.4 已新增并通过 P0 定向测试
- 已新增 [`tests/test_clawradar_real_source_p0.py`](tests/test_clawradar_real_source_p0.py)；
- 已验证以下三类行为：
  - `real_source` 多源轮转合并
  - `user_topic` 多 Provider 融合
  - 多 Provider 上下文回填
- 定向测试命令 `python -m unittest tests.test_clawradar_real_source_p0 -v` 已通过。

### 2.5 已修正 `project/reports/` 版本控制边界
- `project/reports/` 曾被误推送到远端；
- 当前已从版本控制移除；
- [`.gitignore`](.gitignore) 已加入 `project/reports/`，后续默认不再推送；
- 本地 `project/reports/` 目录继续保留，作为本地分析目录使用。

## 3. 本轮未发生且不得越界写成已完成的事项
- 本轮未进行四引擎内部子功能裁剪；
- 本轮未对 `ReportEngine` 内部兼容层做删除；
- 本轮未完成 `real_source` / `user_topic` 的 P1 能力；
- 本轮未形成新的对外运行手册、回放手册或新增验收包；
- 本轮未把本地 `project/reports/` 重新纳入远端协议材料。

## 4. 当前阶段性结论
- 第一轮“外壳剥离”已经完成；
- 当前阶段已经转入“边界固化 + P1 增强”；
- 后续重点不再是继续大删目录，而是建立依赖图并增强输入层能力。