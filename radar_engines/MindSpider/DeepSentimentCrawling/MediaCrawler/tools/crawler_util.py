# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/crawler_util.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/2 12:53
# @Desc    : Crawler utility functions

import base64
import http.server
import json
import os as _os_module
import random
import re
import secrets
import socketserver
import string
import sys as _sys
import threading
import urllib
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, cast

import httpx
from PIL import Image, ImageDraw
from playwright.async_api import BrowserContext, Cookie, Page

from . import utils
from .httpx_util import make_async_client


async def find_login_qrcode(page: Page, selector: Union[str, List[str], Tuple[str, ...]], timeout: int = 3000) -> str:
    """find login qrcode image from target selector"""
    selectors = [selector] if isinstance(selector, str) else list(selector)
    for current_selector in selectors:
        try:
            elements = await page.wait_for_selector(
                selector=current_selector,
                timeout=timeout,
            )
            login_qrcode_img = str(await elements.get_property("src"))  # type: ignore
            if "http://" in login_qrcode_img or "https://" in login_qrcode_img:
                async with make_async_client(follow_redirects=True) as client:
                    utils.logger.info(f"[find_login_qrcode] get qrcode by url:{login_qrcode_img}")
                    resp = await client.get(login_qrcode_img, headers={"User-Agent": get_user_agent()})
                    if resp.status_code == 200:
                        image_data = resp.content
                        base64_image = base64.b64encode(image_data).decode('utf-8')
                        return base64_image
                    raise Exception(f"fetch login image url failed, response message:{resp.text}")
            return login_qrcode_img
        except Exception as e:
            utils.logger.info(f"[find_login_qrcode] selector failed: {current_selector}, timeout={timeout}ms, error: {e}")
            continue
    return ""


async def find_qrcode_img_from_canvas(page: Page, canvas_selector: str) -> str:
    """
    find qrcode image from canvas element
    Args:
        page:
        canvas_selector:

    Returns:

    """

    # Wait for Canvas element to load
    canvas = await page.wait_for_selector(canvas_selector)

    # Take screenshot of Canvas element
    screenshot = await canvas.screenshot()

    # Convert screenshot to base64 format
    base64_image = base64.b64encode(screenshot).decode('utf-8')
    return base64_image


# ---- QR Code HTTP server (singleton per process) ----

_QRCODE_SERVER_STARTED = False
_QRCODE_SERVER_LOCK = threading.Lock()


def _read_env_value(key: str, default: str = "") -> str:
    """Read value from environment or walk-up .env files (no dotenv dependency)."""
    val = _os_module.environ.get(key, "")
    if val:
        return val
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        env_file = parent / ".env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip().strip('"').strip("'")
            except Exception:
                pass
    return default


def _resolve_qrcode_http_token() -> str:
    """Resolve QR code HTTP auth token.

    Priority: env QRCODE_HTTP_TOKEN > .env QRCODE_HTTP_TOKEN > random 7-char.
    """
    token = _read_env_value("QRCODE_HTTP_TOKEN")
    if token:
        return token
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(7))


def _extract_platform_name() -> str:
    """Extract platform name from subprocess command line."""
    try:
        argv = _sys.argv
        if "--platform" in argv:
            idx = argv.index("--platform")
            if idx + 1 < len(argv):
                return argv[idx + 1]
    except Exception:
        pass
    return "unknown"


