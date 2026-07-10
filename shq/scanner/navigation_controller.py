"""山河器界面导航控制器。

工作流：
1. 固定窗口客户区大小（默认 1334x750）。
2. 截图当前游戏界面。
3. OCR 识别右侧导航标签（搜寻、复归、灵鉴、武库）。
4. 根据识别结果计算标签中心坐标。
5. 点击目标标签（如武库）。
6. 循环验证，直到进入目标界面。

注意：
- 所有坐标均基于当前截图实时计算，不依赖硬编码坐标。
- 窗口大小被固定为基准分辨率后，OCR 区域可以稳定裁剪。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import cv2
import numpy as np

from shq.scanner.input_simulator import InputSimulator
from shq.scanner.ocr_scanner import EasyOCRBackend, OCRBackend, PlaceholderOCRBackend
from shq.scanner.window_capture import (
    DEFAULT_CLIENT_HEIGHT,
    DEFAULT_CLIENT_WIDTH,
    WindowCapture,
    capture_game_window,
)


NAV_LABELS = ("搜寻", "复归", "灵鉴", "武库")


@dataclass
class NavButton:
    """识别到的导航按钮。"""

    name: str
    center_x: int
    center_y: int
    confidence: float


class NavigationController:
    """山河器界面导航控制器。"""

    def __init__(
        self,
        ocr_backend: Optional[OCRBackend] = None,
        client_width: int = DEFAULT_CLIENT_WIDTH,
        client_height: int = DEFAULT_CLIENT_HEIGHT,
        attach_thread: bool = True,
    ):
        self.ocr = ocr_backend or PlaceholderOCRBackend()
        self.client_width = client_width
        self.client_height = client_height
        self._sim = InputSimulator(default_delay=0.8)
        self._cap: Optional[WindowCapture] = None
        self._attach_thread = attach_thread
        # 导航标签 y 轴偏移：截图坐标与实际可点击坐标之间的差值，自动校准
        self._nav_offset_y: Optional[int] = None

    def _get_window_capture(self) -> WindowCapture:
        """获取并缓存游戏窗口截图器。"""
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

    def ensure_fixed_size(self) -> bool:
        """尝试把窗口调整为基准大小；若游戏窗口拒绝 resize，则使用当前实际大小。

        后续所有 ROI 坐标都基于当前窗口实际大小按比例计算，不再依赖固定分辨率。
        """
        cap = self._get_window_capture()
        try:
            return cap.ensure_client_size(self.client_width, self.client_height)
        except Exception:
            return False

    def screenshot(self) -> np.ndarray:
        """截图并返回 BGR 图像。"""
        cap = self._get_window_capture()
        # 不再强制 resize：游戏窗口可能拒绝，直接用实际大小按比例算坐标
        img = cap.capture(bring_to_front=True)
        if img is None:
            raise RuntimeError("截图失败")
        return img

    def detect_nav_buttons(self, img: np.ndarray) -> List[NavButton]:
        """在当前截图中检测右侧导航按钮。

        策略：
        1. 裁剪右侧区域（约占宽度 82%~98%）。
        2. 用 OCR 识别文字并获取边界框。
        3. 归一化竖排文字（去掉空白、换行）。
        4. 匹配预设标签名，返回相对于原图的中心坐标。
        """
        h, w = img.shape[:2]
        # 右侧导航栏大致区域
        x1 = int(w * 0.82)
        x2 = w
        y1 = 0
        y2 = h
        right_region = img[y1:y2, x1:x2]

        results = self.ocr.recognize_with_boxes(right_region)
        buttons: List[NavButton] = []

        for result in results:
            text = self._normalize_label(result.text)
            if text not in NAV_LABELS:
                continue

            center = result.center
            if center is None:
                # 没有 bbox 时兜底估算
                center_x = x1 + (x2 - x1) // 2
                center_y = self._estimate_y_for_label(text, h)
            else:
                # right_region 中的坐标转换回原图坐标
                center_x = center[0] + x1
                center_y = center[1] + y1

            buttons.append(NavButton(text, center_x, center_y, result.confidence))

        return buttons

    @staticmethod
    def _normalize_label(text: str) -> str:
        """归一化 OCR 结果，去掉空格、换行、标点，只保留中文字符。"""
        chars = []
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                chars.append(ch)
        return "".join(chars)

    @staticmethod
    def _estimate_y_for_label(label: str, img_height: int) -> int:
        """根据标签顺序估算纵坐标（兜底策略）。"""
        positions = {
            "搜寻": 0.15,
            "复归": 0.35,
            "灵鉴": 0.55,
            "武库": 0.78,
        }
        return int(img_height * positions.get(label, 0.5))

    def click_button(self, name: str, max_retries: int = 3) -> bool:
        """点击指定名称的导航按钮。

        Args:
            name: 搜寻 / 复归 / 灵鉴 / 武库
            max_retries: 最大重试次数
        """
        if name not in NAV_LABELS:
            raise ValueError(f"未知导航标签：{name}")

        for attempt in range(max_retries):
            img = self.screenshot()
            buttons = self.detect_nav_buttons(img)
            targets = [b for b in buttons if b.name == name]

            if not targets:
                time.sleep(0.5)
                continue

            btn = max(targets, key=lambda b: b.confidence)
            self._click_nav_button(btn)
            print(f"已点击 [{name}]，坐标：({btn.center_x}, {btn.center_y})")
            return True

        return False

    def ensure_in_wuku(
        self, max_retries: int = 5, manual_fallback: bool = False
    ) -> bool:
        """确保当前在武库界面；若不在，点击武库标签。

        如果截图坐标与实际可点击区域存在纵向偏移，会自动校准。

        Args:
            max_retries: 自动点击最大重试次数。
            manual_fallback: 自动点击失败后是否提示用户手动点击并按回车继续。
        """
        for attempt in range(max_retries):
            img = self.screenshot()
            buttons = self.detect_nav_buttons(img)
            print(f"[调试] 识别到导航标签：{[(b.name, b.center_x, b.center_y, round(b.confidence, 2)) for b in buttons]}")
            wuku_buttons = [b for b in buttons if b.name == "武库"]

            if not wuku_buttons:
                print("[调试] 未识别到武库标签，等待重试...")
                time.sleep(0.5)
                continue

            wuku = max(wuku_buttons, key=lambda b: b.confidence)

            if self._is_in_wuku(img):
                print("当前已在武库界面")
                return True

            clicked_y = self._click_nav_button(wuku)
            time.sleep(0.8)

            # 点击后检测实际高亮了哪个标签，自动学习 y 偏移
            img = self.screenshot()
            selected = self._detect_selected_nav_label(img)
            if selected and selected != "武库":
                selected_btn = next((b for b in buttons if b.name == selected), None)
                if selected_btn is not None:
                    self._nav_offset_y = clicked_y - selected_btn.center_y
                    print(f"[调试] 检测到 y 偏移：{self._nav_offset_y}（实际点到 {selected}）")

        if manual_fallback:
            return self._manual_fallback_to_wuku()
        return False

    def _click_nav_button(self, btn: NavButton) -> int:
        """点击导航按钮，应用已校准的 y 偏移。

        返回实际点击的客户区 y 坐标。
        """
        cap = self._get_window_capture()
        click_y = btn.center_y
        if self._nav_offset_y is not None:
            click_y = btn.center_y + self._nav_offset_y
            print(f"[调试] 点击 {btn.name}：({btn.center_x}, {btn.center_y}) + 偏移 {self._nav_offset_y} -> ({btn.center_x}, {click_y})")
        else:
            print(f"[调试] 点击 {btn.name}：({btn.center_x}, {click_y})")
        self._sim.click_on_window(
            cap.hwnd, btn.center_x, click_y, attach_thread=self._attach_thread
        )
        return click_y

    def _manual_fallback_to_wuku(self) -> bool:
        """手动降级：提示用户手动点击武库标签后按回车继续。"""
        print("\n自动点击未生效，请手动在游戏窗口中点击【武库】标签。")
        print("点击完成后，回到本终端按回车键继续...")
        try:
            input()
        except EOFError:
            print("无法读取用户输入，手动降级失败")
            return False

        img = self.screenshot()
        if self._is_in_wuku(img):
            print("已确认进入武库界面")
            return True
        print("仍未检测到武库界面高亮，手动降级失败")
        return False

    def _detect_selected_nav_label(self, img: np.ndarray) -> Optional[str]:
        """通过右侧导航标签的高亮背景判断当前选中的标签。

        山河器右侧导航栏中，当前选中标签会有白色/浅色背景，未选中标签为透明暗底。
        对右侧导航栏 OCR 后，计算每个标签文字区域背景的平均亮度，最亮且明显高于
        其他的即为当前选中标签。
        """
        h, w = img.shape[:2]
        x1 = int(w * 0.82)
        right_region = img[0:h, x1:w]
        gray = cv2.cvtColor(right_region, cv2.COLOR_BGR2GRAY)

        results = self.ocr.recognize_with_boxes(right_region)
        candidates: List[Tuple[str, float]] = []
        for result in results:
            text = self._normalize_label(result.text)
            if text not in NAV_LABELS or not result.bbox:
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

        # 选中标签亮度需明显高于未选中标签；阈值根据 1334x750 截图标定。
        if top_brightness < 140 or top_brightness - second_brightness < 25:
            return None
        return selected

    def _is_in_wuku(self, img: np.ndarray) -> bool:
        """判断当前截图是否已在武库界面。

        通过右侧导航标签的高亮状态判断当前所在子界面。
        """
        return self._detect_selected_nav_label(img) == "武库"


def auto_navigate_to_wuku(ocr_backend: Optional[OCRBackend] = None) -> bool:
    """便捷函数：导航到武库界面。"""
    ctrl = NavigationController(ocr_backend=ocr_backend)
    return ctrl.ensure_in_wuku()
