# ClawRadar 通用通知模块设计方案报告

日期：2026-04-28

## 一、背景

当前 `ClawRadar` 已具备较完整的产物发布链路：

- 写作阶段生成 `content_bundle`
- 交付阶段根据发布渠道将产物投递到目标平台
- 发布结果通过 `delivery_receipt` 回传给 orchestrator / publish-only

现有交付核心集中在：

- 通道枚举：`clawradar/delivery.py:29-35`
- 通道解析与校验：`clawradar/delivery.py:357-377`
- 参数脱敏与透传：`clawradar/delivery.py:402-451`
- 消息构造：`clawradar/delivery.py:454-505`
- 每个内容包逐条投递：`clawradar/delivery.py:848-903`

但目前项目中“发布”和“通知”仍未被明确区分。

现状问题是：

1. **发布渠道承担的是产物交付职责**
   - 例如微信公众号草稿、飞书消息等，本质是把生成结果投递到目标平台。
2. **通知需求是另一类职责**
   - 例如任务完成提醒、失败告警、发布成功/失败汇总。
3. **如果继续把通知堆进 delivery 语义中，会让交付层职责不断膨胀**
   - `delivery.py` 当前关注的是 `content_bundle` 与 event 级投递，不适合作为所有状态通知的统一承载层。

因此，有必要新增一套**独立于发布模块的通用通知模块**，使系统同时具备：

- 发布能力：把内容发布到平台
- 通知能力：把任务状态通知给人

本次方案重点是：

- 引入一套通用通知层
- 保持与现有发布链路解耦
- 第一阶段先支持 `PushPlus`
- 后续可扩展飞书机器人、企微机器人、邮件等通知渠道

---

## 二、总体结论

推荐将系统拆分为两条并列能力链路：

1. **Delivery（发布）**
   - 负责将生成产物发布/传输至平台
   - 输入核心是 `content_bundle`
   - 输出核心是 `delivery_receipt`

2. **Notification（通知）**
   - 负责将任务完成情况、错误情况、发布结果通知给操作者
   - 输入核心是 orchestrator 最终运行结果、发布结果摘要、错误摘要
   - 输出核心是 `notification_receipt`

### 结论判断

- **PushPlus 适合作为通知模块的首个渠道**
  - 它本质是统一消息推送网关，适合做运行完成通知、失败提醒、发布结果汇总。
- **PushPlus 不适合替代现有微信公众号发布链路**
  - 当前微信发布实现是公众号草稿语义，已经包含草稿上传、标题/摘要长度重试、`media_id` 处理等公众号特有逻辑，见 `clawradar/publishers/wechat/service.py:432-457`。
- **通知模块应独立于 `delivery.py` 设计**
  - 但可以复用 delivery 在通道枚举、参数脱敏、消息构造、结果回执上的成熟模式。

---

## 三、现有架构分析

## 3.1 发布链路的职责边界已经比较清晰

当前项目的发布逻辑是围绕“把内容交付到平台”展开的，而不是围绕“通知状态”展开。

关键证据：

### 1. Delivery 通道模型
- `clawradar/delivery.py:29-35`
  - 当前仅定义 `feishu`、`wechat`、`wechat_official_account`

### 2. Delivery 输入要求
- `clawradar/delivery.py:48-62`
  - 需要 `request_id`、`trigger_source`、`decision_status`、`delivery_target`
  - `content_bundle` 必须带 `event_id`、`title`、`draft`、`summary` 等产物字段

### 3. Delivery 消息构造是平台交付语义
- `clawradar/delivery.py:454-493`
  - 飞书消息是稿件摘要交付
- `clawradar/delivery.py:502-505`
  - 根据 `delivery_channel` 路由到微信或飞书消息构造

### 4. Delivery 执行是逐事件逐内容包的循环
- `clawradar/delivery.py:848-903`
  - 对 `normalized_payload["content_bundles"]` 逐个投递

### 5. 微信通道是正式草稿发布语义
- `clawradar/publishers/wechat/service.py:394-409`
  - 实际调用公众号草稿上传逻辑
- `clawradar/publishers/wechat/service.py:432-457`
  - `msg_type = "draft"`
  - `requires_manual_publish = True`

以上说明：当前 delivery 模块语义明确是“**交付内容产物**”。

## 3.2 通知需求的语义与发布不同

通知模块关注的不是稿件正文，而是：

