"""武库右侧面板读取器。

点击山河器后，从右侧面板解析名称、元素、等级、主属性、评分和素蕴。
"""

from __future__ import annotations

import re
from typing import List, Optional

import numpy as np

from shq.scanner.ocr_scanner import OCRBackend, OCRResult
from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.models import AffixData, DetailData


class DetailPanelReader:
    """解析武库右侧面板信息。"""

    # 元素字符集合
    ELEMENTS = {"金", "木", "水", "火", "土"}

    # 主属性中可能出现的键名（用于从 OCR 文本中提取）
    STAT_KEYS = (
        "气血上限",
        "外功防御",
        "内功防御",
        "内外功攻击",
        "内外防",
        "攻击最小值",
        "攻击最大值",
        "命中",
        "坚韧",
        "暴击抵抗",
        "无咎",
        "振击",
    )

    def __init__(self, ocr_backend: OCRBackend, config: Optional[WukuConfig] = None):
        self.ocr = ocr_backend
        self.cfg = config or WukuConfig()

    def parse(self, img: np.ndarray) -> DetailData:
        """从完整窗口截图中解析右侧面板。

        Args:
            img: 点击 item 后的完整窗口截图。

        Returns:
            DetailData 对象。
        """
        h, w = img.shape[:2]
        dx, dy, dw, dh = self.cfg.detail_roi.abs(w, h)
        detail_img = img[dy : dy + dh, dx : dx + dw]

        results = self.ocr.recognize_with_boxes(detail_img)
        # 转回完整窗口坐标（便于 debug，但解析时不需要）
        for r in results:
            if r.bbox:
                r.bbox = [(p[0] + dx, p[1] + dy) for p in r.bbox]

        return self._parse_results(results)

    def _parse_results(self, results: List[OCRResult]) -> DetailData:
        """从 OCR 结果解析 DetailData。"""
        data = DetailData(name="")
        texts = [r.text.strip() for r in results if r.text.strip()]
        joined = " ".join(texts)

        # 名称：取最上方且较长的文本，排除“等级”“主属性”等已知 UI 词
        data.name = self._extract_name(results)

        # 元素
        data.element = self._extract_element(texts)

        # 等级
        data.level = self._extract_level(joined)

        # 评分
        data.score = self._extract_score(joined)

        # 主属性
        data.main_stats = self._extract_main_stats(texts)

        # 素蕴
        data.affixes = self._extract_affixes(texts)

        return data

    def _extract_name(self, results: List[OCRResult]) -> str:
        """提取山河器名称。

        策略：取 y 坐标最小（最靠上）且长度 >= 2 的文本，
        排除已知 UI 文字和元素单字。
        """
        candidates: List[OCRResult] = []
        for r in results:
            text = r.text.strip()
            if len(text) < 2:
                continue
            if text in ("主属性", "专属词条", "评分", "派生素蕴", "等级"):
                continue
            if text in self.ELEMENTS:
                continue
            candidates.append(r)

        if not candidates:
            return ""

        # 按 y 坐标排序，取最上方
        def top_y(r: OCRResult) -> int:
            if not r.bbox:
                return 0
            return min(p[1] for p in r.bbox)

        candidates.sort(key=top_y)
        return candidates[0].text.strip()

    def _extract_element(self, texts: List[str]) -> Optional[str]:
        """从文本中提取元素。"""
        for text in texts:
            for ch in self.ELEMENTS:
                if ch in text and len(text) <= 3:
                    return ch
        return None

    @staticmethod
    def _extract_level(joined_text: str) -> int:
        """提取等级，如“等级 10级”。"""
        m = re.search(r"等级\s*(\d+)级", joined_text)
        if m:
            return int(m.group(1))
        # 兜底：直接找“X级”
        m = re.search(r"(\d+)级", joined_text)
        if m:
            return int(m.group(1))
        return 1

    @staticmethod
    def _extract_score(joined_text: str) -> float:
        """提取评分，如“评分：1420”。"""
        m = re.search(r"评分[:：]\s*([\d,]+)", joined_text)
        if m:
            return float(m.group(1).replace(",", ""))
        return 0.0

    def _extract_main_stats(self, texts: List[str]) -> dict:
        """提取主属性键值对。"""
        stats: dict = {}
        for text in texts:
            # 匹配“键：值”或“键:值”
            m = re.match(r"(.+?)[:：]\s*([\d,]+)", text)
            if not m:
                continue
            key, val_str = m.group(1).strip(), m.group(2).replace(",", "")
            # 只保留已知属性键，避免把“评分”也当属性
            if any(k in key for k in self.STAT_KEYS):
                try:
                    stats[key] = float(val_str)
                except ValueError:
                    pass
        return stats

    def _extract_affixes(self, texts: List[str]) -> List[AffixData]:
        """提取素蕴列表。

        格式示例：
        - "2级水之力,评分:800"
        - "1级金之力,评分:160"
        """
        affixes: List[AffixData] = []
        pattern = re.compile(r"(\d+)级(.+?)[,，]评分[:：]\s*([\d,]+)")
        for text in texts:
            for m in pattern.finditer(text):
                level = int(m.group(1))
                name = m.group(2).strip()
                score = float(m.group(3).replace(",", ""))
                affixes.append(AffixData(name=name, level=level, score=score))
        return affixes
