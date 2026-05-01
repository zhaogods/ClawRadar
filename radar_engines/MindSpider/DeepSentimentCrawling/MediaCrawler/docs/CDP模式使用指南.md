# CDP模式使用指南

## 概述

CDP（Chrome DevTools Protocol）模式是一种高级的反检测爬虫技术，通过控制用户现有的Chrome/Edge浏览器来进行网页爬取。与传统的Playwright自动化相比，CDP模式具有以下优势：

### 🎯 主要优势

1. **真实浏览器环境**: 使用用户实际安装的浏览器，包含所有扩展、插件和个人设置
2. **更好的反检测能力**: 浏览器指纹更加真实，难以被网站检测为自动化工具
3. **保留用户状态**: 自动继承用户的登录状态、Cookie和浏览历史
4. **扩展支持**: 可以利用用户安装的广告拦截器、代理扩展等工具
5. **更自然的行为**: 浏览器行为模式更接近真实用户

### 📌 两种 CDP 模式

CDP模式支持两种使用方式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **连接已有浏览器** | 连接一个已经开启远程调试的 Chrome 浏览器，复用浏览器当前状态 | 调试、人工干预、临时接管 |
| **启动新浏览器**（服务器正式方案） | 由程序自动拉起真实 Chrome/Edge 并通过 CDP 连接 | Ubuntu 服务器正式运行、长期复用登录态 |

## Ubuntu 服务器正式方案

这是当前项目推荐的服务器落地方式：**真实 Chrome + Xvfb + CDP**。

### 目标形态

- Ubuntu 服务器安装真实 Chrome
- 通过 Xvfb 提供虚拟显示环境
- DeepSentimentCrawling 主流程启用 CDP
- 由程序直接拉起真实 Chrome（默认不连接已有浏览器）
- 使用服务器本机生成的持久化 profile 沉淀登录态

### 必备依赖

```bash
sudo apt update
sudo apt install -y xvfb wget gnupg
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
printf 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main\n' | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable
```

安装完成后确认路径：

```bash
which google-chrome
google-chrome --version
Xvfb -version
```

### 服务器环境变量（正式运行推荐）

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
- `CLAWRADAR_ENABLE_CDP_MODE=1`：强制 DeepSentimentCrawling 主流程进入 CDP 模式
- `CLAWRADAR_CDP_CONNECT_EXISTING=0`：正式环境默认由程序拉起 Chrome，而不是连接现有浏览器
- `CLAWRADAR_CDP_HEADLESS=0`：配合 Xvfb 使用可见界面，便于扫码和登录态沉淀
- `CLAWRADAR_CDP_DEBUG_PORT=9222`：Chrome 远程调试端口
- `CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/usr/bin/google-chrome`：指定 Ubuntu 真实 Chrome 路径

### 运行方式

先导出环境变量，再按正常主流程运行：

```bash
python run_clawradar_deliverable.py --input-mode real_source --source-ids ks --limit 5 --server-mode
```

或在 MindSpider 侧运行：

```bash
python main.py --deep-sentiment --test
```

### 登录态沉淀

CDP 启动新浏览器模式下，程序会在 `browser_data/` 下为 CDP 浏览器生成持久化 profile。首次扫码成功后，后续任务会优先复用服务器本机的登录态。

推荐做法：

1. 首次运行时保留 `CLAWRADAR_CDP_HEADLESS=0`
2. 在 Xvfb 提供的显示环境下完成扫码
3. 确认浏览器 profile 已生成且登录成功
4. 后续继续复用同一服务器环境与 profile

## 调试/应急模式：连接已有浏览器

仅在需要人工介入或调试时启用。

