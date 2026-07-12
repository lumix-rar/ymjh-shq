"""LingjianNavigator 单元测试（不依赖真实窗口/OCR）。"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from shq.scanner.lingjian_navigator import LingjianNavigator
from shq.scanner.ocr_scanner import OCRResult


class MockOCRBackend:
    """可控 OCR 后端。

    支持两种传参方式：
    - 传一个列表：每次调用返回该列表；
    - 传一个列表的列表：按调用顺序依次返回每个子列表。
    """

    def __init__(self, with_boxes=None, texts=None):
        self._with_boxes = self._normalize_boxes(with_boxes)
        self._texts = self._normalize_texts(texts)
        self._with_boxes_idx = 0
        self._texts_idx = 0

    @staticmethod
    def _normalize_texts(value):
        if value is None:
            return []
        # texts 单条结果是 (str, float) 元组
        if value and isinstance(value[0], tuple):
            return [value]
        return list(value)

    @staticmethod
    def _normalize_boxes(value):
        if value is None:
            return []
        # with_boxes 单条结果是 OCRResult 对象
        if value and isinstance(value[0], OCRResult):
            return [value]
        return list(value)

    def recognize(self, img):
        if not self._texts:
            return []
        result = self._texts[self._texts_idx]
        if self._texts_idx + 1 < len(self._texts):
            self._texts_idx += 1
        return list(result)

    def recognize_with_boxes(self, img):
        if not self._with_boxes:
            return []
        result = self._with_boxes[self._with_boxes_idx]
        if self._with_boxes_idx + 1 < len(self._with_boxes):
            self._with_boxes_idx += 1
        return list(result)


class TestLingjianNavigator(unittest.TestCase):
    def _make_navigator(self, backend=None):
        nav = LingjianNavigator(ocr_backend=backend or MockOCRBackend())
        nav._cap = MagicMock()
        nav._cap.hwnd = 12345
        nav._cap.get_client_size.return_value = (1334, 750)
        return nav

    def test_detect_current_region_returns_topmost(self):
        backend = MockOCRBackend(
            with_boxes=[
                OCRResult(text="长烟烽火", confidence=0.9, bbox=[[10, 100], [90, 100], [90, 130], [10, 130]]),
                OCRResult(text="驿寄梅花", confidence=0.9, bbox=[[10, 50], [90, 50], [90, 80], [10, 80]]),
            ]
        )
        nav = self._make_navigator(backend)
        img = np.zeros((750, 1334, 3), dtype=np.uint8)

        current = nav.detect_current_region(img)
        self.assertEqual(current, "驿寄梅花")

    def test_select_region_opens_dropdown_when_not_current(self):
        backend = MockOCRBackend(
            with_boxes=[
                # 第一次截图：收起状态，当前是驿寄梅花
                [OCRResult(text="驿寄梅花", confidence=0.9, bbox=[[10, 50], [90, 50], [90, 80], [10, 80]])],
                # 第二次截图：展开状态，有关河道远
                [OCRResult(text="关河道远", confidence=0.9, bbox=[[10, 200], [90, 200], [90, 230], [10, 230]])],
                # 第三次截图：验证切换后当前为关河道远
                [OCRResult(text="关河道远", confidence=0.9, bbox=[[10, 50], [90, 50], [90, 80], [10, 80]])],
            ]
        )
        nav = self._make_navigator(backend)
        nav._capture = MagicMock(return_value=np.zeros((750, 1334, 3), dtype=np.uint8))
        nav._click_and_wait_for_stable = MagicMock()

        ok = nav.select_region("关河道远")

        self.assertTrue(ok)
        # 第一次点击下拉框，第二次点击目标
        self.assertEqual(nav._click_and_wait_for_stable.call_count, 2)

    def test_select_region_already_current(self):
        backend = MockOCRBackend(
            with_boxes=[
                OCRResult(text="驿寄梅花", confidence=0.9, bbox=[[10, 50], [90, 50], [90, 80], [10, 80]]),
            ]
        )
        nav = self._make_navigator(backend)
        nav._capture = MagicMock(return_value=np.zeros((750, 1334, 3), dtype=np.uint8))
        nav._click_client = MagicMock()

        ok = nav.select_region("驿寄梅花")

        self.assertTrue(ok)
        nav._click_client.assert_not_called()

    def test_is_region_locked_detects_unlock_text(self):
        backend = MockOCRBackend(texts=[("未解锁", 0.9)])
        nav = self._make_navigator(backend)
        img = np.zeros((750, 1334, 3), dtype=np.uint8)

        self.assertTrue(nav.is_region_locked(img))

    def test_is_region_locked_not_locked(self):
        backend = MockOCRBackend(texts=[("孔位培养", 0.9)])
        nav = self._make_navigator(backend)
        img = np.zeros((750, 1334, 3), dtype=np.uint8)

        self.assertFalse(nav.is_region_locked(img))

    def test_click_cultivation_button_finds_button(self):
        backend = MockOCRBackend(
            with_boxes=[
                OCRResult(text="孔位培养", confidence=0.9, bbox=[[500, 600], [600, 600], [600, 640], [500, 640]]),
            ],
            texts=[
                [("孔位培养", 0.9)],  # 第一次：标签可见但详情未出
                [("孔位培养", 0.9), ("壹孔", 0.9)],  # 第二次：已切换成功
            ],
        )
        nav = self._make_navigator(backend)
        nav._capture = MagicMock(return_value=np.zeros((750, 1334, 3), dtype=np.uint8))
        nav._click_and_wait_for_stable = MagicMock()

        ok = nav.click_cultivation_button()

        self.assertTrue(ok)
        nav._click_and_wait_for_stable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