def _send_pushplus_notification(platform: str, url: str) -> None:
    """Send QR code login link via PushPlus notification (best-effort)."""
    pushplus_token = (
        _os_module.environ.get("PUSHPLUS_TOKEN", "").strip()
        or _read_env_value("PUSHPLUS_TOKEN")
    )
    if not pushplus_token:
        return
    try:
        data = json.dumps({
            "token": pushplus_token,
            "title": f"ClawRadar - {platform} 需要扫码登录",
            "content": f"## {platform} 平台需要扫码登录\n\n"
                       f"请打开以下地址查看二维码并扫码：\n\n"
                       f"**{url}**\n\n"
                       f"[点击打开二维码]({url})",
            "template": "markdown",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"[QRCode] PushPlus 通知已发送")
    except Exception as e:
        print(f"[QRCode] PushPlus 通知发送失败: {e}")


class _QRCodeHandler(http.server.BaseHTTPRequestHandler):
    """Serve qrcode_login.png with token-in-path auth."""

    def do_GET(self):
        expected = f"/{self.server.token}/qrcode_login.png"
        if self.path == expected:
            try:
                with open(self.server.png_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_error(404, "QR code image not found")
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        pass  # suppress access logs


class _QRCodeServerRef:
    port = 0
    token = ""


_QRCODE_SERVER = _QRCodeServerRef()


def _start_qrcode_http_server(png_path: str) -> str:
    """Start a background HTTP server to serve the QR code PNG.

    Returns the public URL (with token).
    """
    global _QRCODE_SERVER_STARTED
    with _QRCODE_SERVER_LOCK:
        if _QRCODE_SERVER_STARTED:
            pass
        else:
            token = _resolve_qrcode_http_token()
            port = int(_read_env_value("QRCODE_HTTP_PORT", "8888"))

            for offset in range(10):
                try:
                    server = socketserver.TCPServer(
                        ("0.0.0.0", port + offset),
                        _QRCodeHandler,
                    )
                    server.token = token
                    server.png_path = png_path
                    break
                except OSError:
                    pass
            else:
                print(f"[QRCode] HTTP server: all ports {port}-{port + 9} in use, skip")
                return ""

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _QRCODE_SERVER_STARTED = True
            _QRCODE_SERVER.port = server.server_address[1]
            _QRCODE_SERVER.token = token

    host = _read_env_value("QRCODE_HTTP_HOST", "")
    if not host:
        host = "127.0.0.1"
    final_url = f"http://{host}:{_QRCODE_SERVER.port}/{_QRCODE_SERVER.token}/qrcode_login.png"
    return final_url


def show_qrcode(qr_code) -> None:  # type: ignore
    """Parse base64 QR code image and display it via zbarimg + qrencode + HTTP server."""
    import shutil
    import subprocess

    if "," in qr_code:
        qr_code = qr_code.split(",")[1]
    qr_code = base64.b64decode(qr_code)
    image = Image.open(BytesIO(qr_code))

    # Add a square border around the QR code to improve scanning accuracy.
    width, height = image.size
    new_image = Image.new('RGB', (width + 20, height + 20), color=(255, 255, 255))
    new_image.paste(image, (10, 10))
    draw = ImageDraw.Draw(new_image)
    draw.rectangle((0, 0, width + 19, height + 19), outline=(0, 0, 0), width=1)

    # Save PNG file
    qr_png_path = str(Path.cwd() / "qrcode_login.png")
    new_image.save(qr_png_path, "PNG")
    print(f"\n[QRCode] QR code image saved to: {qr_png_path}")

    # HTTP server with token auth — start once per process
    http_url = _start_qrcode_http_server(qr_png_path)
    if http_url:
        print(f"[QRCode] HTTP 扫码地址: {http_url}")
        platform = _extract_platform_name()
        _send_pushplus_notification(platform, http_url)

    # Check zbarimg / qrencode availability
    if not shutil.which("zbarimg") or not shutil.which("qrencode"):
        print("[QRCode] zbarimg / qrencode not installed! Run: sudo apt install zbar-tools qrencode")
        print("[QRCode] Use the HTTP address above or saved file\n")
        return

    # zbarimg decode QR → qrencode re-encode for high-precision terminal display
    result = subprocess.run(
        ["zbarimg", "--quiet", "--raw", qr_png_path],
        capture_output=True, text=True, timeout=10,
    )
    qr_data = result.stdout.strip()
    if not qr_data or result.returncode != 0:
        print(f"[QRCode] zbarimg decode failed (rc={result.returncode}), use HTTP address above")
        if result.stderr:
            print(f"[QRCode] stderr: {result.stderr.strip()}")
        return

    result = subprocess.run(
        ["qrencode", "-t", "utf8", "-s", "3", "-m", "2", "-l", "H", qr_data],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"[QRCode] qrencode generation failed (rc={result.returncode}), use HTTP address above")
        if result.stderr:
            print(f"[QRCode] stderr: {result.stderr.strip()}")
        return

    print("\n[QRCode] Please scan the QR code below with your phone:\n")
    print(result.stdout)


def get_user_agent() -> str:
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5112.79 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.5060.53 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.4844.84 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5112.79 Safari/537.36"
    ]
    return random.choice(ua_list)


def get_mobile_user_agent() -> str:
    ua_list = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    ]
    return random.choice(ua_list)


