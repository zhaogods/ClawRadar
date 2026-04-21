#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
寰俊鍏紬鍙疯崏绋垮姪鎵?- WeChat Official Account Draft Helper
鍩轰簬寰俊鍏紬鍙?API锛屽疄鐜版枃绔犺嚜鍔ㄥ垱寤鸿崏绋垮姛鑳?

娉ㄦ剰锛氭湰宸ュ叿鍙垱寤鸿崏绋匡紝涓嶈嚜鍔ㄥ彂甯冦€傜敤鎴烽渶瑕佹墜鍔ㄥ湪鍏紬鍙峰悗鍙板彂甯冦€?

Usage:
    python publisher.py --appid "YOUR_APPID" --secret "YOUR_SECRET" --article article.md
    python publisher.py --appid "YOUR_APPID" --secret "YOUR_SECRET" --title "鏍囬" --content "鍐呭"

Example:
    python publisher.py --appid "YOUR_APPID" --secret "YOUR_SECRET" \
        --article ml-article.md --author "鏄屽摜" --no-cover
"""

import argparse
import json
import os
import sys
import tempfile
import re
from datetime import datetime
from typing import Optional

import requests
import markdown
from PIL import Image, ImageDraw, ImageFont


class WeChatPublisher:
    """
    寰俊鍏紬鍙疯崏绋垮姪鎵?
    
    鍔熻兘锛?
    - 鑾峰彇 Access Token
    - 涓婁紶灏侀潰鍥剧墖
    - 鍒涘缓鑽夌鍒拌崏绋跨
    - Markdown 杞井淇?HTML
    
    娉ㄦ剰锛氬彧鍒涘缓鑽夌锛屼笉鑷姩鍙戝竷
    """
    
    def __init__(self, appid: str, secret: str):
        """
        鍒濆鍖栧彂甯冨姪鎵?
        
        Args:
            appid: 寰俊鍏紬鍙?AppID
            secret: 寰俊鍏紬鍙?AppSecret
        """
        self.appid = appid
        self.secret = secret
        self.access_token: Optional[str] = None
        self.base_url = "https://api.weixin.qq.com/cgi-bin"
    
    def get_access_token(self) -> Optional[str]:
        """
        鑾峰彇寰俊鍏紬鍙?Access Token
        
        Returns:
            access_token 瀛楃涓诧紝澶辫触杩斿洖 None
        """
        print("馃攽 姝ｅ湪鑾峰彇 access_token...")
        
        url = f"{self.base_url}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.appid,
            "secret": self.secret
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if "access_token" in data:
                self.access_token = data["access_token"]
                expires_in = data.get("expires_in", 7200)
                print(f"鉁?access_token 鑾峰彇鎴愬姛锛堟湁鏁堟湡 {expires_in//60} 鍒嗛挓锛?)
                return self.access_token
            else:
                error_code = data.get("errcode", "Unknown")
                error_msg = data.get("errmsg", "Unknown error")
                print(f"鉂?access_token 鑾峰彇澶辫触锛歿error_code} - {error_msg}")
                return None
                
        except requests.RequestException as e:
            print(f"鉂?缃戠粶璇锋眰澶辫触锛歿e}")
            return None
        except Exception as e:
            print(f"鉂?鏈煡閿欒锛歿e}")
            return None
    
    def upload_draft(self, title: str, content: str, author: str = None, 
                     digest: str = "", thumb_media_id: str = None) -> Optional[str]:
        """
        涓婁紶鏂囩珷鍒拌崏绋跨
        
        Args:
            title: 鏂囩珷鏍囬锛堚墹64 瀛楋級
            content: 鏂囩珷鍐呭锛圚TML 鏍煎紡锛屽井淇″唴鑱旀牱寮忥級
            author: 浣滆€呭悕
            digest: 鎽樿锛堚墹120 瀛楋紝榛樿绌哄瓧绗︿覆锛?
            thumb_media_id: 灏侀潰鍥剧墖 media_id
            
        Returns:
            media_id: 涓婁紶鎴愬姛杩斿洖 media_id锛屽け璐ヨ繑鍥?None
        """
        if not self.access_token:
            print("鉂?璇峰厛鑾峰彇 access_token")
            return None
        
        print(f"馃摑 姝ｅ湪涓婁紶鑽夌锛歿title}")
        
        url = f"{self.base_url}/draft/add?access_token={self.access_token}"
        
        # 鏋勫缓鏂囩珷鏁版嵁锛坉igest 闄愬埗 120 瀛楋紝title 闄愬埗 64 瀛楋級
        safe_title = title[:64] if len(title) > 64 else title
        # digest 鍙互涓虹┖锛岄伩鍏嶈秴闄?
        safe_digest = digest[:120] if digest and len(digest) > 120 else (digest or "")
        
        articles = {
            "articles": [
                {
                    "title": safe_title,
                    "author": author or "LucianaiB",
                    "digest": safe_digest,
                    "content": content,
                    "content_source_url": "",
                    "thumb_media_id": thumb_media_id,  # 蹇呴』鎻愪緵鏈夋晥鐨?media_id
                    "show_cover_pic": 1,  # 鏄剧ず灏侀潰鍥?
                    "need_open_comment": 0,  # 鍏抽棴璇勮
                    "only_fans_can_comment": 0  # 鎵€鏈変汉鍙瘎璁?
                }
            ]
        }
        
        try:
            # 浣跨敤 json.dumps 纭繚涓枃姝ｇ‘缂栫爜锛坋nsure_ascii=False锛?
            import json
            response = requests.post(
                url, 
                data=json.dumps(articles, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json; charset=utf-8'},
                timeout=30
            )
            data = response.json()
            
            # 寰俊鑽夌绠?API 鎴愬姛鏃惰繑鍥?media_id锛屼笉涓€瀹氭湁 errcode
            if data.get("media_id"):
                media_id = data.get("media_id")
                print(f"鉁?鑽夌涓婁紶鎴愬姛锛乵edia_id: {media_id}")
                return media_id
            elif data.get("errcode") == 0:
                media_id = data.get("media_id")
                print(f"鉁?鑽夌涓婁紶鎴愬姛锛乵edia_id: {media_id}")
                return media_id
            else:
                error_code = data.get("errcode", "Unknown")
                error_msg = data.get("errmsg", "Unknown error")
                print(f"鉂?鑽夌涓婁紶澶辫触锛歿error_code} - {error_msg}")
                
                # 灏侀潰瑁佸壀澶辫触鏃讹紝灏濊瘯涓婁紶榛樿灏侀潰
                if error_code == 53402 and not thumb_media_id:
                    print("馃挕 灏濊瘯涓婁紶榛樿灏侀潰鍚庨噸璇?..")
                    default_media_id = self.upload_default_cover()
                    if default_media_id:
                        articles["articles"][0]["thumb_media_id"] = default_media_id
                        return self.upload_draft(title, content, author, digest, default_media_id)
                
                # 甯歌閿欒澶勭悊
                if error_code == 40001:
                    print("馃挕 鎻愮ず锛欰ppSecret 鍙兘涓嶆纭?)
                elif error_code == 40014:
                    print("馃挕 鎻愮ず锛歛ccess_token 宸茶繃鏈燂紝璇烽噸鏂拌幏鍙?)
                elif error_code == 45009:
                    print("馃挕 鎻愮ず锛欰PI 璋冪敤棰戠巼瓒呴檺锛岃绋嶅悗鍐嶈瘯")
                elif error_code == 53402:
                    print("馃挕 鎻愮ず锛氬皝闈㈣鍓け璐ワ紝璇锋彁渚涙湁鏁堢殑灏侀潰鍥剧墖")
                
                return None
                
        except Exception as e:
            print(f"鉂?璇锋眰澶辫触锛歿e}")
            return None
    
    # 娉ㄦ剰锛歱ublish_article 鏂规硶宸茬Щ闄?
    # 鍘熷洜锛歠reepublish/submit 鎺ュ彛闇€瑕佺兢鍙戞潈闄愶紝涓汉璁㈤槄鍙烽粯璁や笉鏀寔
    # 鐢ㄦ埛闇€瑕佹墜鍔ㄥ湪寰俊鍏紬鍙峰悗鍙板彂甯冭崏绋?
    
    def upload_image(self, image_path: str) -> Optional[str]:
        """
        涓婁紶灏侀潰鍥剧墖锛堜娇鐢?material/add_material 鎺ュ彛鑾峰彇 media_id锛?
        
        Args:
            image_path: 鍥剧墖鏂囦欢璺緞
            
        Returns:
            media_id: 涓婁紶鎴愬姛杩斿洖 media_id锛屽け璐ヨ繑鍥?None
        """
        if not self.access_token:
            print("鉂?璇峰厛鑾峰彇 access_token")
            return None
        
        print(f"馃柤锔?姝ｅ湪涓婁紶灏侀潰鍥剧墖锛歿image_path}")
        
        # 浣跨敤 material/add_material 鎺ュ彛鑾峰彇 media_id锛堣崏绋跨闇€瑕侊級
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={self.access_token}&type=image"
        
        try:
            with open(image_path, 'rb') as f:
                files = {"media": f}
                response = requests.post(url, files=files, timeout=30)
                data = response.json()
            
            if "media_id" in data:
                media_id = data["media_id"]
                print(f"鉁?灏侀潰鍥剧墖涓婁紶鎴愬姛锛乵edia_id: {media_id}")
                return media_id
            else:
                error_code = data.get("errcode", "Unknown")
                error_msg = data.get("errmsg", "Unknown error")
                print(f"鉂?灏侀潰鍥剧墖涓婁紶澶辫触锛歿error_code} - {error_msg}")
                return None
                
        except Exception as e:
            print(f"鉂?璇锋眰澶辫触锛歿e}")
            return None
    
    def delete_draft(self, media_id: str) -> bool:
        """
        鍒犻櫎鑽夌
        
        Args:
            media_id: 鑽夌鐨?media_id
            
        Returns:
            bool: 鍒犻櫎鎴愬姛杩斿洖 True锛屽け璐ヨ繑鍥?False
        """
        if not self.access_token:
            print("鉂?璇峰厛鑾峰彇 access_token")
            return False
        
        print(f"馃棏锔?姝ｅ湪鍒犻櫎鑽夌锛歿media_id}")
        
        url = f"{self.base_url}/draft/delete?access_token={self.access_token}"
        
        data = {"media_id": media_id}
        
        try:
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            
            if result.get("errcode") == 0:
                print(f"鉁?鑽夌鍒犻櫎鎴愬姛")
                return True
            else:
                error_code = result.get("errcode", "Unknown")
                error_msg = result.get("errmsg", "Unknown error")
                print(f"鉂?鑽夌鍒犻櫎澶辫触锛歿error_code} - {error_msg}")
                return False
                
        except Exception as e:
            print(f"鉂?璇锋眰澶辫触锛歿e}")
            return False
    
    def get_article_url(self, article_id: str) -> str:
        """
        鐢熸垚鏂囩珷閾炬帴
        
        Args:
            article_id: 鏂囩珷 ID
            
        Returns:
            str: 鏂囩珷閾炬帴
        """
        # 寰俊鍏紬鍙锋枃绔犻摼鎺ユ牸寮?
        return f"https://mp.weixin.qq.com/s/{article_id}"
    
    def publish_from_markdown(self, markdown_file: str, title: str = None, 
                              author: str = "LucianaiB", thumb_media_id: str = None) -> Optional[str]:
        """
        浠?Markdown 鏂囦欢鍒涘缓鑽夌
        
        娴佺▼锛?
        1. 璇诲彇 Markdown 鏂囦欢
        2. 鎻愬彇鏍囬锛堝鏋滄病鏈夋彁渚涳級
        3. Markdown 杞?HTML
        4. 涓婁紶鑽夌鍒拌崏绋跨
        
        Args:
            markdown_file: Markdown 鏂囦欢璺緞
            title: 鏂囩珷鏍囬锛堝彲閫夛紝榛樿浠庢枃浠舵彁鍙栵級
            author: 浣滆€呭悕
            thumb_media_id: 灏侀潰鍥剧墖 media_id锛堝彲閫夛級
            
        Returns:
            media_id: 鑽夌鍒涘缓鎴愬姛杩斿洖 media_id锛屽け璐ヨ繑鍥?None
        """
        print(f"馃搫 姝ｅ湪璇诲彇 Markdown 鏂囦欢锛歿markdown_file}")
        
        # 妫€鏌ユ枃浠舵槸鍚﹀瓨鍦?
        if not os.path.exists(markdown_file):
            print(f"鉂?鏂囦欢涓嶅瓨鍦細{markdown_file}")
            return None
        
        # 璇诲彇 Markdown 鍐呭
        with open(markdown_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 濡傛灉娌℃湁鎸囧畾鏍囬锛屼粠鏂囦欢鍐呭鎻愬彇
        if not title:
            for line in content.split('\n'):
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            if not title:
                title = os.path.basename(markdown_file).replace('.md', '')
        
        print(f"馃摑 鏂囩珷鏍囬锛歿title}")
        
        # Markdown 杞?HTML锛堢畝鍗曡浆鎹級
        html_content = self._markdown_to_html(content)
        
        # 鑾峰彇 access_token
        self.get_access_token()
        if not self.access_token:
            return None
        
        # 涓婁紶鑽夌锛坉igest 闄愬埗 120 瀛楋紝鐩存帴浼犵┖瀛楃涓查伩鍏嶈秴闄愶級
        media_id = self.upload_draft(
            title=title,
            content=html_content,
            author=author,
            digest="",  # 绌烘憳瑕侊紝閬垮厤瓒呴檺
            thumb_media_id=thumb_media_id
        )
        
        if media_id:
            print(f"\n鉁?鏂囩珷宸蹭繚瀛樺埌鑽夌绠憋紒")
            print(f"   Media ID: {media_id}")
            print(f"\n馃挕 鎻愮ず锛氳鍓嶅線寰俊鍏紬鍙峰悗鍙?(https://mp.weixin.qq.com/) 鏌ョ湅骞跺彂甯冦€俓n")
            return media_id
        
        return None
    
    def _markdown_to_html(self, md_text: str) -> str:
        """
        Markdown 杞井淇″吋瀹?HTML锛堢函鍐呰仈鏍峰紡锛?
        
        浣跨敤 markdown 搴撳仛鍩虹杞崲锛屽啀閫氳繃姝ｅ垯鍋氬井淇℃牱寮忛€傞厤銆?
        鏀寔锛氭爣棰樸€佹钀姐€佺矖浣撱€佹枩浣撱€佸紩鐢ㄣ€佸垪琛ㄣ€佷唬鐮佸潡銆侀摼鎺ャ€佸浘鐗囥€佽〃鏍笺€?
        
        Args:
            md_text: Markdown 鏍煎紡瀛楃涓?
            
        Returns:
            寰俊鍏煎鐨?HTML 瀛楃涓诧紙绾唴鑱旀牱寮忥級
        """
        # 1. 鐢?markdown 搴撳仛鍩虹杞崲锛堝甫鎵╁睍锛?
        html = markdown.markdown(md_text, extensions=[
            'fenced_code',    # ``` 浠ｇ爜鍧?
            'codehilite',     # 浠ｇ爜楂樹寒
            'tables',         # 琛ㄦ牸
            'toc',            # 鐩綍
            'nl2br',          # 鎹㈣杞?br
            'sane_lists',     # 鏇村畨鍏ㄧ殑鍒楄〃瑙ｆ瀽
        ])
        
        # 2. 鏍囬鏍峰紡鍖栵紙鍏煎甯?id 灞炴€х殑 h 鏍囩锛?
        html = re.sub(
            r'<h1[^>]*>(.*?)</h1>',
            r'<section style="font-size:20px;font-weight:bold;margin:20px 0 10px;color:#333;">\1</section>',
            html
        )
        html = re.sub(
            r'<h2[^>]*>(.*?)</h2>',
            r'<section style="font-size:18px;font-weight:bold;margin:16px 0 8px;color:#333;">\1</section>',
            html
        )
        html = re.sub(
            r'<h3[^>]*>(.*?)</h3>',
            r'<section style="font-size:16px;font-weight:bold;margin:12px 0 6px;color:#333;">\1</section>',
            html
        )
        
        # 3. 娈佃惤鏍峰紡鍖?
        html = re.sub(
            r'<p>(.*?)</p>',
            r'<section style="font-size:17px;line-height:1.75;color:#333;margin:12px 0;word-break:break-word;">\1</section>',
            html,
            flags=re.DOTALL
        )
        
        # 4. 寮曠敤鍧楁牱寮忓寲
        html = re.sub(
            r'<blockquote>(.*?)</blockquote>',
            r'<section style="border-left:4px solid #ddd;padding:8px 12px;margin:12px 0;color:#666;font-style:italic;background:#f9f9f9;">\1</section>',
            html,
            flags=re.DOTALL
        )
        
        # 5. 浠ｇ爜鍧楁牱寮忓寲锛堝吋瀹?codehilite 鎵╁睍杈撳嚭锛?
        # codehilite 浼氬湪 <pre> 鍐呮彃 <span></span>
        html = re.sub(
            r'<div class="codehilite"><pre>(?:<span></span>)?<code[^>]*>(.*?)</code></pre></div>',
            r'<section style="background:#f6f8fa;padding:12px;border-radius:6px;margin:12px 0;overflow-x:auto;font-size:14px;"><pre style="margin:0;">\1</pre></section>',
            html,
            flags=re.DOTALL
        )
        html = re.sub(
            r'<pre><code( class="[^"]*")?>(.*?)</code></pre>',
            r'<section style="background:#f6f8fa;padding:12px;border-radius:6px;margin:12px 0;overflow-x:auto;font-size:14px;"><pre style="margin:0;">\2</pre></section>',
            html,
            flags=re.DOTALL
        )
        
        # 6. 琛屽唴浠ｇ爜鏍峰紡鍖?
        html = re.sub(
            r'<code>(.*?)</code>',
            r'<code style="background:#f6f8fa;padding:2px 6px;border-radius:3px;font-size:14px;color:#e83e8c;">\1</code>',
            html
        )
        
        # 7. 鍒楄〃鏍峰紡鍖?
        html = re.sub(
            r'<ul>',
            r'<section style="margin:12px 0;padding-left:20px;">',
            html
        )
        html = re.sub(
            r'</ul>',
            r'</section>',
            html
        )
        html = re.sub(
            r'<li>',
            r'<section style="margin:6px 0;">鈥?',
            html
        )
        html = re.sub(
            r'</li>',
            r'</section>',
            html
        )
        
        # 8. 閾炬帴鏍峰紡鍖?
        html = re.sub(
            r'<a href="(.*?)"\s*>(.*?)</a>',
            r'<a href="\1" style="color:#576b95;text-decoration:none;">\2</a>',
            html
        )
        
        # 9. 鍥剧墖閫傞厤寰俊
        html = re.sub(
            r'<img src="(.*?)"\s*(alt="[^"]*")?\s*/?>',
            r'<section style="text-align:center;margin:12px 0;"><img src="\1" style="max-width:100%;height:auto;border-radius:4px;" /></section>',
            html
        )
        
        # 10. 琛ㄦ牸鏍峰紡鍖?
        html = re.sub(
            r'<table>',
            r'<section style="overflow-x:auto;margin:12px 0;"><table style="width:100%;border-collapse:collapse;font-size:14px;">',
            html
        )
        html = re.sub(
            r'</table>',
            r'</table></section>',
            html
        )
        html = re.sub(
            r'<th>',
            r'<th style="border:1px solid #ddd;padding:8px;background:#f6f8fa;font-weight:bold;">',
            html
        )
        html = re.sub(
            r'<td>',
            r'<td style="border:1px solid #ddd;padding:8px;">',
            html
        )
        
        return html
    
    def upload_default_cover(self, title: str = "") -> Optional[str]:
        """
        涓婁紶榛樿灏侀潰鍥撅紙900x500 鍍忕礌锛屽井淇¤姹傛渶灏?200x200锛?
        
        绛栫暐锛氫娇鐢?Pillow 鐢熸垚娓愬彉鑳屾櫙 + 鏍囬鏂囧瓧鐨勭簿缇?JPG 灏侀潰銆?
        
        Returns:
            media_id: 涓婁紶鎴愬姛杩斿洖 media_id锛屽け璐ヨ繑鍥?None
        """
        try:
            width, height = 900, 500
            
            # 1. 鍒涘缓娓愬彉鑳屾櫙
            img = Image.new('RGB', (width, height))
            draw = ImageDraw.Draw(img)
            
            # 娓愬彉锛氭繁钃?-> 绱?
            for y in range(height):
                r = int(30 + (100 - 30) * y / height)
                g = int(40 + (60 - 40) * y / height)
                b = int(80 + (140 - 80) * y / height)
                draw.line([(0, y), (width, y)], fill=(r, g, b))
            
            # 2. 缁樺埗鏍囬鏂囧瓧
            title_text = title[:20] if title else "Article"
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            except (IOError, OSError):
                font = ImageFont.load_default()
            
            # 鏂囧瓧灞呬腑
            bbox = draw.textbbox((0, 0), title_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            text_x = (width - text_w) // 2
            text_y = (height - text_h) // 2
            
            # 鏂囧瓧闃村奖
            draw.text((text_x + 2, text_y + 2), title_text, fill=(0, 0, 0, 128), font=font)
            draw.text((text_x, text_y), title_text, fill=(255, 255, 255, 255), font=font)
            
            # 3. 淇濆瓨涓?JPG
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                img.save(f.name, 'JPEG', quality=90)
                temp_path = f.name
            
            media_id = self.upload_image(temp_path)
            os.unlink(temp_path)
            return media_id
            
        except Exception as e:
            print(f"鉂?榛樿灏侀潰鐢熸垚澶辫触锛歿e}")
            return None
    
    def print_config(self):
        """鎵撳嵃閰嶇疆淇℃伅"""
        print("\n" + "=" * 60)
        print("馃摫 寰俊鍏紬鍙峰彂甯冨姪鎵?)
        print("=" * 60)
        print(f"AppID: {self.appid[:10]}...{self.appid[-6:]}")
        print(f"Secret: {self.secret[:6]}...{self.secret[-6:]}")
        print("=" * 60 + "\n")


def main():
    """
    涓诲嚱鏁?- 瑙ｆ瀽鍛戒护琛屽弬鏁板苟鎵ц鐩稿簲鎿嶄綔
    
    鏀寔涓ょ妯″紡锛?
    1. Markdown 鏂囦欢妯″紡锛?-article article.md
    2. 鐩存帴杈撳叆妯″紡锛?-title "鏍囬" --content "鍐呭"
    """
    parser = argparse.ArgumentParser(
        description='寰俊鍏紬鍙疯崏绋垮姪鎵?- 涓€閿垱寤鸿崏绋垮埌鑽夌绠?,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
绀轰緥:
  python publisher.py --appid "YOUR_APPID" --secret "YOUR_SECRET" --article article.md --author "鏄屽摜" --no-cover
  python publisher.py --appid "YOUR_APPID" --secret "YOUR_SECRET" --title "鏍囬" --content "鍐呭" --no-cover
        '''
    )
    parser.add_argument('--appid', type=str, required=True,
                        help='寰俊鍏紬鍙?AppID锛堝繀濉級')
    parser.add_argument('--secret', type=str, required=True,
                        help='寰俊鍏紬鍙?AppSecret锛堝繀濉級')
    parser.add_argument('--article', type=str, metavar='FILE',
                        help='Markdown 鏂囩珷鏂囦欢璺緞')
    parser.add_argument('--title', type=str, metavar='TITLE',
                        help='鏂囩珷鏍囬锛堜笌 --content 閰嶅悎浣跨敤锛?)
    parser.add_argument('--content', type=str, metavar='CONTENT',
                        help='鏂囩珷鍐呭锛圚TML 鏍煎紡锛屼笌 --title 閰嶅悎浣跨敤锛?)
    parser.add_argument('--author', type=str, default='鏄屽摜',
                        help='浣滆€呭悕锛堥粯璁わ細鏄屽摜锛?)
    parser.add_argument('--image', type=str, metavar='IMAGE_FILE',
                        help='鑷畾涔夊皝闈㈠浘鐗囪矾寰?)
    parser.add_argument('--no-cover', action='store_true',
                        help='璺宠繃灏侀潰鐢熸垚锛屼娇鐢ㄩ粯璁ゅ皝闈紙鎺ㄨ崘锛?)
    
    args = parser.parse_args()
    
    # 鍒涘缓鍙戝竷鍔╂墜
    publisher = WeChatPublisher(args.appid, args.secret)
    publisher.print_config()
    
    # 鑾峰彇 access_token
    publisher.get_access_token()
    if not publisher.access_token:
        return
    
    # 鎻愬彇鏍囬锛堢敤浜庡皝闈㈢敓鎴愶級
    cover_title = args.title or ""
    if args.article and not cover_title:
        try:
            with open(args.article, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('# '):
                        cover_title = line[2:].strip()
                        break
        except Exception:
            pass
    
    # 涓婁紶灏侀潰鍥撅紙濡傛灉鏈夛級
    thumb_media_id = None
    if args.image and os.path.exists(args.image):
        thumb_media_id = publisher.upload_image(args.image)
    elif args.no_cover:
        print("馃搶 浣跨敤榛樿灏侀潰...")
        thumb_media_id = publisher.upload_default_cover(title=cover_title)
    
    # 濡傛灉鏈?Markdown 鏂囦欢
    if args.article:
        publisher.publish_from_markdown(
            markdown_file=args.article,
            title=args.title,
            author=args.author,
            thumb_media_id=thumb_media_id
        )
    # 濡傛灉鏈夋爣棰樺拰鍐呭
    elif args.title and args.content:
        # 涓婁紶鑽夌
        media_id = publisher.upload_draft(
            title=args.title,
            content=args.content,
            author=args.author,
            thumb_media_id=thumb_media_id
        )
        if media_id:
            print(f"\n鉁?鏂囩珷宸蹭繚瀛樺埌鑽夌绠憋紒")
            print(f"   Media ID: {media_id}")
            print(f"\n馃挕 鎻愮ず锛氳鍓嶅線寰俊鍏紬鍙峰悗鍙?(https://mp.weixin.qq.com/) 鏌ョ湅骞跺彂甯冦€俓n")
    else:
        print("鉂?璇锋彁渚涙枃绔犲唴瀹癸紙--article 鎴?--title + --content锛?)
        parser.print_help()


if __name__ == '__main__':
    main()
