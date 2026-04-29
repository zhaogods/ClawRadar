# radar_engines 下一步剥壳方案报告

生成时间：2026-04-20

## 1. 报告目的

本报告用于明确 `radar_engines` 的下一阶段剥壳方案，并吸收最新的目录规范结论。

当前约束已经明确：

- 四个原有引擎继续完整保留
  - `MindSpider`
  - `QueryEngine`
  - `MediaEngine`
  - `ReportEngine`
- 四个引擎内部子功能暂不裁剪
- 下一阶段不以“删功能”为优先，而以“解耦、壳层化、统一接入”为优先
- 在继续推进引擎剥壳之前，应优先规范 `/outputs` 输出目录结构
- 输出目录规范应坚持“最简可读”，避免再次引入复杂层级

因此，下一步工作不再只是继续拆 `radar_engines`，而是先建立一个更清晰的系统外壳：

- 对内：统一四引擎接入方式
- 对外：统一 `/outputs` 输出协议

---

## 2. 当前问题判断

从现状看，当前项目的主要问题已经不只是引擎耦合，还包括输出结构本身不够直观。

### 2.1 引擎侧问题

当前 `radar_engines` 的主要风险包括：

1. 模式层、编排层、引擎实现层边界不清晰。
2. 引擎能力的调用方式不统一，不利于后续替换和裁剪。
3. 配置、模型、输出路径、依赖关系容易散落在引擎内部。
4. 后续若直接删除子功能，容易引发链式回归。
5. `real_source` 和 `user_topic` 的能力装配关系尚未完全标准化。

### 2.2 输出侧问题

`/outputs` 目前也存在明显问题：

1. 嵌套层级过深，不直观。
2. 一次运行的关键信息分散在多个目录中。
3. 原始运行、补救运行、审计信息混在一起，阅读成本高。
4. 对人工排查不友好，必须频繁进入 `meta / stages / reports / events` 多层目录。
5. 当前结构更像程序内部存储结构，而不是面向人阅读的结果目录。

因此，当前阶段的正确顺序应调整为：

1. 先规范 `/outputs`
2. 再统一引擎壳层
3. 再迁移模式接入方式
4. 最后才进入子功能裁剪

---

## 3. 下一阶段总目标

下一阶段的目标分为两个部分。

### 3.1 外部目标：输出结构先变简单

先把 `/outputs` 从“深层、分散、混合职责的运行目录”收敛成“按模式分组、按运行聚合、面向人阅读”的最简输出协议。

### 3.2 内部目标：四引擎再壳层化

在输出协议收敛后，再把 `radar_engines` 从“被业务代码直接调用的一组引擎目录”，升级为“有统一能力接口、统一注册、统一装配的引擎层”。

### 3.3 阶段验收目标

建议采用以下验收标准：

1. `real_source` 和 `user_topic` 的行为保持不变。
2. 四个引擎完整保留。
3. `/outputs` 目录结构明显变浅，人工可直观定位结果。
4. 模式层不再继续新增对引擎内部实现的直接依赖。
5. 后续进入子功能裁剪时，能够按引擎、按能力点逐步下刀。

---

## 4. 第一优先级：先规范 /outputs

这是当前最新调整后的优先事项，优先级高于继续剥四个引擎。

### 4.1 为什么要前置处理 `/outputs`

原因很直接：

1. `/outputs` 横跨模式层、编排层、写作层、交付层、恢复层。
2. 如果先剥引擎，再改输出协议，后面还会重复改一次。
3. 当前最大主观痛点不是引擎数量，而是输出目录“看不懂、找不快、层级太深”。
4. 如果输出协议不先收敛，后续恢复、归档、回归验证都会持续混乱。

因此，`/outputs` 规范应该提升为下一阶段的 `P0`。

### 4.2 输出结构设计原则

新的 `/outputs` 结构建议只坚持四条原则：