def convert_cookies(cookies: Optional[List[Cookie]]) -> Tuple[str, Dict]:
    if not cookies:
        return "", {}
    cookies_str = ";".join([f"{cookie.get('name')}={cookie.get('value')}" for cookie in cookies])
    cookie_dict = dict()
    for cookie in cookies:
        cookie_dict[cookie.get('name')] = cookie.get('value')
    return cookies_str, cookie_dict


async def convert_browser_context_cookies(
    browser_context: BrowserContext, urls: Optional[List[str]] = None
) -> Tuple[str, Dict]:
    cookies = (
        await browser_context.cookies(urls=urls)
        if urls
        else await browser_context.cookies()
    )
    return convert_cookies(cookies)


def convert_str_cookie_to_dict(cookie_str: str) -> Dict:
    cookie_dict: Dict[str, str] = dict()
    if not cookie_str:
        return cookie_dict
    for cookie in cookie_str.split(";"):
        cookie = cookie.strip()
        if not cookie:
            continue
        cookie_list = cookie.split("=")
        if len(cookie_list) != 2:
            continue
        cookie_value = cookie_list[1]
        if isinstance(cookie_value, list):
            cookie_value = "".join(cookie_value)
        cookie_dict[cookie_list[0]] = cookie_value
    return cookie_dict


def match_interact_info_count(count_str: str) -> int:
    if not count_str:
        return 0

    match = re.search(r'\d+', count_str)
    if match:
        number = match.group()
        return int(number)
    else:
        return 0


def format_proxy_info(ip_proxy_info) -> Tuple[Optional[Dict], Optional[str]]:
    """format proxy info for playwright and httpx"""
    # fix circular import issue
    from proxy.proxy_ip_pool import IpInfoModel
    ip_proxy_info = cast(IpInfoModel, ip_proxy_info)

    # Playwright proxy server should be in format "host:port" without protocol prefix
    server = f"{ip_proxy_info.ip}:{ip_proxy_info.port}"

    playwright_proxy = {
        "server": server,
    }

    # Only add username and password if they are not empty
    if ip_proxy_info.user and ip_proxy_info.password:
        playwright_proxy["username"] = ip_proxy_info.user
        playwright_proxy["password"] = ip_proxy_info.password

    # httpx 0.28.1 requires passing proxy URL string directly, not a dictionary
    if ip_proxy_info.user and ip_proxy_info.password:
        httpx_proxy = f"http://{ip_proxy_info.user}:{ip_proxy_info.password}@{ip_proxy_info.ip}:{ip_proxy_info.port}"
    else:
        httpx_proxy = f"http://{ip_proxy_info.ip}:{ip_proxy_info.port}"
    return playwright_proxy, httpx_proxy


def extract_text_from_html(html: str) -> str:
    """Extract text from HTML, removing all tags."""
    if not html:
        return ""

    # Remove script and style elements
    clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL)
    # Remove all other tags
    clean_text = re.sub(r'<[^>]+>', '', clean_html).strip()
    return clean_text

def extract_url_params_to_dict(url: str) -> Dict:
    """Extract URL parameters to dict"""
    url_params_dict = dict()
    if not url:
        return url_params_dict
    parsed_url = urllib.parse.urlparse(url)
    url_params_dict = dict(urllib.parse.parse_qsl(parsed_url.query))
    return url_params_dict
