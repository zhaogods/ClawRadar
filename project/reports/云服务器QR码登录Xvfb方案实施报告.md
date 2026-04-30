# 云服务器 QR 码登录 Xvfb 方案实施报告

生成时间：2026-04-30

## 1. 问题背景

ClawRadar 深爬阶段通过 MediaCrawler + Playwright 爬取 7 个社媒平台（小红书、抖音、快手、B站、微博、贴吧、知乎）。用户在无 GUI 的 Linux 云服务器上运行时，QR 码扫码登录无法工作。

## 2. 根因分析

### 2.1 原始代码行为

原始代码一直以 **HEADLESS=False**（非无头模式）运行：

```
platform_crawler.py create_base_config() → HEADLESS = True   (写配置文件)
platform_crawler.py run_crawler()        → --headless "false" (CLI 覆盖配置)
MediaCrawler arg.py                      → config.HEADLESS = False
平台 core.py                             → headless=False → 有浏览器窗口
```

本地桌面有物理显示器，浏览器以非 headless 模式运行，平台反爬不触发，QR 码正常渲染。

### 2.2 问题引入

server_mode 实现时误将浏览器改为 HEADLESS=True：

```python
# 错误改动
elif line.startswith('HEADLESS = '):
    replaced = f'HEADLESS = {str(self._server_mode)}'  # server_mode → HEADLESS=True

cmd --headless "true"  # 子进程 CLI 覆盖
```

中国社媒平台检测 headless 浏览器指纹，检测到后拒绝渲染 QR 码登录元素。`find_login_qrcode()` 等待超时，QR 码从未出现。

### 2.3 CDP 死路

曾尝试在 server_mode 下启用 CDP（Chrome DevTools Protocol）绕过检测：

- CDP 连接系统 Chrome → Chrome headless 仍被平台检测
- Chrome non-headless 需要 GUI → 自相矛盾

用户明确指出此矛盾后回退。

## 3. 解决方案：Xvfb 虚拟显示

### 3.1 原理

```
Xvfb :99 (虚拟帧缓冲 ~50MB 内存)
    ↓
Chrome HEADLESS=False → 连接 Xvfb → 以为有真显示器
    ↓
平台不检测 headless → 登录页正常渲染 QR 码
    ↓
find_login_qrcode() 成功获取 base64 数据
    ↓
show_qrcode() → _print_qrcode_to_terminal() → 终端 █ 方块
    ↓
手机扫描终端 QR 码 → 登录成功
```

核心思路：Xvfb 替代物理显示器，浏览器行为与桌面完全一致（HEADLESS=False），反爬检测无触发条件。

### 3.2 改动范围

仅修改 2 个文件：

| 文件 | 改动 |
|------|------|
| `platform_crawler.py` | Xvfb 启动/停止 + HEADLESS 修正 + CDP 回退 + DISPLAY 传参 |
| `main.py` (DeepSentimentCrawling) | close() 增加 platform_crawler.close() 调用 |

其他文件不动：

- 7 个 `core.py` 的 `--no-sandbox` 逻辑 — 之前已完成
- `crawler_util.py` 终端 QR 码渲染 — 之前已完成
- `base_config.py` `SERVER_MODE` 配置 — 之前已完成
- `run_clawradar_deliverable.py` `--server-mode` flag — 之前已完成
- `start.py` 交互 — 之前已完成

### 3.3 关键设计决策

| 决策 | 说明 |
|------|------|
| HEADLESS 永远 False | 与原始代码一致，不随 server_mode 变动 |
| 删除 `--headless` CLI 参数 | 让 MediaCrawler 读配置文件（HEADLESS=False） |
| CDP 始终关闭 | Xvfb + Playwright 原生 Chromium 即可，无需 CDP |
| 仅 Linux 启动 Xvfb | `sys.platform` 判断，Windows/macOS 跳过（有原生显示） |
| 复用已有 Xvfb | 检测 :99 是否被占用，避免重复启动 |
| close() 清理 Xvfb | 爬取结束自动终止 Xvfb 进程 |

## 4. server_mode 与桌面模式差异

浏览器行为一致（均为 HEADLESS=False），差异在基础设施：

| | 桌面 | 服务器 (server_mode) |
|------|------|------|
| 显示器 | 物理 | Xvfb 虚拟 (:99) |
| `--no-sandbox` | 不需要 | 需要 |
| DISPLAY | 桌面环境自带 | 需设 `:99` |
| 启动 Xvfb | 不启动 | 自动启动 |

## 5. 部署步骤

### 5.1 安装 Xvfb

```bash
# Ubuntu/Debian
sudo apt install xvfb

# CentOS/RHEL
sudo yum install xorg-x11-server-Xvfb
```

### 5.2 运行

```bash
export CLAWRADAR_SERVER_MODE=1
python run_clawradar_deliverable.py --server-mode --deep-crawl ...
```

或交互式：

```bash
python start.py
# 选择: 服务器模式 = 是
```

### 5.3 扫码流程

1. 程序启动 Xvfb，浏览器以非 headless 模式运行
2. 平台登录页正常渲染 QR 码
3. 终端输出 █ 方块 QR 码
4. 手机对终端屏幕扫码
5. 登录成功，开始爬取
6. 爬取结束，Xvfb 自动清理

## 6. 未解决问题

- **QR 码登录窗口仅 2 分钟**：`_patch_login_timeouts()` 已将超时从 600s 改为 120s，运维需在此窗口内完成扫码
- **Cookie 有效期**：社媒平台 cookie 通常 7-30 天过期，需定期在桌面刷新后上传

## 7. 文件清单

| 文件 | 状态 |
|------|------|
| `radar_engines/.../platform_crawler.py` | 已修改（Xvfb + HEADLESS 修正 + CDP 回退） |
| `radar_engines/.../main.py` (DeepSentimentCrawling) | 已修改（close() 清理 Xvfb） |
| `radar_engines/.../MediaCrawler/config/base_config.py` | 之前已完成（SERVER_MODE 配置） |
| `radar_engines/.../MediaCrawler/tools/crawler_util.py` | 之前已完成（终端 QR 渲染） |
| `radar_engines/.../MediaCrawler/media_platform/*/core.py` (7个) | 之前已完成（--no-sandbox） |
| `run_clawradar_deliverable.py` | 之前已完成（--server-mode flag） |
| `start.py` | 之前已完成（服务器模式交互） |
| `docs/cloud-deployment.md` | 之前已完成（部署文档） |