1. 顶层只按模式分组。
2. 一次运行只对应一个运行目录。
3. 每次运行只保留四个主入口：`summary / reports / recovery / debug`。
4. 其他复杂性全部下沉到 `debug/`，而不是继续扩散目录层级。

### 4.3 推荐的最简输出结构

建议采用最简版结构：

```text
outputs/
  real_source/
    latest.json
    20260420_0844/
      summary.json
      reports/
      recovery/
      debug/

  user_topic/
    latest.json
    20260419_1808/
      summary.json
      reports/
      recovery/
      debug/
```

如果后续确实需要，也可以保留 `runs/` 这一层，但当前更推荐直接去掉，进一步降低阅读成本。

### 4.4 目录职责定义

#### `outputs/<mode>/latest.json`

只做一件事：告诉使用者“当前模式最新一次运行结果在哪”。

建议字段只保留：

- `latest_run`
- `status`
- `summary_path`

#### `outputs/<mode>/<run_id>/summary.json`

这是最重要的文件。要求做到：

- 看这一份就能判断本次运行是否完成
- 看这一份就能知道是否发生补救
- 看这一份就能知道最终结果在哪里

建议只保留高价值汇总字段：

- `mode`
- `run_id`
- `request_id`
- `status`
- `final_stage`
- `candidate_count`
- `publish_ready_count`
- `write_success_count`
- `deliver_success_count`
- `recovery_used`
- `main_reports_path`

#### `outputs/<mode>/<run_id>/reports/`

只放最终结果，面向人工查看。

不要把中间 IR、调试文件、状态文件继续混进来。

#### `outputs/<mode>/<run_id>/recovery/`

只放补救信息。

建议包含：

- `recovery_summary.json`
- 单事件恢复记录文件

恢复信息继续挂在原始运行目录下，不再单独拆顶层 `recoveries/`。

#### `outputs/<mode>/<run_id>/debug/`

所有低频、程序用、审计用、排障用的内容都统一下沉到这里，例如：

- `input.json`
- `errors.json`
- `crawl.json`
- `ingest.json`
- `topics.json`
- `score.json`
- `write.json`
- `deliver.json`
- `writer_receipts.json`
- `log.txt`

这样主目录将保持非常干净。

### 4.5 这一步建议砍掉的旧概念

为了让结构足够简单，建议在新协议里不再把以下概念暴露为主入口：

1. 不再单独突出 `meta/`
2. 不再单独突出 `stages/`
3. 不再单独突出 `events/`
4. 不再单独新增 `index/`
5. 不再单独新增顶层 `recoveries/`
6. 不再使用 `request_id/run_slug` 双层目录作为主阅读入口

这些信息如果仍有程序需要，可以保留在 `debug/` 内部结构中，但不应继续污染主视图。

### 4.6 run_id 命名建议

建议把运行目录名简化为：

- `YYYYMMDD_HHMM`

例如：

- `20260420_0844`
- `20260419_1808`

而不是继续把 `request_id`、`mode`、`slug` 全堆进目录名。更复杂的身份信息保留在 `summary.json` 中即可。

### 4.7 关键文件字段协议草案

为了避免 `/outputs` 只有目录重构、没有数据协议，建议这一步同时固定三个关键文件。

#### `latest.json` 建议字段

建议仅保留最小字段：

- `mode`
- `latest_run`
- `status`
- `summary_path`

建议示例：

```json
{
  mode: real_source,
  latest_run: 20260420_0844,
  status: completed_with_recovery,
  summary_path: 20260420_0844/summary.json
}
```

#### `summary.json` 建议字段

建议固定为“单次运行总览文件”，最少包含：

- `mode`
- `run_id`
- `request_id`
- `status`
- `final_stage`
- `started_at`
- `completed_at`
- `candidate_count`
- `publish_ready_count`
- `write_success_count`
- `deliver_success_count`
- `recovery_used`
- `main_reports_path`
- `debug_path`

建议示例：

