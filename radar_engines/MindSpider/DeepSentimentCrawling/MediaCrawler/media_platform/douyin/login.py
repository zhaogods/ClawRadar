# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/login.py
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
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import (RetryError, retry, retry_if_result, stop_after_attempt,
                      wait_fixed)

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils


class DouYinLogin(AbstractLogin):

    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext, # type: ignore
                 context_page: Page, # type: ignore
                 login_phone: Optional[str] = "",
                 cookie_str: Optional[str] = ""
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.scan_qrcode_time = 60
        self.cookie_str = cookie_str
        self._login_page_url = ""

    async def begin(self):
        """
            Start login douyin website
            The verification accuracy of the slider verification is not very good... If there are no special requirements, it is recommended not to use Douyin login, or use cookie login
        """

        # popup login dialog
        await self.popup_login_dialog()

        # Capture login page URL for redirect detection
        self._login_page_url = self.context_page.url

        # select login type
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("[DouYinLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")

        # If the page redirects to the slider verification page, need to slide again
        await asyncio.sleep(6)
        current_page_title = await self.context_page.title()
        if "验证码中间页" in current_page_title:
            await self.check_page_display_slider(move_step=3, slider_level="hard")

        # check login state
        utils.logger.info(f"[DouYinLogin.begin] login finished then check login state ...")
        try:
            await self.check_login_state()
        except RetryError:
            utils.logger.info("[DouYinLogin.begin] login failed please confirm ...")
            sys.exit(42)

        # wait for redirect
        wait_redirect_seconds = 5
        utils.logger.info(f"[DouYinLogin.begin] Login successful then wait for {wait_redirect_seconds} seconds redirect ...")
        await asyncio.sleep(wait_redirect_seconds)

    @retry(stop=stop_after_attempt(config.QR_LOGIN_WAIT_SECONDS), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self):
        """Check if the current login status is successful and return True otherwise return False

        Multi-signal detection: URL redirect, login dialog gone, localStorage,
        cookie, user avatar. Active page refresh every 20s to trigger post-login
        page state update that the page's own JS may miss in Xvfb.
        """
        self._qr_check_count = getattr(self, '_qr_check_count', 0) + 1
        cnt = self._qr_check_count

        # 0. Active page refresh to trigger post-login redirect
        if cnt % 20 == 0 and cnt >= 20 and self._login_page_url:
            utils.logger.info(f"[Douyin] Active refresh #{cnt // 20} — reloading page...")
            try:
                await self.context_page.goto(self._login_page_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            except Exception as e:
                utils.logger.info(f"[Douyin] Refresh goto failed: {e}")

        # 1. URL redirect detection
        if self._login_page_url:
            current_url = self.context_page.url
            if current_url != self._login_page_url:
                utils.logger.info("[Douyin] Login confirmed by URL redirect")
                return True

        # 2. Login UI disappeared → verify with state checks
        try:
            login_panel_gone = not await self.context_page.is_visible(
                "xpath=//div[@id='login-panel-new']", timeout=300
            )
            qrcode_gone = not await self.context_page.is_visible(
                "xpath=//div[@id='animate_qrcode_container']", timeout=300
            )
            if login_panel_gone and qrcode_gone:
                # Login dialog closed — check if user is actually logged in
                user_selectors = [
                    "xpath=//img[contains(@class, 'avatar')]",
                    "xpath=//div[contains(@class, 'user-info')]",
                    "xpath=//span[contains(@class, 'user-name')]",
                    "xpath=//a[@data-e2e='user-info']",
                ]
                for sel in user_selectors:
                    try:
                        if await self.context_page.is_visible(sel, timeout=300):
                            utils.logger.info("[Douyin] Login dialog gone + user element visible")
                            # Double-check with localStorage
                            for page in self.browser_context.pages:
                                try:
                                    ls = await page.evaluate("() => window.localStorage")
                                    if ls.get("HasUserLogin", "") == "1":
                                        utils.logger.info("[Douyin] Confirmed by localStorage")
                                        return True
                                except Exception:
                                    pass
                            # Check cookie
                            ck = await self.browser_context.cookies()
                            _, cd = utils.convert_cookies(ck)
                            if cd.get("LOGIN_STATUS") == "1":
                                utils.logger.info("[Douyin] Confirmed by LOGIN_STATUS cookie")
                                return True
                            # User element visible + login gone → likely logged in
                            utils.logger.info("[Douyin] Login confirmed by UI signals (dialog gone + user visible)")
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. localStorage check (standalone, in case UI checks missed)
        for page in self.browser_context.pages:
            try:
                local_storage = await page.evaluate("() => window.localStorage")
                if local_storage.get("HasUserLogin", "") == "1":
                    utils.logger.info("[Douyin] Login confirmed by localStorage HasUserLogin")
                    return True
            except Exception:
                await asyncio.sleep(0.1)

        # 4. Cookie-based detection
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        if cookie_dict.get("LOGIN_STATUS") == "1":
            utils.logger.info("[Douyin] Login confirmed by LOGIN_STATUS cookie")
            return True

        return False

    async def popup_login_dialog(self):
        """If the login dialog box does not pop up automatically, we will manually click the login button"""
        dialog_selector = "xpath=//div[@id='login-panel-new']"
        try:
            # check dialog box is auto popup and wait for 10 seconds
            await self.context_page.wait_for_selector(dialog_selector, timeout=1000 * 10)
        except Exception as e:
            utils.logger.error(f"[DouYinLogin.popup_login_dialog] login dialog box does not pop up automatically, error: {e}")
            utils.logger.info("[DouYinLogin.popup_login_dialog] login dialog box does not pop up automatically, we will manually click the login button")
            login_button_ele = self.context_page.locator("xpath=//p[text() = '登录']")
            await login_button_ele.click()
            await asyncio.sleep(0.5)

    async def login_by_qrcode(self):
        utils.logger.info("[DouYinLogin.login_by_qrcode] Begin login douyin by qrcode...")

        # Switch to QR code tab — login dialog defaults to phone login
        qr_tab_selectors = [
            "xpath=//li[contains(text(), '扫码')]",
            "xpath=//span[contains(text(), '扫码')]",
            "xpath=//div[contains(@class, 'qrcode')]//..",
        ]
        qr_tab_found = False
        for sel in qr_tab_selectors:
            try:
                tab_ele = self.context_page.locator(sel)
                if await tab_ele.is_visible(timeout=2000):
                    await tab_ele.click()
                    await asyncio.sleep(1)
                    utils.logger.info(f"[DouYinLogin.login_by_qrcode] Switched to QR tab via: {sel}")
                    qr_tab_found = True
                    break
            except Exception:
                continue

        if not qr_tab_found:
            utils.logger.info("[DouYinLogin.login_by_qrcode] QR tab not found, trying direct QR detection...")

        # Find login qrcode — try multiple selectors
        qrcode_img_selectors = [
            "xpath=//div[@id='animate_qrcode_container']//img",
            "xpath=//div[contains(@class, 'qrcode')]//img",
            "xpath=//canvas[contains(@class, 'qrcode')]",
        ]
        base64_qrcode_img = ""
        for sel in qrcode_img_selectors:
            base64_qrcode_img = await utils.find_login_qrcode(
                self.context_page,
                selector=sel
            )
            if base64_qrcode_img:
                break

        if not base64_qrcode_img:
            utils.logger.info("[DouYinLogin.login_by_qrcode] login qrcode not found please confirm ...")
            sys.exit(42)

        partial_show_qrcode = functools.partial(utils.show_qrcode, base64_qrcode_img)
        asyncio.get_running_loop().run_in_executor(executor=None, func=partial_show_qrcode)
        await asyncio.sleep(2)

    async def login_by_mobile(self):
        utils.logger.info("[DouYinLogin.login_by_mobile] Begin login douyin by mobile ...")
        mobile_tap_ele = self.context_page.locator("xpath=//li[text() = '验证码登录']")
        await mobile_tap_ele.click()
        await self.context_page.wait_for_selector("xpath=//article[@class='web-login-mobile-code']")
        mobile_input_ele = self.context_page.locator("xpath=//input[@placeholder='手机号']")
        await mobile_input_ele.fill(self.login_phone)
        await asyncio.sleep(0.5)
        send_sms_code_btn = self.context_page.locator("xpath=//span[text() = '获取验证码']")
        await send_sms_code_btn.click()

        # Check if there is slider verification
        await self.check_page_display_slider(move_step=10, slider_level="easy")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 60 * 2  # Maximum time to get verification code is 2 minutes
        while max_get_sms_code_time > 0:
            utils.logger.info(f"[DouYinLogin.login_by_mobile] get douyin sms code from redis remaining time {max_get_sms_code_time}s ...")
            await asyncio.sleep(1)
            sms_code_key = f"dy_{self.login_phone}"
            sms_code_value = cache_client.get(sms_code_key)
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue

            sms_code_input_ele = self.context_page.locator("xpath=//input[@placeholder='请输入验证码']")
            await sms_code_input_ele.fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            submit_btn_ele = self.context_page.locator("xpath=//button[@class='web-login-button']")
            await submit_btn_ele.click()  # Click login
            # todo ... should also check the correctness of the verification code, it may be incorrect
            break

    async def check_page_display_slider(self, move_step: int = 10, slider_level: str = "easy"):
        """
        Check if slider verification appears on the page
        :return:
        """
        # Wait for slider verification to appear
        back_selector = "#captcha-verify-image"
        try:
            await self.context_page.wait_for_selector(selector=back_selector, state="visible", timeout=30 * 1000)
        except PlaywrightTimeoutError:  # No slider verification, return directly
            return

        gap_selector = 'xpath=//*[@id="captcha_container"]/div/div[2]/img[2]'
        max_slider_try_times = 20
        slider_verify_success = False
        while not slider_verify_success:
            if max_slider_try_times <= 0:
                utils.logger.error("[DouYinLogin.check_page_display_slider] slider verify failed ...")
                sys.exit(42)
            try:
                await self.move_slider(back_selector, gap_selector, move_step, slider_level)
                await asyncio.sleep(1)

                # If the slider is too slow or verification failed, it will prompt "The operation is too slow", click the refresh button here
                page_content = await self.context_page.content()
                if "操作过慢" in page_content or "提示重新操作" in page_content:
                    utils.logger.info("[DouYinLogin.check_page_display_slider] slider verify failed, retry ...")
                    await self.context_page.click(selector="//a[contains(@class, 'secsdk_captcha_refresh')]")
                    continue

                # After successful sliding, wait for the slider to disappear
                await self.context_page.wait_for_selector(selector=back_selector, state="hidden", timeout=1000)
                # If the slider disappears, it means the verification is successful, break the loop. If not, it means the verification failed, the above line will throw an exception and be caught to continue the loop
                utils.logger.info("[DouYinLogin.check_page_display_slider] slider verify success ...")
                slider_verify_success = True
            except Exception as e:
                utils.logger.error(f"[DouYinLogin.check_page_display_slider] slider verify failed, error: {e}")
                await asyncio.sleep(1)
                max_slider_try_times -= 1
                utils.logger.info(f"[DouYinLogin.check_page_display_slider] remaining slider try times: {max_slider_try_times}")
                continue

    async def move_slider(self, back_selector: str, gap_selector: str, move_step: int = 10, slider_level="easy"):
        """
        Move the slider to the right to complete the verification
        :param back_selector: Selector for the slider verification background image
        :param gap_selector:  Selector for the slider verification slider
        :param move_step: Controls the ratio of single movement speed, default is 1, meaning the distance moves in 0.1 seconds no matter how far, larger value means slower
        :param slider_level: Slider difficulty easy hard, corresponding to the slider for mobile verification code and the slider in the middle of verification code
        :return:
        """

        # get slider background image
        slider_back_elements = await self.context_page.wait_for_selector(
            selector=back_selector,
            timeout=1000 * 10,  # wait 10 seconds
        )
        slide_back = str(await slider_back_elements.get_property("src")) # type: ignore

        # get slider gap image
        gap_elements = await self.context_page.wait_for_selector(
            selector=gap_selector,
            timeout=1000 * 10,  # wait 10 seconds
        )
        gap_src = str(await gap_elements.get_property("src")) # type: ignore

        # Identify slider position
        slide_app = utils.Slide(gap=gap_src, bg=slide_back)
        distance = slide_app.discern()

        # Get movement trajectory
        tracks = utils.get_tracks(distance, slider_level)
        new_1 = tracks[-1] - (sum(tracks) - distance)
        tracks.pop()
        tracks.append(new_1)

        # Drag slider to specified position according to trajectory
        element = await self.context_page.query_selector(gap_selector)
        bounding_box = await element.bounding_box() # type: ignore

        await self.context_page.mouse.move(bounding_box["x"] + bounding_box["width"] / 2, # type: ignore
                                           bounding_box["y"] + bounding_box["height"] / 2) # type: ignore
        # Get x coordinate center position
        x = bounding_box["x"] + bounding_box["width"] / 2 # type: ignore
        # Simulate sliding operation
        await element.hover() # type: ignore
        await self.context_page.mouse.down()

        for track in tracks:
            # Loop mouse movement according to trajectory
            # steps controls the ratio of single movement speed, default is 1, meaning the distance moves in 0.1 seconds no matter how far, larger value means slower
            await self.context_page.mouse.move(x + track, 0, steps=move_step)
            x += track
        await self.context_page.mouse.up()

    async def login_by_cookies(self):
        utils.logger.info("[DouYinLogin.login_by_cookies] Begin login douyin by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".douyin.com",
                'path': "/"
            }])
