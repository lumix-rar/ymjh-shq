"""DetailPanelReader 单元测试。"""

import numpy as np

from shq.scanner.ocr_scanner import OCRBackend, OCRResult
from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.detail_reader import DetailPanelReader


class MockOCRBackend(OCRBackend):
    """返回固定 OCR 结果的测试后端。"""

    def __init__(self, results):
        self._results = results

    @property
    def name(self) -> str:
        return "mock"

    def recognize_with_boxes(self, img):
        return self._results


def make_reader(results):
    backend = MockOCRBackend(results)
    return DetailPanelReader(backend, WukuConfig())


def test_parse_name_and_score():
    results = [
        OCRResult("伏威刀", 1.0, [(100, 100), (200, 100), (200, 140), (100, 140)]),
        OCRResult("等级 10级", 1.0, [(100, 150), (220, 150), (220, 190), (100, 190)]),
        OCRResult("评分：1420", 1.0, [(100, 300), (250, 300), (250, 340), (100, 340)]),
    ]
    reader = make_reader(results)
    img = np.zeros((750, 1334, 3), dtype=np.uint8)
    data = reader.parse(img)

    assert data.name == "伏威刀"
    assert data.level == 10
    assert data.score == 1420


def test_parse_affixes():
    results = [
        OCRResult("伏威刀", 1.0, [(100, 100), (200, 100), (200, 140), (100, 140)]),
        OCRResult("2级水之力,评分:800", 1.0, [(100, 400), (350, 400), (350, 440), (100, 440)]),
        OCRResult("1级金之力,评分:160", 1.0, [(100, 450), (350, 450), (350, 490), (100, 490)]),
    ]
    reader = make_reader(results)
    img = np.zeros((750, 1334, 3), dtype=np.uint8)
    data = reader.parse(img)

    assert len(data.affixes) == 2
    assert data.affixes[0].name == "水之力"
    assert data.affixes[0].level == 2
    assert data.affixes[0].score == 800


def test_parse_main_stats():
    results = [
        OCRResult("伏威刀", 1.0, [(100, 100), (200, 100), (200, 140), (100, 140)]),
        OCRResult("气血上限：219", 1.0, [(100, 220), (300, 220), (300, 260), (100, 260)]),
        OCRResult("外功防御：4", 1.0, [(100, 270), (280, 270), (280, 310), (100, 310)]),
        OCRResult("暴击抵抗：14", 1.0, [(100, 320), (280, 320), (280, 360), (100, 360)]),
    ]
    reader = make_reader(results)
    img = np.zeros((750, 1334, 3), dtype=np.uint8)
    data = reader.parse(img)

    assert data.main_stats["气血上限"] == 219
    assert data.main_stats["外功防御"] == 4
    assert data.main_stats["暴击抵抗"] == 14
