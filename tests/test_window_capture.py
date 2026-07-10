"""窗口截图模块测试。"""

import numpy as np
import pytest

from shq.scanner.window_capture import ROI


def test_roi_crop():
    """测试 ROI 裁剪。"""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[10:30, 20:60] = 255

    roi = ROI(name="test", x=20, y=10, width=40, height=20)
    cropped = roi.crop(img)

    assert cropped.shape == (20, 40, 3)
    assert cropped.min() == 255 and cropped.max() == 255


def test_roi_crop_clamped():
    """测试 ROI 超出图像边界时的裁剪。"""
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    roi = ROI(name="test", x=30, y=30, width=40, height=40)
    cropped = roi.crop(img)

    assert cropped.shape == (20, 20, 3)