```json
{
  mode: real_source,
  run_id: 20260420_0844,
  request_id: req-real-source-full-001,
  status: completed_with_recovery,
  final_stage: deliver,
  started_at: 2026-04-20T08:44:00Z,
  completed_at: 2026-04-20T08:58:00Z,
  candidate_count: 10,
  publish_ready_count: 10,
  write_success_count: 10,
  deliver_success_count: 10,
  recovery_used: true,
  main_reports_path: reports/,
  debug_path: debug/
}
```

#### `recovery/recovery_summary.json` 建议字段

如果本次运行发生补救，建议固定一个总览文件，而不是只散落单事件恢复记录。

建议至少包含：

- `recovery_used`
- `failed_event_count`
- `recovered_event_count`
- `failed_event_ids`
- `recovered_event_ids`
- `final_status`

建议示例：

```json
{
  recovery_used: true,
  failed_event_count: 1,
  recovered_event_count: 1,
  failed_event_ids: [real-source-weibo-rank-4],
  recovered_event_ids: [real-source-weibo-rank-4],
  final_status: recovered_complete
}
```

### 4.8 旧结构到新结构的合并建议

为了避免后续落地时再次产生理解偏差，建议对当前常见旧目录做明确合并规则：

1. 旧 `meta/run_summary.json` 合并到新 `summary.json`
2. 旧 `meta/errors.json` 下沉到新 `debug/errors.json`
3. 旧 `stages/*` 结果文件下沉到新 `debug/`
4. 旧 `reports/final/` 保留并映射为新 `reports/`
5. 旧单事件恢复结果不再单独作为顶层 request 目录主视图，而应汇总挂到原始运行的 `recovery/`

这一步的目标不是一次性迁移全部历史目录，而是先明确今后的标准写法。

---

## 5. 第二优先级：四引擎整体剥壳

在 `/outputs` 规范之后，再推进四引擎壳层化。

### 5.1 推荐架构方向

建议将整体结构收敛为四层：

1. 模式层
2. 编排层
3. 引擎适配层
4. 引擎运行时层

### 5.2 模式层

负责：

- `real_source`
- `user_topic`
- 后续其他输入模式

模式层只负责模式逻辑、输入来源选择、能力需求声明，不直接依赖具体引擎实现。

### 5.3 编排层

负责：

- `crawl`
- `ingest`
- `topics`
- `score`
- `write`
- `deliver`

编排层负责阶段流转、状态控制、失败恢复、降级策略，但不直接承载具体引擎实现细节。

### 5.4 引擎适配层

这是剥壳的核心。

引擎适配层负责：

- 统一暴露四个引擎的能力入口
- 统一能力契约
- 屏蔽各引擎内部目录差异
- 将模式层和引擎运行时解耦

### 5.5 引擎运行时层

这一层就是现有四个引擎自身：

- `MindSpider`
- `QueryEngine`
- `MediaEngine`
- `ReportEngine`

本阶段原则上不删其子功能，只对其外部接入方式做壳层化。

---

## 6. 四引擎下一步具体方案

### 6.1 先建立“四引擎能力清单”

目标：先把四个引擎各自对外到底提供什么能力说清楚。

建议输出四类能力定义：

#### MindSpider

负责方向：

- 实时源抓取
- 热榜/站点候选采集
- 多来源 source 接入
- 输入候选生成

#### QueryEngine

负责方向：

- 搜索补证
- 事实扩展
- 结果召回
- 证据增强

#### MediaEngine

负责方向：

- 媒体传播分析
- 舆情/扩散相关处理
- 媒体侧内容补充
- 传播结构类能力

#### ReportEngine

负责方向：

- 报告生成
- 模板选择
- 章节生成
- 图表处理
- HTML/IR/状态文件输出

### 6.2 为四个引擎定义统一能力接口

建议先按能力语义定义统一接口：

- `mindspider.collect(...)`
- `query.search(...)`
- `media.analyze(...)`
- `report.generate(...)`

