# ReportEngine 章节列表结构错位缺陷修复报告

生成时间：2026-04-21

## 1. 背景

本报告记录一次发生在 `ReportEngine` 章节生成链路中的结构性缺陷修复。

问题最初表现为：最终报告正文后半段出现明显的标题、段落、列表边界错乱。表面上看像是“排版问题”，但继续排查后确认，这并不是渲染样式或编码异常，而是 `ReportEngine` 在章节 JSON 规范化阶段未能正确修复坏结构，导致章节级 block 被错误保留在前一个 `list item` 中。

这类问题一旦进入下游渲染链路，浏览器虽然会对错误 HTML 结构进行一定程度的容错，但结构本身已经不合法；在更严格或更扁平化的消费链路中，异常会被明显放大。因此，本次修复的目标不是调整表现层，而是修复 `ReportEngine` 自身的结构边界处理能力。

---

## 2. 问题发现过程

### 2.1 从最终报告异常入手

问题首先是从最终生成报告中被观察到的。目标样本位于：

- `outputs/user_topic/20260420_0332/reports/final_report_开源智能体技术发展观察多平台协作与记忆机制引关注_20260420_132636.html`

在该报告后半段，`6.1.2`、`6.1.3`、`6.2.3` 等小节前后出现了典型的结构错乱现象：

1. 上一个列表项没有在语义上结束；
2. 新的小节标题被粘连进前一个列表项；
3. 标题、正文、列表之间的边界变得不清晰。

这个现象说明：异常并不是某个单独文本节点换行失败，而更像是更上游的 block 结构已经发生错位。

### 2.2 沿渲染结果反查 HTML 结构

接下来检查 `ReportEngine` 的 HTML 输出结构，重点关注列表渲染实现：

- `radar_engines/ReportEngine/renderers/html_renderer.py:1261`

关键实现如下：

- `_render_list()` 会对 `list.items` 中的每一个 item 调用 `_render_blocks(item)`；
- 然后直接拼成 `<li>{content}</li>`。

这说明只要上游 IR 把 `heading`、`paragraph`、甚至新的 `list` 放进同一个 `item` 里，渲染器就会忠实生成如下错误结构：

- `<li><p>...</p><h3>...</h3><p>...</p><ul>...</ul></li>`

因此，渲染层不是根因，它只是把坏 IR 原样输出了出来。

### 2.3 继续上查到章节中间产物

为了确认坏结构是渲染前就已存在，继续检查章节级中间产物：

- `outputs/user_topic/20260420_0332/debug/chapters/report-cee09be9/060-section-6-0/stream.raw`
- `outputs/user_topic/20260420_0332/debug/chapters/report-cee09be9/060-section-6-0/chapter.json`

在 `stream.raw` 中可以直接看到，`6.1.2 应用风险` 被放进了上一条列表项内部；同样，`6.1.3 竞争与市场风险` 也被保留在更早的列表项中。说明原始章节输出就已经出现了“章节边界越界进入 list item”的问题。

而在 `chapter.json` 中，这种错误结构仍然被保留并落盘，证明：

- 问题不是 HTML 渲染阶段引入的；
- 问题也不是后续链路重写造成的；
- 问题出在章节 JSON 规范化与校验阶段，没有把坏结构拦住或修正掉。

---

## 3. 排查选线与判断过程

本次排查没有停留在最终表现层，而是沿着“现象 -> HTML -> IR -> 规范化逻辑”逐层上查，原因如下。

### 3.1 为什么没有按“样式问题”处理

如果只是样式问题，通常会表现为：

- CSS 样式丢失；
- 某个标签默认 margin/padding 异常；
- 文本内容正确但视觉间距不符合预期。

但本次问题的特征不是“样式轻微异常”，而是：

- 标题进入了列表项内部；
- 新段落与旧列表项共享同一个语义容器；
- 列表后续小节被整体吞入前一个 item。

这类问题更符合“结构错位”，不符合单纯样式问题特征。

### 3.2 为什么没有停留在渲染层修补

渲染层确实暴露了错误 HTML，但 `html_renderer.py:1261` 的实现逻辑很直接：它只是把 `list.items` 中的 block 原样渲染为 `<li>` 内容。

如果在渲染层增加特殊兜底逻辑，例如“遇到 `heading` 就强行断开列表”，虽然可以掩盖一部分现象，但会带来两个问题：

1. 坏 IR 仍会继续存在，后续 Markdown/PDF/其他消费方仍可能受影响；
2. 渲染层会开始承担不属于自己的结构修复职责，导致语义边界更加混乱。

因此，本次选线明确转向章节 IR 的生成与规范化层。

### 3.3 为什么最终定位到章节规范化阶段

继续阅读 `chapter_generation_node.py` 后发现：

- `_sanitize_chapter_blocks()` 是章节落盘前的统一修正入口；
- `_normalize_list_items()` 和 `_coerce_list_item()` 负责把 `list.items` 规范化为二维 block 数组；
- 但旧逻辑只做“形状修正”，并不识别“语义越界”。

