"""山河器界面导航模块。

职责单一：根据外部传入的目标名称，OCR 识别右侧导航按钮的实际位置，点击并确认到达目标界面。
支持目标："搜寻"、"复归"、"灵鉴"、"武库"。

该模块不处理任何业务逻辑，只负责界面跳转。
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from shq.scanner.exceptions import ScanInterruptedError
from shq.scanner.input_simulator import InputSimulator
from shq.scanner.ocr_scanner import OCRBackend, PlaceholderOCRBackend
from shq.scanner.window_capture import (
    DEFAULT_CLIENT_HEIGHT,
    DEFAULT_CLIENT_WIDTH,
    WindowCapture,
    wait_for_stable,
)


NAV_TARGETS = {"搜寻", "复归", "灵鉴", "武库"}


class WukuNavigator:
    """山河器右侧导航控制器。"""

    def __init__(
        self,
        ocr_backend: Optional[OCRBackend] = None,
        attach_thread: bool = True,
        auto_resize: bool = True,
        stop_event: Optional[threading.Event] = None,
    ):
        self.backend = ocr_backend or PlaceholderOCRBackend()
        self._sim = InputSimulator(default_delay=0.5)
        self._attach_thread = attach_thread
        self._cap: Optional[WindowCapture] = None
        self._window_prepared = False
        self.auto_resize = auto_resize
        self.stop_event = stop_event

    # ------------------------------------------------------------------
    # 窗口 / 截图 / 点击
    # ------------------------------------------------------------------
    def _check_stopped(self) -> None:
        """若用户请求停止，则抛出 ScanInterruptedError。"""
        if self.stop_event is not None and self.stop_event.is_set():
            raise ScanInterruptedError()

    def _get_cap(self) -> WindowCapture:
        if self._cap is not None:
            return self._cap

        from shq.config import YMJH_PROCESS_RULE

        hwnd = None
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] and proc.info["name"].lower() in [
                    n.lower() for n in YMJH_PROCESS_RULE.get("names", [])
                ]:
                    hwnd = WindowCapture.find_by_pid(proc.info["pid"])
                    if hwnd:
                        break
        except Exception:
            pass

        if hwnd is None:
            for title in YMJH_PROCESS_RULE.get("window_titles", []):
                hwnd = WindowCapture.find_by_title(title)
                if hwnd:
                    break

        if hwnd is None:
            raise RuntimeError("未找到一梦江湖窗口")

        self._cap = WindowCapture(hwnd)
        return self._cap

    def _ensure_fixed_size(self) -> None:
        """确保窗口客户区为基准分辨率，避免缩放后 OCR/坐标失效。"""
        try:
            cap = self._get_cap()
            size = cap.get_client_size()
            if size == (DEFAULT_CLIENT_WIDTH, DEFAULT_CLIENT_HEIGHT):
                return
            if not self.auto_resize:
                print(
                    f"[警告] 游戏窗口客户区为 {size}，不是基准分辨率 "
                    f"{DEFAULT_CLIENT_WIDTH}x{DEFAULT_CLIENT_HEIGHT}，"
                    f"但已禁用自动调整，继续扫描可能导致坐标/OCR 偏差"
                )
                return
            ok = cap.resize_client(DEFAULT_CLIENT_WIDTH, DEFAULT_CLIENT_HEIGHT)
            if not ok:
                print(f"[警告] 无法固定窗口大小：resize_client 失败")
        except Exception as exc:
            print(f"[警告] 无法固定窗口大小：{exc}")

    def _bring_to_front(self, wait: float = 0.5) -> None:
        cap = self._get_cap()
        hwnd = cap.hwnd
        if hwnd is None:
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 已经是前台窗口时避免焦点切换和等待
        if hwnd == user32.GetForegroundWindow() and not user32.IsIconic(hwnd):
            return

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)

        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)

        attached = False
        try:
            if fg_tid and target_tid and fg_tid != target_tid:
                user32.AttachThreadInput(fg_tid, target_tid, True)
                attached = True
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.SwitchToThisWindow(hwnd, True)
        finally:
            if attached:
                user32.AttachThreadInput(fg_tid, target_tid, False)

        time.sleep(wait)

    def prepare(self) -> None:
        """扫描/导航前一次性准备：找窗口、调尺寸、置顶。"""
        self._get_cap()
        if not self._window_prepared:
            self._ensure_fixed_size()
            self._bring_to_front()
            self._window_prepared = True

    def _capture(self) -> np.ndarray:
        if not self._window_prepared:
            self._bring_to_front()
        cap = self._get_cap()
        img = cap.capture(bring_to_front=False)
        if img is None:
            raise RuntimeError("截图失败")
        return img

    def _click_client(self, cx: int, cy: int, delay: float = 1.0) -> None:
        if not self._window_prepared:
            self._bring_to_front()
        cap = self._get_cap()
        if cap.hwnd is None:
            raise RuntimeError("窗口句柄为空")
        self._sim.click_on_window(cap.hwnd, cx, cy, attach_thread=self._attach_thread)
        time.sleep(delay)

    def _wait_for_stable(
        self, timeout: float = 2.0, stable_frames: int = 2, threshold: float = 0.02
    ) -> bool:
        """等待游戏画面稳定，替代固定 time.sleep。等待期间也会检查是否停止。"""
        def _capture_and_check():
            self._check_stopped()
            return self._capture()

        return wait_for_stable(
            _capture_and_check,
            timeout=timeout,
            stable_frames=stable_frames,
            threshold=threshold,
        )

    def _click_and_wait_for_stable(
        self,
        cx: int,
        cy: int,
        max_wait: float = 1.2,
        stable_frames: int = 2,
    ) -> None:
        """点击后等待画面稳定，最大等待 max_wait 秒。"""
        if not self._window_prepared:
            self._bring_to_front()
        cap = self._get_cap()
        if cap.hwnd is None:
            raise RuntimeError("窗口句柄为空")
        self._sim.click_on_window(
            cap.hwnd, cx, cy, attach_thread=self._attach_thread, delay=0.05
        )
        self._wait_for_stable(timeout=max_wait, stable_frames=stable_frames)

    # ------------------------------------------------------------------
    # 导航核心
    # ------------------------------------------------------------------
    def navigate_to(self, target: str, max_retries: int = 5) -> bool:
        """OCR 识别右侧导航按钮并点击，直到确认到达 target 界面。

        Args:
            target: "搜寻" / "复归" / "灵鉴" / "武库"
            max_retries: 最大重试次数

        Returns:
            是否成功到达目标界面
        """
        if target not in NAV_TARGETS:
            raise ValueError(f"未知导航目标：{target}，可选：{sorted(NAV_TARGETS)}")

        # 导航前一次性准备窗口，避免扫描过程中反复置顶
        self.prepare()

        for attempt in range(max_retries):
            self._check_stopped()
            img = self._capture()
            if self._is_at(target, img):
                print(f"[导航] 已在 {target} 界面")
                return True

            buttons = self._detect_nav_buttons(img)
            if target not in buttons:
                print(f"[导航] 未识别到 {target} 按钮，等待重试")
                time.sleep(0.5)
                continue

            cx, cy = buttons[target]
            print(f"[导航] 点击 {target}：({cx}, {cy})")
            self._click_and_wait_for_stable(cx, cy, max_wait=1.2)

            img = self._capture()
            if self._is_at(target, img):
                print(f"[导航] 已切换到 {target} 界面")
                return True

        print(f"[导航] 无法到达 {target} 界面")
        return False

    def _detect_nav_buttons(self, img: np.ndarray) -> Dict[str, Tuple[int, int]]:
        """OCR 识别右侧导航栏按钮，返回 {名称: 中心坐标}。

        由于按钮是“图标 + 竖排文字”，文字在图标下方，这里返回文字 bbox 中心。
        如果实际可点击区域偏上，可在调用处根据文字位置向上微调。
        """
        h, w = img.shape[:2]
        # 右侧导航栏大致占窗口右侧 15%
        x1 = int(w * 0.80)
        right_region = img[0:h, x1:w]
        results = self.backend.recognize_with_boxes(right_region)

        buttons: Dict[str, Tuple[int, int]] = {}
        for r in results:
            text = self._normalize_label(r.text)
            if text not in NAV_TARGETS or not r.bbox:
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            cx = int(sum(xs) / len(xs)) + x1
            cy = int(sum(ys) / len(ys))
            # 同一标签可能出现多次（竖排被拆成多框），保留置信度最高的
            if text not in buttons or (r.confidence > 0.5):
                buttons[text] = (cx, cy)
        return buttons

    def _is_at(self, target: str, img: np.ndarray) -> bool:
        """判断当前截图是否位于 target 界面。"""
        if target == "武库":
            # 武库网格有左上角“全部”下拉；如果 OCR 没识别出来，再用右侧高亮标签兜底
            if self._has_all_dropdown(img):
                return True
            return self._detect_selected_label(img) == "武库"

        selected = self._detect_selected_label(img)
        return selected == target

    def _has_all_dropdown(self, img: np.ndarray) -> bool:
        """判断左上角是否出现武库网格的‘全部’下拉菜单。"""
        h, w = img.shape[:2]
        x1, x2 = int(w * 0.04), int(w * 0.18)
        y1, y2 = int(h * 0.10), int(h * 0.18)
        roi = img[y1:y2, x1:x2]
        texts = [self._normalize_label(t) for t, _ in self.backend.recognize(roi)]
        return "全部" in texts

    def _detect_selected_label(self, img: np.ndarray) -> Optional[str]:
        """通过右侧导航栏文字区域亮度判断当前高亮标签。"""
        h, w = img.shape[:2]
        x1 = int(w * 0.80)
        right_region = img[0:h, x1:w]
        if right_region.size == 0:
            return None

        gray = cv2.cvtColor(right_region, cv2.COLOR_BGR2GRAY)
        results = self.backend.recognize_with_boxes(right_region)
        candidates: List[Tuple[str, float]] = []

        for result in results:
            text = self._normalize_label(result.text)
            if text not in NAV_TARGETS or not result.bbox:
                continue

            xs = [int(p[0]) for p in result.bbox]
            ys = [int(p[1]) for p in result.bbox]
            bx1 = max(0, min(xs) - 5)
            bx2 = min(right_region.shape[1], max(xs) + 5)
            by1 = max(0, min(ys) - 5)
            by2 = min(right_region.shape[0], max(ys) + 5)
            brightness = float(gray[by1:by2, bx1:bx2].mean())
            candidates.append((text, brightness))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[1], reverse=True)
        selected, top_brightness = candidates[0]
        second_brightness = candidates[1][1] if len(candidates) > 1 else 0.0

        if top_brightness < 140 or top_brightness - second_brightness < 25:
            return None
        return selected

    @staticmethod
    def _normalize_label(text: str) -> str:
        """保留中文字符。"""
        return "".join(ch for ch in text if "一" <= ch <= "鿿")
