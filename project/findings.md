# ClawRadar 剥壳发现记录

## 结论

当前项目里，`radar_engines` 的实际使用已经收敛到四个保留引擎：

- `MindSpider`
- `QueryEngine`
- `MediaEngine`
- `ReportEngine`

## 已确认使用情况

- `clawradar/real_source.py` 直接复用 `MindSpider`、`QueryEngine`、`MediaEngine` 的能力。
- `clawradar/writing.py` 直接复用 `ReportEngine`。
- `radar_engines/config.py`、`radar_engines/utils/`、`radar_engines/static/` 仍是共享基础设施，不能删。

## 已删除的旧平台外壳

这些目录和文件已经从 `radar_engines` 顶层剥离：

- `ForumEngine/`
- `InsightEngine/`
- `SingleEngineApp/`
- `SentimentAnalysisModel/`
- `insight_engine_streamlit_reports/`
- `media_engine_streamlit_reports/`
- `query_engine_streamlit_reports/`
- `tests/`
- `templates/`
- `app.py`
- `report_engine_only.py`
- `export_pdf.py`
- `regenerate_latest_html.py`
- `regenerate_latest_md.py`
- `regenerate_latest_pdf.py`

## 残留引用分类

- 文档引用：`README.md`、`clawradar-doc/archive/` 中仍有大量旧名字，这些大多只是历史说明。
- 共享资源引用：`radar_engines/static/pdf-export-readme/README.md` 仍被 `ReportEngine` 依赖。
- 兼容逻辑引用：`radar_engines/ReportEngine/agent.py`、`flask_interface.py`、`utils/chart_repair_api.py`、`state/state.py` 里还保留对旧模块名的兼容字串。

## 风险判断

- 现在不适合删除 `ReportEngine` 内部的兼容字串或静态资源，因为它仍然是保留四引擎之一。
- 现在也不适合删 `config.py`、`utils/`、`static/`，因为主线代码仍然依赖它们。
- 下一阶段应优先固化四引擎最小运行边界，再判断哪些兼容层可以收缩。
## 2026-04-21 WeChat Image Planning

### Current State
- The WeChat publisher currently supports four media policies: `drop`, `placeholder`, `fallback_table`, and `upload`.
- `upload` already works for real `<img>` nodes and can upload local files, HTTP images, and data URLs to WeChat `media/uploadimg`.
- The latest generated report used for publishing contains `img=0`, `canvas=8`, `svg=3`, and `chart-fallback=8`, so switching to `upload` alone does not make charts visible.
- The current publish path parses static HTML only and does not execute the report page's JavaScript, so a `<canvas>` element is only an empty drawing target at parse time.

### ReportEngine Clues
- `radar_engines/ReportEngine/renderers/html_renderer.py` renders chart widgets as `canvas + chart-fallback table`.
- `html_renderer.py` also includes front-end hydration logic that instantiates Chart.js from `canvas[data-config-id]` plus adjacent JSON payload.
- `radar_engines/ReportEngine/renderers/chart_to_svg.py` already exists and converts Chart.js-like widget payloads into static SVG using matplotlib.
- This means the upstream report engine already has a static chart rendering direction; a WeChat solution does not have to start from browser screenshots only.

### Option Comparison
- Option A: keep `fallback_table` as default.
  Pros: most stable, lowest maintenance, safest for WeChat draft publishing.
  Cons: weak visual fidelity.
- Option B: support `<img>` only.
  Pros: already available, low implementation cost, good for screenshot/image-rich reports.
  Cons: does nothing for Chart.js canvas charts.
- Option C: render `chart-fallback` tables into PNG and upload.
  Pros: works with current report output, no browser dependency, predictable behavior.
  Cons: visual result is a table image, not the original chart.
- Option D: reuse `chart_to_svg.py` to render chart payloads into SVG, then convert SVG to PNG for WeChat.
  Pros: closer to the real chart visual; aligned with existing ReportEngine capability; avoids browser runtime.
  Cons: needs payload extraction from report HTML and reliable SVG-to-PNG conversion.
