"""WeChat Official Account API client — token, material upload, draft creation."""

from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path
from typing import Any, Optional

import markdown
import requests
from PIL import Image, ImageDraw, ImageFont

WECHAT_TITLE_MAX_CHARS = 64
WECHAT_AUTHOR_MAX_CHARS = 8
WECHAT_DIGEST_MAX_CHARS = 120


def _truncate_chars(text: str, max_chars: int, fallback: str = "") -> str:
    value = str(text or "").strip()
    if not value:
        value = fallback.strip()
    if not value:
        return ""
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


class WeChatDraftUploadError(RuntimeError):
    def __init__(self, *, errcode: str, errmsg: str, attempted_title: str, attempted_title_utf8_bytes: int):
        self.errcode = str(errcode or "").strip()
        self.errmsg = str(errmsg or "").strip()
        self.attempted_title = str(attempted_title or "").strip()
        self.attempted_title_utf8_bytes = int(attempted_title_utf8_bytes)
        message = f"创建微信草稿失败：errcode={self.errcode}，errmsg={self.errmsg or '未返回错误信息'}。"
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "errcode": self.errcode,
            "errmsg": self.errmsg,
            "attempted_title": self.attempted_title,
            "attempted_title_utf8_bytes": self.attempted_title_utf8_bytes,
        }


class WeChatPublisher:
    def __init__(self, appid: str, secret: str):
        self.appid = appid
        self.secret = secret
        self.access_token: Optional[str] = None
        self.last_error_message: Optional[str] = None
        self.last_error_code: Optional[str] = None
        self.last_error_details: Optional[dict[str, Any]] = None
        self.base_url = "https://api.weixin.qq.com/cgi-bin"

    def get_access_token(self) -> Optional[str]:
        if self.access_token:
            self.last_error_message = None
            self.last_error_code = None
            self.last_error_details = None
            return self.access_token

        response = requests.get(
            f"{self.base_url}/token",
            params={
                "grant_type": "client_credential",
                "appid": self.appid,
                "secret": self.secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        token = str(data.get("access_token") or "").strip()
        if not token:
            errcode = str(data.get("errcode") or "").strip()
            errmsg = str(data.get("errmsg") or "").strip()
            self.last_error_code = errcode or None
            self.last_error_details = {"errcode": errcode, "errmsg": errmsg} if errcode else None
            if errcode:
                self.last_error_message = f"获取微信 access_token 失败：errcode={errcode}，errmsg={errmsg or '未返回错误信息'}。"
            else:
                self.last_error_message = "获取微信 access_token 失败：微信接口未返回 access_token。"
            return None
        self.last_error_message = None
        self.last_error_code = None
        self.last_error_details = None
        self.access_token = token
        return token

    def upload_image(self, image_path: str) -> Optional[str]:
        access_token = self.access_token or self.get_access_token()
        if not access_token:
            return None

        with Path(image_path).open("rb") as handle:
            response = requests.post(
                f"{self.base_url}/material/add_material",
                params={"access_token": access_token, "type": "image"},
                files={"media": handle},
                timeout=30,
            )
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") not in (None, 0):
            errcode = str(data.get("errcode") or "").strip()
            errmsg = str(data.get("errmsg") or "").strip()
            self.last_error_code = errcode or None
            self.last_error_details = {"errcode": errcode, "errmsg": errmsg} if errcode else None
            self.last_error_message = f"上传微信图片失败：errcode={errcode}，errmsg={errmsg or '未返回错误信息'}。"
            return None
        self.last_error_message = None
        self.last_error_code = None
        self.last_error_details = None
        media_id = str(data.get("media_id") or "").strip()
        return media_id or None

    def upload_default_cover(self, title: str = "") -> Optional[str]:
        image = Image.new("RGB", (900, 383), color=(242, 247, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        accent = (55, 94, 212)
        draw.rectangle((0, 0, 900, 383), fill=(242, 247, 255))
        draw.rectangle((0, 0, 900, 28), fill=accent)
        draw.text((60, 72), "ClawRadar", fill=accent, font=font)

        safe_title = (title or "ClawRadar Report").strip() or "ClawRadar Report"
        wrapped_lines = []
        current = ""
        for char in safe_title[:80]:
            trial = f"{current}{char}"
            if len(trial) <= 26:
                current = trial
            else:
                wrapped_lines.append(current)
                current = char
        if current:
            wrapped_lines.append(current)
        wrapped_lines = wrapped_lines[:3]

        y = 132
        for line in wrapped_lines:
            draw.text((60, y), line, fill=(34, 34, 34), font=font)
            y += 36

        draw.text((60, 316), "Generated for WeChat draft cover", fill=(102, 102, 102), font=font)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            temp_path = Path(tmp.name)
        try:
            image.save(temp_path, format="PNG")
            return self.upload_image(str(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)

    def upload_draft(
        self,
        title: str,
        content: str,
        author: str | None = None,
        digest: str = "",
        thumb_media_id: str | None = None,
    ) -> Optional[str]:
        access_token = self.access_token or self.get_access_token()
        if not access_token or not thumb_media_id:
            return None

        attempted_title = _truncate_chars(title, WECHAT_TITLE_MAX_CHARS, "Untitled")
        attempted_title_utf8_bytes = len(attempted_title.encode("utf-8"))
        digest_value = str(digest or "").strip()
        constrained_digest = _truncate_chars(digest_value, WECHAT_DIGEST_MAX_CHARS, "")
        article = {
            "title": attempted_title,
            "author": _truncate_chars(author, WECHAT_AUTHOR_MAX_CHARS, "ClawRadar"),
            "digest": constrained_digest,
            "content": content,
            "content_source_url": "",
            "thumb_media_id": thumb_media_id,
            "show_cover_pic": 1,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        body = json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8")
        response = requests.post(
            f"{self.base_url}/draft/add",
            params={"access_token": access_token},
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()
        if data.get("errcode") not in (None, 0):
            errcode = str(data.get("errcode") or "").strip()
            errmsg = str(data.get("errmsg") or "").strip()
            self.last_error_code = errcode or None
            self.last_error_details = {
                "errcode": errcode,
                "errmsg": errmsg,
                "attempted_title": attempted_title,
                "attempted_title_utf8_bytes": attempted_title_utf8_bytes,
                "attempted_digest": constrained_digest,
                "attempted_digest_utf8_bytes": len(constrained_digest.encode("utf-8")),
                "attempted_digest_chars": len(constrained_digest),
                "attempted_digest_text_units": len(constrained_digest),
            }
            self.last_error_message = f"创建微信草稿失败：errcode={errcode}，errmsg={errmsg or '未返回错误信息'}。"
            raise WeChatDraftUploadError(
                errcode=errcode,
                errmsg=errmsg,
                attempted_title=attempted_title,
                attempted_title_utf8_bytes=attempted_title_utf8_bytes,
            )
        self.last_error_message = None
        self.last_error_code = None
        self.last_error_details = None
        media_id = str(data.get("media_id") or "").strip()
        return media_id or None

    def _markdown_to_html(self, markdown_text: str) -> str:
        rendered = markdown.markdown(
            markdown_text or "",
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
        return rendered or f"<section>{html.escape(markdown_text or '')}</section>"
