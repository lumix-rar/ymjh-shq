"""WukuConfig 单元测试。"""

import pytest

from shq.scanner.wuku.config import ROIConfig, WukuConfig


def test_roi_config_abs():
    roi = ROIConfig(x=0.1, y=0.2, width=0.3, height=0.4)
    x, y, w, h = roi.abs(1000, 500)
    assert x == 100
    assert y == 100
    assert w == 300
    assert h == 200


def test_wuku_config_defaults():
    cfg = WukuConfig()
    assert cfg.ocr_workers == 4
    assert cfg.overlap_rows == 1
    assert cfg.scroll_delta == -1200
    assert "起势" in cfg.derived_affix_candidates


def test_wuku_config_custom():
    cfg = WukuConfig(ocr_workers=8, overlap_rows=2)
    assert cfg.ocr_workers == 8
    assert cfg.overlap_rows == 2
