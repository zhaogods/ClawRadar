# radar_engines 四引擎原有功能分析报告

生成时间：2026-04-19

## 1. 报告目的

本报告基于当前仓库 `radar_engines/` 中保留的四个核心引擎：

- `MindSpider`
- `QueryEngine`
- `MediaEngine`
- `ReportEngine`

目标是回答四个问题：

1. 每个引擎原本负责什么；
2. 当前主线 `clawradar/` 实际调用了它们的哪些功能；
3. 哪些能力当前只是整体保留、但尚未被主线直接触达；
4. 在当前“先保留四引擎整体，再做剥壳”的策略下，后续应如何处理。

---

## 2. 总体结论

当前 `radar_engines` 已从旧平台外壳中剥离出四个保留引擎，但主线对它们的使用并不平均：

- `MindSpider`：当前主线明确使用的是 `BroadTopicExtraction` 的热点采集能力。
- `QueryEngine`：当前主线明确使用的是搜索工具层，尤其是按主题检索最近一周新闻的能力。
- `MediaEngine`：当前主线明确使用的是多模态搜索工具层，尤其是 `Bocha` 和 `Anspire` 的最近一周搜索能力。
- `ReportEngine`：当前主线明确使用的是报告生成主入口 `create_agent()` / `generate_report()`。

换句话说，四个引擎都在用，但当前真正直接接入主链路的，是它们各自的“最核心入口子集”，而不是整个引擎内部全部能力。

---

## 3. MindSpider 分析

### 3.1 原有定位

`MindSpider` 是一套围绕“热点发现 + 内容深爬”的采集型引擎。按目录结构和现有代码看，它至少包含两层能力：

1. `BroadTopicExtraction`
   - 面向来源榜单的热点抓取与话题提取；
   - 典型入口是 `get_today_news.py`；
   - 当前主线实际接入的就是这一层。

2. `DeepSentimentCrawling`
   - 面向社媒/平台内容的进一步深爬；
   - 还带有数据库、平台 crawler、结构化存储等能力；
   - 当前主线没有直接接入这一层。

### 3.2 当前主线使用情况

主线通过 [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py) 动态导入 `MindSpider.BroadTopicExtraction.get_today_news`。

关键代码：

- `clawradar.real_source._load_mindspider_module()`
- `clawradar.real_source._collect_mindspider_news()`
- `clawradar.real_source._load_source_driven_payload()`

具体导入位置：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L101)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L140)

MindSpider 内部当前主线实际触发的函数：

- `NewsCollector.get_popular_news()`
- [get_today_news.py](F:/02_code/ClawRadar/radar_engines/MindSpider/BroadTopicExtraction/get_today_news.py#L122)

### 3.3 当前实际承担的角色

当前它承担的是：

- 按来源榜单抓热点；
- 输出候选新闻条目；
- 供 `real_source` 模式转换为统一的 `topic_candidates`。

### 3.4 当前未被主线直接用到的能力

- `DeepSentimentCrawling` 深爬链路；
- 数据库相关能力；
- 更完整的 MindSpider 主程序和初始化流程；
- 可能存在的话题抽取后的后处理链路。

### 3.5 结论

MindSpider 当前是“热点发现层”，不是完整舆情采集平台在主链路中的全量复用。主线只取了它最靠前的榜单热点抓取入口。

---

## 4. QueryEngine 分析

### 4.1 原有定位

`QueryEngine` 是面向新闻和信息检索的搜索引擎，围绕 Tavily 工具集封装了一组不同粒度的新闻搜索能力。

从工具定义可见，它原有能力至少包括：

- `basic_search_news`
- `deep_search_news`
- `search_news_last_24_hours`
- `search_news_last_week`
- `search_images_for_news`
- `search_news_by_date`

这些都定义在：

- [search.py](F:/02_code/ClawRadar/radar_engines/QueryEngine/tools/search.py)

### 4.2 当前主线使用情况

主线通过 [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py) 动态导入 `QueryEngine.tools.search`。

关键代码：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L113)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L462)

当前主线明确使用的具体功能：