- Option E: open the report in a headless browser and capture each chart canvas.
  Pros: best visual fidelity, captures the same chart users see in the report.
  Cons: highest operational complexity and runtime fragility.
- Option F: change ReportEngine outputs so it emits channel-ready static chart assets during report generation.
  Pros: architecturally clean for long-term multi-channel publishing.
  Cons: largest upstream scope and coordination cost.

### Recommended Path
- P0: keep `fallback_table` as the default safe mode.
- P1: formally support `<img>` upload mode in channel-local `.env` and docs.
- P2: evaluate static chart generation before browser capture.
  Preferred order: `chart_to_svg.py` reuse first, table-to-image second if payload extraction is too costly.
- P3: only introduce headless browser capture if business value requires near-perfect chart fidelity.

### Architectural Guidance
- Keep `service.py` as orchestration only.
- Keep media handling split by responsibility:
  - `image_handler.py`: policy routing and upload coordination.
  - `report_html_cleaner.py`: article extraction and sanitization.
  - new `chart_renderer.py`: chart staticization for WeChat-safe media.
- If `chart_to_svg.py` is reused, prefer a thin adapter in `clawradar/publishers/wechat/` rather than directly embedding ReportEngine internals in service code.

## 2026-04-21 ReportEngine 章节结构验证

- `tests/test_report_engine_chapter_structure.py` 的 4 个用例已通过，覆盖 list item 越界 `heading` 提升、后续 block 提升、validator 拒绝非法结构、正常 list 不受影响。
- `python -m py_compile` 已通过 `radar_engines/ReportEngine/ir/validator.py`、`radar_engines/ReportEngine/nodes/chapter_generation_node.py`、`radar_engines/ReportEngine/prompts/prompts.py`、`tests/test_report_engine_chapter_structure.py`。
- 当前修复链路是闭环的：sanitize 修结构、validator 硬拦截、prompts 降低坏结构生成概率、tests 提供回归保护。
- 额外发现：测试模块直接运行依赖 `PYTHONPATH` 包含 `F:/02_code/ClawRadar/radar_engines`，原因是 `radar_engines/ReportEngine/utils/__init__.py` 仍使用 `from ReportEngine...` 绝对导入。

## 2026-04-23 微信标题长度根因修复专项发现

- 当前主路径在 [`clawradar/writing.py`](clawradar/writing.py) 中把 `_constrain_title()` 建立在 `_truncate_utf8()` 之上，内建写作标题默认由 [`_build_title()`](clawradar/writing.py:232) 先拼接再裁切，外部写作标题则在 [`_build_external_writer_bundle()`](clawradar/writing.py:545) 中对 `report_title` 再次裁切；这说明当前系统把“截断”当成主生成策略，而不是兜底。
- 微信发布末端在 [`third_party/wechat_publisher/publisher.py`](third_party/wechat_publisher/publisher.py:134) 的 [`upload_draft()`](third_party/wechat_publisher/publisher.py:134) 内仍会对标题执行 `_truncate_utf8(title, 64, ...)`；该层已经是最后边界，但当前测试主要验证这里能截断成功，没有验证“上游直接生成合规标题”。
- 微信渠道编排层 [`build_wechat_delivery_message()`](clawradar/publishers/wechat/service.py:198) 当前直接信任 `content_bundle.title.text`，未区分“标题本来就合规”与“标题已被上游截断后勉强合规”两种状态。
- 内建写作链路可直接修复点集中在 [`_build_title()`](clawradar/writing.py:232)、[`_rewrite_content_bundle()`](clawradar/writing.py:321)、[`topic_radar_write()`](clawradar/writing.py:826) 所在流转，适合新增标题策略函数、标题校验结果和失败/降级语义。
- 外部写作链路的真正上游在 [`SYSTEM_PROMPT_DOCUMENT_LAYOUT`](radar_engines/ReportEngine/prompts/prompts.py:389) 与 [`DocumentLayoutNode.run()`](radar_engines/ReportEngine/nodes/document_layout_node.py:38)，因为 ReportEngine 的最终 `metadata.title` 来自 [`layout_design.get("title")`](radar_engines/ReportEngine/agent.py:535)；仅在 [`clawradar/writing.py`](clawradar/writing.py) 末端裁切 `report_title` 不能算根因修复。
- [`SYSTEM_PROMPT_DOCUMENT_LAYOUT`](radar_engines/ReportEngine/prompts/prompts.py:389) 当前只有“优先控制在 20 个汉字左右”的软约束，缺少“64 UTF-8 字节硬上限”“禁止依赖截断”“标题必须语义完整不歧义”“超限时优先压缩修饰语而非砍掉核心宾语”等明确规则。
- 当前测试缺口主要有三类：
  1. [`tests/test_clawradar_writing.py`](tests/test_clawradar_writing.py) 只断言字节数不超限，未断言“标题不是由机械截断得到”。
  2. [`tests/test_clawradar_delivery.py`](tests/test_clawradar_delivery.py:781) 仍以 publisher 末端截断为正向行为。
  3. 缺少针对外部写作链路的“布局阶段直出微信安全标题”测试。