### 启动已有 Chrome

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp
```

### 切换配置

```bash
export CLAWRADAR_ENABLE_CDP_MODE=1
export CLAWRADAR_CDP_CONNECT_EXISTING=1
export CLAWRADAR_CDP_DEBUG_PORT=9222
```

此时程序会连接已有浏览器，而不会自行拉起新的 Chrome。

## 配置优先级

在当前项目中，DeepSentimentCrawling 外层封装会在运行前写入 MediaCrawler 配置。正式运行时应优先通过以下环境变量控制 CDP：

- `CLAWRADAR_SERVER_MODE`
- `CLAWRADAR_ENABLE_CDP_MODE`
- `CLAWRADAR_CDP_CONNECT_EXISTING`
- `CLAWRADAR_CDP_HEADLESS`
- `CLAWRADAR_CDP_DEBUG_PORT`
- `CLAWRADAR_CDP_CUSTOM_BROWSER_PATH`

如果未显式设置：

- 服务器模式默认启用 CDP
- 服务器模式默认由程序拉起真实 Chrome
- 非服务器模式默认更偏向连接已有浏览器

## 基础配置项说明

`MediaCrawler/config/base_config.py` 中的相关字段：

```python
ENABLE_CDP_MODE = False
SERVER_MODE = False
CDP_DEBUG_PORT = 9222
CUSTOM_BROWSER_PATH = ""
CDP_HEADLESS = False
CDP_CONNECT_EXISTING = True
AUTO_CLOSE_BROWSER = True
```

这些值会被外层封装在运行时按环境变量重写，实际以运行期配置为准。

## 故障排除

### 1. 浏览器检测失败
**错误**: `No available browser found`

**解决方案**:
- 确认已安装 `google-chrome-stable`
- 用 `which google-chrome` 确认路径
- 显式设置 `CLAWRADAR_CDP_CUSTOM_BROWSER_PATH=/usr/bin/google-chrome`

### 2. CDP 端口不可用
**错误**: CDP 连接失败或端口不可访问

**解决方案**:
- 检查 `CLAWRADAR_CDP_DEBUG_PORT`
- 确认没有其他 Chrome 占用相同端口
- 切换到其他端口重新运行

### 3. Xvfb 未安装或未启动
**错误**: 提示 Xvfb 缺失

**解决方案**:
- 安装 `xvfb`
- 确保 `CLAWRADAR_SERVER_MODE=1`
- 由外层封装负责启动和复用 `:99`

### 4. 页面能打开但 API 仍然 `No Login`
**原因**:
- 页面态与 API 会话态未对齐
- 首次登录未在服务器本机 profile 上沉淀成功
- Chrome 环境仍未稳定复用

**解决方案**:
- 确保使用真实 Chrome，而不是默认 Chromium
- 确保 `CLAWRADAR_CDP_CONNECT_EXISTING=0` 让程序固定使用服务器本机 profile
- 完成一次服务器侧扫码并保留 profile 后再观察后续任务
# Windows
tasklist | findstr chrome

# macOS/Linux  
ps aux | grep chrome
```

## 最佳实践

### 1. 反检测优化
- 保持`CDP_HEADLESS = False`以获得最佳反检测效果
- 使用真实的User-Agent字符串
- 避免过于频繁的请求

### 2. 性能优化
- 合理设置`AUTO_CLOSE_BROWSER`
- 复用浏览器实例而不是频繁重启
- 监控内存使用情况

### 3. 安全考虑
- 不要在生产环境中保存敏感Cookie
- 定期清理浏览器数据
- 注意用户隐私保护

### 4. 兼容性
- 测试不同浏览器版本的兼容性
- 准备回退方案（标准Playwright模式）
- 监控目标网站的反爬策略变化

## 技术原理

### 连接已有浏览器模式（推荐）

1. **用户开启远程调试**: 在 `chrome://inspect/#remote-debugging` 中勾选启用
2. **WebSocket连接**: 程序通过 `ws://localhost:9222/devtools/browser` 直接连接浏览器
3. **用户确认**: Chrome 弹出确认对话框，用户点击接受后连接建立
4. **Playwright集成**: 使用 `connectOverCDP` 方法接管浏览器控制
5. **上下文复用**: 直接使用浏览器已有的上下文（包含用户的Cookie、登录状态等）

> 💡 与传统CDP模式的区别：传统方式通过 `--remote-debugging-port` 启动新浏览器，使用 HTTP 接口 `/json/version` 获取 WebSocket URL。而连接已有浏览器方式直接通过 WebSocket 连接，Chrome 新版（136+）的远程调试不提供 HTTP 接口，需要用户在浏览器端确认授权。

### 启动新浏览器模式

1. **浏览器检测**: 自动扫描系统中的Chrome/Edge安装路径
2. **进程启动**: 使用`--remote-debugging-port`参数启动浏览器
3. **CDP连接**: 通过 HTTP 获取 WebSocket URL，再连接到浏览器的调试接口
4. **Playwright集成**: 使用`connectOverCDP`方法接管浏览器控制
5. **上下文管理**: 创建或复用浏览器上下文进行操作

两种方式都绕过了传统WebDriver的检测机制，提供了更加隐蔽的自动化能力。连接已有浏览器模式的反检测效果更好，因为使用的是用户真实的浏览器环境。

## 更新日志

### v1.0.0
- 初始版本发布
- 支持Windows和macOS的Chrome/Edge检测
- 集成到所有平台爬虫
- 提供完整的配置选项和错误处理

## 贡献

欢迎提交Issue和Pull Request来改进CDP模式功能。

## 许可证

本功能遵循项目的整体许可证条款，仅供学习和研究使用。