也就是说，旧逻辑能够把“看起来像二维数组”的结构放过，却不会判断 `heading` 是否已经越过列表边界。问题因此被带入正式章节 JSON。

这就是本次排查选线的关键判断：

- 渲染器无罪；
- 真正缺口在 `ReportEngine` 的章节 JSON sanitize 与 validate。

---

## 4. 根因结论

### 4.1 一句话结论

根因是：`ReportEngine` 在章节 JSON 规范化阶段，没有识别并拆出误混入 `list.items[*]` 的章节级 block，导致 `heading`、后续 `paragraph`、甚至新的 `list` 被错误保留在前一个列表项中。

### 4.2 结构层根因拆解

从结构层次上看，问题可以分为三层：

1. **原始章节输出层**  
   `stream.raw` 已经出现 `heading` 混入 `list item` 的坏结构。

2. **规范化与校验层**  
   `chapter_generation_node.py` 没有把这些章节级 block 从 `list item` 中拆出；`validator.py` 也没有禁止 `heading` 出现在 `list.items[*]` 中。

3. **渲染层**  
   `html_renderer.py` 忠实地把错误 IR 渲染成错误嵌套 HTML。

因此，本次缺陷的根因属于 `ReportEngine` 的章节结构治理能力不足，而非渲染器行为异常。

---

## 5. 关键证据

### 5.1 原始章节输出已经错误

证据文件：

- `outputs/user_topic/20260420_0332/debug/chapters/report-cee09be9/060-section-6-0/stream.raw`

该文件证明：

- 在模型原始输出阶段，`6.1.2 应用风险` 已经被放进上一个 `list item`；
- 后续的 `paragraph` 与嵌套 `list` 也跟随留在该 item 内；
- 这不是渲染层后加出来的结构，而是章节生成结果本身有误。

### 5.2 落盘后的章节 JSON 保留了坏结构

证据文件：

- `outputs/user_topic/20260420_0332/debug/chapters/report-cee09be9/060-section-6-0/chapter.json`

该文件证明：

- 坏结构并未在落盘前被 sanitize 修复；
- `heading` 仍然作为 `list.items[*][*]` 中的 block 存在；
- 说明规范化与校验阶段没有阻断该问题。

### 5.3 渲染器会把坏 IR 原样放进 `<li>`

证据文件：

- `radar_engines/ReportEngine/renderers/html_renderer.py:1261`

该实现证明：

- `_render_list()` 对 item 内的所有 block 直接 `_render_blocks(item)`；
- 只要 item 中有 `heading`，就会产出 `<li>...<h3>...</h3>...</li>` 这种结构；
- 渲染器没有也不应承担语义边界修正职责。

---

## 6. 核心问题代码

### 6.1 `chapter_generation_node.py` 的旧缺口

关键位置：

- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:958`
- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:1933`
- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:1942`

旧逻辑的问题在于：

1. `_normalize_list_items()` 只负责把 item 规整成二维数组；
2. `_coerce_list_item()` 会把同一个 item 内的 dict block 整包保留；
3. 逻辑中没有“章节边界 block 不允许留在 list item 内”的判断。

因此，只要 LLM 输出了：

- `paragraph + heading + paragraph + list`

这样的 item，旧逻辑就会把它视为“合法 item”，从而让坏结构继续流入后续链路。

### 6.2 `validator.py` 的校验缺口

关键位置：

- `radar_engines/ReportEngine/ir/validator.py:92`

旧版 `_validate_list_block()` 只检查：

- `listType` 是否合法；
- `items` 是否是数组；
- 子 block 是否属于允许的 block 类型。

但它不会进一步判断：

- `heading` 是否本就不该存在于 `list.items[*]` 内。

这导致结构虽然“形状合法”，却“语义不合法”，从而被错误放行。

### 6.3 `prompts.py` 的约束缺口

关键位置：

- `radar_engines/ReportEngine/prompts/prompts.py:337`
- `radar_engines/ReportEngine/prompts/prompts.py:359`

旧提示词虽然要求 `list.items` 是二维数组，但没有明确强调：

- `heading` 绝不能出现在 `list.items[*]` 中；
- 新小节开始前必须结束当前 list block。

这使模型更容易输出“结构看似合法、语义却越界”的 JSON。

---

## 7. 解决方案

本次修复没有选择在渲染层打补丁，而是直接修正 `ReportEngine` 的结构治理链路。

### 7.1 在 sanitize 阶段增加 list 边界修复

修改位置：

- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:992`
- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:1968`
- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:1970`
- `radar_engines/ReportEngine/nodes/chapter_generation_node.py:1998`

核心思路：

1. 先继续做原有的 `list.items` 形状规范化；
2. 再额外识别章节边界 block；
3. 一旦在 item 中遇到 `heading` / `hr` / `list`：
   - 当前 item 在该处截断；
   - 边界 block 及其后的内容被提升到当前 list 之后；
   - 后续原本仍挂在旧 list 里的 item 也一并提升；
