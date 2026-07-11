"""WukuScanner 核心逻辑单元测试（不依赖真实窗口/OCR）。"""

import json
import tempfile
import unittest
from pathlib import Path

from shq.models import Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.ocr_scanner import PlaceholderOCRBackend
from shq.scanner.wuku_scanner import ScanResult, WukuScanner


class TestWukuScannerFinalize(unittest.TestCase):
    def setUp(self):
        self.scanner = WukuScanner(ocr_backend=PlaceholderOCRBackend())

    def _make_shq(
        self,
        name: str = "测试",
        quality: Quality = Quality.SIMPLE,
        shanheqi_type: ShanheqiType = ShanheqiType.NORMAL,
    ) -> Shanheqi:
        return Shanheqi(
            id="old_id",
            name=name,
            quality=quality,
            element=Element.METAL,
            shanheqi_type=shanheqi_type,
            level=5,
            base_score=100.0,
        )

    def test_finalize_simple_quality(self):
        self.scanner._current_quality = "朴素"
        shq = self._make_shq(name="测试")
        shq = self.scanner._finalize_shanheqi(shq, "朴素", None)
        self.assertEqual(shq.quality, Quality.SIMPLE)
        self.assertEqual(shq.shanheqi_type, ShanheqiType.NORMAL)
        self.assertEqual(shq.id, "wuku_朴素_普通_测试_5")

    def test_finalize_peerless_sub_tag(self):
        self.scanner._current_quality = "绝世"
        # 视觉未检测到特殊图标，resolver 给出 玄枢
        shq = self._make_shq(quality=Quality.PEERLESS, shanheqi_type=ShanheqiType.NORMAL)
        shq = self.scanner._finalize_shanheqi(shq, "绝世", "玄枢")
        self.assertEqual(shq.quality, Quality.PEERLESS)
        self.assertEqual(shq.shanheqi_type, ShanheqiType.XUANSHU)
        self.assertEqual(shq.id, "wuku_绝世_玄枢_测试_5")

    def test_finalize_visual_conflicts_resolver(self):
        self.scanner._current_quality = "绝世"
        # 视觉检测到 卓异，但 resolver 给出 普通，应以底稿为准
        shq = self._make_shq(quality=Quality.PEERLESS, shanheqi_type=ShanheqiType.ZHUOYI)
        shq = self.scanner._finalize_shanheqi(shq, "绝世", "普通")
        self.assertEqual(shq.shanheqi_type, ShanheqiType.NORMAL)
        self.assertEqual(shq.id, "wuku_绝世_普通_测试_5")

    def test_finalize_non_peerless_forces_normal(self):
        self.scanner._current_quality = "朴素"
        # 视觉误检为 玄枢，但朴素品质不可能有子标签，应强制为普通
        shq = self._make_shq(quality=Quality.SIMPLE, shanheqi_type=ShanheqiType.XUANSHU)
        shq = self.scanner._finalize_shanheqi(shq, "朴素", None)
        self.assertEqual(shq.shanheqi_type, ShanheqiType.NORMAL)
        self.assertEqual(shq.id, "wuku_朴素_普通_测试_5")

    def test_duplicate_considers_quality(self):
        a = self._make_shq(name="恶来双戟", quality=Quality.SIMPLE)
        b = self._make_shq(name="恶来双戟", quality=Quality.MAGNIFICENT)
        self.assertFalse(self.scanner._is_duplicate(a, [b]))

        c = self._make_shq(name="恶来双戟", quality=Quality.SIMPLE)
        self.assertTrue(self.scanner._is_duplicate(a, [c]))


class TestWukuScannerSave(unittest.TestCase):
    def setUp(self):
        self.scanner = WukuScanner(ocr_backend=PlaceholderOCRBackend())
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        for f in self.tmp.iterdir():
            f.unlink()
        self.tmp.rmdir()

    def test_save_includes_quality_summary_and_reconciliation(self):
        result = ScanResult()
        result.shanheqis.append(
            Shanheqi(
                id="wuku_朴素_普通_测试_5",
                name="测试",
                quality=Quality.SIMPLE,
                element=Element.METAL,
                level=5,
                base_score=100.0,
            )
        )
        result.quality_summary = {
            "朴素": {"expected": 20, "detected": 1, "missing": 19, "reconciled": 0}
        }
        result.reconciliation_report = [
            {"missing": "缺失项", "action": "未找到可信匹配", "best_score": 0.0}
        ]

        output = self.scanner.save(result, self.tmp / "out.json")
        data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["total_owned"], 1)
        self.assertIn("quality_summary", data)
        self.assertEqual(data["quality_summary"]["朴素"]["detected"], 1)
        self.assertIn("reconciliation_reports", data)
        self.assertEqual(len(data["reconciliation_reports"]), 1)


if __name__ == "__main__":
    unittest.main()
