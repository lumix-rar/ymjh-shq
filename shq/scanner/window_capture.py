"""游戏窗口截图模块。

为 OCR 提供图像来源：
1. 通过进程/窗口标题定位一梦江湖窗口句柄。
2. 使用 Windows API 截取窗口客户区图像。
3. 返回 OpenCV 可用的 numpy 数组，便于后续裁剪与 OCR。

注意：
- 游戏窗口需在前台或可见；部分全屏/最小化窗口可能无法截取。
- 本模块仅用于截图，不涉及内存读取、注入或自动化点击。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2
import numpy as np


# 设置当前进程为 Per-monitor DPI 感知，确保坐标是物理像素
# 必须在创建任何窗口前调用
_dpi_set = False


def _ensure_dpi_aware() -> None:
    global _dpi_set
    if _dpi_set:
        return
    try:
        # Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PerMonitorDpiAware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _dpi_set = True


_ensure_dpi_aware()


# 默认固定客户区大小。后续 ROI 坐标均基于此分辨率标定。
DEFAULT_CLIENT_WIDTH = 1334
DEFAULT_CLIENT_HEIGHT = 750

# 虚拟屏幕指标（多显示器环境下确保窗口不超出屏幕）
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


@dataclass
class ROI:
    """图像中的感兴趣区域（相对窗口坐标）。"""

    name: str
    x: int
    y: int
    width: int
    height: int
    description: str = ""

    def crop(self, img: np.ndarray) -> np.ndarray:
        """从完整窗口图像中裁剪出 ROI。"""
        h, w = img.shape[:2]
        x1 = max(0, self.x)
        y1 = max(0, self.y)
        x2 = min(w, self.x + self.width)
        y2 = min(h, self.y + self.height)
        return img[y1:y2, x1:x2]


@dataclass
class WindowRect:
    """窗口矩形区域（屏幕坐标）。"""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class WindowCapture:
    """基于 Windows GDI 的窗口截图器。"""

    def __init__(self, hwnd: Optional[int] = None):
        self.hwnd = hwnd

    @classmethod
    def find_by_title(cls, title_substring: str) -> Optional[int]:
        """按窗口标题子串查找窗口句柄。"""
        result: list[int] = []
        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, _extra):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if title_substring in buffer.value:
                result.append(hwnd)
                return False  # 找到第一个就停止
            return True

        user32.EnumWindows(enum_callback, None)
        return result[0] if result else None

    @classmethod
    def find_by_pid(cls, pid: int) -> Optional[int]:
        """按进程 PID 查找主窗口句柄。"""
        result: list[int] = []
        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, _extra):
            if not user32.IsWindowVisible(hwnd):
                return True
            target_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
            if target_pid.value == pid:
                result.append(hwnd)
                return False
            return True

        user32.EnumWindows(enum_callback, None)
        return result[0] if result else None

    def get_window_rect(self) -> Optional[WindowRect]:
        """获取窗口整体矩形区域（含标题栏和边框）。"""
        if self.hwnd is None:
            return None
        rect = ctypes.wintypes.RECT()
        ok = ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        if not ok:
            return None
        return WindowRect(rect.left, rect.top, rect.right, rect.bottom)

    def get_rect(self) -> Optional[WindowRect]:
        """获取窗口客户区在屏幕上的矩形区域（不含标题栏和边框）。"""
        if self.hwnd is None:
            return None

        # 获取客户区大小（相对于窗口左上角）
        client_rect = ctypes.wintypes.RECT()
        ok = ctypes.windll.user32.GetClientRect(self.hwnd, ctypes.byref(client_rect))
        if not ok:
            return None

        # 将客户区左上角 (0,0) 转换为屏幕坐标
        point = ctypes.wintypes.POINT(0, 0)
        ok = ctypes.windll.user32.ClientToScreen(self.hwnd, ctypes.byref(point))
        if not ok:
            return None

        left = point.x
        top = point.y
        right = left + client_rect.right
        bottom = top + client_rect.bottom

        return WindowRect(left, top, right, bottom)

    def get_client_size(self) -> Optional[Tuple[int, int]]:
        """获取窗口客户区大小。"""
        rect = self.get_rect()
        if rect is None:
            return None
        return (rect.width, rect.height)

    def resize_client(self, client_width: int, client_height: int) -> bool:
        """调整窗口客户区大小。

        使用 AdjustWindowRectEx 根据客户区大小计算窗口整体大小，
        然后通过 SetWindowPos 设置。
        """
        if self.hwnd is None:
            return False

        user32 = ctypes.windll.user32
        win_rect = self.get_window_rect()
        if win_rect is None:
            return False

        GWL_STYLE = -16
        GWL_EXSTYLE = -20
        style = user32.GetWindowLongW(self.hwnd, GWL_STYLE)
        ex_style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)

        rect = ctypes.wintypes.RECT(0, 0, client_width, client_height)
        ok = user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, ex_style)
        if not ok:
            return False

        window_width = rect.right - rect.left
        window_height = rect.bottom - rect.top

        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        left = win_rect.left
        top = win_rect.top
        right = left + window_width
        bottom = top + window_height

        # 获取虚拟屏幕边界，确保调整后的窗口不会跑到屏幕外，
        # 否则后续 ClientToScreen + SendInput 的坐标会超出虚拟屏幕，鼠标不会移动。
        v_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        v_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        v_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        v_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        v_right = v_left + v_width
        v_bottom = v_top + v_height

        if right > v_right:
            left -= right - v_right
        if bottom > v_bottom:
            top -= bottom - v_bottom
        if left < v_left:
            left = v_left
        if top < v_top:
            top = v_top

        ok = user32.SetWindowPos(
            self.hwnd,
            0,
            left,
            top,
            window_width,
            window_height,
            SWP_NOZORDER | SWP_FRAMECHANGED,
        )
        if not ok:
            return False

        # 等待窗口重绘
        time.sleep(0.3)
        return True

    def ensure_client_size(
        self,
        client_width: int = DEFAULT_CLIENT_WIDTH,
        client_height: int = DEFAULT_CLIENT_HEIGHT,
    ) -> bool:
        """确保窗口客户区为指定大小且完全在虚拟屏幕内。"""
        size = self.get_client_size()
        if size is None:
            return False
        current_w, current_h = size
        if current_w == client_width and current_h == client_height:
            # 大小正确时也要确保窗口在屏幕内，否则点击坐标会超出虚拟屏幕
            return self.ensure_on_screen()
        return self.resize_client(client_width, client_height)

    def ensure_on_screen(self) -> bool:
        """若窗口客户区超出虚拟屏幕，则将其移动到屏幕内。"""
        if self.hwnd is None:
            return False

        rect = self.get_rect()
        if rect is None:
            return False

        user32 = ctypes.windll.user32
        v_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        v_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        v_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        v_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        v_right = v_left + v_width
        v_bottom = v_top + v_height

        # 窗口整体矩形（含标题栏边框）
        win_rect = self.get_window_rect()
        if win_rect is None:
            return False

        new_left = win_rect.left
        new_top = win_rect.top

        # 客户区右侧/下侧超出屏幕：向左/上移动
        if rect.right > v_right:
            new_left -= rect.right - v_right
        if rect.bottom > v_bottom:
            new_top -= rect.bottom - v_bottom
        if new_left < v_left:
            new_left = v_left
        if new_top < v_top:
            new_top = v_top

        # 如果已经在屏幕内，无需移动
        if new_left == win_rect.left and new_top == win_rect.top:
            return True

        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        ok = user32.SetWindowPos(
            self.hwnd,
            0,
            new_left,
            new_top,
            win_rect.width,
            win_rect.height,
            SWP_NOZORDER | SWP_FRAMECHANGED,
        )
        time.sleep(0.2)
        return bool(ok)

    def bring_to_front(self, wait: float = 0.5) -> bool:
        """将窗口带到前台并等待其渲染。

        Windows 限制非前台进程调用 SetForegroundWindow。这里使用
        AttachThreadInput 把当前前台线程的输入队列临时挂接到目标窗口线程，
        从而获得 SetForegroundWindow 权限，比模拟 Alt 键更可靠。
        """
        if self.hwnd is None:
            return False
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 如果窗口最小化，先恢复
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE

        # 通过 AttachThreadInput 获取 SetForegroundWindow 权限
        target_tid = user32.GetWindowThreadProcessId(self.hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)

        attached = False
        try:
            if foreground_tid and target_tid and foreground_tid != target_tid:
                user32.AttachThreadInput(foreground_tid, target_tid, True)
                attached = True

            ok = user32.SetForegroundWindow(self.hwnd)
            if not ok:
                # 兜底：模拟 Alt 键尝试获得权限
                VK_MENU = 0x12
                user32.keybd_event(VK_MENU, 0, 0, 0)
                user32.keybd_event(VK_MENU, 0, 2, 0)
                user32.SetForegroundWindow(self.hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(foreground_tid, target_tid, False)

        time.sleep(wait)
        return True

    def capture(self, bring_to_front: bool = True) -> Optional[np.ndarray]:
        """截取窗口并返回 BGR 格式的 numpy 数组。

        Args:
            bring_to_front: 截图前是否将窗口切换到前台。

        Returns:
            OpenCV 格式的图像数组（H, W, 3），失败返回 None。
        """
        if self.hwnd is None:
            return None

        rect = self.get_rect()
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return None

        if bring_to_front:
            self.bring_to_front(wait=0.5)
            # 窗口移动后重新获取矩形
            rect = self.get_rect()
            if rect is None or rect.width <= 0 or rect.height <= 0:
                return None

        # 对游戏类 DirectX 窗口，GDI 方式通常黑屏：
        # 1. 优先尝试基于 DXGI Desktop Duplication 的 mss（对全屏/无边框游戏更友好）
        # 2. 其次使用 ImageGrab 截取屏幕区域
        # 3. 最后 fallback 到 GDI
        img = self._capture_with_mss(rect)
        if img is not None and img.mean() > 1.0:
            return img

        img = self._capture_with_image_grab(rect)
        if img is not None and img.mean() > 1.0:
            return img

        # fallback：GDI 方式（BitBlt + PrintWindow），对被遮挡窗口可能有效
        return self._capture_with_gdi(rect)

    def _capture_with_gdi(self, rect: WindowRect) -> Optional[np.ndarray]:
        """使用 GDI BitBlt/PrintWindow 截取窗口。"""
        hwnd_dc = ctypes.windll.user32.GetWindowDC(self.hwnd)
        if not hwnd_dc:
            return None

        try:
            mfc_dc = ctypes.windll.gdi32.CreateCompatibleDC(hwnd_dc)
            save_bitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(
                hwnd_dc, rect.width, rect.height
            )
            ctypes.windll.gdi32.SelectObject(mfc_dc, save_bitmap)

            SRCCOPY = 0x00CC0020
            ctypes.windll.gdi32.BitBlt(
                mfc_dc, 0, 0, rect.width, rect.height, hwnd_dc, 0, 0, SRCCOPY
            )
            PW_RENDERFULLCONTENT = 0x00000002
            ctypes.windll.user32.PrintWindow(self.hwnd, mfc_dc, PW_RENDERFULLCONTENT)

            bmi = ctypes.create_string_buffer(40)
            ctypes.memset(bmi, 0, 40)
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint32))[0] = 40
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[1] = rect.width
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[2] = -rect.height
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[7] = 1
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[8] = 24

            buffer_len = rect.width * rect.height * 3
            buffer = ctypes.create_string_buffer(buffer_len)
            ctypes.windll.gdi32.GetDIBits(
                mfc_dc, save_bitmap, 0, rect.height, buffer, bmi, 0
            )

            img = np.frombuffer(buffer, dtype=np.uint8).reshape(
                rect.height, rect.width, 3
            )
            return img.copy()
        finally:
            ctypes.windll.gdi32.DeleteObject(save_bitmap)
            ctypes.windll.gdi32.DeleteDC(mfc_dc)
            ctypes.windll.user32.ReleaseDC(self.hwnd, hwnd_dc)

    def save(self, path: str | Path) -> bool:
        """截图并保存到文件。"""
        img = self.capture()
        if img is None:
            return False
        return cv2.imwrite(str(path), img)

    def capture_roi(self, roi: ROI) -> Optional[np.ndarray]:
        """截取窗口客户区中的指定 ROI 区域（屏幕绝对坐标）。

        相比 capture() 全屏截图，可减少 GPU 回读数据量，适合高频局部 OCR。
        """
        if self.hwnd is None:
            return None
        rect = self.get_rect()
        if rect is None:
            return None

        left = rect.left + roi.x
        top = rect.top + roi.y
        right = left + roi.width
        bottom = top + roi.height

        # 限制在客户区内
        right = min(right, rect.right)
        bottom = min(bottom, rect.bottom)
        if right <= left or bottom <= top:
            return None

        try:
            from PIL import ImageGrab
        except ImportError as e:
            raise RuntimeError(
                "Pillow 未安装，无法使用屏幕截图 fallback。请运行：pip install pillow"
            ) from e

        try:
            screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise RuntimeError(f"ImageGrab 截图失败：{e}") from e

    @staticmethod
    def _is_black(mfc_dc, bitmap, rect: WindowRect) -> bool:
        """简单判断截图是否全黑。"""
        try:
            # 构造 BITMAPINFO
            bmi = ctypes.create_string_buffer(40)
            ctypes.memset(bmi, 0, 40)
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint32))[0] = 40
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[1] = 1
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_int32))[2] = -1
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[7] = 1
            ctypes.cast(bmi, ctypes.POINTER(ctypes.c_uint16))[8] = 24
            buffer = ctypes.create_string_buffer(3)
            ctypes.windll.gdi32.GetDIBits(mfc_dc, bitmap, 0, 1, buffer, bmi, 0)
            return buffer == b"\x00\x00\x00"
        except Exception:
            return False

    def _capture_with_mss(self, rect: WindowRect) -> Optional[np.ndarray]:
        """使用 mss 通过 DXGI Desktop Duplication 截取屏幕区域。

        mss 对全屏/无边框 DirectX 游戏的干扰比 ImageGrab 更小，
        且能避免部分 GDI 黑屏问题。若未安装则返回 None。
        """
        try:
            import mss
            import mss.tools
        except ImportError:
            return None

        try:
            with mss.mss() as sct:
                monitor = {
                    "left": rect.left,
                    "top": rect.top,
                    "width": rect.width,
                    "height": rect.height,
                }
                screenshot = sct.grab(monitor)
                # mss.grab 返回 BGRA 格式
                img = np.array(screenshot)
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def _capture_with_image_grab(self, rect: WindowRect) -> Optional[np.ndarray]:
        """使用 Pillow ImageGrab 截取屏幕区域（对 DirectX 游戏通常有效）。"""
        try:
            from PIL import ImageGrab
        except ImportError as e:
            raise RuntimeError(
                "Pillow 未安装，无法使用屏幕截图 fallback。请运行：pip install pillow"
            ) from e

        try:
            screenshot = ImageGrab.grab(
                bbox=(rect.left, rect.top, rect.right, rect.bottom)
            )
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise RuntimeError(f"ImageGrab 截图失败：{e}") from e


def capture_game_window(
    bring_to_front: bool = True,
    fixed_size: bool = True,
) -> Optional[np.ndarray]:
    """便捷函数：自动查找一梦江湖窗口并截图。

    Args:
        bring_to_front: 截图前是否将窗口切换到前台。
        fixed_size: 是否强制调整窗口为默认客户区大小。
    """
    from shq.config import YMJH_PROCESS_RULE

    # 优先按进程 PID 查找（比标题更可靠，避免匹配浏览器标签页等）
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"] and proc.info["name"].lower() in [
                n.lower() for n in YMJH_PROCESS_RULE.get("names", [])
            ]:
                hwnd = WindowCapture.find_by_pid(proc.info["pid"])
                if hwnd:
                    cap = WindowCapture(hwnd)
                    if fixed_size:
                        cap.ensure_client_size()
                    return cap.capture(bring_to_front=bring_to_front)
    except Exception:
        pass

    # 退而按窗口标题查找
    for title in YMJH_PROCESS_RULE.get("window_titles", []):
        hwnd = WindowCapture.find_by_title(title)
        if hwnd:
            cap = WindowCapture(hwnd)
            if fixed_size:
                cap.ensure_client_size()
            return cap.capture(bring_to_front=bring_to_front)

    return None


def frames_changed(
    a: np.ndarray, b: np.ndarray, threshold: float = 0.02, min_diff: int = 15
) -> bool:
    """判断两帧是否发生显著变化。

    Args:
        a, b: BGR 图像数组，形状需一致。
        threshold: 变化像素占比超过该阈值视为有变化。
        min_diff: 单像素灰度差超过该值才计入变化。

    Returns:
        True 表示两帧差异显著。
    """
    if a is None or b is None or a.shape != b.shape:
        return True
    gray_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)
    _, diff_bin = cv2.threshold(diff, min_diff, 255, cv2.THRESH_BINARY)
    changed_ratio = float(np.count_nonzero(diff_bin)) / diff_bin.size
    return changed_ratio > threshold


def wait_for_stable(
    capture_func: Callable[[], np.ndarray],
    timeout: float = 2.0,
    poll_interval: float = 0.05,
    stable_frames: int = 2,
    threshold: float = 0.02,
) -> bool:
    """轮询截图，等待画面稳定（连续 stable_frames 帧变化小于阈值）。

    Args:
        capture_func: 无参函数，返回 BGR 图像数组。
        timeout: 最长等待时间（秒）。
        poll_interval: 每次截图间隔（秒）。
        stable_frames: 连续多少帧差异小于阈值才认为稳定。
        threshold: 变化像素占比阈值。

    Returns:
        True 表示在超时前已稳定，False 表示超时。
    """
    import time

    start = time.monotonic()
    prev = capture_func()
    stable = 0
    while time.monotonic() - start < timeout:
        time.sleep(poll_interval)
        current = capture_func()
        if frames_changed(prev, current, threshold=threshold):
            stable = 0
        else:
            stable += 1
            if stable >= stable_frames:
                return True
        prev = current
    return False
