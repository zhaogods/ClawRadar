#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSentimentCrawling模块 - 平台爬虫管理器
负责配置和调用MediaCrawler进行多平台爬取
"""

import os
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import json
from loguru import logger

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))


def _get_server_mode() -> bool:
    """检测是否运行在无 GUI 的 Linux 云服务器上。

    优先级：
    1. 环境变量 CLAWRADAR_SERVER_MODE（1/true/yes = 强制启用，0/false/no = 强制禁用）
    2. 自动检测：Linux 且无 DISPLAY 环境变量 → 视为云服务器
    """
    import sys as _sys

    env_val = os.environ.get("CLAWRADAR_SERVER_MODE", "").lower()
    if env_val in ("1", "true", "yes"):
        return True
    if env_val in ("0", "false", "no"):
        return False

    # Auto-detect: Linux without DISPLAY → headless server
    if _sys.platform == "linux" and not os.environ.get("DISPLAY"):
        return True

    return False

try:
    import config
except ImportError:
    raise ImportError("无法导入config.py配置文件")

class PlatformCrawler:
    """平台爬虫管理器"""

    def __init__(self, server_mode: bool | None = None):
        """初始化平台爬虫管理器

        Args:
            server_mode: 是否运行在无头服务器模式。None 时读取环境变量
                CLAWRADAR_SERVER_MODE。
        """
        if server_mode is None:
            server_mode = _get_server_mode()
        self._server_mode = server_mode
        self._xvfb_process = None
        self._xvfb_display = ":99"

        self.mediacrawler_path = Path(__file__).parent / "MediaCrawler"
        self.supported_platforms = ['xhs', 'dy', 'ks', 'bili', 'wb', 'tieba', 'zhihu']
        self.crawl_stats = {}
        self._cookie_failed = False  # 任一平台 cookie 失败则后续全用 qrcode
        
        # 确保MediaCrawler子模块已初始化
        db_config_path = self.mediacrawler_path / "config" / "db_config.py"
        if not self.mediacrawler_path.exists() or not db_config_path.exists():
            logger.error("MediaCrawler子模块未初始化或不完整")
            logger.error("请在项目根目录运行以下命令初始化子模块:")
            logger.error("   git submodule update --init --recursive")
            raise FileNotFoundError("MediaCrawler子模块未初始化，请先运行: git submodule update --init --recursive")

        logger.info(f"初始化平台爬虫管理器，MediaCrawler路径: {self.mediacrawler_path}")

        # 一次性修补 MediaCrawler 登录超时：600s → 120s（2分钟）
        self._patch_login_timeouts()

    def _patch_login_timeouts(self):
        """修补 MediaCrawler 各平台 login.py 的登录超时和退出行为。

        原始行为：二维码登录等待 600 秒（10 分钟），失败后 sys.exit() 杀死子进程。
        修补后：等待 120 秒（2 分钟），失败后 sys.exit(42) 由父进程识别为"登录失败跳过"。
        """
        platform_dir = self.mediacrawler_path / "media_platform"
        patched_count = 0

        for platform in self.supported_platforms:
            # platform key → MediaCrawler directory name
            _dir_map = {
                "dy": "douyin",
                "ks": "kuaishou",
                "bili": "bilibili",
                "wb": "weibo",
            }
            dir_name = _dir_map.get(platform, platform)
            login_path = platform_dir / dir_name / "login.py"

            if not login_path or not login_path.is_file():
                continue

            try:
                content = login_path.read_text(encoding="utf-8")
                modified = content

                # 1) 登录超时：600 次 → 120 次（2 分钟，1 秒间隔）
                modified = modified.replace(
                    "stop=stop_after_attempt(600)",
                    "stop=stop_after_attempt(120)",
                )

                # 2) 登录失败退出码：sys.exit() → sys.exit(42)
                #    父进程可通过返回码 42 识别为"登录失败，跳过该平台"
                modified = modified.replace("sys.exit()", "sys.exit(42)")

                if modified != content:
                    login_path.write_text(modified, encoding="utf-8")
                    patched_count += 1
                    logger.info(
                        f"已修补 {platform} 登录超时: 600s→120s, sys.exit→exit(42)"
                    )
            except Exception:
                logger.warning(f"修补 {platform} login.py 失败，将使用原始超时")

        if patched_count:
            logger.info(f"登录超时修补完成：{patched_count}/{len(self.supported_platforms)} 个平台")
        else:
            logger.info("所有平台登录超时无需修补（可能已修补过）")

    def _start_xvfb(self):
        """启动 Xvfb 虚拟显示（仅 Linux server_mode）。"""
        if not self._server_mode:
            return
        import sys
        import time
        import shutil

        # Xvfb 仅在 Linux 无 GUI 环境需要，Windows/macOS 有原生显示
        if sys.platform != "linux":
            logger.info(f"非 Linux 平台 ({sys.platform})，跳过 Xvfb")
            return

        if not shutil.which("Xvfb"):
            raise RuntimeError(
                "Xvfb 未安装，服务器模式需要 Xvfb 虚拟显示。"
                "  Ubuntu/Debian: sudo apt install xvfb"
                "  CentOS/RHEL:   sudo yum install xorg-x11-server-Xvfb"
            )

        # 检查是否已有 Xvfb 在 :99 运行（通过锁文件）
        lock_file = f"/tmp/.X99-lock"
        if os.path.exists(lock_file):
            logger.info(f"Xvfb {self._xvfb_display} 锁文件已存在，尝试复用")
            # 验证锁文件中的进程是否还活着
            try:
                with open(lock_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)  # 发送信号0检测进程是否存在
                logger.info(f"复用已有 Xvfb {self._xvfb_display} (pid {pid})")
                return
            except (OSError, ValueError):
                logger.info("锁文件存在但进程已死，重新启动")

        logger.info(f"启动 Xvfb {self._xvfb_display} ...")
        self._xvfb_process = subprocess.Popen(
            ["Xvfb", self._xvfb_display, "-screen", "0", "1920x1080x24", "-ac"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        logger.info(f"Xvfb {self._xvfb_display} 已启动")

    def _stop_xvfb(self):
        """停止 Xvfb 进程。"""
        if self._xvfb_process:
            self._xvfb_process.terminate()
            try:
                self._xvfb_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._xvfb_process.kill()
            logger.info(f"Xvfb {self._xvfb_display} 已停止")
            self._xvfb_process = None

    def close(self):
        """关闭资源（停止 Xvfb）。"""
        self._stop_xvfb()

    def configure_mediacrawler_db(self):
        """配置MediaCrawler使用我们的数据库（MySQL或PostgreSQL）"""
        try:
            # 判断数据库类型
            db_dialect = (config.settings.DB_DIALECT or "mysql").lower()
            is_postgresql = db_dialect in ("postgresql", "postgres")
            
            # 修改MediaCrawler的数据库配置
            db_config_path = self.mediacrawler_path / "config" / "db_config.py"
            
            # 读取原始配置
            with open(db_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # PostgreSQL配置值：统一使用MindSpider配置
            pg_password = (config.settings.DB_PASSWORD or "")
            pg_user = (config.settings.DB_USER or "")
            pg_host = (config.settings.DB_HOST or "127.0.0.1")
            pg_port = (config.settings.DB_PORT or 5444)
            pg_db_name = (config.settings.DB_NAME or "")
            
            # 替换数据库配置 - 使用MindSpider的数据库配置
            new_config = f'''# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：  
# 1. 不得用于任何商业用途。  
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。  
# 3. 不得进行大规模爬取或对平台造成运营干扰。  
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。   
# 5. 不得用于任何非法或不当的用途。
#   
# 详细许可条款请参阅项目根目录下的LICENSE文件。  
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。  


import os

# mysql config - 使用MindSpider的数据库配置
MYSQL_DB_PWD = "{config.settings.DB_PASSWORD}"
MYSQL_DB_USER = "{config.settings.DB_USER}"
MYSQL_DB_HOST = "{config.settings.DB_HOST}"
MYSQL_DB_PORT = {config.settings.DB_PORT}
MYSQL_DB_NAME = "{config.settings.DB_NAME}"

mysql_db_config = {{
    "user": MYSQL_DB_USER,
    "password": MYSQL_DB_PWD,
    "host": MYSQL_DB_HOST,
    "port": MYSQL_DB_PORT,
    "db_name": MYSQL_DB_NAME,
}}


# redis config
REDIS_DB_HOST = "127.0.0.1"  # your redis host
REDIS_DB_PWD = os.getenv("REDIS_DB_PWD", "123456")  # your redis password
REDIS_DB_PORT = os.getenv("REDIS_DB_PORT", 6379)  # your redis port
REDIS_DB_NUM = os.getenv("REDIS_DB_NUM", 0)  # your redis db num

# cache type
CACHE_TYPE_REDIS = "redis"
CACHE_TYPE_MEMORY = "memory"

# sqlite config
SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "sqlite_tables.db")

sqlite_db_config = {{
    "db_path": SQLITE_DB_PATH
}}

# mongodb config
MONGODB_HOST = os.getenv("MONGODB_HOST", "localhost")
MONGODB_PORT = os.getenv("MONGODB_PORT", 27017)
MONGODB_USER = os.getenv("MONGODB_USER", "")
MONGODB_PWD = os.getenv("MONGODB_PWD", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "media_crawler")

mongodb_config = {{
    "host": MONGODB_HOST,
    "port": int(MONGODB_PORT),
    "user": MONGODB_USER,
    "password": MONGODB_PWD,
    "db_name": MONGODB_DB_NAME,
}}

# postgres config - 使用MindSpider的数据库配置（如果DB_DIALECT是postgresql）或环境变量
POSTGRES_DB_PWD = os.getenv("POSTGRES_DB_PWD", "{pg_password}")
POSTGRES_DB_USER = os.getenv("POSTGRES_DB_USER", "{pg_user}")
POSTGRES_DB_HOST = os.getenv("POSTGRES_DB_HOST", "{pg_host}")
POSTGRES_DB_PORT = os.getenv("POSTGRES_DB_PORT", "{pg_port}")
POSTGRES_DB_NAME = os.getenv("POSTGRES_DB_NAME", "{pg_db_name}")

postgres_db_config = {{
    "user": POSTGRES_DB_USER,
    "password": POSTGRES_DB_PWD,
    "host": POSTGRES_DB_HOST,
    "port": POSTGRES_DB_PORT,
    "db_name": POSTGRES_DB_NAME,
}}

'''
            
            # 写入新配置
            with open(db_config_path, 'w', encoding='utf-8') as f:
                f.write(new_config)

            db_type = "PostgreSQL" if is_postgresql else "MySQL"
            logger.info(f"已配置MediaCrawler使用MindSpider {db_type}数据库")

            # 自动创建MediaCrawler平台数据表（幂等，首次运行时建表）
            try:
                _mediacrawler_root = str(self.mediacrawler_path)
                if _mediacrawler_root not in sys.path:
                    sys.path.insert(0, _mediacrawler_root)
                from database.models import Base as MCBase
                from sqlalchemy import create_engine as sync_create_engine

                db_charset = getattr(config.settings, "DB_CHARSET", "utf8mb4") or "utf8mb4"
                if is_postgresql:
                    db_url = (
                        f"postgresql+psycopg://{config.settings.DB_USER}:{config.settings.DB_PASSWORD}"
                        f"@{config.settings.DB_HOST}:{config.settings.DB_PORT}/{config.settings.DB_NAME}"
                    )
                else:
                    db_url = (
                        f"mysql+pymysql://{config.settings.DB_USER}:{config.settings.DB_PASSWORD}"
                        f"@{config.settings.DB_HOST}:{config.settings.DB_PORT}/{config.settings.DB_NAME}"
                        f"?charset={db_charset}"
                    )

                _sync_engine = sync_create_engine(db_url, echo=False)
                MCBase.metadata.create_all(_sync_engine)
                _sync_engine.dispose()
                logger.info("MediaCrawler 平台数据表自动创建/校验完成（22 tables）")
            except Exception as _e:
                logger.warning(f"MediaCrawler 平台表自动创建失败，将由子进程 init_db 回退: {_e}")

            return True

        except Exception as e:
            logger.exception(f"配置MediaCrawler数据库失败: {e}")
            return False
    
    def create_base_config(self, platform: str, keywords: List[str],
                          crawler_type: str = "search", max_notes: int = 50,
                          login_type: str = "qrcode") -> bool:
        """
        创建MediaCrawler的基础配置

        Args:
            platform: 平台名称
            keywords: 关键词列表
            crawler_type: 爬取类型
            max_notes: 最大爬取数量
            login_type: 登录方式 qrcode/phone/cookie
        
        Returns:
            是否配置成功
        """
        try:
            # 判断数据库类型，确定 SAVE_DATA_OPTION
            db_dialect = (config.settings.DB_DIALECT or "mysql").lower()
            is_postgresql = db_dialect in ("postgresql", "postgres")
            save_data_option = "postgres" if is_postgresql else "db"

            base_config_path = self.mediacrawler_path / "config" / "base_config.py"
            
            # 将关键词列表转换为逗号分隔的字符串
            keywords_str = ",".join(keywords)
            
            # 读取原始配置文件
            with open(base_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 修改关键配置项
            # skip_until_paren: 当原始行是多行赋值（以"("结尾）被替换为单行后，
            # 需要跳过后续续行直到遇到配对的")"
            def _env_bool(name: str, default: bool) -> bool:
                raw = os.environ.get(name, "").strip().lower()
                if raw in ("1", "true", "yes", "on"):
                    return True
                if raw in ("0", "false", "no", "off"):
                    return False
                return default

            def _env_int(name: str, default: int) -> int:
                raw = os.environ.get(name, "").strip()
                if not raw:
                    return default
                try:
                    return int(raw)
                except ValueError:
                    logger.warning(f"环境变量 {name}={raw} 不是有效整数，使用默认值 {default}")
                    return default

            def _env_str(name: str, default: str = "") -> str:
                raw = os.environ.get(name, "").strip()
                return raw or default

            # 服务器模式默认直接启用 CDP + 真实 Chrome，避免再回退到标准 Playwright 模式。
            enable_cdp_mode = _env_bool("CLAWRADAR_ENABLE_CDP_MODE", self._server_mode)
            cdp_connect_existing = _env_bool(
                "CLAWRADAR_CDP_CONNECT_EXISTING",
                False if self._server_mode else True,
            )
            cdp_headless = _env_bool("CLAWRADAR_CDP_HEADLESS", False)
            cdp_debug_port = _env_int("CLAWRADAR_CDP_DEBUG_PORT", 9222)
            cdp_custom_browser_path = _env_str("CLAWRADAR_CDP_CUSTOM_BROWSER_PATH", "")

            logger.info(
                "CDP配置: enable=%s, connect_existing=%s, headless=%s, debug_port=%s, browser_path=%s"
                % (
                    enable_cdp_mode,
                    cdp_connect_existing,
                    cdp_headless,
                    cdp_debug_port,
                    cdp_custom_browser_path or "auto-detect",
                )
            )
            lines = content.split('\n')
            new_lines = []
            skip_until_paren = False

            for line in lines:
                # 跳过多行赋值的续行
                if skip_until_paren:
                    if line.strip() == ')':
                        skip_until_paren = False
                    continue

                replaced = None
                if line.startswith('PLATFORM = '):
                    replaced = f'PLATFORM = "{platform}"  # 平台，xhs | dy | ks | bili | wb | tieba | zhihu'
                elif line.startswith('KEYWORDS = '):
                    replaced = f'KEYWORDS = "{keywords_str}"  # 关键词搜索配置，以英文逗号分隔'
                elif line.startswith('CRAWLER_TYPE = '):
                    replaced = f'CRAWLER_TYPE = "{crawler_type}"  # 爬取类型，search(关键词搜索) | detail(帖子详情)| creator(创作者主页数据)'
                elif line.startswith('SAVE_DATA_OPTION = '):
                    replaced = f'SAVE_DATA_OPTION = "{save_data_option}"  # csv or db or json or sqlite or postgres'
                elif line.startswith('CRAWLER_MAX_NOTES_COUNT = '):
                    replaced = f'CRAWLER_MAX_NOTES_COUNT = {max_notes}'
                elif line.startswith('ENABLE_GET_COMMENTS = '):
                    replaced = 'ENABLE_GET_COMMENTS = True'
                elif line.startswith('CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = '):
                    replaced = 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = 20'
                elif line.startswith('HEADLESS = '):
                    replaced = 'HEADLESS = False'
                elif line.startswith('ENABLE_CDP_MODE = '):
                    replaced = f'ENABLE_CDP_MODE = {enable_cdp_mode}'
                elif line.startswith('SERVER_MODE = '):
                    replaced = f'SERVER_MODE = {str(self._server_mode)}'
                elif line.startswith('CDP_CONNECT_EXISTING = '):
                    replaced = f'CDP_CONNECT_EXISTING = {cdp_connect_existing}'
                elif line.startswith('CDP_HEADLESS = '):
                    replaced = f'CDP_HEADLESS = {cdp_headless}'
                elif line.startswith('CDP_DEBUG_PORT = '):
                    replaced = f'CDP_DEBUG_PORT = {cdp_debug_port}'
                elif line.startswith('CUSTOM_BROWSER_PATH = '):
                    replaced = f'CUSTOM_BROWSER_PATH = "{cdp_custom_browser_path}"'
                elif line.startswith('LOGIN_TYPE = '):
                    replaced = f'LOGIN_TYPE = "{login_type}"'

                if replaced is not None:
                    new_lines.append(replaced)
                    # 若原始行是多行赋值开头（以"("结尾），跳过后续续行
                    if line.rstrip().endswith('('):
                        skip_until_paren = True
                else:
                    new_lines.append(line)
            
            # 写入新配置
            with open(base_config_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines))
            
            logger.info(f"已配置 {platform} 平台，爬取类型: {crawler_type}，关键词数量: {len(keywords)}，最大爬取数量: {max_notes}，保存数据方式: {save_data_option}")
            return True
            
        except Exception as e:
            logger.exception(f"创建基础配置失败: {e}")
            return False
    
    def run_crawler(self, platform: str, keywords: List[str],
                   login_type: str = "auto", max_notes: int = 50) -> Dict:
        """
        运行爬虫

        Args:
            platform: 平台名称
            keywords: 关键词列表
            login_type: 登录方式
            max_notes: 最大爬取数量

        Returns:
            爬取结果统计
        """
        if platform not in self.supported_platforms:
            raise ValueError(f"不支持的平台: {platform}")

        if not keywords:
            raise ValueError("关键词列表不能为空")

        start_message = f"\n开始爬取平台: {platform}"
        start_message += f"\n关键词: {keywords[:5]}{'...' if len(keywords) > 5 else ''} (共{len(keywords)}个)"
        logger.info(start_message)
        
        start_time = datetime.now()
        
        try:
            # 配置数据库
            if not self.configure_mediacrawler_db():
                return {"success": False, "error": "数据库配置失败"}
            
            # 自动检测登录方式：默认 qrcode，pong() 自己判断是否已有登录态跳过
            effective_login_type = login_type
            if login_type == "auto":
                effective_login_type = "qrcode"
                logger.info(f"[{platform}] 自动选择登录方式: qrcode（已有登录态则自动跳过）")

            # 创建基础配置（用实际登录方式，MediaCrawler 不支持 "auto"）
            if not self.create_base_config(platform, keywords, "search", max_notes, effective_login_type):
                return {"success": False, "error": "基础配置创建失败"}

            # 判断数据库类型，确定 save_data_option
            db_dialect = (config.settings.DB_DIALECT or "mysql").lower()
            is_postgresql = db_dialect in ("postgresql", "postgres")
            save_data_option = "postgres" if is_postgresql else "db"

            # 构建命令
            cmd = [
                sys.executable, "main.py",
                "--platform", platform,
                "--lt", effective_login_type,
                "--type", "search",
                "--save_data_option", save_data_option,
            ]

            logger.info(f"[{platform}] server_mode: {self._server_mode}")
            logger.info(f"执行命令: {' '.join(cmd)}")

            # 子进程超时控制：
            #  - 扫码/手机登录：2分钟登录窗口 + 爬取时间，总计 15 分钟
            #  - cookie 登录：无等待窗口，总计 30 分钟
            if effective_login_type in ("qrcode", "phone"):
                subprocess_timeout = 900  # 15 分钟
            else:
                subprocess_timeout = 1800  # 30 分钟

            # server_mode: 启动 Xvfb 虚拟显示，传入 DISPLAY 环境变量
            self._start_xvfb()
            env = os.environ.copy()
            if self._server_mode:
                env["DISPLAY"] = self._xvfb_display

            # 切换到MediaCrawler目录并执行
            # 子进程输出直接继承 stdout/stderr（QR 码需在终端实时显示），
            # 不在 Python 层捕获，避免阻塞 QR 码扫码流程
            result = subprocess.run(
                cmd,
                cwd=self.mediacrawler_path,
                timeout=subprocess_timeout,
                env=env,
            )

            return_code = result.returncode

            # cookie 登录失败 → 自动回退到 qrcode，并标记后续平台
            if return_code != 0 and effective_login_type == "cookie":
                self._cookie_failed = True
                logger.warning(f"[{platform}] cookie 登录失败 (rc={return_code})，自动回退到 qrcode 扫码登录...")
                logger.warning(f"[{platform}] 后续平台将强制使用 qrcode，确保 QR 码正常显示")
                cmd[cmd.index("--lt") + 1] = "qrcode"
                logger.info(f"重试命令: {' '.join(cmd)}")
                result = subprocess.run(
                    cmd,
                    cwd=self.mediacrawler_path,
                    timeout=900,  # qrcode 15 分钟超时
                    env=env,
                )
                return_code = result.returncode
                effective_login_type = "qrcode"

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            if return_code == 42:
                login_error = True
                error_message = (
                    f"登录失败（{effective_login_type}）：2分钟内未完成登录，跳过 {platform} 平台"
                )
            elif return_code != 0:
                login_error = False
                error_message = f"爬取失败，返回码: {return_code}"
            else:
                login_error = False
                error_message = ""

            # 创建统计信息
            crawl_stats = {
                "platform": platform,
                "keywords_count": len(keywords),
                "duration_seconds": duration,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "return_code": return_code,
                "success": return_code == 0,
                "login_failed": login_error,
                "login_type": effective_login_type,
                "notes_count": 0,
                "comments_count": 0,
                "errors_count": 0,
            }

            # 保存统计信息
            self.crawl_stats[platform] = crawl_stats

            if return_code == 0:
                logger.info(f"✅ {platform} 爬取完成，耗时: {duration:.1f}秒")
            elif login_error:
                logger.warning(f"🔐 {platform} {error_message}")
            else:
                logger.error(f"❌ {platform} {error_message}")

            return crawl_stats

        except subprocess.TimeoutExpired:
            logger.warning(
                f"⏰ {platform} 登录/爬取超时（{login_type}），跳过该平台"
            )
            return {
                "success": False,
                "error": f"登录超时（{login_type}，{subprocess_timeout}s）",
                "platform": platform,
                "login_failed": login_type in ("qrcode", "phone"),
            }
        except Exception as e:
            logger.exception(f"❌ {platform} 爬取异常: {e}")
            return {"success": False, "error": str(e), "platform": platform}
    
    def _parse_crawl_output(self, output_lines: List[str], error_lines: List[str]) -> Dict:
        """解析爬取输出，提取统计信息"""
        stats = {
            "notes_count": 0,
            "comments_count": 0,
            "errors_count": 0,
            "login_required": False
        }
        
        # 解析输出行
        for line in output_lines:
            if "条笔记" in line or "条内容" in line:
                try:
                    # 提取数字
                    import re
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats["notes_count"] = int(numbers[0])
                except:
                    pass
            elif "条评论" in line:
                try:
                    import re
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats["comments_count"] = int(numbers[0])
                except:
                    pass
            elif "登录" in line or "扫码" in line:
                stats["login_required"] = True
        
        # 解析错误行
        for line in error_lines:
            if "error" in line.lower() or "异常" in line:
                stats["errors_count"] += 1
        
        return stats
    
    def run_multi_platform_crawl_by_keywords(self, keywords: List[str], platforms: List[str],
                                            login_type: str = "qrcode", max_notes_per_keyword: int = 50) -> Dict:
        """
        基于关键词的多平台爬取 - 每个关键词在所有平台上都进行爬取
        
        Args:
            keywords: 关键词列表
            platforms: 平台列表
            login_type: 登录方式
            max_notes_per_keyword: 每个关键词在每个平台的最大爬取数量
        
        Returns:
            总体爬取统计
        """
        
        start_message = f"\n🚀 开始全平台关键词爬取"
        start_message += f"\n   关键词数量: {len(keywords)}"
        start_message += f"\n   平台数量: {len(platforms)}"
        start_message += f"\n   登录方式: {login_type}"
        start_message += f"\n   每个关键词在每个平台的最大爬取数量: {max_notes_per_keyword}"
        start_message += f"\n   总爬取任务: {len(keywords)} × {len(platforms)} = {len(keywords) * len(platforms)}"
        logger.info(start_message)
        
        total_stats = {
            "total_keywords": len(keywords),
            "total_platforms": len(platforms),
            "total_tasks": len(keywords) * len(platforms),
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_notes": 0,
            "total_comments": 0,
            "keyword_results": {},
            "platform_summary": {}
        }
        
        # 初始化平台统计
        for platform in platforms:
            total_stats["platform_summary"][platform] = {
                "successful_keywords": 0,
                "failed_keywords": 0,
                "total_notes": 0,
                "total_comments": 0
            }
        
        # 对每个平台一次性爬取所有关键词
        # 自适应登录：前期平台 cookie 失败 → 后续自动切换 qrcode
        effective_login = login_type
        for platform in platforms:
            # 某平台 cookie 失败后，后续全用 qrcode
            if self._cookie_failed and effective_login in ("auto", "cookie"):
                effective_login = "qrcode"
                logger.warning(f"⚠️ 已有平台 cookie 登录失败，{platform} 强制使用 qrcode")

            logger.info(f"\n📝 在 {platform} 平台爬取所有关键词")
            logger.info(f"   关键词: {', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}")

            try:
                # 一次性传递所有关键词给平台
                result = self.run_crawler(platform, keywords, effective_login, max_notes_per_keyword)
                
                if result.get("success"):
                    total_stats["successful_tasks"] += len(keywords)
                    total_stats["platform_summary"][platform]["successful_keywords"] = len(keywords)
                    
                    notes_count = result.get("notes_count", 0)
                    comments_count = result.get("comments_count", 0)
                    
                    total_stats["total_notes"] += notes_count
                    total_stats["total_comments"] += comments_count
                    total_stats["platform_summary"][platform]["total_notes"] = notes_count
                    total_stats["platform_summary"][platform]["total_comments"] = comments_count
                    
                    # 为每个关键词记录结果
                    for keyword in keywords:
                        if keyword not in total_stats["keyword_results"]:
                            total_stats["keyword_results"][keyword] = {}
                        total_stats["keyword_results"][keyword][platform] = result
                    
                    logger.info(f"   ✅ 爬取成功")
                else:
                    total_stats["failed_tasks"] += len(keywords)
                    total_stats["platform_summary"][platform]["failed_keywords"] = len(keywords)
                    
                    # 为每个关键词记录失败结果
                    for keyword in keywords:
                        if keyword not in total_stats["keyword_results"]:
                            total_stats["keyword_results"][keyword] = {}
                        total_stats["keyword_results"][keyword][platform] = result
                    
                    logger.error(f"   ❌ 失败: {result.get('error', '未知错误')}")
            
            except Exception as e:
                total_stats["failed_tasks"] += len(keywords)
                total_stats["platform_summary"][platform]["failed_keywords"] = len(keywords)
                error_result = {"success": False, "error": str(e)}
                
                # 为每个关键词记录异常结果
                for keyword in keywords:
                    if keyword not in total_stats["keyword_results"]:
                        total_stats["keyword_results"][keyword] = {}
                    total_stats["keyword_results"][keyword][platform] = error_result
                
                logger.error(f"   ❌ 异常: {e}")
        
        # 打印详细统计
        finish_message = f"\n📊 全平台关键词爬取完成!"
        finish_message += f"\n   总任务: {total_stats['total_tasks']}"
        finish_message += f"\n   成功: {total_stats['successful_tasks']}"
        finish_message += f"\n   失败: {total_stats['failed_tasks']}"
        finish_message += f"\n   成功率: {total_stats['successful_tasks']/total_stats['total_tasks']*100:.1f}%"
        logger.info(finish_message)
        
        platform_summary_message = f"\n📈 各平台统计:"
        for platform, stats in total_stats["platform_summary"].items():
            success_rate = stats["successful_keywords"] / len(keywords) * 100 if keywords else 0
            platform_summary_message += f"\n   {platform}: {stats['successful_keywords']}/{len(keywords)} 关键词成功 ({success_rate:.1f}%)"
        logger.info(platform_summary_message)
        
        return total_stats
    
    def get_crawl_statistics(self) -> Dict:
        """获取爬取统计信息"""
        return {
            "platforms_crawled": list(self.crawl_stats.keys()),
            "total_platforms": len(self.crawl_stats),
            "detailed_stats": self.crawl_stats
        }
    
    def save_crawl_log(self, log_path: str = None):
        """保存爬取日志"""
        if not log_path:
            log_path = f"crawl_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(self.crawl_stats, f, ensure_ascii=False, indent=2)
            logger.info(f"爬取日志已保存到: {log_path}")
        except Exception as e:
            logger.exception(f"保存爬取日志失败: {e}")

if __name__ == "__main__":
    # 测试平台爬虫管理器
    crawler = PlatformCrawler()
    
    # 测试配置
    test_keywords = ["科技", "AI", "编程"]
    result = crawler.run_crawler("xhs", test_keywords, max_notes=5)
    
    logger.info(f"测试结果: {result}")
    logger.info("平台爬虫管理器测试完成！")
