# Input Modes

本 skill 围绕统一入口 `topic_radar_orchestrate()` 工作。输入模式优先级如下。

## `user_topic`

适合用户只提供主题意图，而没有结构化事件的时候。

典型输入：

- topic
- company
- track
- summary
- keywords

适用场景：

- 跟进某公司最近动态
- 围绕某主题做一轮候选发现
- 先看是否值得写，再决定是否交付

## `real_source`

适合要先抓取真实来源热点，再走后续评分或交付的时候。

典型输入：

- source_ids
- limit

注意：

- 它依赖 `radar_engines` 中的真实来源能力
- 本地环境没有相关依赖时，应该清楚报告为环境不可用

## Inline 工件

适合上游已经准备好了中间工件的时候。此时不应再把它退回到更早阶段。

常见工件：

- `topic_candidates`
- `normalized_events`
- `topic_cards`
- `scored_events`
- `content_bundle` / `content_bundles`

推荐原则：

- 已有 `topic_cards` 时，优先 `inline_topic_cards`
- 已有 `normalized_events` 时，优先 `inline_normalized`
- 已有 `scored_events` 时，可直接进入 `write_only` 或 `resume`
- 已有 `content_bundles` 时，可直接 `deliver_only`
