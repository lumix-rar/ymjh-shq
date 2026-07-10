"""武库列表滚动控制器。

负责在武库网格区域发送鼠标滚轮事件，并通过跟踪每页出现的 item
判断是否已经滚动到底部。
"""

from __future__ import annotations

import ctypes
import time
from typing import List, Optional, Set

from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.models import GridItem


class ScrollController:
    """武库网格滚动控制器。"""

    def __init__(self, hwnd: int, config: Optional[WukuConfig] = None):
        self.hwnd = hwnd
        self.cfg = config or WukuConfig()
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        # 已经出现过 item 的 key 集合
        self._seen_item_keys: Set[str] = set()
        # 连续多少页没有新 item
        self._no_new_count: int = 0

    def scroll_one_page(
        self, window_width: int, window_height: int, attach_thread: bool = True
    ) -> None:
        """滚动一屏（考虑重叠行）。"""
        # 计算需要滚动的行数
        rows_per_page = self._estimate_rows_per_page(window_height) - self.cfg.overlap_rows
        rows_per_page = max(1, rows_per_page)

        # 每次 scroll_delta 约移动 1 行，因此滚动行数次
        for _ in range(rows_per_page):
            self._send_wheel(
                self.cfg.scroll_delta, window_width, window_height, attach_thread=attach_thread
            )
            time.sleep(self.cfg.scroll_delay / rows_per_page)

    def is_at_bottom(self, items: List[GridItem]) -> bool:
        """根据当前页检测到的 item 判断是否已滚动到底部。

        逻辑：若当前页出现任何之前未见过的新 item，说明列表还在滚动；
        若连续多页都没有新 item 出现，则认为已经触底。

        注意：若当前页一个 item 都没检测到（OCR/检测失败），
        不应当作触底，否则检测异常会导致提前退出。
        """
        if not items:
            return False

        current_keys = {item.unique_key for item in items}
        new_keys = current_keys - self._seen_item_keys

        if new_keys:
            self._seen_item_keys.update(new_keys)
            self._no_new_count = 0
            return False

        self._no_new_count += 1
        return self._no_new_count >= self.cfg.bottom_no_new_items_count

    def reset(self) -> None:
        """重置触底检测状态。"""
        self._seen_item_keys.clear()
        self._no_new_count = 0

    def _estimate_rows_per_page(self, window_height: int) -> int:
        """估算当前窗口可视行数。"""
        row_height = int(self.cfg.item_cell_height * window_height)
        grid_height = int(self.cfg.grid_roi.height * window_height)
        return max(1, grid_height // row_height)

    def _send_wheel(
        self,
        delta: int,
        window_width: int,
        window_height: int,
        attach_thread: bool = True,
    ) -> None:
        """在网格中心位置发送滚轮事件。"""
        gx, gy, gw, gh = self.cfg.grid_roi.abs(window_width, window_height)
        client_x = gx + gw // 2
        client_y = gy + gh // 2

        point = ctypes.wintypes.POINT(client_x, client_y)
        self._user32.ClientToScreen(self.hwnd, ctypes.byref(point))

        v_left = self._user32.GetSystemMetrics(76)
        v_top = self._user32.GetSystemMetrics(77)
        v_width = self._user32.GetSystemMetrics(78)
        v_height = self._user32.GetSystemMetrics(79)
        nx = int((point.x - v_left) * 65535 / v_width)
        ny = int((point.y - v_top) * 65535 / v_height)

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT_I(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("ii", INPUT_I)]

        target_tid = self._user32.GetWindowThreadProcessId(self.hwnd, None)
        current_tid = self._kernel32.GetCurrentThreadId()
        attached = False

        try:
            if attach_thread and target_tid and current_tid != target_tid:
                self._user32.AttachThreadInput(current_tid, target_tid, True)
                attached = True

            # 将目标窗口带到前台，确保滚轮事件被该窗口接收
            self._user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.05)

            # 先移动鼠标到网格中心
            inp = INPUT()
            inp.type = 0
            inp.ii.mi = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000, 0, None)
            self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            time.sleep(0.05)

            # 发送滚轮事件
            inp2 = INPUT()
            inp2.type = 0
            inp2.ii.mi = MOUSEINPUT(0, 0, delta, 0x0800, 0, None)
            self._user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))
        finally:
            if attached:
                self._user32.AttachThreadInput(current_tid, target_tid, False)
