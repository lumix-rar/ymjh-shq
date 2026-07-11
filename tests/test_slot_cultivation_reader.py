"""SlotCultivationReader 单元测试（不依赖真实窗口/OCR）。"""

import numpy as np
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shq.models import Lingjian, Region, Slot
from shq.scanner.ocr_scanner import PlaceholderOCRBackend
from shq.scanner.readers import SlotCultivationReader
from shq.scanner.slot_cultivation_scanner import (
    RegionCultivationResult,
    SlotCultivationScanResult,
    SlotCultivationValue,
)
from shq.scanner.topology_loader import Topology, TopologyLoader


class TestSlotCultivationReader(unittest.TestCase):
    def _make_topology(self):
        # 使用真实拓扑文件加载，但替换为空目录下的路径以避免 IO 依赖
        return Topology(
            lingjian=Lingjian(
                regions=[
                    Region(
                        id="yiji_meihua",
                        name="驿寄梅花",
                        slots=[Slot(id="yiji_s1", region_id="yiji_meihua")],
                    ),
                    Region(
                        id="guanhe_daoyuan",
                        name="关河道远",
                        slots=[
                            Slot(id="guanhe_s1", region_id="guanhe_daoyuan"),
                            Slot(id="guanhe_s2", region_id="guanhe_daoyuan"),
                        ],
                    ),
                ]
            ),
            region_calibrations={},
        )

    def _make_reader(self, topology=None):
        return SlotCultivationReader(
            topology=topology or self._make_topology(),
            ocr_backend=PlaceholderOCRBackend(),
            output_dir=Path("/tmp/lingjian_reader_test"),
        )

    @patch("shq.scanner.readers.slot_cultivation_reader.LingjianNavigator")
    @patch("shq.scanner.readers.slot_cultivation_reader.SlotCultivationScanner")
    def test_read_navigates_and_reads_all_regions(
        self, mock_scanner_cls, mock_navigator_cls
    ):
        reader = self._make_reader()
        reader.navigator.navigate_to_lingjian.return_value = True
        reader.navigator.select_region.return_value = True
        reader.navigator.is_region_locked.return_value = False
        reader.navigator.click_cultivation_button.return_value = True
        reader.navigator.capture.return_value = np.zeros((750, 1334, 3), dtype=np.uint8)

        def fake_read_region(img, region, calibration, panel_open=True):
            return RegionCultivationResult(
                region_id=region.id,
                region_name=region.name,
                slots=[
                    SlotCultivationValue(
                        slot_id=slot.id,
                        number=idx + 1,
                        score=3600.0,
                        confidence=0.95,
                        raw_text="+3600",
                    )
                    for idx, slot in enumerate(region.slots)
                ],
            )

        reader.scanner.read_region.side_effect = fake_read_region

        result = reader.read()

        reader.navigator.navigate_to_lingjian.assert_called_once()
        self.assertEqual(reader.navigator.select_region.call_count, 2)
        self.assertEqual(len(result.scan_result.region_results), 2)

        # 验证分数已回填到模型
        region = result.lingjian.get_region("guanhe_daoyuan")
        self.assertIsNotNone(region)
        self.assertEqual(region.slots[0].cultivation_score, 3600.0)
        self.assertEqual(region.slots[1].cultivation_score, 3600.0)

    @patch("shq.scanner.readers.slot_cultivation_reader.LingjianNavigator")
    @patch("shq.scanner.readers.slot_cultivation_reader.SlotCultivationScanner")
    def test_read_skips_locked_region(
        self, mock_scanner_cls, mock_navigator_cls
    ):
        reader = self._make_reader()
        reader.navigator.navigate_to_lingjian.return_value = True
        reader.navigator.select_region.return_value = True
        reader.navigator.capture.return_value = np.zeros((750, 1334, 3), dtype=np.uint8)
        # 第一个区域成功打开面板；第二个区域打开失败且检测到未解锁
        reader.navigator.click_cultivation_button.side_effect = [True, False]
        reader.navigator.is_region_locked.return_value = True
        reader.scanner.read_region.return_value = RegionCultivationResult(
            region_id="yiji_meihua",
            region_name="驿寄梅花",
            locked=False,
        )

        result = reader.read()

        locked = [rr for rr in result.scan_result.region_results if rr.locked]
        self.assertEqual(len(locked), 1)
        self.assertEqual(locked[0].region_id, "guanhe_daoyuan")
        self.assertIn("guanhe_daoyuan", result.scan_result.locked_region_ids)
        reader.scanner.read_region.assert_called_once()
        reader.navigator.is_region_locked.assert_called_once()

    @patch("shq.scanner.readers.slot_cultivation_reader.LingjianNavigator")
    @patch("shq.scanner.readers.slot_cultivation_reader.SlotCultivationScanner")
    def test_read_navigation_failure_raises(
        self, mock_scanner_cls, mock_navigator_cls
    ):
        reader = self._make_reader()
        reader.navigator.navigate_to_lingjian.return_value = False

        with self.assertRaises(RuntimeError):
            reader.read()

    @patch("shq.scanner.readers.slot_cultivation_reader.LingjianNavigator")
    @patch("shq.scanner.readers.slot_cultivation_reader.SlotCultivationScanner")
    def test_calibrate_runs_through_regions(
        self, mock_scanner_cls, mock_navigator_cls
    ):
        reader = self._make_reader()
        reader.navigator.navigate_to_lingjian.return_value = True
        reader.navigator.select_region.return_value = True
        reader.navigator.is_region_locked.return_value = False
        reader.navigator.click_cultivation_button.return_value = True
        reader.navigator.detect_current_region.side_effect = ["驿寄梅花", "关河道远"]
        reader.navigator.detect_region_buttons.return_value = {
            "驿寄梅花": (120, 200),
            "关河道远": (120, 300),
        }

        reader.scanner.calibrate_panel.return_value = {
            "region_id": "yiji_meihua",
            "panel_roi": {"name": "panel", "x": 0, "y": 0, "width": 100, "height": 100},
            "texts": [],
            "number_candidates": [
                {
                    "x": 10,
                    "y": 10,
                    "w": 20,
                    "h": 20,
                    "text": "壹",
                    "parsed_number": 1,
                    "confidence": 0.9,
                }
            ],
            "score_candidates": [
                {
                    "x": 10,
                    "y": 40,
                    "w": 80,
                    "h": 20,
                    "text": "孔位评分：+3600",
                    "parsed_score": 3600.0,
                    "confidence": 0.9,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "calibrated.json"
            path = reader.calibrate(output_path=out)
            self.assertTrue(path.exists())

        reader.navigator.select_region.assert_called()
        reader.scanner.calibrate_panel.assert_called()


if __name__ == "__main__":
    unittest.main()
