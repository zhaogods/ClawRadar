# ClawRadar 云服务器部署指南

## 适用场景

本文适用于在 **Ubuntu 无桌面服务器** 上运行 ClawRadar 的深爬能力（DeepSentimentCrawling）。当前推荐的正式方案是：

- **真实 Chrome**
- **Xvfb 虚拟显示**
- **CDP（Chrome DevTools Protocol）连接**
- **服务器本机持久化 profile 复用登录态**

这套方案的目标不是临时跑通，而是让服务器形成一条可长期运行、可复用登录态、尽量接近本地真实浏览器效果的正式链路。

## 正式运行原理

服务器环境下的推荐运行形态是：**Xvfb 提供显示环境，程序通过 CDP 拉起或连接真实 Chrome，再由深爬主流程接管浏览器完成扫码与抓取。**

关键点：

- `Xvfb` 提供虚拟显示，不需要安装完整桌面环境
- 浏览器使用系统安装的真实 Chrome，而不是仅依赖 Playwright 默认 Chromium
- DeepSentimentCrawling 外层通过环境变量把 CDP 配置写入 MediaCrawler 运行期配置
- 首次扫码成功后，登录态沉淀到服务器本机 profile，后续任务优先复用

## 系统依赖

### 1. Xvfb

```bash
sudo apt update
sudo apt install -y xvfb
```

安装后可验证：

```bash
Xvfb -version
```

### 2. Node.js

部分平台签名脚本依赖 `execjs` 调用本机 JavaScript 运行时，例如抖音、知乎相关能力，因此服务器仍需安装 Node.js：

```bash
sudo apt install -y nodejs npm
```

验证：

```bash
node --version
npm --version
```

### 3. QR 码辅助工具

如果你希望在终端里直接查看二维码，建议安装：

```bash
sudo apt install -y zbar-tools qrencode
```

未安装时不影响正式流程，只是终端二维码渲染会跳过，仍可通过 PNG 或 HTTP 方式查看二维码。

### 4. 中文字体

用于报告渲染与部分页面显示：

```bash
sudo apt install -y fonts-noto-cjk fonts-wqy-zenhei
```

### 5. 常见图形/浏览器系统库

```bash
sudo apt install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0
```

## Ubuntu 安装真实 Chrome

这是当前正式方案的核心前置条件。

```bash
sudo apt update
sudo apt install -y wget gnupg
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
printf 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main\n' | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable
```

安装后验证：

```bash
which google-chrome
google-chrome --version
```

常见路径：

- `/usr/bin/google-chrome`
- `/usr/bin/google-chrome-stable`

如果自动探测失败，建议显式设置：

```bash
export CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/usr/bin/google-chrome
```

## Python 依赖安装

先在项目根目录创建虚拟环境并安装 Python 包：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

说明：

- `requirements.txt` 只负责 Python 依赖
- `Chrome`、`Xvfb`、`Node.js` 等系统组件不在 Python requirements 中，需要按本文单独安装

## Xvfb 运行方式

DeepSentimentCrawling 在 `server_mode` 下会尝试负责 `DISPLAY=:99` 和 Xvfb 复用，但你仍应确认服务器具备 Xvfb 运行条件。

手动验证示例：

```bash
Xvfb :99 -screen 0 1920x1080x24 -ac &
DISPLAY=:99 xdpyinfo >/dev/null && echo "Xvfb OK"
```

正式运行时建议启用：

```bash
export CLAWRADAR_SERVER_MODE=1
```

## 正式运行环境变量

推荐使用以下环境变量固定正式方案：

```bash
export CLAWRADAR_SERVER_MODE=1
export CLAWRADAR_ENABLE_CDP_MODE=1
export CLAWRADAR_CDP_CONNECT_EXISTING=0
export CLAWRADAR_CDP_HEADLESS=0
export CLAWRADAR_CDP_DEBUG_PORT=9222
export CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/usr/bin/google-chrome
```

含义：

- `CLAWRADAR_SERVER_MODE=1`：启用服务器模式，并由外层封装负责 Xvfb
- `CLAWRADAR_ENABLE_CDP_MODE=1`：强制主流程进入 CDP 模式
- `CLAWRADAR_CDP_CONNECT_EXISTING=0`：默认由程序拉起服务器本机的真实 Chrome
- `CLAWRADAR_CDP_HEADLESS=0`：配合 Xvfb 使用可见界面，便于扫码和登录态沉淀
- `CLAWRADAR_CDP_DEBUG_PORT=9222`：Chrome 远程调试端口
- `CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/usr/bin/google-chrome`：显式指定 Chrome 路径

