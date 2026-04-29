# 微信发布渠道异常分析报告

日期：2026-04-26

## 结论

这次微信草稿发布失败，**更像是发布请求体编码方式与微信草稿 API 的校验方式不一致**，而不只是标题/作者/摘要本身超出网页端可见长度。

最强嫌疑是：当前实现使用 `requests.post(..., json=...)` 发送草稿数据，导致中文字段在 JSON 中以 `\uXXXX` 形式出现；而微信官方草稿 API 文档明确提醒**不要使用 Unicode 转义格式**，直接传字符串。官方文档还给出了字段长度限制：`title` 32 字、`author` 16 字、`digest` 128 字，并说明 `digest` 为空时会默认抓正文前 54 个字。

## 官方文档结论

来源：
- `https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html`
- `https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_batchget.html`
- `https://developers.weixin.qq.com/doc/service/api/draftbox/draftmanage/api_draft_add`

官方 `draft/add` 文档里，核心字段约束如下：

- `title`：总长度不超过 32 个字，且不要使用 Unicode 转义格式。
- `author`：总长度不超过 16 个字，且不要使用 Unicode 转义格式。
- `digest`：总长度不超过 128 个字；仅单图文有摘要；未填写则默认抓取正文前 54 个字。
- `content`：正文内容，支持 HTML。

官方 `draft/batchget` 文档也再次说明：
- `digest` 未填写时，默认抓正文前 54 个字。

## 本地实现对照

### 1. 微信请求体发送方式

`third_party/wechat_publisher/publisher.py:195-199` 当前是：

```python
response = requests.post(
    f"{self.base_url}/draft/add",
    params={"access_token": access_token},
    json={"articles": [article]},
    timeout=30,
)
```

这会让 `requests` 走默认 JSON 序列化路径，中文字段容易变成 `\uXXXX` 转义形式。

我做了本地验证：同样的草稿字段用 `requests.Request(..., json=...)` 预处理后，标题和摘要都出现了 Unicode 转义字符串，说明这个风险不是假设。

### 2. 当前长度规则与官方口径不一致

当前仓库里还有一套自定义约束：
- `clawradar/writing.py:21` 里 `MAX_WECHAT_DIGEST_TEXT_UNITS = 52`
- `third_party/wechat_publisher/publisher.py:173-186` 里标题/作者/摘要分别按 UTF-8 bytes 和自定义 text units 裁剪

这套逻辑和官方文档的“32 字 / 16 字 / 128 字”不是同一口径。它可能让我们误以为“已经够短”，但微信后端仍按不同规则拒绝。

### 3. 现有重试只覆盖一部分场景

`clawradar/delivery.py:946-983` 对 `45004` 做了摘要重写重试，对 `45003` 做了标题重试。

但如果根因是请求体编码错误，或者微信后端按转义后的原始字符串计算长度，那么“重写一次摘要”并不能消除问题。

## 失败样本分析

你提供的样本里：

- 第一次：标题较长，报 `45003 title size out of limit`
- 第二次：标题缩短后，摘要仍报 `45004 description size out of limit`
- 失败摘要本身看起来并不夸张，按网页端直觉不该超限

这说明至少有一层不是“肉眼可见字符数”这么简单，结合官方文档的 Unicode 警告，**请求体编码方式**是目前最可疑的根因。

## 可能的根因排序

### 第一优先级：Unicode 转义发送导致 API 误判

最符合官方提示，也最符合现象。

### 第二优先级：我们当前的字数/字节截断规则与微信真实规则不一致

这是长期存在的准确性问题，但单独不足以解释这次样本。

### 第三优先级：显式传入 digest 与留空 digest 的行为不同

官方文档说明 digest 可省略，省略后会自动抓正文前 54 个字。我们当前总是显式传 digest，可能放大了校验风险。

## 建议的修复顺序

1. **先修请求体发送方式**
   - 不要再用 `json=...`
   - 改成显式 UTF-8 JSON body，确保中文按真实字符发送，不出现 `\uXXXX`

2. **再调整字段约束策略**
   - title / author / digest 的限制按官方文档重新建模
   - 维持一个保守 fallback，避免 undocumented 限制

3. **补回归测试**
   - 验证发送出去的 body 不含 `\u`
   - 验证 digest 省略时的 fallback 行为
   - 验证 45003 / 45004 的重试链路

## 附：仓库内相关位置

- `third_party/wechat_publisher/publisher.py:173-199`
- `clawradar/publishers/wechat/service.py:326-388`
- `clawradar/delivery.py:946-983`
- `clawradar/writing.py:21-23`

## 结论一句话

这次问题**更像是 API 请求编码与微信官方草稿接口校验不一致**，而不是单纯的网页端长度超限；优先修请求体编码，其次再修字段长度策略。
