"""导航控制器测试。"""

import numpy as np

from shq.scanner.navigation_controller import NavigationController
from shq.scanner.ocr_scanner import OCRResult, PlaceholderOCRBackend


def test_normalize_label():
    assert NavigationController._normalize_label("武 库") == "武库"
    assert NavigationController._normalize_label("武\n库") == "武库"
    assert NavigationController._normalize_label("灵鉴!") == "灵鉴"


def test_detect_nav_buttons_with_mock_ocr():
    """用 mock OCR 测试导航按钮检测与坐标转换。"""

    class MockOCR(PlaceholderOCRBackend):
        def recognize_with_boxes(self, img):
            h, w = img.shape[:2]
            # 在右侧区域中心返回"武库"
            return [OCRResult("武库", 0.95, [(w // 4, h // 4), (w * 3 // 4, h // 4), (w * 3 // 4, h * 3 // 4), (w // 4, h * 3 // 4)])]

    ctrl = NavigationController(ocr_backend=MockOCR())
    img = np.zeros((750, 1334, 3), dtype=np.uint8)
    buttons = ctrl.detect_nav_buttons(img)
    assert len(buttons) == 1
    assert buttons[0].name == "武库"
    # 右侧区域起始于 0.82 * 1334 ≈ 1093
    assert buttons[0].center_x > 1093


def test_manual_fallback_prompts_user(monkeypatch):
    """手动降级模式会读取用户输入并再次检测武库高亮。"""
    ctrl = NavigationController(ocr_backend=PlaceholderOCRBackend())
    monkeypatch.setattr("builtins.input", lambda: None)
    # 默认黑色截图不会触发高亮，因此会失败；主要验证流程不抛异常
    assert ctrl._manual_fallback_to_wuku() is False
