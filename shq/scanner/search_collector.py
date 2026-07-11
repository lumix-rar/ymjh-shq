"""搜寻页面收集度读取模块。

职责单一：从当前已经是“搜寻”界面的截图中，OCR 解析出收集度。
不执行任何点击、不导航。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

import numpy as np

from shq.scanner.ocr_scanner import OCRBackend, PlaceholderOCRBackend


class SearchCollector:
    """搜寻界面收集度读取器。"""

    def __init__(self, ocr_backend: Optional[OCRBackend] = None):
        self.backend = ocr_backend or PlaceholderOCRBackend()

    def read(self, img: np.ndarray) -> Tuple[Optional[int], Optional[int]]:
        """从截图中读取已获取 / 总数。

        Returns:
            (owned_count, total_count)，解析失败时返回 (None, None)
        """
        texts = self.backend.recognize(img)
        joined = "\n".join(t for t, _ in texts)

        patterns = [
            r"(?:收集度|已获取|已获得|拥有|搜寻到).*?(\d+)\s*/\s*(\d+)",
            r"(\d+)\s*/\s*(\d+)",
        ]
        for pat in patterns:
            m = re.search(pat, joined)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None, None
