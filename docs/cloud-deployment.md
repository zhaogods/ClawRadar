# ClawRadar 云服务器部署指南

## 适用场景

在无 GUI 的 Linux 云服务器（Ubuntu/Debian/CentOS）上运行 ClawRadar 深爬（DeepSentimentCrawling）。

## 原理

`server_mode` 启用后：

- **Xvfb 虚拟显示**：创建虚拟帧缓冲（:99），Chrome 以 `HEADLESS=False` 运行，行为与桌面一致
- 社媒平台无法检测 headless 指纹，正常渲染 QR 码登录页面
- QR 码通过终端 Unicode 块字符渲染（手机对终端屏幕扫码）
- Playwright 启动时添加 `--no-sandbox --disable-dev-shm-usage`

**关键**：Xvfb 替代物理显示器，浏览器行为与桌面完全一致（`HEADLESS=False`），反爬检测无触发条件。CDP 模式已废弃（headless Chrome 仍被检测，非 headless 又需要 GUI，自相矛盾）。

## 系统依赖

### 1. Node.js（必需）

`pyexecjs` 需要 JS 运行时执行各平台签名脚本（如 `douyin.js`），缺失会导致爬虫启动直接失败：

```bash
# Debian/Ubuntu
sudo apt install nodejs

# CentOS/RHEL
sudo yum install nodejs
```

### 2. Xvfb（必需）

```bash
# Debian/Ubuntu
sudo apt install xvfb

# CentOS/RHEL
sudo yum install xorg-x11-server-Xvfb
```

### 3. Playwright 浏览器

```bash
playwright install --with-deps chromium
```

### 4. 中文字体（报告渲染用）

```bash
sudo apt install fonts-noto-cjk fonts-wqy-zenhei
```

### 5. 系统库

```bash
sudo apt install -y \
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

### Node.js 未安装

错误特征：`execjs._exceptions.RuntimeUnavailableError: Could not find an available JavaScript runtime.`

```bash
node --version           # 确认已安装
sudo apt install nodejs  # Debian/Ubuntu
```

### Xvfb 无法启动

```bash
# 检查 :99 端口是否被占用
ps aux | grep Xvfb

# 手动测试 Xvfb
Xvfb :99 -screen 0 1920x1080x24 -ac &
DISPLAY=:99 xdpyinfo || echo "Xvfb 未正常工作"
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