- 任务是否完成
- 任务在哪个阶段结束
- 发布是否成功
- 成功/失败数量
- 首个错误原因
- 结果归档位置

它更像是 **run-level 状态汇总**，而不是 event 级内容交付。

这与 delivery 当前围绕 `content_bundle` 的模型明显不同，因此应独立建模。

---

## 四、推荐目标架构

推荐形成如下结构：

```text
launcher
  -> orchestrator
    -> writing
    -> delivery
    -> notification
```

职责拆分如下：

### 1. Writing
- 负责内容生成
- 产出 `content_bundle`

### 2. Delivery
- 负责内容交付到平台
- 消费 `content_bundle`
- 产出 `delivery_receipt`

### 3. Notification
- 负责运行状态通知
- 消费 orchestrator 最终结果、`delivery_receipt`、错误摘要
- 产出 `notification_receipt`

### 设计原则

1. 发布与通知互不替代
2. 通知不直接处理完整正文产物
3. 通知应优先消费“最终状态”而不是“中间步骤”
4. 通知模块需要可扩展为多渠道体系

---

## 五、模块设计方案

## 5.1 新增模块结构

建议新增：

```text
clawradar/
  notifications.py
  notifiers/
    __init__.py
    pushplus/
      service.py
```

## 5.2 文件职责划分

### `clawradar/notifications.py`
职责：

- 定义通知通道枚举
- 定义通知错误码
- 归一化通知 payload
- 判断是否需要发通知
- 根据渠道路由消息构造与发送
- 统一生成 `notification_receipt`

### `clawradar/notifiers/pushplus/service.py`
职责：

- 封装 PushPlus API 调用
- 处理 token / access-key 等认证参数
- 构造 PushPlus 请求体
- 解析 PushPlus 返回结果
- 统一包装错误信息和 metadata

---

## 六、通知协议设计

通知协议不建议复用 `delivery` 协议，因为两者的输入结构和关注点不同。

## 6.1 推荐通知入参结构

建议通知模块接收如下统一结构：

```python
{
  "request_id": "...",
  "run_status": "completed|failed|skipped",
  "final_stage": "crawl|score|write|deliver|publish",
  "decision_status": "publish_ready|no_publish|...",
  "notification_channel": "pushplus",
  "notification_target": "pushplus://default",
  "notification_reason": "run_completed|run_failed|publish_succeeded|publish_failed",
  "run_summary": {...},
  "delivery_receipt": {...},
  "errors": [...],
  "output_root": "...",
  "notification_options": {...}
}
```

## 6.2 为什么这样设计

因为通知模块不应该依赖完整 `content_bundle`，也不应该被平台正文格式绑死。它只需要知道：

- 这次任务的运行结果
- 有没有发生错误
- 发布阶段是否成功
- 成功/失败的数量汇总
- 输出目录与关键定位信息

这样通知层可以保持稳定与轻量。

---

## 七、通知事件语义设计

建议第一阶段固定 4 类通知原因：

### 1. `run_completed`
适用场景：
- full pipeline 正常结束
- 即使没有进入 publish，也视为运行完成

### 2. `run_failed`
适用场景：
- orchestrator 在任意阶段失败
- 任务提前终止

### 3. `publish_succeeded`
适用场景：
- 存在 `delivery_receipt.events`
- 所有交付事件都成功

### 4. `publish_failed`
适用场景：
- 发布阶段被执行
- 但存在 event 失败或 `errors` 非空

这样可以同时覆盖：

- full pipeline
- write-only / deliver-only
- publish-only

---

## 八、通知触发点设计

## 8.1 Full pipeline 触发点

最佳触发点应放在 orchestrator 的最终收束出口，而不是某个渠道内部。

关键线索：
- `clawradar/orchestrator.py:2158-2183`
  - 当没有 `publish_ready_events` 时，当前逻辑会直接 finalize

说明 orchestrator 已经是“运行最终状态汇总点”。

### 推荐做法
在 orchestrator 所有 `_finalize_orchestration(...)` 返回前统一触发通知：

1. 构建通知 payload
2. 根据 `notify_on` 判断是否需要发送
3. 调用 `topic_radar_notify(...)`
4. 将 `notification_receipt` 挂入最终返回结果

最终 orchestrator 返回结构建议变成：

```python
{
  ...,
  "delivery_receipt": {...},
  "notification_receipt": {...}
}
```

## 8.2 publish-only 触发点

`publish_only` 是另一条独立运行路径，也需要通知能力。

