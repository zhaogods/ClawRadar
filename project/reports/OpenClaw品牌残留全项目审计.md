# ClawRadar 项目中 OpenClaw 残留内容梳理报告

## 一、背景

当前仓库 `ClawRadar` 在早期定位上带有明显的 `OpenClaw skill` 属性，但现在项目目标已转向“独立项目”。  
本次梳理的目标是：

- 通读项目并识别所有与 `openclaw / OpenClaw` 相关的残留内容
- 区分这些内容对项目的影响面
- 仅做归档整理，不提出代码修改

---

## 二、总体结论

项目中与 `OpenClaw` 相关的残留，主要分布在以下 5 类区域：

1. **运行入口与启动文案**
2. **核心代码执行语义**
3. **测试与样例数据**
4. **skill 定位相关文档**
5. **历史资料与归档目录**

其中，最关键的问题不是单个字符串，而是**整个项目仍保留了“OpenClaw 作为上层 skill/编排器”的命名痕迹**，包括：

- 顶层入口文件名仍为 `run_openclaw_deliverable.py`
- 默认执行器仍叫 `openclaw_builtin`
- 默认 request id、标题、交付标题、摘要兜底等仍含 `OpenClaw`
- 文档中仍把该项目描述为 skill 或依附于 OpenClaw 的能力

---

## 三、按影响面分级整理

---

## A. 一级：直接影响项目对外身份识别的残留

这类内容最容易让人误以为当前项目仍然属于 OpenClaw 子能力，而不是独立项目。

### 1. 顶层运行入口
- `run_openclaw_deliverable.py:16`
  - CLI 描述：`Run OpenClaw one-day deliverable flow`
- `run_openclaw_deliverable.py:25`
  - 默认 `request_id`: `req-openclaw-deliverable`

### 2. 交互启动脚本
- `start.py:8`
  - 直接依赖 `run_openclaw_deliverable`
- `start.py:195`
  - 默认 `request_id`: `req-openclaw-deliverable`
- `start.py:236-238`
  - 启动标题：`OpenClaw 交互式启动`

### 3. README / 使用入口说明
- `README.md:17,35,41`
  - 主入口与示例命令仍写为 `run_openclaw_deliverable.py`
- `README.md:47`
  - 示例 target：`wechat://draft-box/openclaw-review`

### 4. 项目内协作文档
- `CLAUDE.md:41,42,48,122,128`
  - 默认 launcher 与示例 target 仍是 openclaw 命名

### 判断
这一层属于**品牌与项目身份级别残留**，影响最大。

---

## B. 二级：核心代码中的执行语义残留

这部分不是单纯文案，而是**真实参与流程控制和默认行为的术语**。

### 1. Orchestrator
- `clawradar/orchestrator.py:95`
  - 写作执行器允许值含 `openclaw_builtin`
- `clawradar/orchestrator.py:98`
  - 降级策略含 `fallback_openclaw_builtin`
- `clawradar/orchestrator.py:133`
  - 默认 `request_id`: `openclaw-run`
- `clawradar/orchestrator.py:2237-2251`
  - external writer 失败后回退到 `openclaw_builtin`

### 2. Writing
- `clawradar/writing.py:43-47`
  - `WriteExecutor.OPENCLAW_BUILTIN = "openclaw_builtin"`
- `clawradar/writing.py:68`
  - 标题兜底：`OpenClaw Report`
- `clawradar/writing.py:135,165,167,169,582`
  - 摘要兜底：`OpenClaw 摘要`
- `clawradar/writing.py:871,883,892`
  - 外部写作输入标题含 `OpenClaw`

### 3. Delivery
- `clawradar/delivery.py:486`
  - 飞书标题：`OpenClaw 交付｜{title_text}`
- `clawradar/delivery.py:985`
  - regenerate summary 时指定 `executor="openclaw_builtin"`

### 4. WeChat Publisher
- `clawradar/publishers/wechat/service.py:297`
  - 微信标题 fallback：`OpenClaw Report`

### 判断
这一层说明：项目在内部术语上，仍把 `OpenClaw` 当作一类内建执行器或能力名，而不是历史品牌残留而已。

---

## C. 三级：模块说明、注释与内部文案残留

这类内容不一定影响运行，但会强化“该项目来自 OpenClaw 流程”的认知。

### 1. 合同 / 打分 / 写作 / 交付阶段注释
- `clawradar/contracts.py:1`
  - `BettaFish -> OpenClaw ingest contract`
- `clawradar/scoring.py:1`
  - `OpenClaw score contract`
- `clawradar/writing.py:1`
  - `OpenClaw 可调用内容生成能力`
- `clawradar/delivery.py:1`
  - `OpenClaw 可调用交付能力`

### 2. real_source 文案
- `clawradar/real_source.py:93`
  - capability label：`OpenClaw settings`
- `clawradar/real_source.py:238,621`
  - timeline summary 文案含 `OpenClaw`

### 判断
这部分主要体现历史上下文：项目结构曾按 OpenClaw 编排阶段来设计。

---

## D. 四级：测试、fixture 与回归样例中的残留

这部分不会直接影响最终用户，但会持续固化旧命名。

### 1. 自动化测试
- `tests/test_clawradar_automation.py:35`
  - `feishu://openclaw/p0-review`
- `tests/test_clawradar_automation.py:37`
  - `write.executor = "openclaw_builtin"`