## 运行方式

### 方式一：交互式启动

```bash
python start.py
```

推荐选择：

- 深爬：启用
- 服务器模式：是
- CDP 真实浏览器模式：启用
- 连接已有 Chrome：否
- Chrome 路径：`/usr/bin/google-chrome` 或留空自动探测
- CDP 端口：`9222`
- CDP headless：否

说明：`start.py` 只负责收集并透传参数，不负责替你安装 Chrome 或 Xvfb。

### 方式二：主流程命令行启动

先设置环境变量，再运行主流程：

```bash
python run_clawradar_deliverable.py \
    --input-mode real_source \
    --source-ids weibo zhihu \
    --limit 5 \
    --deep-crawl \
    --deep-crawl-platforms ks zhihu bili \
    --server-mode
```

### 方式三：MindSpider 侧单独验证

```bash
python radar_engines/MindSpider/main.py --deep-sentiment --test
```

## 首次扫码与登录态沉淀

正式方案下，首次运行应让浏览器完成一次真实扫码登录，并把 profile 保存在服务器本机。

建议流程：

1. 保持 `CLAWRADAR_CDP_HEADLESS=0`
2. 在 Xvfb 环境下启动任务
3. 完成一次扫码登录
4. 确认后续任务复用同一服务器环境与 profile

如果你需要人工介入调试，也可以临时切换为连接已有浏览器模式：

```bash
export CLAWRADAR_ENABLE_CDP_MODE=1
export CLAWRADAR_CDP_CONNECT_EXISTING=1
export CLAWRADAR_CDP_DEBUG_PORT=9222
```

然后手工启动 Chrome：

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp
```

这更适合调试，不建议作为正式长期运行方案。

## 二维码查看方式

扫码阶段仍可沿用当前项目已有的二维码输出能力：

1. 终端渲染（依赖 `zbar-tools` + `qrencode`）
2. HTTP 方式查看二维码图片
3. 输出 `qrcode_login.png` 后通过 scp 下载查看

如果需要扫码通知，可继续配置：

```bash
export PUSHPLUS_TOKEN=你的token
```

## 故障排查

### 1. 浏览器检测失败

错误特征：`No available browser found`

处理方式：

```bash
which google-chrome
google-chrome --version
```

若路径不是 `/usr/bin/google-chrome`，请显式设置：

```bash
export CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/你的/chrome/路径
```

### 2. CDP 端口不可用

错误特征：CDP 连接失败、端口被占用或无法访问。

处理方式：

```bash
ss -ltnp | grep 9222
```

如有冲突，切换端口：

```bash
export CLAWRADAR_CDP_DEBUG_PORT=9333
```

### 3. Xvfb 未安装或未正常工作

处理方式：

```bash
ps aux | grep Xvfb
Xvfb :99 -screen 0 1920x1080x24 -ac &
DISPLAY=:99 xdpyinfo || echo "Xvfb 未正常工作"
```

### 4. Node.js 未安装

错误特征：`execjs._exceptions.RuntimeUnavailableError: Could not find an available JavaScript runtime.`

处理方式：

```bash
node --version
sudo apt install -y nodejs npm
```

### 5. 页面已打开但 API 仍然 `No Login`

常见原因：

- 页面态与 API 会话态未对齐
- 首次登录没有在服务器本机 profile 上成功沉淀
- 实际仍在使用默认 Chromium 或临时浏览器环境

建议检查：

- 是否已安装并使用真实 Chrome
- 是否已设置 `CLAWRADAR_CDP_CONNECT_EXISTING=0` 用于固定复用服务器本机 profile
- 是否完成过至少一次服务器侧真实扫码登录

### 6. 缺少字体

错误特征：PDF/图表中文显示为方块。

```bash
sudo apt install -y fonts-noto-cjk fonts-wqy-zenhei
fc-cache -fv
```

### 7. 内存不足

真实 Chrome + Xvfb 会比纯 headless 更占资源。建议服务器至少预留 2GB RAM，并避免同一时刻拉起过多浏览器实例。

## 与旧方案的区别

当前正式方案不再以“服务器上长期依赖 Chromium + 预导出 Cookie”作为默认路径，而是：

- 优先使用真实 Chrome
- 优先让服务器本机沉淀登录态
- 通过 Xvfb 提供显示能力
- 通过 CDP 连接真实浏览器

如果只是本地快速调试，仍然可以临时退回标准 Playwright 模式；但在 Ubuntu 服务器正式落地时，推荐始终以 **真实 Chrome + Xvfb + CDP** 为默认方案。