- 发布层现在只保留最后一级兜底；`clawradar/publishers/wechat/service.py` 会在 `45003` 时做一次基于 `clawradar/writing._regenerate_title()` 的语义重试，并把每次尝试的标题字节数写入 `publish_attempts`。
- `third_party/wechat_publisher/publisher.py` 现在会把微信草稿失败结构化为 `WeChatDraftUploadError`，让上层可以准确区分 `45003` 和其他失败。
- `clawradar/delivery.py` 已把 WeChat 失败 details 透传到回执中，方便直接从 `delivery_receipt.json` 里定位尝试历史与最终失败原因。
- 2026-04-24 新发现：`third_party/wechat_publisher/` 不是历史残留目录，当前主链路仍通过 `clawradar/publishers/wechat/service.py:_load_wechat_publisher_class()` 动态加载它；因此如果要删除该目录，必须先把 publisher 类、错误类型、上传逻辑和测试迁入渠道目录。
- 2026-04-24 新发现：`clawradar/publishers/wechat/service.py:294` 目前对摘要只做 `summary_text[:120]` 字符截断，记录的 `digest_utf8_bytes` 也是传入 publisher 前的长度；这与 `third_party/wechat_publisher/publisher.py:183` 的 `_truncate_utf8(digest, 120, "")` 字节截断口径不一致，且发布层当前没有 `45004 description size out of limit` 的重试分支。
- 2026-04-24 新发现：`clawradar/writing.py:616` 的 `_html_to_text()` 原先使用了错误的脚本剥离正则 `</\\1>`，导致 `external_writer` 返回的 HTML 在转预览文本时没有真正移除 `<script>` 内容；结果 `Chart.js` 嵌入脚本会进入 `report_preview`，再污染 `draft.body_markdown` 和 `summary.text`。
- 2026-04-24 新发现：除了 `title` 外，`ReportEngine` 文档布局阶段现在也适合作为摘要生成入口；`DocumentLayoutNode` 已天然持有 `subtitle`、`tagline`、`hero.summary`、`tocPlan.description` 等语义面，因此把 `summaryPack` 放在这里比从最终 HTML 反解摘要更稳定。
- 2026-04-24 新发现：`radar_engines/ReportEngine/agent.py` 的 `manifest_meta` 是 external_writer 摘要透传的最小侵入落点；把 `summaryPack` 写进 metadata，再由 `generation_result.report_metadata` 返回，`clawradar/writing.py` 就可以在不侵入 HTML renderer 的情况下消费上游结构化摘要。
- 2026-04-24 新发现：`clawradar/publishers/wechat/service.py` 适合只做字段选择，不适合再理解报告结构；当前最稳的职责边界是优先消费 `content_bundle.summary.channel_variants.wechat`，其次 `summary.text`，最后才退回文章文本兜底。