4. 修复后的 list 只保留真正属于该列表项的内容。

这样做的结果是：

- 列表语义边界被恢复；
- 新小节不会继续附着在旧 item 上；
- 结构修复发生在章节正式落盘前。

### 7.2 在 validator 阶段显式禁止 `heading` 出现在 list item 中

修改位置：

- `radar_engines/ReportEngine/ir/validator.py:92`

新增规则：

- 如果 `list.items[*][*].type == "heading"`，直接报错；
- 错误信息明确指出：新小节必须先结束当前 list block。

这样即使未来又有坏结构漏过 sanitize，也不会再静默流入渲染环节。

### 7.3 在提示词阶段补充明确约束

修改位置：

- `radar_engines/ReportEngine/prompts/prompts.py:337`
- `radar_engines/ReportEngine/prompts/prompts.py:359`

新增约束：

1. `heading` 绝不能出现在 `list.items[*]` 内；
2. 新小节/新标题开始前必须结束当前 list；
3. 如果 item 中已经混入 `heading`、`hr` 或新的 `list`，修复阶段必须将这些 block 提升到当前 list 之后。

这一步不是唯一防线，但能显著降低模型继续生成该类坏结构的概率。

---

## 8. 本次解决了什么

本次改动不是简单修复了一个样本，而是补上了 `ReportEngine` 在章节结构治理中的三道缺口。

### 8.1 修复了 list item 与章节级 block 的边界错位

现在 `heading`、`hr`、新的 `list` 不再会被默认为当前 item 的合法内容，而会被显式识别为章节边界并拆出。

### 8.2 阻止坏结构继续落盘

即使原始生成结果仍然带有类似问题，sanitize 会优先尝试修复；如果仍未修复干净，validator 会明确拒绝该结构，而不再让它静默通过。

### 8.3 降低后续同类问题复发概率

通过在 prompts 中增加规则，本次不仅修复了后处理能力，也降低了上游继续生成坏结构的概率。

### 8.4 为后续回归提供了结构化测试保护

本次补充了专门的回归测试，覆盖：

1. `paragraph + heading + paragraph + list` 被正确拆分；
2. `validator` 对 `heading in list item` 直接报错；
3. 正常 list item 不受影响。

---

## 9. 效果评估

### 9.1 结构效果

修复后，章节 block 边界恢复正确：

- 当前列表项只保留真正属于该 item 的 paragraph；
- `6.1.2`、`6.1.3`、`6.2.3` 这类小节标题重新成为顶层 block；
- 标题、正文、列表之间重新形成正确的章节层级。

### 9.2 渲染效果

由于上游 IR 已恢复正常，渲染层不再生成错误嵌套：

- 不再出现 `<li><p>...<h3>...</h3>...</li>` 这种结构；
- 后续 HTML 的语义边界恢复正常；
- 下游消费链路看到的结构也更稳定。

### 9.3 工程效果

本次修复将问题闭环在 `ReportEngine` 内部，而不是把责任下推给渲染器或消费方：

- 结构修复归位到章节 sanitize；
- 结构约束归位到 validator；
- 生成约束归位到 prompts；
- 回归保护归位到 tests。

这是一次符合引擎职责边界的修复，而不是表现层补丁。

---

## 10. 验证结果

本次已完成以下验证：

1. 新增测试文件：
   - `tests/test_report_engine_chapter_structure.py`

2. 通过测试：
   - `python -m unittest tests.test_report_engine_chapter_structure`

3. 编译校验通过：
   - `python -m py_compile` 已覆盖本次修改文件

已验证的核心行为包括：

- 错位 `heading` 能被从 list item 中拆出；
- 后续误挂在旧 list 中的 block 会被提升；
- 正常 list 不被破坏；
- validator 会拒绝 `heading in list item`。

---

## 11. 后续建议

### 11.1 扫描历史章节产物

建议后续对历史 `chapter.json` 样本做一次批量扫描，识别是否还存在：

- `heading` 混入 `list.items[*]`
- `hr` 混入 `list.items[*]`
- `list` 混入 `list.items[*]`

这有助于确认当前问题是否为单点样本，还是一类更广泛的结构性历史问题。

### 11.2 继续收紧章节边界规则

本次先覆盖了最直接的边界 block：

- `heading`
- `hr`
- `list`

后续可以根据样本继续评估，是否还需要把更多“明显属于章节级”的 block 纳入边界判断。

### 11.3 将结构语义校验前移

如果未来 `ReportEngine` 继续扩展 block 类型，建议在“类型合法”之外，持续补强“语义合法”的校验规则。因为本次问题已经证明：

- 结构形状正确，不代表语义边界正确；
- 仅靠二维数组校验不足以保证章节结构可靠。

---

## 12. 一句话结论

本次修复的本质，不是处理某个单独报告的排版异常，而是补上了 `ReportEngine` 在章节 JSON 规范化、校验与生成约束上的结构边界缺口：让误混入 `list item` 的章节级 block 能被及时拆出、拦截并回归测试覆盖，从根上恢复章节结构的稳定性。