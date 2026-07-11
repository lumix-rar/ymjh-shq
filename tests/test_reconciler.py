"""ScanReconciler 单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from shq.models import Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.name_resolver import ShanheqiNameResolver
from shq.scanner.reconciler import ScanReconciler


class TestReconciler(unittest.TestCase):
    def setUp(self):
        self.master = {
            "version": "1.0",
            "qualities": {
                "朴素": ["缤铁雪花", "螭尾凤头", "竹节锏", "锐明盔"],
                "精巧": ["吟秋扇"],
            },
        }
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        json.dump(self.master, self.tmp)
        self.tmp.close()
        self.resolver = ShanheqiNameResolver(Path(self.tmp.name))
        self.reconciler = ScanReconciler(resolver=self.resolver, score_threshold=0.55)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def _make_shq(self, name: str, quality: Quality = Quality.SIMPLE) -> Shanheqi:
        return Shanheqi(
            id=f"wuku_{quality.value}_普通_{name}_1",
            name=name,
            quality=quality,
            element=Element.METAL,
            shanheqi_type=ShanheqiType.NORMAL,
            level=1,
            base_score=100.0,
        )

    def test_no_missing(self):
        owned = [
            self._make_shq("缤铁雪花"),
            self._make_shq("螭尾凤头"),
            self._make_shq("竹节锏"),
            self._make_shq("锐明盔"),
        ]
        _, report = self.reconciler.reconcile("朴素", owned)
        self.assertEqual(report, [])

    def test_rename_wrong_ocr_name(self):
        # OCR 把 缤铁雪花 错识为 铁雪花，reconciler 应补齐
        owned = [
            self._make_shq("铁雪花"),
            self._make_shq("螭尾凤头"),
            self._make_shq("竹节锏"),
            self._make_shq("锐明盔"),
        ]
        _, report = self.reconciler.reconcile("朴素", owned)
        filled = [r for r in report if r["action"] == "已补齐"]
        self.assertEqual(len(filled), 1)
        self.assertEqual(filled[0]["missing"], "缤铁雪花")
        self.assertEqual(owned[0].name, "缤铁雪花")
        self.assertIn("缤铁雪花", [s.name for s in owned])

    def test_unresolved_still_reported(self):
        # 有一个完全无关的错误名字，无法补齐
        owned = [
            self._make_shq("完全不相关"),
            self._make_shq("螭尾凤头"),
            self._make_shq("竹节锏"),
            self._make_shq("锐明盔"),
        ]
        _, report = self.reconciler.reconcile("朴素", owned)
        unresolved = [r for r in report if r["action"] == "未找到可信匹配"]
        # 缤铁雪花 无法与 完全不相关 匹配，应报 unresolved
        self.assertTrue(any(r["missing"] == "缤铁雪花" for r in unresolved))

    def test_remaining_missing(self):
        owned = [self._make_shq("缤铁雪花")]
        self.reconciler.reconcile("朴素", owned)
        remaining = self.reconciler.remaining_missing("朴素", owned)
        self.assertIn("锐明盔", remaining)


if __name__ == "__main__":
    unittest.main()