核心要求：

1. 方法名统一
2. 输入输出结构可控
3. 不暴露引擎内部目录布局
4. 不把业务层绑定到某个引擎内部模块名

### 6.3 建立引擎注册中心

目标：以后模式层或编排层不再手写 import 路径，而是从注册中心拿能力。

注册中心建议承担以下职责：

1. 声明当前启用哪些引擎
2. 声明每个引擎可提供哪些能力
3. 根据模式或配置装配可用引擎
4. 支持后续替换、降级、禁用和 mock

### 6.4 增加兼容适配层

建议策略：

1. 外部新增 adapter
2. adapter 内部调用现有四个引擎实现
3. 旧代码逐步切换到 adapter
4. 暂时不强改引擎内部结构

这样可以做到：

- 行为尽量不变
- 改造风险可控
- 迁移可阶段推进

### 6.5 将 `real_source` 与 `user_topic` 切换为“按能力装配”

建议不是重写模式逻辑，而是把它们的引擎依赖方式改为声明式。

#### `real_source`

建议依赖：

- 输入候选主要依赖 `MindSpider`
- 后续补证依赖 `QueryEngine`
- 传播/媒体增强依赖 `MediaEngine`
- 报告与交付依赖 `ReportEngine`

#### `user_topic`

建议依赖：

- 用户输入主题处理能力
- 检索与证据扩展能力
- 媒体传播与舆情补充能力
- 报告生成能力

### 6.6 建立“模式-能力-引擎”映射表

建议至少包括：

1. 模式名
2. 所需能力
3. 当前对应引擎
4. 是否核心依赖
5. 是否允许降级

这个映射表未来将直接决定：

- 哪些能力必须保留
- 哪些能力可以替换
- 哪些能力可以降级
- 哪些能力后续可以裁掉

---

## 7. 当前阶段不建议做的事情

为了避免剥壳过程中引入无谓风险，当前阶段不建议做以下动作：

1. 不建议直接删除四个引擎中的任一子目录。
2. 不建议先砍未使用子功能。
3. 不建议先做大规模目录移动。
4. 不建议继续扩展当前复杂的 `/outputs` 多层结构。
5. 不建议让模式层继续新增对引擎内部实现的直接引用。
6. 不建议在未建立统一接口前做“精细化裁剪”。

原因很简单：当前阶段的核心是“先简化外壳、再解耦内部”，而不是先瘦身。

---

## 8. 推荐推进顺序

建议下一步按照以下顺序推进。

### 第一阶段：先定输出协议

1. 固化 `/outputs` 最简结构
2. 明确 `summary / reports / recovery / debug` 四入口职责
3. 明确 `latest.json` 和 `summary.json` 的字段协议

### 第二阶段：再定引擎边界

1. 输出四引擎能力清单
2. 输出模式-能力-引擎映射表
3. 明确统一能力接口草案

### 第三阶段：建立壳层

1. 建立引擎适配层
2. 建立引擎注册中心
3. 建立统一装配入口

### 第四阶段：迁移核心模式

1. 让 `real_source` 切到壳层入口
2. 让 `user_topic` 切到壳层入口
3. 跑回归验证行为一致性

### 第五阶段：准备后续裁剪

1. 识别真正未使用能力
2. 识别高耦合能力
3. 识别可降级能力
4. 再进入子功能级裁剪

---

## 9. 阶段性交付物建议

为保证下一阶段推进清晰，建议最终交付以下文档或成果：

1. `/outputs` 目录协议说明
2. `latest.json` / `summary.json` 字段说明
3. 四引擎能力清单
4. 模式-能力-引擎映射表
5. 引擎统一接口草案
6. 引擎注册中心方案
7. `real_source` / `user_topic` 迁移方案
8. 回归验证清单

---

## 10. 实施清单

为了把上面的顺序变成可执行动作，建议直接按 `P0 / P1 / P2` 分层推进。

