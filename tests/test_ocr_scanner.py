"""OCR 扫描器测试。"""

import numpy as np

from shq.models import Element, Quality
from shq.scanner.ocr_scanner import PlaceholderOCRBackend, ShanheqiOCR


def test_placeholder_ocr_returns_todo():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    backend = PlaceholderOCRBackend()
    results = backend.recognize(img)
    assert len(results) == 1
    assert "TODO" in results[0][0]


def test_parse_shanheqi_placeholder():
    texts = [("示例山河器", 0.9), ("绝世", 0.8)]
    shq = ShanheqiOCR._parse_shanheqi(texts, 0)
    assert shq is not None
    assert shq.id == "ocr_shq_0"
    assert shq.quality == Quality.SIMPLE  # 占位实现未解析品质
    assert shq.element == Element.METAL  # 占位实现未解析五行