- `TavilyNewsAgency.search_news_last_week(query)`
- [search.py](F:/02_code/ClawRadar/radar_engines/QueryEngine/tools/search.py#L161)

### 4.3 当前实际承担的角色

当前它承担的是：

- 在 `user_topic` 模式下围绕主题生成检索结果；
- 为主题驱动抓取提供一周内相关新闻结果；
- 作为主题驱动候选发现的一个 provider。

### 4.4 当前未被主线直接用到的能力

- 深度新闻分析能力 `deep_search_news`；
- 24 小时内新闻搜索；
- 图片搜索；
- 按日期范围搜索；
- `QueryEngine.agent` 那套更完整的 Agent 推理链；
- 内部 prompts / nodes / state 所构成的完整智能体工作流。

### 4.5 结论

QueryEngine 当前不是以“完整搜索 Agent”身份被主线调用，而是被裁成了“主题检索 provider”的一个工具层入口。

---

## 5. MediaEngine 分析

### 5.1 原有定位

`MediaEngine` 是多模态搜索与媒体检索引擎。它在原始设计中不只是一个普通 web search 封装，而是面向“更丰富的媒体搜索能力”构建的工具集。

当前可见的核心搜索类包括：

- `BochaMultimodalSearch`
- `AnspireAISearch`

工具定义位置：

- [search.py](F:/02_code/ClawRadar/radar_engines/MediaEngine/tools/search.py)

### 5.2 当前主线使用情况

主线通过 [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py) 动态导入 `MediaEngine.tools.search`。

关键代码：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L125)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L482)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L502)

当前主线明确使用的具体功能：