- `tests/test_clawradar_automation.py:277-278,333-344`
  - 动态加载 `run_openclaw_deliverable.py`
- `tests/test_clawradar_automation.py:1050,1072,1088`
  - `archive://openclaw-p0-tests`
- `tests/test_clawradar_automation.py:1305,1323,1333,1358,1360`
  - `wechat://draft-box/openclaw-review`

### 2. 交付测试
- `tests/test_clawradar_delivery.py:269,342,410,459,549,619,692,781,857,913,1001,1085,1210`
  - 多处 `wechat://draft-box/openclaw-review`

### 3. publish-only 测试
- `tests/test_publish_only.py:149,189,197,229,241,278,320`
  - 多处 `wechat://draft-box/openclaw-review`

### 4. fixture
- `tests/fixtures/clawradar_deliver_publish_ready_input.json:6`
  - `feishu://chat/openclaw-review`
- `tests/fixtures/clawradar_deliver_need_more_evidence_input.json:6`
  - `feishu://chat/openclaw-review`

### 判断
这类残留说明测试基线仍继承 OpenClaw 时代的命名规范。

---

## E. 五级：skill 定位相关残留

这是与你当前关注点最相关的一组：项目早期定位为 skill 的痕迹仍然很明显。

### 1. 当前 skill 文档
- `clawradar-skill/SKILL.md:54,141,168,174,180,186,222`
  - 仍把 `run_openclaw_deliverable.py` 作为默认入口和检查项

### 2. 使用文档中的 skill 组织语义
- `使用.md:93-107,434,439`
  - 仍有 launcher / skill 自动补参与调用方式描述

### 3. 兼容 skill 文档
- `openclaw-doc/compat/SKILL.md:2`
  - legacy skill：`openclaw-workflow-legacy`
- `openclaw-doc/compat/SKILL.md:12,16,18,42`
  - `openclaw-topic-radar`

### 4. 历史说明文档
- `openclaw-doc/archive/比赛论坛投稿重写稿-当前项目版.md:77,79,83`
  - 把当前项目描述为 Skill
- `openclaw-doc/archive/需求对话.md`
  - 大量 `skills / agent / workspace / OpenClaw` 相关叙述

### 判断
这部分可以明确支持当前判断：  
**项目曾以 OpenClaw skill 的方式被设计和叙述，而非纯独立应用。**

---

## F. 六级：历史资料区与归档目录

这部分对当前运行影响较小，但对仓库整体认知影响很大。

### 1. 目录本身
- `openclaw-doc/`
  - 目录名直接带 `openclaw`

### 2. 文档标题与产品资料
- `openclaw-doc/README.md:1`
  - `# OpenClaw 说明文档`
- `openclaw-doc/README.md`
  - 多处 `docs.openclaw.ai`、`openclaw@latest`、`openclaw onboard`、`openclaw doctor`

### 3. 历史策划与比赛材料
- `openclaw-doc/archive/比赛论坛投稿初稿.md:1`
  - `基于 OpenClaw + BettaFish`
- `openclaw-doc/archive/需求对话.md`
  - 大量 OpenClaw 竞赛、技能系统、agent 设计内容

### 判断
这一层说明仓库中保留了大量 OpenClaw 时代的背景材料，属于明显历史归档残留。

---

## G. 七级：缓存与编译产物

这类信息不影响逻辑，但仍可见旧命名。

- `tests/__pycache__/...`
  - 保留 `test_openclaw_p0_*`
- `__pycache__/...`
  - 保留 `run_openclaw_deliverable*`

---

## 四、结构性观察

从全局看，当前仓库中的 `OpenClaw` 残留不是零散字符串问题，而是分成了三种不同层级：

### 1. 品牌层残留
表现为：
- 文件名
- 标题
- README 命令
- 交付标题
- 默认 request id

### 2. 能力层残留
表现为：
- `openclaw_builtin`
- `fallback_openclaw_builtin`
- `openclaw-run`

这说明 `OpenClaw` 一度不只是品牌，也被编码成“执行器/策略名”。

### 3. 组织层残留
表现为：
- `SKILL.md`
- `openclaw-topic-radar`
- 历史文档中的 skill / agent / workspace 叙述

这说明项目最初并不是单纯的独立仓库，而是被放在“OpenClaw skill 体系”里理解和设计的。

---

## 五、最关键的残留清单

如果只看最核心的一组，当前最能代表“OpenClaw 残留”的内容是：

1. `run_openclaw_deliverable.py`
2. `start.py` 中的 `OpenClaw 交互式启动`
3. `clawradar/orchestrator.py` 中的 `openclaw_builtin` / `fallback_openclaw_builtin`
4. `clawradar/writing.py` 中的 `OpenClaw Report` / `OpenClaw 摘要`
5. `clawradar/delivery.py` 中的 `OpenClaw 交付`
6. `clawradar-skill/SKILL.md`
7. `openclaw-doc/` 整个历史目录

---

## 六、结论

结论可以概括为一句话：

**ClawRadar 当前已经具备独立项目形态，但仓库内仍保留大量 OpenClaw 时代的命名、执行术语、skill 结构和历史文档痕迹。**

其中最值得注意的是：

- **入口名仍是 OpenClaw**
- **默认执行器术语仍是 OpenClaw**
- **交付与写作默认文案仍是 OpenClaw**
- **文档体系仍保留 skill 定位**
- **历史资料区仍强烈绑定 OpenClaw**
