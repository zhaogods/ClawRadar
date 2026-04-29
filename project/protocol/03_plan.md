# OpenClaw 下一阶段执行计划

## 1. 计划定位
本文档用于在阶段十历史基线之上，明确区分三类内容：
- 哪些能力属于阶段十已经完成的历史基线；
- 哪些能力属于本轮已经落地并已由实现与测试核对的新增事实；
- 哪些事项仍然保留为后续补齐或增强方向。

本文档不把阶段十历史材料改写为本轮新增能力证明，也不把尚未核实的后续目标提前写成既成事实。

## 2. 当前事实分层
### 2.1 阶段十已完成基线
当前仓库已经具备以下历史基线事实：
- 已有统一编排主入口 [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398)；
- 已有 ingest、score、write、deliver 主链路；
- 已有最小真实来源接入路径；
- 已有原项目既有报告撰写接入路径；
- 已有 `archive_only` 本地留档与阶段十演示材料包；
- 已有 `entry_options` 与 `entry_resolution` 作为内部统一入口口径。

### 2.2 本轮新增完成事实
基于当前实现状态，以下能力已经从计划项转化为已完成事实：
- `radar_engines/` 已完成第一轮外壳剥离，只保留四个核心引擎：`MindSpider`、`QueryEngine`、`MediaEngine`、`ReportEngine`，以及共享基础设施 `config.py`、`utils/`、`static/`；
- 旧平台外壳 `ForumEngine`、`InsightEngine`、`SingleEngineApp`、`SentimentAnalysisModel` 及旧入口脚本、旧模板、旧测试已经从主仓库当前运行边界中剥离；
- [`README.md`](README.md) 已完成与当前四引擎保留边界、统一编排结构和输入模式的重新对齐；
- [`clawradar/real_source.py`](clawradar/real_source.py) 已完成 `real_source` / `user_topic` 的 P0 增强：
  - `real_source` 默认源从 `("weibo",)` 扩展为 `("weibo", "zhihu", "36kr")`
  - `real_source` 默认候选上限从 `5` 提升到 `10`
  - `real_source` 改为多来源轮转合并，而不是前序来源吃满 quota
  - `user_topic` 改为 Tavily / Bocha / Anspire 多 Provider 融合，而不是首个成功即返回
  - `user_topic_context.applied_source_ids` 记录全部实际参与 Provider
- 已新增 [`tests/test_clawradar_real_source_p0.py`](tests/test_clawradar_real_source_p0.py)，并通过 `python -m unittest tests.test_clawradar_real_source_p0 -v` 验证 3 个 P0 定向测试全部通过；
- `project/reports/` 已被明确降级为仅本地分析目录，不再纳入版本控制，且已通过 [`.gitignore`](.gitignore) 收口为忽略目录。

### 2.3 仍待后续补齐事项
以下内容仍保留为后续工作，不得写成本轮已完成事实：
- 四引擎内部最小运行依赖图仍未完全梳理完成，当前只是完成了第一轮外壳剥离；
- `real_source` / `user_topic` 当前只完成了 P0，多源召回已经增强，但统一去重、聚类、多样性排序、补搜与二跳补证据仍属于 P1；
- `ReportEngine` 当前仍整体保留，内部兼容逻辑、静态资源依赖与最小运行边界仍需后续评估，不得提前写成可删事实；
- `project/reports/` 当前只保留本地使用，不再作为远端协议材料或交付物的一部分；
- 面向真实使用者的总启动门面、运行说明、工件回放说明与新增验收材料仍需继续收口。

## 3. 当前阶段总览
| 项目 | 当前状态 | 依据 | 后续动作 |
|---|---|---|---|
| 统一编排核心 | 已完成基线 | [`topic_radar_orchestrate()`](clawradar/orchestrator.py:1398) | 继续作为唯一主编排核心 |
| 四引擎整体保留 | 本轮已完成边界收缩 | [`README.md`](README.md)、[`radar_engines/`](radar_engines) | 后续只做依赖评估，不做盲删 |
| 旧平台外壳删除 | 本轮已完成 | 当前仓库目录结构 | 不回滚，转入边界固化 |
| `real_source` / `user_topic` P0 | 本轮已完成 | [`clawradar/real_source.py`](clawradar/real_source.py)、[`tests/test_clawradar_real_source_p0.py`](tests/test_clawradar_real_source_p0.py) | 进入 P1 增强 |
| `project/reports/` 本地化 | 本轮已完成 | [`.gitignore`](.gitignore) | 保持本地分析用途，不再推送 |
| P1 输入层增强 | 仍待后续 | 当前计划 | 继续补去重、聚类、补搜、多样性排序 |
| `ReportEngine` 最小依赖图 | 仍待后续 | 当前计划 | 做依赖收缩评估，不直接删模块 |

## 4. 下一阶段执行重点
### 4.1 四引擎边界固化
- 输出四引擎最小运行边界清单；
- 区分主线直接调用、引擎内部间接依赖、纯兼容保留与历史残留；
- 为下一轮精细瘦身建立依赖依据。

### 4.2 输入层 P1 增强
- 给 `real_source` 增加跨源去重、候选聚类与来源多样性排序；
- 给 `user_topic` 增加结果不足时的补搜与 query 扩展；
- 评估是否给热点候选增加新闻 / 网页二跳补证据；
- 把当前 P0 定向测试扩展为更完整的输入层回归测试。

### 4.3 `ReportEngine` 依赖评估
- 梳理 [`clawradar/writing.py`](clawradar/writing.py) 到 `ReportEngine.agent.create_agent()` 的最小依赖链；
- 识别 `static/`、模板、状态管理、chart repair 相关模块中哪些是实际运行依赖；
- 暂不删除内部模块，只输出依赖图与可移出候选清单。

## 5. 当前完成判断
截至当前轮次，以下事项可以判定为完成：
- `radar_engines` 已完成第一轮外壳剥离，当前运行边界缩减到四引擎加共享基础设施；
- `README.md` 已与当前结构重新对齐；
- `real_source` 与 `user_topic` 已完成 P0 多源融合增强；
- `project/reports/` 已从版本控制中移除并被忽略；
- 项目下一阶段方向已经从“继续删目录”切换到“边界固化 + P1 增强”。

以下事项仍保留为后续完成标准：
- 四引擎最小运行依赖图；
- `real_source` / `user_topic` P1 实现；
- `ReportEngine` 最小依赖评估与兼容层清单；
- 面向真实使用者的稳定运行说明与回放文档。