参考位置：
- `tests/test_publish_only.py:145-158`
  - 当前已对 `topic_radar_deliver(...)` 的结果进行断言

### 推荐做法
在 `clawradar/publish_only.py` 中：

- 在 `topic_radar_deliver(...)` 返回之后
- 在 publish 记录写入完成前后
- 触发 `topic_radar_notify(...)`

这样 publish-only 也可以发：

- 发布成功通知
- 发布失败通知

并保持 `delivery_receipt` 原有结构不变。

---

## 九、配置面设计

## 9.1 不复用 delivery 配置

当前入口层已有：
- `delivery_channel`
- `delivery_target`

来源：
- `run_openclaw_deliverable.py:24-29`
- `run_openclaw_deliverable.py:38-76`

但通知模块不应复用这些字段，否则会出现：

- 发布和通知语义混杂
- 无法实现“微信发布 + PushPlus 通知”并行配置
- 后续渠道扩展困难

## 9.2 推荐新增配置字段

建议新增：

- `notification_channel`
- `notification_target`
- `notification_options`
- `notify_on`

推荐在 payload 中与 `entry_options.delivery` 并列：

```json
{
  "entry_options": {
    "delivery": {
      "target_mode": "wechat",
      "target": "wechat://draft-box/openclaw-review"
    },
    "notification": {
      "channel": "pushplus",
      "target": "pushplus://default",
      "notify_on": [
        "run_completed",
        "run_failed",
        "publish_failed"
      ],
      "pushplus": {
        "token": "***"
      }
    }
  }
}
```

## 9.3 凭证组织建议

- 通用字段放 `notification_options`
- 渠道专属字段放 `notification_options.pushplus`
- 未来可扩展：
  - `notification_options.feishu_bot`
  - `notification_options.wecom_bot`
  - `notification_options.mail`

## 9.4 凭证脱敏建议

可复用 delivery 的脱敏设计思路：
- `clawradar/delivery.py:402-451`

建议通知模块也实现：
- sanitize entry options
- sanitize channel options
- 输出与归档时剔除 token / secret 等敏感信息

---

## 十、PushPlus 渠道接入方案

## 10.1 PushPlus 的适配定位

PushPlus 更适合：

- 任务完成通知
- 任务失败告警
- 发布成功/失败汇总
- 运行摘要推送

不适合：

- 替代微信公众号正式草稿发布
- 承担图文草稿管理职责

## 10.2 建议的 PushPlus service 接口

建议在 `clawradar/notifiers/pushplus/service.py` 提供：

```python
def send_pushplus_notification(
    payload: Dict[str, Any],
    *,
    notification_target: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    ...
```

其职责包括：

1. 从 `options` 中读取 token / channel / template
2. 构建 PushPlus title 与 content
3. 发起 HTTP POST
4. 解析返回的 code / msg / data
5. 产出统一的通知消息结构

## 10.3 PushPlus 消息格式建议

第一阶段建议仅做一种通用“运行摘要消息”。

### 标题建议
- `ClawRadar 通知｜任务完成`
- `ClawRadar 通知｜任务失败`
- `ClawRadar 通知｜发布失败`

### 正文建议包含
- 请求 ID
- 运行状态
- 最终阶段
- 决策状态
- 发布渠道
- 发布目标
- 成功发布数
- 失败发布数
- 首个错误摘要
- 输出目录

### 示例正文

```markdown
**请求 ID**：req-20260428-001
**运行状态**：completed
**最终阶段**：deliver
**决策状态**：publish_ready
**发布渠道**：wechat
**发布目标**：wechat://draft-box/openclaw-review
**成功发布**：3
**失败发布**：1
**输出目录**：outputs/real_source/2026-04-28/run-001
**提示**：1 个事件发布失败，请检查 delivery_receipt
```

---

## 十一、通知结果回执设计

通知模块也应生成自己的 receipt，而不是复用或污染 `delivery_receipt`。

## 11.1 推荐回执结构

```python
{
  "run_status": "completed|failed",
  "notification_channel": "pushplus",
  "notification_target": "pushplus://default",
  "notification_reason": "run_completed",
  "message_path": ".../notification_message.json",
  "receipt_path": ".../notification_receipt.json",
  "failure_info": None,
  "metadata": {...}
}
```

## 11.2 与 orchestrator 最终结果的关系

建议与 `delivery_receipt` 并列存在：

