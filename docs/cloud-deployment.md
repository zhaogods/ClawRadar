# ClawRadar 云服务器部署指南

## 适用场景

在无 GUI 的 Linux 云服务器（Ubuntu/Debian/CentOS）上运行 ClawRadar 深爬（DeepSentimentCrawling）。

## 原理

`--server-mode` 启用后：

- **CDP 模式**：使用系统安装的 Chrome/Chromium（真实浏览器），绕过平台反爬检测
- Playwright 启动时添加 `--no-sandbox --disable-dev-shm-usage`
- QR 码通过终端 Unicode 块字符渲染（手机对终端屏幕扫码）
- 强制 headless 模式

**关键**：服务器模式依赖 CDP（Chrome DevTools Protocol）连接系统 Chrome。无 CDP，headless Chromium 被社媒平台反爬拦截，QR 码根本不渲染。

## 系统依赖

### 1. Chrome / Chromium

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y chromium-browser

# 或 Google Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
sudo apt-get update
sudo apt-get install -y google-chrome-stable
```

### 2. Playwright 浏览器

```bash
playwright install --with-deps chromium
```

### 3. 中文字体（报告渲染用）

```bash
sudo apt-get install -y fonts-noto-cjk fonts-wqy-zenhei
```

### 4. 系统库

```bash
sudo apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0
```

## Cookie 配置

服务器模式下，登录需要预配置 Cookie。获取方法：

### 步骤

1. **本地桌面登录**: 在本地机器上运行 `python start.py`，选择深爬 + 扫码登录，扫码完成登录。

2. **导出 Cookie**: 登录成功后，浏览器 DevTools → Application → Cookies → 复制所有 cookie。

   或者从浏览器数据目录导出：
   ```bash
   # Chrome cookie 存储在:
   # Linux: ~/.config/google-chrome/Default/Cookies
   # Windows: %LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies
   # macOS: ~/Library/Application Support/Google/Chrome/Default/Cookies
   ```

3. **填入配置**: 在 `.env` 中或 MediaCrawler 配置中填入 cookie 字符串。

### 各平台 Cookie 格式

```python
# XHS (小红书)
COOKIES = "abRequestId=xxx; a1=xxx; webId=xxx; gid=xxx; web_session=xxx; ..."

# Douyin (抖音)
COOKIES = "sessionid=xxx; passport_csrf_token=xxx; ..."

# Weibo (微博)
COOKIES = "SUB=xxx; SUBP=xxx; ..."

# Bilibili (B站)
COOKIES = "SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx; ..."

# Zhihu (知乎)
COOKIES = "z_c0=xxx; d_c0=xxx; ..."
```

Cookie 通常有 7-30 天有效期，需要定期刷新。

## 运行

### 方式一: 命令行

```bash
# 设置环境变量
export CLAWRADAR_SERVER_MODE=1

# 运行
python run_clawradar_deliverable.py \
    --input-mode real_source \
    --source-ids weibo zhihu \
    --limit 5 \
    --deep-crawl \
    --deep-crawl-platforms zhihu weibo bili \
    --deep-crawl-login-type cookie
```

### 方式二: --server-mode 参数

```bash
python run_clawradar_deliverable.py \
    --server-mode \
    --deep-crawl \
    --deep-crawl-platforms zhihu bili
```

### 方式三: 交互式

```bash
python start.py
# 按提示选择: 服务器模式 = 是
```

## QR 码登录（备用）

服务器模式下 QR 码会在终端用 █ 字符渲染，手机可直接扫描。登录有 2 分钟超时。

终端输出示例：
```
[QRCode] 请用手机扫描下方二维码完成登录:

██████████████████████████████████████████████████████████████████
██████████████████████████████████████████████████████████████████
██                          ██████                        ██████
██  ██████████████████████  ██████  ██████████████████████  ████
██  ██        ██        ██  ██████  ██  ██  ██        ██  ████
...
```

## 故障排查

### Chrome 无法启动

```bash
# 确认 Chrome 已安装
which google-chrome-stable || which chromium-browser

# 确认无沙箱模式可用
google-chrome-stable --no-sandbox --disable-gpu --headless --dump-dom https://example.com
```

### Cookie 过期

错误特征：`登录失败（cookie）：2分钟内未完成登录` 或返回 401/403。

解决：重新导出 cookie，更新 `.env` 配置。

### 缺少字体

错误特征：PDF/图表中文显示为方块。

```bash
sudo apt-get install -y fonts-noto-cjk
fc-cache -fv
```

### 内存不足

Chromium 每个实例约 200-400MB。7 个平台串行爬取，峰值约 400MB。建议服务器至少 2GB RAM。
