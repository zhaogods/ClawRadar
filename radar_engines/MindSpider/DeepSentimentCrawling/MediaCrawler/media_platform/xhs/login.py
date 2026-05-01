# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/xhs/login.py
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
import time
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import (RetryError, retry, retry_if_result, stop_after_attempt,
                      wait_fixed)

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils


class XiaoHongShuLogin(AbstractLogin):

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
    async def check_login_state(self, no_logged_in_session: str, login_page_url: str = "") -> bool:
        """
        Verify login status using multi-signal detection + active page refresh.

        Passive checks run every 1s. After 20s, page is actively refreshed every 20s
        to trigger the post-login redirect that the page's own JS polling may miss.

        UI-based checks (QR gone, user elements) are NOT trusted alone —
        after page refresh the homepage shows sidebar/Me even when logged out.
        These checks now require API-level confirmation.
        """
        self._qr_check_count = getattr(self, '_qr_check_count', 0) + 1
        cnt = self._qr_check_count

        # 0. Active page refresh — trigger post-login redirect
        #    XHS page uses JS polling/WebSocket to detect scan confirmation.
        #    In Playwright + Xvfb this sometimes stalls. Periodic goto() forces
        #    a fresh navigation; if the session is authenticated server-side,
        #    the page loads without the login modal.
        if cnt % 20 == 0 and cnt >= 20 and login_page_url:
            utils.logger.info(f"[XHS] Active refresh #{cnt // 20} — reloading page to trigger redirect...")
            try:
                await self.context_page.goto(login_page_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                utils.logger.info(f"[XHS] Refresh goto failed: {e}")

        # 1. URL redirect detection — page navigated away from login
        if login_page_url:
            current_url = self.context_page.url
            if current_url != login_page_url and "/login" not in current_url.lower():
                utils.logger.info("[XHS] Login confirmed by URL redirect")
                return True

        # 2. QR code disappearance + user content appeared → API verify
        try:
            qrcode_gone = not await self.context_page.is_visible(
                "xpath=//img[@class='qrcode-img']", timeout=300
            )
            login_dialog_gone = not await self.context_page.is_visible(
                "div.login-container", timeout=300
            )
            if qrcode_gone or login_dialog_gone:
                user_selectors = [
                    "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']",
                    "xpath=//*[@id='app']//div[contains(@class, 'user')]",
                    "xpath=//div[contains(@class, 'side-bar')]",
                ]
                for sel in user_selectors:
                    try:
                        if await self.context_page.is_visible(sel, timeout=300):
                            utils.logger.info("[XHS] QR gone + user element visible, verifying with API...")
                            if await self._verify_login_via_api():
                                utils.logger.info("[XHS] Login confirmed by API (QR gone + user element)")
                                return True
                            utils.logger.info("[XHS] UI signals were false positive, API denied")
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. UI element check — "Me" button → API verify
        try:
            user_profile_selector = "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']"
            is_visible = await self.context_page.is_visible(user_profile_selector, timeout=500)
            if is_visible:
                utils.logger.info("[XHS] UI element ('Me' button) visible, verifying with API...")
                if await self._verify_login_via_api():
                    utils.logger.info("[XHS] Login confirmed by API ('Me' button)")
                    return True
                utils.logger.info("[XHS] UI element was false positive, API denied")
        except Exception:
            pass

        # 4. CAPTCHA appeared
        if "请通过验证" in await self.context_page.content():
            utils.logger.info("[XHS] CAPTCHA appeared, please verify manually")

        # 5. Cookie-based change detection (trusted — cookie changes only on real login)
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        current_web_session = cookie_dict.get("web_session")
        if current_web_session and current_web_session != no_logged_in_session:
            utils.logger.info("[XHS] Login confirmed by Cookie (web_session changed)")
            return True

        return False

    async def _verify_login_via_api(self) -> bool:
        """Call XHS user/selfinfo API from browser context to confirm login.

        Uses page.evaluate() to fetch the API with browser cookies.
        Cooldown: 5s between attempts to avoid rate limiting.
        """
        now = time.monotonic()
        last = getattr(self, '_last_api_verify_attempt', 0)
        if now - last < 5:
            return False
        self._last_api_verify_attempt = now

        api_host = "https://webapi.rednote.com" if config.XHS_INTERNATIONAL else "https://edith.xiaohongshu.com"
        try:
            result = await self.context_page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch('{api_host}/api/sns/web/v1/user/selfinfo', {{
                            credentials: 'include'
                        }});
                        if (!resp.ok) return false;
                        const data = await resp.json();
                        return data && data.data && data.data.result && data.data.result.success === true;
                    }} catch(e) {{
                        return false;
                    }}
                }}
            """)
            return bool(result)
        except Exception:
            return False

    async def begin(self):
        """Start login xiaohongshu"""
        utils.logger.info("[XiaoHongShuLogin.begin] Begin login xiaohongshu ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("[XiaoHongShuLogin.begin]I nvalid Login Type Currently only supported qrcode or phone or cookies ...")

    async def login_by_mobile(self):
        """Login xiaohongshu by mobile"""
        utils.logger.info("[XiaoHongShuLogin.login_by_mobile] Begin login xiaohongshu by mobile ...")
        await asyncio.sleep(1)
        try:
            # After entering Xiaohongshu homepage, the login dialog may not pop up automatically, need to manually click login button
            login_button_ele = await self.context_page.wait_for_selector(
                selector="xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button",
                timeout=5000
            )
            await login_button_ele.click()
            # The login dialog has two forms: one shows phone number and verification code directly
            # The other requires clicking to switch to phone login
            element = await self.context_page.wait_for_selector(
                selector='xpath=//div[@class="login-container"]//div[@class="other-method"]/div[1]',
                timeout=5000
            )
            await element.click()
        except Exception as e:
            utils.logger.info("[XiaoHongShuLogin.login_by_mobile] have not found mobile button icon and keep going ...")

        await asyncio.sleep(1)
        login_container_ele = await self.context_page.wait_for_selector("div.login-container")
        input_ele = await login_container_ele.query_selector("label.phone > input")
        await input_ele.fill(self.login_phone)
        await asyncio.sleep(0.5)

        send_btn_ele = await login_container_ele.query_selector("label.auth-code > span")
        await send_btn_ele.click()  # Click to send verification code
        sms_code_input_ele = await login_container_ele.query_selector("label.auth-code > input")
        submit_btn_ele = await login_container_ele.query_selector("div.input-container > button")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 60 * 2  # Maximum time to get verification code is 2 minutes
        no_logged_in_session = ""
        while max_get_sms_code_time > 0:
            utils.logger.info(f"[XiaoHongShuLogin.login_by_mobile] get sms code from redis remaining time {max_get_sms_code_time}s ...")
            await asyncio.sleep(1)
            sms_code_key = f"xhs_{self.login_phone}"
            sms_code_value = cache_client.get(sms_code_key)
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue

            current_cookie = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookie)
            no_logged_in_session = cookie_dict.get("web_session")

            await sms_code_input_ele.fill(value=sms_code_value.decode())  # Enter SMS verification code
            await asyncio.sleep(0.5)
            agree_privacy_ele = self.context_page.locator("xpath=//div[@class='agreements']//*[local-name()='svg']")
            await agree_privacy_ele.click()  # Click to agree to privacy policy
            await asyncio.sleep(0.5)

            await submit_btn_ele.click()  # Click login

            # TODO: Should also check if the verification code is correct, as it may be incorrect
            break

        try:
            await self.check_login_state(no_logged_in_session)
        except RetryError:
            utils.logger.info("[XiaoHongShuLogin.login_by_mobile] Login xiaohongshu failed by mobile login method ...")
            sys.exit(42)

        wait_redirect_seconds = 5
        utils.logger.info(f"[XiaoHongShuLogin.login_by_mobile] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    async def login_by_qrcode(self):
        """login xiaohongshu website and keep webdriver login state"""
        utils.logger.info("[XiaoHongShuLogin.login_by_qrcode] Begin login xiaohongshu by qrcode ...")
        # login_selector = "div.login-container > div.left > div.qrcode > img"
        qrcode_img_selector = "xpath=//img[@class='qrcode-img']"
        # find login qrcode
        base64_qrcode_img = await utils.find_login_qrcode(
            self.context_page,
            selector=qrcode_img_selector
        )
        if not base64_qrcode_img:
            utils.logger.info("[XiaoHongShuLogin.login_by_qrcode] login failed , have not found qrcode please check ....")
            # if this website does not automatically popup login dialog box, we will manual click login button
            await asyncio.sleep(0.5)
            login_button_ele = self.context_page.locator("xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button")
            await login_button_ele.click()
            base64_qrcode_img = await utils.find_login_qrcode(
                self.context_page,
                selector=qrcode_img_selector
            )
            if not base64_qrcode_img:
                sys.exit(42)

        # Capture login page URL for redirect detection
        login_page_url = self.context_page.url

        # get not logged session
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        no_logged_in_session = cookie_dict.get("web_session")

        # show login qrcode
        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)

        utils.logger.info(f"[XiaoHongShuLogin.login_by_qrcode] waiting for scan code login, remaining time is 180s")
        try:
            await self.check_login_state(no_logged_in_session, login_page_url)
        except RetryError:
            utils.logger.info("[XiaoHongShuLogin.login_by_qrcode] Login xiaohongshu failed by qrcode login method ...")
            sys.exit(42)

        wait_redirect_seconds = 5
        utils.logger.info(f"[XiaoHongShuLogin.login_by_qrcode] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    async def login_by_cookies(self):
        """login xiaohongshu website by cookies"""
        utils.logger.info("[XiaoHongShuLogin.login_by_cookies] Begin login xiaohongshu by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            if key != "web_session":  # Only set web_session cookie attribute
                continue
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".rednote.com" if config.XHS_INTERNATIONAL else ".xiaohongshu.com",
                'path': "/"
            }])
