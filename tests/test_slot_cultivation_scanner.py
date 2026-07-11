"""SlotCultivationScanner 单元测试（不依赖真实窗口/OCR）。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

from shq.models import Region, Slot
from shq.scanner.ocr_scanner import OCRResult
from shq.scanner.slot_cultivation_scanner import SlotCultivationScanner
from shq.scanner.topology_loader import RegionCalibration, SlotCalibration
from shq.scanner.window_capture import ROI


class MockOCRBackend:
    """可控 OCR 后端。"""

    def __init__(self, recognize_results=None, recognize_with_boxes_results=None):
        self._recognize = recognize_results or []
        self._recognize_with_boxes = recognize_with_boxes_results or []

    def recognize(self, img):
        return list(self._recognize)

    def recognize_with_boxes(self, img):
        return list(self._recognize_with_boxes)


class TestSlotCultivationScanner(unittest.TestCase):
    def _make_scanner(self, backend=None):
        return SlotCultivationScanner(
            ocr_backend=backend,
            confidence_threshold=0.5,
            output_dir=Path("/tmp/lingjian_test"),
        )

    def _draw_square(self, img, x, y, size, color=(200, 200, 200), thickness=3):
        """在图像上绘制一个空心正方形，模拟编号方块。"""
        cv2.rectangle(img, (x, y), (x + size, y + size), color, thickness)

    def test_parse_score_variants(self):
        scanner = self._make_scanner()
        self.assertEqual(scanner._parse_score("+3600"), 3600.0)
        self.assertEqual(scanner._parse_score("3600分"), 3600.0)
        self.assertEqual(scanner._parse_score("评分：3,600"), 3600.0)
        self.assertEqual(scanner._parse_score("培养: +1,200"), 1200.0)
        self.assertEqual(scanner._parse_score("孔位1 评分 500"), 500.0)
        self.assertIsNone(scanner._parse_score("孔位培养"))

    def test_read_region_detects_squares_and_scores(self):
        """通过方块检测定位孔位，并将下方加分文字归到对应编号。"""
        backend = MockOCRBackend(
            recognize_with_boxes_results=[
                # 壹下方加分
                OCRResult(text="孔位评分：+3600", confidence=0.9, bbox=[[80, 90], [200, 90], [200, 115], [80, 115]]),
            ]
        )
        scanner = self._make_scanner(backend)

        region = Region(
            id="yiji_meihua",
            name="驿寄梅花",
            slots=[Slot(id="yiji_s1", region_id="yiji_meihua")],
        )
        calibration = RegionCalibration(
            region_id="yiji_meihua",
            panel_roi=ROI("panel", 0, 0, 300, 200),
            slots=[SlotCalibration(slot_id="yiji_s1", number=1)],
        )

        # 构造一张带方块的图（方块放在远离面板中心的位置，避免被中心装饰过滤）
        panel = np.zeros((200, 300, 3), dtype=np.uint8)
        self._draw_square(panel, 50, 20, 60)  # 编号方块
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        img[0:200, 0:300] = panel

        rr = scanner.read_region(img, region, calibration, panel_open=True)

        self.assertEqual(rr.region_id, "yiji_meihua")
        self.assertFalse(rr.locked)
        self.assertEqual(len(rr.slots), 1)
        self.assertEqual(rr.slots[0].score, 3600.0)
        self.assertEqual(rr.slots[0].number, 1)
        self.assertEqual(rr.slots[0].raw_text, "孔位评分：+3600")

    def test_read_region_zero_score_when_no_score_text(self):
        """只有方块、没有加分文字时， cultivation_score 应为 0。"""
        backend = MockOCRBackend(recognize_with_boxes_results=[])
        scanner = self._make_scanner(backend)
        region = Region(
            id="yiji_meihua",
            name="驿寄梅花",
            slots=[Slot(id="yiji_s1", region_id="yiji_meihua")],
        )
        calibration = RegionCalibration(
            region_id="yiji_meihua",
            panel_roi=ROI("panel", 0, 0, 300, 200),
            slots=[SlotCalibration(slot_id="yiji_s1", number=1)],
        )
        panel = np.zeros((200, 300, 3), dtype=np.uint8)
        self._draw_square(panel, 50, 20, 60)
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        img[0:200, 0:300] = panel

        rr = scanner.read_region(img, region, calibration, panel_open=True)
        self.assertEqual(rr.slots[0].score, 0.0)
        self.assertEqual(rr.slots[0].raw_text, "")

    def test_read_region_count_mismatch(self):
        """检测到的方块数量与拓扑不一致时，应记录 low_confidence。"""
        backend = MockOCRBackend(recognize_with_boxes_results=[])
        scanner = self._make_scanner(backend)
        region = Region(
            id="yiji_meihua",
            name="驿寄梅花",
            slots=[
                Slot(id="yiji_s1", region_id="yiji_meihua"),
                Slot(id="yiji_s2", region_id="yiji_meihua"),
            ],
        )
        calibration = RegionCalibration(
            region_id="yiji_meihua",
            panel_roi=ROI("panel", 0, 0, 300, 200),
            slots=[
                SlotCalibration(slot_id="yiji_s1", number=1),
                SlotCalibration(slot_id="yiji_s2", number=2),
            ],
        )
        panel = np.zeros((200, 300, 3), dtype=np.uint8)
        self._draw_square(panel, 50, 20, 60)  # 只画 1 个方块，但拓扑期望 2 个
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        img[0:200, 0:300] = panel

        rr = scanner.read_region(img, region, calibration, panel_open=True)
        self.assertEqual(len(rr.low_confidence), 1)
        self.assertEqual(rr.low_confidence[0]["reason"], "slot_count_mismatch")

    def test_calibrate_panel_detects_numbers_and_scores(self):
        backend = MockOCRBackend(
            recognize_with_boxes_results=[
                OCRResult(text="孔位评分：+3600", confidence=0.9, bbox=[[80, 90], [200, 90], [200, 115], [80, 115]]),
                OCRResult(text="孔位评分：+4800", confidence=0.9, bbox=[[80, 160], [200, 160], [200, 185], [80, 185]]),
            ]
        )
        scanner = self._make_scanner(backend)
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        # 画两个方块
        self._draw_square(img, 100, 20, 60)
        self._draw_square(img, 100, 90, 60)
        panel_roi = ROI("panel", 0, 0, 300, 200)

        data = scanner.calibrate_panel(img, "yiji_meihua", panel_roi=panel_roi)

        self.assertEqual(data["region_id"], "yiji_meihua")
        self.assertEqual(len(data["score_candidates"]), 2)
        scores = [c["parsed_score"] for c in data["score_candidates"]]
        self.assertIn(3600.0, scores)
        self.assertIn(4800.0, scores)


if __name__ == "__main__":
    unittest.main()
