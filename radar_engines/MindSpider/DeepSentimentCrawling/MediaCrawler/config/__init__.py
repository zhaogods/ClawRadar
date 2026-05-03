# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/__init__.py
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

import os
from pathlib import Path as _Path

from .base_config import *
from .db_config import *

# 浏览器 profile 数据根目录（固定路径，不依赖 os.getcwd()）
# 优先读取环境变量 MEDIACRAWLER_BROWSER_DATA_DIR，未设置时锚定在项目根目录下
# 远程 Windows CDP 场景下，可设置此环境变量与 Chrome 启动目录对齐
_MEDIACRAWLER_ROOT = _Path(__file__).resolve().parent.parent
BROWSER_DATA_BASE = os.environ.get(
    "MEDIACRAWLER_BROWSER_DATA_DIR",
    str(_MEDIACRAWLER_ROOT / "browser_data"),
)
