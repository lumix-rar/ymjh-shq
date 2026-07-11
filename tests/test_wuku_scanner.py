"""WukuScanner 核心逻辑单元测试（不依赖真实窗口/OCR）。"""

import unittest

from shq.models import Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.ocr_scanner import PlaceholderOCRBackend
from shq.scanner.wuku_scanner import WukuScanner


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


if __name__ == "__main__":
    unittest.main()
