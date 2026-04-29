# real_source 与 user_topic 增强方案报告

生成时间：2026-04-19

## 1. 报告目的

本报告围绕当前统一入口中的两个核心输入模式：

- `real_source`
- `user_topic`

目标是回答五个问题：

1. 当前两个模式分别如何工作；
2. 当前能力短板在哪里；
3. 为什么会出现数据来源单一、结果单薄的问题；
4. 如何按 P0 / P1 / P2 分阶段增强；
5. 每项增强对应应该落在哪些代码位置。

---

## 2. 当前模式现状

### 2.1 real_source 当前现状

`real_source` 当前走的是来源驱动抓取分支：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L275)

其逻辑是：

1. 从 `source_ids` 读取来源；
2. 调用 `MindSpider` 的热点采集能力；
3. 把抓回来的榜单项映射成统一的 `topic_candidates`；
4. 再交给主链路后续阶段处理。

当前默认 CLI 参数：

- `--input-mode real_source`
- `--source-ids weibo`
- `--limit 5`
- [run_openclaw_deliverable.py](F:/02_code/ClawRadar/run_openclaw_deliverable.py#L16)

这意味着当前默认行为天然偏向：

- 单来源；
- 小样本；
- 热点榜单驱动。

### 2.2 user_topic 当前现状

`user_topic` 当前不是独立实现抓取，而是先做输入规范化，再委托给 `real_source` 的 topic-driven 分支。

入口在：

- [topics.py](F:/02_code/ClawRadar/clawradar/topics.py#L196)

委托落点在：

- [topics.py](F:/02_code/ClawRadar/clawradar/topics.py#L219)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L680)

其逻辑是：

1. 从 `topic / company / track / keywords` 组装主题上下文；
2. 构造一个搜索 query；
3. 依次尝试 Tavily、Bocha、Anspire；
4. 只要某个 provider 有结果，就直接返回；
5. 把搜索结果映射成 `topic_candidates`。

当前 provider 尝试逻辑在：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L622)

当前返回逻辑的关键问题在：

- 首个 provider 有结果即直接 `return`
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L664)

这决定了它当前并不是“多源融合检索”，而更像“按优先级挑一个能用的 provider”。

---

## 3. 当前短板分析

### 3.1 real_source 的短板

1. 默认来源过少
   - 当前 CLI 默认 `source_ids=["weibo"]`；
   - 会让热点视角天然偏微博。

2. 配额分配不合理
   - 当前抓取逻辑一旦候选数量达到 `limit` 就提前停止；
   - [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L338)
   - [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L341)
   - 导致前面来源可能吃掉全部 quota，后面来源没有机会。

3. 只有榜单抓取，没有热点扩证
   - 当前抓到榜单项后，直接映射候选事件；
   - 没有用 `QueryEngine` / `MediaEngine` 对热点做二跳补证据。

4. 没有事件聚类和来源多样性约束
   - 多来源情况下，可能出现相同事件重复进入；
   - 当前没有系统化的跨源去重和聚类。

### 3.2 user_topic 的短板

1. query 过于单一
   - 当前 query 只是把主题上下文拼成一条搜索语句；
   - 无法覆盖不同研究角度。

2. provider 策略过于保守
   - 当前是首个成功即返回；
   - 没有把 Tavily / Bocha / Anspire 合并后再筛选。

3. 缺少多轮召回
   - 当前只做一轮搜索；
   - 没有针对“结果不足”“结果重复”“来源偏单一”触发补搜。

4. 缺少热点池协同
   - 当前 `user_topic` 主要依赖搜索；
   - 没有把 `MindSpider` 热点池作为第二条召回来源接入。

---

## 4. 增强目标

增强后的两个模式，不应该被做成同一种模式，而应该保留各自语义：

- `real_source`：从“来源榜单”出发发现热点；
- `user_topic`：从“主题意图”出发发现事件。

但它们应该共用一套更强的能力内核：

1. 多源召回；
2. 候选归一化；
3. 跨源去重；
4. 事件聚类；
5. 来源多样性排序；
6. 二跳补证据；
7. 最终候选装配。

---

## 5. P0 / P1 / P2 改造方案

## 5.1 P0：最先落地，直接解决单一问题

### P0-1 real_source 改成默认多来源

目标：

- 不再默认只抓 `weibo`；
- 改成多来源组合，例如社媒、新闻、综合来源包。

落点：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L14)
- [run_openclaw_deliverable.py](F:/02_code/ClawRadar/run_openclaw_deliverable.py#L22)

建议：

- 引入默认来源集合，而不是单值；
- 同时支持调用侧显式覆盖。

### P0-2 real_source 改成配额合并

目标：

- 不再由先到先得的来源吃掉全部候选位；
- 改成每个来源先取固定配额，再统一合并和截断。

落点：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L293)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L338)

建议：

- 先按 source 维度暂存候选；
- 再 round-robin 合并；
- 最后统一去重和截断。

### P0-3 user_topic 改成多 provider 融合

目标：

- 不再首个 provider 成功即返回；
- Tavily / Bocha / Anspire 并行或顺序全量收集后统一融合。

