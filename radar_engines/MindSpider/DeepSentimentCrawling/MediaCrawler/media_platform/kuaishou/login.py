# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/kuaishou/login.py
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


import asyncio
import functools
import sys
from typing import Awaitable, Callable, List, Optional

from playwright.async_api import BrowserContext, Page
from tenacity import (RetryError, retry, retry_if_result, stop_after_attempt,
                      wait_fixed)

import config
from base.base_crawler import AbstractLogin
from tools import utils


class KuaishouLogin(AbstractLogin):
    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext,
                 context_page: Page,
                 login_phone: Optional[str] = "",
                 cookie_str: str = "",
                 api_login_checker: Optional[Callable[[], Awaitable[bool]]] = None
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str
        self.api_login_checker = api_login_checker

    async def begin(self):
        """Start login kuaishou"""
        utils.logger.info("[KuaishouLogin.begin] Begin login kuaishou ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
            await asyncio.sleep(1)
            ck = await self.browser_context.cookies()
            _, cd = utils.convert_cookies(ck)
            if not cd.get("passToken"):
                utils.logger.info("[KuaishouLogin.begin] cookie login failed - no passToken found")
                sys.exit(42)
        else:
            raise ValueError("[KuaishouLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")

    async def _get_cookie_dict(self):
        cookies = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(cookies)
        return cookie_dict

    async def _check_api_login_state(self) -> bool:
        if not self.api_login_checker:
            return False
        try:
            return await self.api_login_checker()
        except Exception as e:
            utils.logger.info(f"[Kuaishou] API login verification failed: {e}")
            return False

    async def _log_post_scan_state(self, stage: str) -> None:
        try:
            current_url = self.context_page.url
        except Exception as e:
            current_url = f"<unavailable: {e}>"
        try:
            current_title = await self.context_page.title()
        except Exception as e:
            current_title = f"<unavailable: {e}>"
        cookie_dict = await self._get_cookie_dict()
        cookie_keys = sorted(cookie_dict.keys())
        interesting_cookie_presence = {
            "passToken": bool(cookie_dict.get("passToken")),
            "userId": bool(cookie_dict.get("userId")),
            "kuaishou.server.web_st": bool(cookie_dict.get("kuaishou.server.web_st")),
            "kuaishou.server.web_ph": bool(cookie_dict.get("kuaishou.server.web_ph")),
            "did": bool(cookie_dict.get("did")),
        }
        page_excerpt = ""
        try:
            content = await self.context_page.content()
            excerpt_parts = []
            for keyword in ("登录", "扫码", "二维码", "确认登录", "安全验证", "头像", "个人主页"):
                if keyword in content:
                    excerpt_parts.append(keyword)
            page_excerpt = ",".join(excerpt_parts)
        except Exception as e:
            page_excerpt = f"<content unavailable: {e}>"
        utils.logger.info(
            f"[Kuaishou] State snapshot ({stage}) - url={current_url}, title={current_title}, "
            f"interesting_cookies={interesting_cookie_presence}, cookie_keys={cookie_keys[:20]}, page_signals={page_excerpt}"
        )

    async def _try_open_login_dialog(self) -> None:
        login_entry_selectors = [
            "xpath=//p[text()='登录']",
            "xpath=//span[text()='登录']",
            "xpath=//div[contains(text(), '登录')]",
            "xpath=//button[contains(., '登录')]",
        ]
        for selector in login_entry_selectors:
            try:
                login_entry_ele = self.context_page.locator(selector)
                if not await login_entry_ele.is_visible(timeout=1500):
                    continue
                utils.logger.info(f"[KuaishouLogin] Trying login entry selector: {selector}")
                try:
                    await login_entry_ele.click(timeout=5000)
                    utils.logger.info(f"[KuaishouLogin] Login entry clicked via normal click: {selector}")
                    return
                except Exception as click_err:
                    utils.logger.info(f"[KuaishouLogin] Normal click failed for {selector}: {click_err}")
                    try:
                        await login_entry_ele.click(force=True, timeout=5000)
                        utils.logger.info(f"[KuaishouLogin] Login entry clicked via force click: {selector}")
                        return
                    except Exception as force_err:
                        utils.logger.info(f"[KuaishouLogin] Force click failed for {selector}: {force_err}")
                        try:
                            await login_entry_ele.evaluate("(el) => el.click()")
                            utils.logger.info(f"[KuaishouLogin] Login entry clicked via DOM click: {selector}")
                            return
                        except Exception as dom_err:
                            utils.logger.info(f"[KuaishouLogin] DOM click failed for {selector}: {dom_err}")
            except Exception:
                continue

    async def _wait_for_qrcode_dialog(self, selectors: List[str], attempts: int = 6, interval_seconds: float = 0.8) -> str:
        for attempt in range(1, attempts + 1):
            utils.logger.info(f"[KuaishouLogin] Waiting for QR dialog attempt {attempt}/{attempts}")
            for selector in selectors:
                base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=selector)
                if base64_qrcode_img:
                    utils.logger.info(f"[KuaishouLogin] QR dialog found via selector: {selector}")
                    return base64_qrcode_img
            await asyncio.sleep(interval_seconds)
        return ""

    @retry(stop=stop_after_attempt(180), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, login_page_url: str = "") -> bool:
        """
        Verify login status: active page refresh + URL redirect + QR gone + cookie + user elements.
        """
        self._qr_check_count = getattr(self, '_qr_check_count', 0) + 1
        cnt = self._qr_check_count

        if cnt % 20 == 0 and cnt >= 20 and login_page_url:
            utils.logger.info(f"[Kuaishou] Active refresh #{cnt // 20} — reloading page...")
            try:
                await self.context_page.goto(login_page_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                utils.logger.info(f"[Kuaishou] Refresh goto failed: {e}")

        if login_page_url:
            current_url = self.context_page.url
            if current_url != login_page_url and "login" not in current_url.lower():
                utils.logger.info("[Kuaishou] Login confirmed by URL redirect")
                return True

        qrcode_selectors = [
            "//div[@class='qrcode-img']//img",
            "//div[contains(@class, 'qrcode-img')]//img",
            "//img[contains(@src, 'qrcode')]",
        ]
        login_button_selectors = [
            "xpath=//p[text()='登录']",
            "xpath=//span[text()='登录']",
            "xpath=//div[contains(text(), '登录')]",
            "xpath=//button[contains(., '登录')]",
        ]

        try:
            qrcode_gone = True
            for selector in qrcode_selectors:
                if await self.context_page.is_visible(selector, timeout=300):
                    qrcode_gone = False
                    break
            login_btn_gone = True
            for selector in login_button_selectors:
                if await self.context_page.is_visible(selector, timeout=300):
                    login_btn_gone = False
                    break
            if qrcode_gone or login_btn_gone:
                utils.logger.info("[Kuaishou] QR/login button gone, checking signals...")
                await self._log_post_scan_state("ui_signals_changed")
                cookie_dict = await self._get_cookie_dict()
                if cookie_dict.get("passToken"):
                    utils.logger.info("[Kuaishou] Login confirmed by passToken cookie")
                    return True
                user_selectors = [
                    "xpath=//div[contains(@class, 'user-info')]",
                    "xpath=//img[contains(@class, 'avatar')]",
                ]
                for sel in user_selectors:
                    try:
                        if await self.context_page.is_visible(sel, timeout=200):
                            utils.logger.info("[Kuaishou] Login confirmed by user element + QR gone")
                            return True
                    except Exception:
                        pass
                if self.api_login_checker:
                    utils.logger.info("[Kuaishou] Browser signals are weak, verifying login via API...")
                    await self._log_post_scan_state("before_api_verify")
                    if await self._check_api_login_state():
                        utils.logger.info("[Kuaishou] Login confirmed by API verification")
                        return True
        except Exception:
            pass

        cookie_dict = await self._get_cookie_dict()
        if cookie_dict.get("passToken"):
            utils.logger.info("[Kuaishou] Login confirmed by passToken cookie")
            return True
        return False

    async def login_by_qrcode(self):
        """login kuaishou website and keep webdriver login state"""
        utils.logger.info("[KuaishouLogin.login_by_qrcode] Begin login kuaishou by qrcode ...")

        qrcode_img_selectors = [
            "//div[@class='qrcode-img']//img",
            "//div[contains(@class, 'qrcode-img')]//img",
            "//img[contains(@src, 'qrcode')]",
        ]
        base64_qrcode_img = await self._wait_for_qrcode_dialog(qrcode_img_selectors, attempts=3, interval_seconds=0.5)
        if not base64_qrcode_img:
            utils.logger.info(
                "[KuaishouLogin.login_by_qrcode] QR code dialog not visible yet, trying login button click ..."
            )
            await self._try_open_login_dialog()
            base64_qrcode_img = await self._wait_for_qrcode_dialog(qrcode_img_selectors, attempts=8, interval_seconds=0.75)
            if not base64_qrcode_img:
                if self.api_login_checker and await self._check_api_login_state():
                    utils.logger.info("[KuaishouLogin.login_by_qrcode] API already reports logged in, skip QR flow")
                    return
                utils.logger.info("[KuaishouLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
                sys.exit(42)
        else:
            utils.logger.info("[KuaishouLogin.login_by_qrcode] QR code already visible, skip login button click")

        # Capture login page URL for redirect detection
        login_page_url = self.context_page.url

        # show login qrcode
        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)

        utils.logger.info(f"[KuaishouLogin.login_by_qrcode] waiting for scan code login, remaining time is 180s")
        try:
            await self.check_login_state(login_page_url)
        except RetryError:
            utils.logger.info("[KuaishouLogin.login_by_qrcode] Login kuaishou failed by qrcode login method ...")
            sys.exit(42)

        wait_redirect_seconds = 5
        utils.logger.info(f"[KuaishouLogin.login_by_qrcode] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    async def login_by_mobile(self):
        pass

    async def login_by_cookies(self):
        utils.logger.info("[KuaishouLogin.login_by_cookies] Begin login kuaishou by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".kuaishou.com",
                'path': "/"
            }])