### 10.1 P0: 先规范 `/outputs`

这一层必须最先完成，因为它决定后续所有运行结果的可读性和可维护性。

#### P0-1: 固化最简目录结构

目标：把 `outputs/` 收敛成按模式分组、按运行聚合的最简结构。

建议动作：

1. 明确顶层只保留 `real_source/` 与 `user_topic/`。
2. 每个模式目录下只保留 `latest.json` 与运行目录。
3. 每次运行只保留 `summary / reports / recovery / debug` 四个入口。

#### P0-2: 固化字段协议

目标：让新的目录结构有固定文件协议，而不是只有目录名变化。

建议动作：

1. 固化 `latest.json` 字段。
2. 固化 `summary.json` 字段。
3. 固化 `recovery/recovery_summary.json` 字段。
4. 约束 `debug/` 只承载低频和审计文件。

#### P0-3: 建立旧到新映射规则

目标：避免新协议和现有目录产生断裂。

建议动作：

1. 将旧 `meta/run_summary.json` 映射到新 `summary.json`。
2. 将旧 `meta/errors.json` 下沉到新 `debug/errors.json`。
3. 将旧 `stages/*` 下沉到新 `debug/`。
4. 将旧 `reports/final/` 保留为新 `reports/`。

### 10.2 P1: 再做四引擎壳层化

这一层在 `/outputs` 稳定后再做，避免重复返工。

#### P1-1: 输出四引擎能力清单

目标：先把四个引擎对外能力说清楚。

建议动作：

1. 给 `MindSpider` 列能力清单。
2. 给 `QueryEngine` 列能力清单。
3. 给 `MediaEngine` 列能力清单。
4. 给 `ReportEngine` 列能力清单。

#### P1-2: 定义统一能力接口

目标：统一调用方式。

建议动作：

1. 定义 `mindspider.collect(...)`。
2. 定义 `query.search(...)`。
3. 定义 `media.analyze(...)`。
4. 定义 `report.generate(...)`。

#### P1-3: 建立引擎注册中心

目标：避免业务代码直接散落 import。

建议动作：

1. 统一声明当前启用的引擎。
2. 声明每个引擎可提供的能力。
3. 支持配置驱动的装配与降级。

#### P1-4: 建立适配层

目标：先包住旧实现，再逐步迁移。

建议动作：

1. 新增 adapter。
2. adapter 内部调用现有引擎实现。
3. 让模式层逐步切换到 adapter。

### 10.3 P2: 再迁移核心模式

这一层是最终让 `real_source` 和 `user_topic` 接入新壳层。

#### P2-1: 迁移 `real_source`

建议动作：

1. 把输入候选能力绑定到 `MindSpider`。
2. 把补证能力绑定到 `QueryEngine`。
3. 把媒体补充能力绑定到 `MediaEngine`。
4. 把报告与交付绑定到 `ReportEngine`。

#### P2-2: 迁移 `user_topic`

建议动作：

1. 把用户主题处理改成声明式能力需求。
2. 把检索与证据扩展绑定到统一能力接口。
3. 跑回归确认行为不变。

#### P2-3: 建立回归验证基线

建议动作：

1. 验证 `real_source` 运行结果与旧版一致。
2. 验证 `user_topic` 运行结果与旧版一致。
3. 验证输出目录比旧版更浅、更好找。
4. 验证补救信息都能在 `recovery/` 中聚合查看。

---

## 11. 一句话结论

`radar_engines` 的下一步剥壳，不应继续直接下刀删功能，而应先把 `/outputs` 收敛成“按模式分、按运行聚合、只保留 summary / reports / recovery / debug 四入口”的最简结构；在输出协议稳定后，再把 `MindSpider`、`QueryEngine`、`MediaEngine`、`ReportEngine` 四个引擎整体保留并做统一接口、统一注册、统一装配，最后再进入后续细分裁剪。