落点：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L622)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L664)

建议：

- 保留 provider 尝试列表；
- 但不在首个成功处 return；
- 改为收集全部 provider 结果，再统一去重、打分、截断。

### P0-4 提高默认候选上限

目标：

- 当前 `limit=5` 太小，不利于多源融合；
- 把默认候选数量提高到更实用的范围。

落点：

- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L15)
- [real_source.py](F:/02_code/ClawRadar/clawradar/real_source.py#L17)
- [run_openclaw_deliverable.py](F:/02_code/ClawRadar/run_openclaw_deliverable.py#L23)

建议：

- 默认提升到 10 或 15；
- 后续再根据去重和聚类结果截断为更稳定的输出。

---

## 5.2 P1：让结果从“能跑”变成“可用”

### P1-1 增加统一去重和事件聚类

目标：

- URL 去重；
- 标题相似度聚类；
- 事件级归一化；
- 防止重复候选淹没结果。

适用模式：

- `real_source`
- `user_topic`

建议位置：

- 新建 `clawradar/engines/sources/merge.py` 或同类融合层；
- 不建议继续把这类逻辑塞回 `real_source.py` 一个文件中。

### P1-2 增加来源多样性排序

目标：

- 同域名不超过固定条数；
- 同 provider 不超过固定条数；
- 优先保留跨源重复验证的候选。

作用：

- 解决“虽然抓了多源，但最终仍被单域名主导”的问题。

### P1-3 给 real_source 增加二跳补证据

目标：

- `MindSpider` 只负责发现热点；
- 对前 N 个热点，再调用：
  - `QueryEngine` 新闻搜索
  - `MediaEngine` 多模态搜索
- 把榜单热点扩成有证据层次的事件包。

作用：

- 让 `real_source` 不再只是热点标题列表，而是更接近可评分事件输入。

### P1-4 给 user_topic 增加失败补搜与空结果补搜

目标：

- 首轮结果为空时自动扩搜；
- 首轮结果过少时自动补搜；
- 首轮来源过单一时自动触发第二轮。

补搜方向可以包括：

- 最近 24 小时新闻；
- 最近一周新闻；
- 图片相关搜索；
- 指定日期范围搜索。

---

## 5.3 P2：把两个模式升级成“真正强”的入口

### P2-1 给 user_topic 增加 query planner

目标：

- 不再只拼一条 query；
- 根据输入上下文自动展开多组查询。

建议查询类型：

- 主题主查询；
- 公司主查询；
- 主题 + 公司；
- 主题 + 关键词；
- 主题 + 风险 / 政策 / 产品 / 融资；
- 竞品对照查询。

### P2-2 给 user_topic 接入 MindSpider 热点池

目标：

- 让 `user_topic` 不只有搜索引擎视角；
- 同时拥有热点池匹配视角。

方式：

- 一边做主题搜索；
- 一边抓 `MindSpider` 热点池；
- 用关键词 / 实体 / 标题相似度匹配与主题相关的热点；
- 最后融合两路候选。

### P2-3 构建统一“检索编排内核”

目标：

- 不让 `real_source` 和 `user_topic` 各自野生增长；
- 让二者共享：
  - recall
  - normalize
  - dedupe
  - cluster
  - rerank
  - enrich

这样：

- `real_source` 只定义召回起点是来源榜单；
- `user_topic` 只定义召回起点是主题意图；
- 后续处理逻辑统一复用。

---

## 6. 推荐实施顺序

### 第一阶段

优先做：

1. `user_topic` 多 provider 融合；
2. `real_source` 多来源默认值；
3. `real_source` 配额合并；
4. 默认候选上限提升。

原因：

- 这四项对结果单一问题最直接；
- 改动范围相对可控；
- 能显著改善当前体验。

### 第二阶段

继续做：

1. 统一去重与聚类；
2. 来源多样性排序；
3. real_source 二跳补证据；
4. user_topic 补搜。

### 第三阶段

最后做：

1. query planner；
2. `user_topic + MindSpider` 双路召回；
3. 统一检索编排内核抽象。

---

## 7. 验收标准

增强完成后，至少应满足：

### real_source

- 默认不再只有单来源；
- 多来源结果不会被首个来源完全占满；
- 输出结果中来源分布更均衡；
- 热点事件具备更丰富的补证据信息。

### user_topic

- 不再是首个 provider 成功即返回；
- 同一主题能同时融合 Tavily / Bocha / Anspire 的结果；
- 结果中域名、来源和 provider 分布更丰富；
- 对于冷门主题也能通过补搜提高召回。

---

## 8. 最终建议

如果只允许做一轮增强，最值得优先投入的是：

1. `user_topic` 多 provider 融合；
2. `real_source` 多来源默认值 + 配额合并。

这是当前 ROI 最高、最能直接解决“数据单一”的两项改造。

如果允许再做第二轮，则继续把：

- 去重
- 聚类
- 多样性排序
- 二跳补证据

补上，两个模式就会从“能跑”升级到“真正可用”。
