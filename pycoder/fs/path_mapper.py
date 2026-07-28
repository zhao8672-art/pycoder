"""路径映射器 — 管理文件系统路径映射关系"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 从环境变量获取配置键，避免硬编码
CONFIG_KEY = os.environ.get("PYCODER_FS_MAPPINGS_KEY", "fs_mappings")

# 其余代码保持不变...