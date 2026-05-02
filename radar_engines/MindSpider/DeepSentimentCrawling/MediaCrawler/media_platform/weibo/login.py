# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/weibo/login.py
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
# @Time    : 2023/12/23 15:42
# @Desc    : Weibo login implementation

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


class WeiboLogin(AbstractLogin):
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
        self.weibo_sso_login_url = "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog"

    async def begin(self):
        """Start login weibo"""
        utils.logger.info("[WeiboLogin.begin] Begin login weibo ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
            await asyncio.sleep(1)
            ck = await self.browser_context.cookies()
            _, cd = utils.convert_cookies(ck)
            if not cd.get("SSOLoginState") and not cd.get("WBPSESS"):
                utils.logger.info("[WeiboLogin.begin] cookie login failed - no SSOLoginState/WBPSESS found")
                sys.exit(42)
        else:
            raise ValueError(
                "[WeiboLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")


    @retry(stop=stop_after_attempt(config.QR_LOGIN_WAIT_SECONDS), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, no_logged_in_session: str, login_page_url: str = "") -> bool:
        """
        Verify login status: active page refresh + URL redirect + cookie checks.
        """
        self._qr_check_count = getattr(self, '_qr_check_count', 0) + 1
        cnt = self._qr_check_count

        # Periodic active refresh to trigger post-login redirect
        if cnt % 20 == 0 and cnt >= 20 and login_page_url:
            utils.logger.info(f"[Weibo] Active refresh #{cnt // 20} — reloading page...")
            try:
                await self.context_page.goto(login_page_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                utils.logger.info(f"[Weibo] Refresh goto failed: {e}")

        if login_page_url:
            current_url = self.context_page.url
            if current_url != login_page_url and "passport.weibo.com" not in current_url:
                utils.logger.info("[Weibo] Login confirmed by URL redirect")
                return True

        try:
            qrcode_gone = not await self.context_page.is_visible(
                "xpath=//img[@class='w-full h-full']", timeout=300
            )
            if qrcode_gone:
                utils.logger.info("[Weibo] QR code disappeared, checking signals...")
                # QR gone → check cookies immediately (strong signal)
                ck = await self.browser_context.cookies()
                _, cd = utils.convert_cookies(ck)
                if cd.get("SSOLoginState"):
                    utils.logger.info("[Weibo] Login confirmed by SSOLoginState cookie")
                    return True
                if cd.get("WBPSESS") and cd.get("WBPSESS") != no_logged_in_session:
                    utils.logger.info("[Weibo] Login confirmed by WBPSESS change")
                    return True
                # Check user elements on refreshed page
                user_selectors = [
                    "xpath=//div[contains(@class, 'woo-box')]",
                    "xpath=//span[contains(@class, 'Frame_name')]",
                ]
                for sel in user_selectors:
                    try:
                        if await self.context_page.is_visible(sel, timeout=200):
                            utils.logger.info("[Weibo] Login confirmed by user element + QR gone")
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        if cookie_dict.get("SSOLoginState"):
            utils.logger.info("[Weibo] Login confirmed by SSOLoginState cookie")
            return True
        current_web_session = cookie_dict.get("WBPSESS")
        if current_web_session and current_web_session != no_logged_in_session:
            utils.logger.info("[Weibo] Login confirmed by WBPSESS change")
            return True
        return False

    async def login_by_qrcode(self):
        """login weibo website and keep webdriver login state"""
        utils.logger.info("[WeiboLogin.login_by_qrcode] Begin login weibo by qrcode ...")
        await self.context_page.goto(self.weibo_sso_login_url)
        # find login qrcode
        qrcode_img_selector = "xpath=//img[@class='w-full h-full']"
        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
        if not base64_qrcode_img:
            utils.logger.info("[WeiboLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
            sys.exit(42)

        # Capture SSO login page URL for redirect detection
        login_page_url = self.context_page.url

        # show login qrcode
        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)

        utils.logger.info(f"[WeiboLogin.login_by_qrcode] Waiting for scan code login, remaining time is {config.QR_LOGIN_WAIT_SECONDS}s")

        # get not logged session
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        no_logged_in_session = cookie_dict.get("WBPSESS")

        try:
            await self.check_login_state(no_logged_in_session, login_page_url)
        except RetryError:
            utils.logger.info("[WeiboLogin.login_by_qrcode] Login weibo failed by qrcode login method ...")
            sys.exit(42)

        wait_redirect_seconds = 5
        utils.logger.info(
            f"[WeiboLogin.login_by_qrcode] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    async def login_by_mobile(self):
        pass

    async def login_by_cookies(self):
        utils.logger.info("[WeiboLogin.login_by_qrcode] Begin login weibo by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".weibo.cn",
                'path': "/"
            }])