- `BochaMultimodalSearch.search_last_week(query)`
  - [search.py](F:/02_code/ClawRadar/radar_engines/MediaEngine/tools/search.py#L260)
- `AnspireAISearch.search_last_week(query, max_results)`
  - [search.py](F:/02_code/ClawRadar/radar_engines/MediaEngine/tools/search.py#L357)

### 5.3 当前实际承担的角色

当前它承担的是：

- 作为 `user_topic` 的补充搜索 provider；
- 在 QueryEngine 之外提供另一套搜索结果来源；
- 提供更偏媒体/网页层面的候选补充。

### 5.4 当前未被主线直接用到的能力

- `search_last_24_hours`；
- 更完整的多模态搜索工具组合；
- `MediaEngine.agent` 的完整 Agent 流程；
- 节点、状态、prompts 等完整推理链。

### 5.5 结论

MediaEngine 当前在主线中的角色和 QueryEngine 类似，但偏向“第二搜索通道”。主线复用的是其搜索工具，不是其完整 Agent 框架。

---

## 6. ReportEngine 分析

### 6.1 原有定位

`ReportEngine` 是四个引擎中最重的一层，负责把输入材料组织成正式报告产物。它不只是一个纯字符串生成器，而是一整套报告生成管线，包含：

- LLM 客户端；
- 模板切片与章节规划；
- 章节生成；
- IR 装订；
- HTML / Markdown / PDF 渲染；
- 状态管理和落盘；
- 校验和修复工具。

### 6.2 当前主线使用情况

主线通过 [writing.py](F:/02_code/ClawRadar/clawradar/writing.py) 动态导入：

- `ReportEngine.agent`
- `radar_engines.ReportEngine.agent`
- `BettaFish.ReportEngine.agent`

关键代码：

- [writing.py](F:/02_code/ClawRadar/clawradar/writing.py#L321)

主线实际取用的入口是：

- `create_agent()`
- [agent.py](F:/02_code/ClawRadar/radar_engines/ReportEngine/agent.py#L1534)

主线最终调用的方法是：

- `ReportAgent.generate_report()`
- [agent.py](F:/02_code/ClawRadar/radar_engines/ReportEngine/agent.py#L406)

`ReportAgent` 自身作为完整报告总控类定义在：

- [agent.py](F:/02_code/ClawRadar/radar_engines/ReportEngine/agent.py#L175)

### 6.3 当前实际承担的角色

当前它承担的是：

- `external_writer` 的正式执行器；
- 接收 `query + reports + forum_logs + custom_template`；
- 生成 HTML / IR / 状态文件等正式写作产物；
- 返回 `writer_receipt` 和报告落盘路径，供上层流程归档。

### 6.4 当前未被主线直接用到的能力

尽管 ReportEngine 整体保留，但当前主线并没有直接接入它的全部能力，例如：

- Flask 接口；
- 内部图表修复与图表审查链；
- 更完整的 PDF 导出链；
- 旧多引擎报告聚合兼容逻辑；
- 旧平台式界面和接口层。

这些功能很多仍然存在于目录中，但并不等于当前主线直接依赖它们。

### 6.5 结论

ReportEngine 当前是四引擎里“最完整被复用”的一个，但即便如此，主线真正调用的仍然只是它的正式写作入口，而不是旧平台式周边接口。

---

## 7. 四引擎当前主线接入对照表

| 引擎 | 当前主线接入的具体入口 | 当前角色 | 是否完整复用 |
|---|---|---|---|
| `MindSpider` | `BroadTopicExtraction.get_today_news -> NewsCollector.get_popular_news()` | 热点发现 | 否 |
| `QueryEngine` | `TavilyNewsAgency.search_news_last_week()` | 主题检索 provider | 否 |
| `MediaEngine` | `BochaMultimodalSearch.search_last_week()` / `AnspireAISearch.search_last_week()` | 多模态检索 provider | 否 |
| `ReportEngine` | `create_agent()` / `ReportAgent.generate_report()` | 正式写作执行器 | 相对最完整，但仍非全量 |

---

## 8. 当前剥壳策略下的判断

在当前策略“先完整保留四引擎整体，再做细分”下，四个引擎都不应继续做内部删除。

原因如下：

1. 当前主线只使用了它们的核心入口，但这些入口往往依赖引擎内部其他模块和共享结构；
2. 目前尚未完成“功能内迁”，仍处于“主链路调用旧引擎能力”的阶段；
3. 过早删除内部能力，容易破坏运行边界，尤其是 `ReportEngine` 和 `MindSpider`。

因此现阶段更合理的做法是：

- 保持四引擎整体完整；
- 继续识别“主链路直接调用的核心子集”；
- 后续再以“引擎内部调用图”为依据，判断哪些模块是纯兼容层，哪些是必须运行依赖。

---

## 9. 对后续阶段的建议

### 9.1 MindSpider

建议后续单独区分：

- 热点榜单抓取最小运行子集；
- 深爬与数据库子集；
- 是否需要在主项目内重构成独立 source provider。

### 9.2 QueryEngine / MediaEngine

建议后续统一处理为“搜索 provider 层”：

- 明确当前主线到底只需要哪些搜索接口；
- 把 `last_week` / `last_24_hours` / 图片搜索等能力整理成可配置 provider；
- 避免继续依赖完整 Agent 框架。

### 9.3 ReportEngine

建议后续先做“接口边界收缩”，而不是立刻删内部文件：

- 先明确 `create_agent()` / `generate_report()` 的最小依赖图；
- 再判断 Flask 接口、旧多引擎兼容逻辑、图表修复链中哪些属于纯兼容保留；
- 最后再决定是否拆出真正的最小写作运行时。

---

## 10. 最终结论

当前 `radar_engines` 四个保留引擎的状态可以概括为：

- `MindSpider`：热点采集层，主线只用到 BroadTopicExtraction 的榜单抓取入口；
- `QueryEngine`：新闻搜索层，主线只用到一周新闻搜索工具；
- `MediaEngine`：多模态搜索层，主线只用到 Bocha / Anspire 的一周搜索能力；
- `ReportEngine`：正式写作层，主线通过 `create_agent()` / `generate_report()` 复用其报告生成管线。

因此，当前最合理的剥壳口径不是“哪些功能没直接被主线调用就先删掉”，而是：

- 先完整保留四引擎整体；
- 先剥掉旧平台外壳；
- 再基于引擎内部依赖图做第二轮精细瘦身。
