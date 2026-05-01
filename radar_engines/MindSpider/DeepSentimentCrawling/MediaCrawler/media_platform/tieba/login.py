# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/tieba/login.py
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
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import (RetryError, retry, retry_if_result, stop_after_attempt,
                      wait_fixed)

import config
from base.base_crawler import AbstractLogin
from tools import utils


class BaiduTieBaLogin(AbstractLogin):

    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext,
                 context_page: Page,
                 login_phone: Optional[str] = "",
                 cookie_str: str = ""
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    @retry(stop=stop_after_attempt(180), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, login_page_url: str = "") -> bool:
        """
        Verify login status: active page refresh + URL redirect + QR gone + cookie + user elements.
        """
        self._qr_check_count = getattr(self, '_qr_check_count', 0) + 1
        cnt = self._qr_check_count

        if cnt % 20 == 0 and cnt >= 20 and login_page_url:
            utils.logger.info(f"[Tieba] Active refresh #{cnt // 20} — reloading page...")
            try:
                await self.context_page.goto(login_page_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                utils.logger.info(f"[Tieba] Refresh goto failed: {e}")

        if login_page_url:
            current_url = self.context_page.url
            if current_url != login_page_url and "login" not in current_url.lower():
                utils.logger.info("[Tieba] Login confirmed by URL redirect")
                return True

        # QR code disappeared → verify with cookies + user elements
        try:
            qrcode_gone = not await self.context_page.is_visible(
                "xpath=//img[@class='tang-pass-qrcode-img']", timeout=300
            )
            if qrcode_gone:
                utils.logger.info("[Tieba] QR code disappeared, checking signals...")
                ck = await self.browser_context.cookies()
                _, cd = utils.convert_cookies(ck)
                if cd.get("STOKEN") or cd.get("PTOKEN"):
                    utils.logger.info("[Tieba] Login confirmed by STOKEN/PTOKEN cookie")
                    return True
                user_selectors = [
                    "xpath=//a[contains(@class, 'u_username')]",
                    "xpath=//span[contains(@class, 'user_name')]",
                ]
                for sel in user_selectors:
                    try:
                        if await self.context_page.is_visible(sel, timeout=200):
                            utils.logger.info("[Tieba] Login confirmed by user element + QR gone")
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        if cookie_dict.get("STOKEN") or cookie_dict.get("PTOKEN"):
            utils.logger.info("[Tieba] Login confirmed by STOKEN/PTOKEN cookie")
            return True
        return False

    async def begin(self):
        """Start login baidutieba"""
        utils.logger.info("[BaiduTieBaLogin.begin] Begin login baidutieba ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
            await asyncio.sleep(1)
            ck = await self.browser_context.cookies()
            _, cd = utils.convert_cookies(ck)
            if not cd.get("STOKEN") and not cd.get("PTOKEN"):
                utils.logger.info("[BaiduTieBaLogin.begin] cookie login failed - no STOKEN/PTOKEN found")
                sys.exit(42)
        else:
            raise ValueError("[BaiduTieBaLogin.begin]Invalid Login Type Currently only supported qrcode or phone or cookies ...")

    async def login_by_mobile(self):
        """Login baidutieba by mobile"""
        pass

    async def login_by_qrcode(self):
        """login baidutieba website and keep webdriver login state"""
        utils.logger.info("[BaiduTieBaLogin.login_by_qrcode] Begin login baidutieba by qrcode ...")
        qrcode_img_selector = "xpath=//img[@class='tang-pass-qrcode-img']"
        # find login qrcode
        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
        if not base64_qrcode_img:
            utils.logger.info("[BaiduTieBaLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
            # if this website does not automatically popup login dialog box, we will manual click login button
            await asyncio.sleep(0.5)
            login_button_ele = self.context_page.locator("xpath=//li[@class='u_login']")
            await login_button_ele.click()
            base64_qrcode_img = await utils.find_login_qrcode(
                self.context_page,
                selector=qrcode_img_selector
            )
            if not base64_qrcode_img:
                utils.logger.info("[BaiduTieBaLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
                sys.exit(42)

        # Capture login page URL for redirect detection
        login_page_url = self.context_page.url

        # show login qrcode
        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)

        utils.logger.info(f"[BaiduTieBaLogin.login_by_qrcode] waiting for scan code login, remaining time is 180s")
        try:
            await self.check_login_state(login_page_url)
        except RetryError:
            utils.logger.info("[BaiduTieBaLogin.login_by_qrcode] Login baidutieba failed by qrcode login method ...")
            sys.exit(42)

        wait_redirect_seconds = 5
        utils.logger.info(f"[BaiduTieBaLogin.login_by_qrcode] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    async def login_by_cookies(self):
        """login baidutieba website by cookies"""
        utils.logger.info("[BaiduTieBaLogin.login_by_cookies] Begin login baidutieba by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".baidu.com",
                'path': "/"
            }])
