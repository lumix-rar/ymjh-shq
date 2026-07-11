"""WukuReader 单元测试（不依赖真实窗口/OCR）。"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from shq.models import Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.ocr_scanner import PlaceholderOCRBackend
from shq.scanner.readers import WukuReader
from shq.scanner.wuku_scanner import ScanResult


class TestWukuReader(unittest.TestCase):
    def _make_reader(self):
        return WukuReader(
            ocr_backend=PlaceholderOCRBackend(),
            output_dir=Path("/tmp/wuku_test"),
            parse_workers=2,
            reconcile_threshold=0.6,
        )

    @patch("shq.scanner.readers.wuku_reader.WukuNavigator")
    @patch("shq.scanner.readers.wuku_reader.WukuScanner")
    def test_read_quality_navigates_and_scans(self, mock_scanner_cls, mock_navigator_cls):
        reader = self._make_reader()
        reader.navigator.navigate_to.return_value = True
        reader.scanner.scan_quality.return_value = ScanResult()

        result = reader.read_quality("朴素")

        reader.navigator.navigate_to.assert_called_once_with("武库")
        reader.scanner.scan_quality.assert_called_once_with("朴素", reconcile=False)
        self.assertIsInstance(result, ScanResult)

    @patch("shq.scanner.readers.wuku_reader.WukuNavigator")
    @patch("shq.scanner.readers.wuku_reader.WukuScanner")
    def test_read_quality_reconcile_applies(self, mock_scanner_cls, mock_navigator_cls):
        reader = self._make_reader()
        reader.navigator.navigate_to.return_value = True

        shq = Shanheqi(
            id="wuku_朴素_普通_测试_1",
            name="测试",
            quality=Quality.SIMPLE,
            element=Element.METAL,
            level=1,
            base_score=100.0,
        )
        scan_result = ScanResult(shanheqis=[shq], low_confidence=[])
        reader.scanner.scan_quality.return_value = scan_result

        with patch("shq.scanner.readers.wuku_reader.ScanReconciler") as mock_reconciler_cls:
            reconciler = MagicMock()
            reconciler.reconcile.return_value = ([shq], [])
            mock_reconciler_cls.return_value = reconciler

            result = reader.read_quality("朴素", reconcile=True)

            mock_reconciler_cls.assert_called_once()
            reconciler.reconcile.assert_called_once_with(
                "朴素", [shq], []
            )
            self.assertEqual(result.shanheqis, [shq])

    @patch("shq.scanner.readers.wuku_reader.WukuNavigator")
    @patch("shq.scanner.readers.wuku_reader.WukuScanner")
    def test_read_quality_navigation_failure_raises(self, mock_scanner_cls, mock_navigator_cls):
        reader = self._make_reader()
        reader.navigator.navigate_to.return_value = False

        with self.assertRaises(RuntimeError):
            reader.read_quality("朴素")

    @patch("shq.scanner.readers.wuku_reader.capture_game_window")
    @patch("shq.scanner.readers.wuku_reader.SearchCollector")
    @patch("shq.scanner.readers.wuku_reader.WukuNavigator")
    @patch("shq.scanner.readers.wuku_reader.WukuScanner")
    def test_read_full_flow(
        self, mock_scanner_cls, mock_navigator_cls, mock_collector_cls, mock_capture
    ):
        reader = self._make_reader()
        reader.navigator.navigate_to.return_value = True

        mock_collector = MagicMock()
        mock_collector.read.return_value = (16, 119)
        mock_collector_cls.return_value = mock_collector

        scan_result = ScanResult(shanheqis=[])
        reader.scanner.run.return_value = scan_result

        result = reader.read(reconcile=True)

        # 1. 导航到搜寻
        self.assertEqual(reader.navigator.navigate_to.call_args_list[0].args, ("搜寻",))
        # 2. 读取收集度
        mock_capture.assert_called_once_with(fixed_size=True)
        mock_collector.read.assert_called_once()
        # 3. 导航到武库
        self.assertEqual(reader.navigator.navigate_to.call_args_list[1].args, ("武库",))
        # 4. 扫描全部品质
        reader.scanner.run.assert_called_once_with(reconcile=True)
        # 5. 收集度写入 screenshots
        self.assertEqual(result.screenshots["_owned_total"], 16)
        self.assertEqual(result.screenshots["_total"], 119)


if __name__ == "__main__":
    unittest.main()