```python
{
  ...,
  "delivery_receipt": {...},
  "notification_receipt": {...}
}
```

这样既不破坏现有调用方，也便于后续消费通知状态。

---

## 十二、通知产物落盘设计

通知模块建议有独立的审计目录，不与 event 级 delivery archive 混放。

### 推荐目录

```text
outputs/<mode>/<run_id>/notifications/<timestamp>/
  notification_message.json
  notification_receipt.json
```

### 这样设计的好处

1. 可单独追踪通知是否发出
2. 排查失败更直观
3. 不破坏现有 `deliver/`、`recovery/` 语义
4. 可在后续支持多次重发与通知补偿

---

## 十三、实现顺序建议

### Phase 1：通知骨架
1. 新增 `clawradar/notifications.py`
2. 定义：
   - `NotificationChannel`
   - `NotificationErrorCode`
   - `topic_radar_notify(...)`
3. 实现 payload 归一化、notify_on 判断、receipt 结构

### Phase 2：PushPlus 渠道
1. 新增 `clawradar/notifiers/pushplus/service.py`
2. 封装 PushPlus 请求发送与响应处理
3. 实现通用摘要通知模板
4. 接入 metadata 和错误处理

### Phase 3：入口配置接入
1. 在 `run_openclaw_deliverable.py` 增加 notification 参数
2. 在 `start.py` 增加交互式通知配置输入
3. 在 payload 的 `entry_options` 中增加 `notification`

### Phase 4：编排器接入
1. 在 orchestrator 最终收束点接入通知调用
2. 在 publish-only 结果收束处接入通知调用
3. 保证 `notification_receipt` 并列返回

### Phase 5：测试与回归
1. 新增通知相关单测
2. 回归 publish-only
3. 回归 orchestrator 主流程
4. 确认未配置通知时行为不变

---

## 十四、测试方案

## 14.1 建议新增测试文件

- `tests/test_clawradar_notifications.py`
- `tests/test_pushplus_notifier.py`

## 14.2 单元测试覆盖点

### 通知模块
- payload 缺字段时失败
- `notify_on` 不命中时跳过发送
- `run_completed` / `run_failed` 判断正确
- `publish_succeeded` / `publish_failed` 判断正确
- receipt 结构正确

### PushPlus notifier
- 成功返回时 receipt 正确
- token 缺失时报错正确
- 接口返回失败码时错误结构正确
- 限流响应时错误结构正确

## 14.3 集成测试覆盖点

### Full pipeline
- run completed 会发通知
- run failed 会发通知
- delivery 全成功时发 `publish_succeeded`
- delivery 有失败时发 `publish_failed`

### publish-only
- 发布成功时发送通知
- 不影响原有 `delivery_receipt` 断言

## 14.4 重点回归文件

- `tests/test_publish_only.py`
- `tests/test_clawradar_automation.py`
- `tests/test_clawradar_scoring.py:15-26`

---

## 十五、风险与约束

### 1. 频率与额度
PushPlus 本身有调用频率与额度限制，因此第一阶段不建议做逐事件多次推送，而应优先做 run-level 汇总通知。

### 2. 通知与发布边界必须稳定
必须坚持：
- delivery = 交付产物
- notification = 传递状态信息

### 3. 凭证安全
PushPlus token 不应直接落盘，必须进行脱敏处理。

### 4. 不建议首期过度抽象
第一期先实现：
- 一个通知入口
- 一个 PushPlus 渠道
- 一种运行摘要模板

暂不建议一步做到：
- 复杂订阅规则系统
- 多模板引擎
- 每 event 通知编排
- 通知重试中心

---

## 十六、最终建议

本项目最合理的演进方向是：

1. **保留现有 delivery 作为正式发布层**
2. **新增独立 notification 作为状态通知层**
3. **首期只做 run-level 摘要通知**
4. **PushPlus 作为首个通知渠道接入**
5. **在 orchestrator 与 publish-only 两个最终结果边界触发通知**

这样可以获得以下收益：

- 发布与通知职责彻底分离
- 通知层具备可复用与可扩展性
- 不破坏现有微信/飞书发布逻辑
- 后续新增企业微信机器人、飞书机器人、邮件等成本更低

一句话总结：

**推荐将 PushPlus 作为“独立通知层”的首个渠道接入，而不是作为现有发布渠道的替代品；通知模块应独立建模、独立配置、独立回执，并在 orchestrator / publish-only 的最终结果边界统一触发。**
