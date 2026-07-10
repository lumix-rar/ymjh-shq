"""ScrollController 单元测试。"""

import pytest

from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.models import BBox, GridItem, Point
from shq.scanner.wuku.scroll_controller import ScrollController


def _make_item(name: str, level: int | None = None) -> GridItem:
    """构造一个用于测试的 GridItem。"""
    bbox = BBox(x=0, y=0, width=100, height=100)
    return GridItem(
        name=name,
        cell_bbox=bbox,
        click_point=bbox.center,
        level=level,
        is_acquired=level is not None,
    )


def test_is_at_bottom_returns_false_when_new_items_appear():
    cfg = WukuConfig(bottom_no_new_items_count=2)
    scroller = ScrollController(hwnd=0, config=cfg)

    # 第一页有 3 个新 item
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B"), _make_item("C")]) is False
    # 第二页有 1 个新 item（D），同时 A/B 已见过
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B"), _make_item("D")]) is False


def test_is_at_bottom_returns_true_after_no_new_items_for_threshold():
    cfg = WukuConfig(bottom_no_new_items_count=2)
    scroller = ScrollController(hwnd=0, config=cfg)

    # 第一页
    scroller.is_at_bottom([_make_item("A"), _make_item("B")])
    # 第二页：无新 item
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is False
    # 第三页：仍无新 item，达到阈值，触底
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is True


def test_is_at_bottom_resets_no_new_count_when_new_item_appears():
    cfg = WukuConfig(bottom_no_new_items_count=2)
    scroller = ScrollController(hwnd=0, config=cfg)

    scroller.is_at_bottom([_make_item("A")])
    # 连续一次无新 item
    assert scroller.is_at_bottom([_make_item("A")]) is False
    # 出现新 item，计数重置
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is False
    # 再次连续两次无新 item 才触底
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is False
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is True


def test_reset_clears_seen_items_and_count():
    cfg = WukuConfig(bottom_no_new_items_count=2)
    scroller = ScrollController(hwnd=0, config=cfg)

    scroller.is_at_bottom([_make_item("A"), _make_item("B")])
    scroller.is_at_bottom([_make_item("A"), _make_item("B")])

    scroller.reset()

    # 重置后原来的 item 变成新的，不会再提前触底
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is False
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is False
    assert scroller.is_at_bottom([_make_item("A"), _make_item("B")]) is True


def test_is_at_bottom_with_empty_items():
    cfg = WukuConfig(bottom_no_new_items_count=2)
    scroller = ScrollController(hwnd=0, config=cfg)

    # 空列表表示检测失败，不应算作触底，避免检测异常导致提前退出
    assert scroller.is_at_bottom([]) is False
    assert scroller.is_at_bottom([]) is False
    assert scroller.is_at_bottom([]) is False

    # 一旦检测到正常 item，逻辑恢复
    assert scroller.is_at_bottom([_make_item("A")]) is False
    assert scroller.is_at_bottom([_make_item("A")]) is False
    assert scroller.is_at_bottom([_make_item("A")]) is True
