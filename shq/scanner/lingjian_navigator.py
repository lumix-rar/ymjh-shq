"""灵鉴界面导航模块。

继承 WukuNavigator 以复用窗口前置、截图、点击、右侧导航到「灵鉴」的能力，
并新增：
- 左侧区域下拉选择框的展开与选择；
- 未解锁区域检测（基于「未解锁」文字）；
- 「孔位培养」按钮点击与面板开关检测；
- 基于校准坐标的快速点击（若校准缺失则回退到 OCR 探测）。
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from shq.scanner.ocr_scanner import OCRBackend, OCRResult, PlaceholderOCRBackend
from shq.scanner.topology_loader import RegionCalibration, Topology
from shq.scanner.wuku_navigator import WukuNavigator


# 左侧区域选择器/下拉框大致占窗口左部 0~30%
LEFT_SIDEBAR_X_RATIO = 0.30
# 下拉框收起时只显示当前选中的区域名，y 范围需避开顶部「山河器」标题（约 y=0~60）
DROPDOWN_Y_START = 70
DROPDOWN_CLOSED_Y_END = 160
# 下拉框展开后可滚动区域
DROPDOWN_EXPANDED_Y_START = 110
DROPDOWN_EXPANDED_Y_END = 360

# 主面板区域，用于探测顶部「孔位培养」标签与未解锁提示
# 注意：标签位于主面板顶部偏右，需把 x 右边界扩展到 0.95
MAIN_PANEL_X_RATIO = 0.25
MAIN_PANEL_X_END_RATIO = 0.96

# Win32 滚轮事件常量
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

# 已知灵鉴区域名（拓扑中的顺序即下拉列表中的顺序）
KNOWN_REGIONS = [
    "驿寄梅花",
    "戍客怀归",
    "长烟烽火",
    "黄泉夜渡",
    "关河道远",
    "骸关断云",
]


class LingjianNavigator(WukuNavigator):
    """灵鉴页面导航控制器。"""

    def __init__(
        self,
        topology: Optional[Topology] = None,
        ocr_backend: Optional[OCRBackend] = None,
        attach_thread: bool = True,
        auto_resize: bool = True,
        stop_event: Optional[threading.Event] = None,
    ):
        super().__init__(
            ocr_backend=ocr_backend,
            attach_thread=attach_thread,
            auto_resize=auto_resize,
            stop_event=stop_event,
        )
        self.topology = topology

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def navigate_to_lingjian(self, max_retries: int = 5) -> bool:
        """导航到灵鉴界面。"""
        return self.navigate_to("灵鉴", max_retries=max_retries)

    def capture(self) -> np.ndarray:
        """截取当前游戏窗口（公开包装）。"""
        return self._capture()

    # ------------------------------------------------------------------
    # 左侧区域下拉选择器
    # ------------------------------------------------------------------
    def detect_region_buttons(
        self,
        img: np.ndarray,
        expanded: bool = False,
    ) -> Dict[str, Tuple[int, int]]:
        """OCR 识别左侧区域选择器中的区域名，返回 {区域名: 中心坐标}。

        Args:
            img: 窗口截图。
            expanded: 是否按展开后的下拉列表区域识别。收起时只显示当前选中项。
        """
        h, w = img.shape[:2]
        x2 = int(w * LEFT_SIDEBAR_X_RATIO)
        y1 = int(DROPDOWN_Y_START)
        y2 = h if expanded else int(DROPDOWN_CLOSED_Y_END)
        left_region = img[y1:y2, 0:x2]
        results = self.backend.recognize_with_boxes(left_region)

        candidates: Dict[str, Tuple[int, int, float]] = {}
        for r in results:
            text = self._normalize_region_name(r.text)
            if not text or not r.bbox:
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys)) + y1
            conf = r.confidence or 0.0
            if text not in candidates or candidates[text][2] < conf:
                candidates[text] = (cx, cy, conf)

        return {name: (cx, cy) for name, (cx, cy, _) in candidates.items()}

    def detect_current_region(self, img: np.ndarray) -> Optional[str]:
        """识别当前下拉框中显示/高亮的区域名。

        收起状态下通常只有当前区域名可见；展开状态下取最上方（y 最小）的区域名。
        """
        buttons = self.detect_region_buttons(img, expanded=False)
        if not buttons:
            return None
        # 取 y 坐标最小的（最上方）作为当前显示项
        return min(buttons.items(), key=lambda item: item[1][1])[0]

    def open_region_dropdown(self) -> bool:
        """点击当前显示的区域名，展开下拉选择框。"""
        img = self._capture()
        current = self.detect_current_region(img)
        if current is None:
            # 未识别到区域名，使用左侧固定坐标兜底点击
            cap = self._get_cap()
            size = cap.get_client_size() or (1334, 750)
            cx, cy = int(size[0] * 0.10), int(size[1] * 0.20)
        else:
            cx, cy = self.detect_region_buttons(img, expanded=False)[current]

        print(f"[灵鉴导航] 点击区域下拉框（当前：{current}）：({cx}, {cy})")
        self._click_and_wait_for_stable(cx, cy, max_wait=0.8)
        return True

    def select_region(
        self,
        region_name: str,
        calibration: Optional[RegionCalibration] = None,
        max_retries: int = 3,
    ) -> bool:
        """展开左侧区域下拉框并选择目标区域。

        流程：
        1. 若当前已显示目标区域，直接通过；
        2. 点击下拉框展开；
        3. 在展开列表中滚动查找目标区域；
        4. 点击目标区域并验证主面板已切换。

        若滚动后仍找不到目标区域，判定为账号未解锁，返回 False。
        """
        calibrated = calibration.list_button if calibration else None
        order = self._get_region_order()

        for attempt in range(max_retries):
            self._check_stopped()
            img = self._capture()
            current = self.detect_current_region(img)

            # 已经是要选的目标
            if current == region_name:
                if self._verify_region_selected(img, region_name):
                    print(f"[灵鉴导航] 已在区域 {region_name}")
                    return True

            # 展开下拉框
            if calibrated and attempt == 0:
                cx, cy = calibrated
                print(f"[灵鉴导航] 使用校准坐标点击区域下拉框：({cx}, {cy})")
                self._click_and_wait_for_stable(cx, cy, max_wait=0.8)
            else:
                self.open_region_dropdown()

            # 在展开列表中查找目标，必要时滚动
            found = self._find_region_in_dropdown(region_name, order, max_scrolls=6)
            if not found:
                print(f"[灵鉴导航] 滚动后仍未找到 {region_name}，判定为未解锁")
                return False

            cx, cy = found
            print(f"[灵鉴导航] 点击区域 {region_name}：({cx}, {cy})")
            self._click_and_wait_for_stable(cx, cy, max_wait=1.0)

            img = self._capture()
            if self._verify_region_selected(img, region_name):
                print(f"[灵鉴导航] 已切换到 {region_name}")
                return True

        print(f"[灵鉴导航] 无法切换到区域 {region_name}")
        return False

    def _get_region_order(self) -> List[str]:
        """返回拓扑中定义的区域顺序（下拉列表中的顺序）。"""
        if self.topology is not None:
            return [r.name for r in self.topology.lingjian.regions]
        return list(KNOWN_REGIONS)

    def _find_region_in_dropdown(
        self,
        region_name: str,
        order: List[str],
        max_scrolls: int = 6,
    ) -> Optional[Tuple[int, int]]:
        """在展开的下拉列表中查找目标区域，支持滚动。

        返回目标区域的中心坐标；若找不到则返回 None。
        """
        target_idx = order.index(region_name) if region_name in order else -1

        for scroll in range(max_scrolls + 1):
            self._check_stopped()
            img = self._capture()
            buttons = self.detect_region_buttons(img, expanded=True)

            if region_name in buttons:
                return buttons[region_name]

            if target_idx < 0 or not buttons:
                # 无法判断方向，向下滚动试试
                self._scroll_dropdown(-1)
                continue

            visible_indices = [
                order.index(name)
                for name in buttons.keys()
                if name in order
            ]
            if not visible_indices:
                self._scroll_dropdown(-1)
                continue

            min_visible = min(visible_indices)
            max_visible = max(visible_indices)

            if target_idx < min_visible:
                # 目标在可见区域上方，向上滚动内容以显示上方
                self._scroll_dropdown(1)
            elif target_idx > max_visible:
                # 目标在可见区域下方，向下滚动内容以显示下方
                self._scroll_dropdown(-1)
            else:
                # 目标理论上应在可见区域之间但未识别到，可能是 OCR 问题
                # 再滚动一次后放弃
                self._scroll_dropdown(-1)

        return None

    def _scroll_dropdown(self, direction: int, clicks: int = 6) -> None:
        """在左侧下拉列表区域滚动。

        Args:
            direction: -1 向下滚动内容（显示列表下方区域），
                       1 向上滚动内容（显示列表上方区域）。
            clicks: 滚轮事件次数。
        """
        cap = self._get_cap()
        size = cap.get_client_size() or (1334, 750)
        w, h = size
        # 滚动条/列表区域在左侧，x 取 0.15w 较合适
        cx = int(w * 0.15)
        cy = (DROPDOWN_EXPANDED_Y_START + DROPDOWN_EXPANDED_Y_END) // 2

        rect = cap.get_rect()
        if rect is not None:
            screen_x = rect.left + cx
            screen_y = rect.top + cy
        else:
            screen_x, screen_y = cx, cy

        self._sim.move_to(screen_x, screen_y)
        time.sleep(0.1)

        delta = WHEEL_DELTA * direction
        user32 = ctypes.windll.user32
        for _ in range(clicks):
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(0.05)
        self._wait_for_stable(timeout=0.5, stable_frames=1)

    def is_region_locked(self, img: np.ndarray) -> bool:
        """检测当前区域是否未解锁。

        仅依据界面中是否出现「未解锁」文字；不再因找不到「孔位培养」按钮就判定锁定。
        """
        h, w = img.shape[:2]

        # 左侧下拉区域
        left = img[0:h, 0:int(w * LEFT_SIDEBAR_X_RATIO)]
        left_texts = [self._normalize_label(t) for t, _ in self.backend.recognize(left)]
        if "未解锁" in left_texts:
            return True

        # 主面板
        main = img[0:h, int(w * MAIN_PANEL_X_RATIO):int(w * MAIN_PANEL_X_END_RATIO)]
        main_texts = [self._normalize_label(t) for t, _ in self.backend.recognize(main)]
        if "未解锁" in main_texts:
            return True

        return False

    # ------------------------------------------------------------------
    # 孔位培养面板
    # ------------------------------------------------------------------
    def click_cultivation_button(
        self,
        calibration: Optional[RegionCalibration] = None,
        max_retries: int = 3,
    ) -> bool:
        """点击「孔位培养」标签页。"""
        calibrated = calibration.cultivation_button if calibration else None

        for attempt in range(max_retries):
            self._check_stopped()
            img = self._capture()
            button = self._find_cultivation_button(img, calibrated)
            if button is None:
                # 找不到按钮时，若已经在孔位培养标签页也视为成功
                if self.is_cultivation_panel_open(img):
                    print("[灵鉴导航] 已在「孔位培养」标签页")
                    return True
                print(f"[灵鉴导航] 未找到「孔位培养」按钮，重试 {attempt + 1}/{max_retries}")
                time.sleep(0.5)
                continue

            cx, cy = button
            print(f"[灵鉴导航] 点击「孔位培养」：({cx}, {cy})")
            self._click_and_wait_for_stable(cx, cy, max_wait=1.0)
            print("[灵鉴导航] 已切换到「孔位培养」标签页")
            return True

        print("[灵鉴导航] 无法打开孔位培养面板")
        return False

    def is_cultivation_panel_open(self, img: np.ndarray) -> bool:
        """判断当前是否处于「孔位培养」标签页。

        依据：主面板区域出现「孔位培养」且同时出现孔位详情相关文字
        （如「壹孔」「下阶预览」「评分提升」等）。
        """
        h, w = img.shape[:2]
        roi = self._get_panel_roi(img)
        if roi is not None:
            panel = roi.crop(img)
        else:
            x1 = int(w * MAIN_PANEL_X_RATIO)
            x2 = int(w * MAIN_PANEL_X_END_RATIO)
            panel = img[0:h, x1:x2]

        texts = [self._normalize_label(t) for t, _ in self.backend.recognize(panel)]
        has_cultivation = any("孔位培养" in t for t in texts)
        has_detail = any(
            kw in t for t in texts for kw in ("壹孔", "下阶预览", "评分提升", "孔位评分")
        )
        return has_cultivation and has_detail

    def close_cultivation_panel(self) -> None:
        """点击面板外区域或空白处关闭培养面板。"""
        cap = self._get_cap()
        size = cap.get_client_size()
        if size is None:
            cx, cy = 160, 480
        else:
            cx, cy = int(size[0] * 0.12), int(size[1] * 0.65)
        self._click_and_wait_for_stable(cx, cy, max_wait=0.6)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _find_cultivation_button(
        self,
        img: np.ndarray,
        calibrated: Optional[Tuple[int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """在主面板中查找「孔位培养」按钮中心坐标。"""
        if calibrated is not None:
            return calibrated

        h, w = img.shape[:2]
        x1 = int(w * MAIN_PANEL_X_RATIO)
        x2 = int(w * MAIN_PANEL_X_END_RATIO)
        main = img[0:h, x1:x2]
        results = self.backend.recognize_with_boxes(main)

        for r in results:
            text = self._normalize_label(r.text)
            if "孔位培养" in text and r.bbox:
                xs = [p[0] for p in r.bbox]
                ys = [p[1] for p in r.bbox]
                cx = int(sum(xs) / len(xs)) + x1
                cy = int(sum(ys) / len(ys))
                return cx, cy
        return None

    def _get_panel_roi(self, img: np.ndarray):
        """获取当前区域的面板 ROI（优先使用拓扑校准）。"""
        if self.topology is None:
            return None
        for rc in self.topology.region_calibrations.values():
            if rc.panel_roi is not None:
                return rc.panel_roi
        return None

    def _verify_region_selected(
        self, img: np.ndarray, region_name: str
    ) -> bool:
        """验证当前是否已切换到目标区域。

        方法：
        1. 下拉框当前显示为目标区域名；
        2. 或主面板顶部出现区域名关键字。
        任一成立即通过。
        """
        current = self.detect_current_region(img)
        if current == region_name:
            return True

        h, w = img.shape[:2]
        top = img[0:int(h * 0.25), int(w * MAIN_PANEL_X_RATIO):int(w * MAIN_PANEL_X_END_RATIO)]
        texts = [self._normalize_label(t) for t, _ in self.backend.recognize(top)]
        return any(region_name in t for t in texts)

    @staticmethod
    def _normalize_region_name(text: str) -> str:
        """保留中文字符并模糊匹配已知的 6 个区域名。"""
        import difflib

        cleaned = "".join(ch for ch in text if "一" <= ch <= "鿿")
        if not cleaned:
            return ""

        # 优先精确子串匹配
        for name in KNOWN_REGIONS:
            if name in cleaned or cleaned in name:
                return name

        # 模糊匹配，阈值 0.5
        matches = difflib.get_close_matches(
            cleaned, KNOWN_REGIONS, n=1, cutoff=0.5
        )
        if matches:
            return matches[0]
        return cleaned

    @staticmethod
    def _normalize_label(text: str) -> str:
        """保留中文字符、数字与常用符号。"""
        return "".join(
            ch
            for ch in text
            if ("一" <= ch <= "鿿") or ch.isdigit() or ch in "+-×÷"
        )
