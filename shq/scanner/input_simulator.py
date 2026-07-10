"""Windows 输入模拟：基于坐标的鼠标点击与键盘事件。

⚠️ 风险提示：
- 自动化点击/按键可能违反《一梦江湖》用户协议，存在封号风险。
- 本模块仅作为技术实现提供，默认不启用；是否使用由用户自行决定并承担责任。
- 建议优先使用手动点击 + 截图的方式完成数据采集。

实现说明：
- 使用 Windows `SendInput` API 发送硬件级输入事件。
- 支持屏幕绝对坐标点击和窗口客户区相对坐标点击。
- 点击后会短暂等待，确保游戏界面完成响应。
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from typing import Optional, Tuple


# INPUT 结构体相关常量
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Mouse event flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# 屏幕坐标归一化到 0..65535
SCREEN_NORMALIZE = 65535.0

# 虚拟屏幕指标（多显示器环境下 SendInput 绝对坐标需基于虚拟桌面）
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_I(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _INPUT_I)]


@dataclass
class Point:
    """屏幕或窗口坐标点。"""

    x: int
    y: int


class InputSimulator:
    """Windows 输入模拟器。"""

    def __init__(self, default_delay: float = 0.5):
        self.default_delay = default_delay
        self._user32 = ctypes.windll.user32
        # None 表示尚未确定当前环境 SendInput 是否可用；True/False 为缓存结果
        self._send_input_works: Optional[bool] = None

    def move_to(self, x: int, y: int) -> None:
        """移动鼠标到屏幕绝对坐标。

        注意：多显示器环境下需基于虚拟屏幕（virtual screen）归一化，
        否则坐标会偏移到错误的显示器。
        """
        self._move_to_with_fallback(x, y)

    def _move_to_with_fallback(self, x: int, y: int) -> None:
        """移动鼠标，若 SendInput 未生效则回退到 SetCursorPos + mouse_event。"""
        v_left = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        v_top = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        v_width = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        v_height = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        nx = int((x - v_left) * SCREEN_NORMALIZE / v_width)
        ny = int((y - v_top) * SCREEN_NORMALIZE / v_height)

        # 如果已知 SendInput 失效，直接走回退方案
        if self._send_input_works is False:
            self._user32.SetCursorPos(x, y)
            self._user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny, 0, 0)
            return

        # 尝试 SendInput
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.ii.mi = _MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)
        self._send_input(inp)

        # 简单校验：如果光标没动，回退到 SetCursorPos + mouse_event
        time.sleep(0.02)
        pt = ctypes.wintypes.POINT()
        if self._user32.GetCursorPos(ctypes.byref(pt)):
            if abs(pt.x - x) <= 3 and abs(pt.y - y) <= 3:
                self._send_input_works = True
                return

        self._send_input_works = False
        # 回退方案
        self._user32.SetCursorPos(x, y)
        self._user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny, 0, 0)

    def click(self, x: int, y: int, button: str = "left", delay: Optional[float] = None) -> None:
        """在屏幕绝对坐标点击一次。

        Args:
            x, y: 屏幕绝对坐标（物理像素）。
            button: left / right。
            delay: 点击后等待时间，默认使用构造时的 default_delay。
        """
        self._move_to_with_fallback(x, y)
        time.sleep(0.05)

        if button == "left":
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP
        elif button == "right":
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        else:
            raise ValueError(f"不支持的鼠标按钮：{button}")

        self._mouse_event(down_flag)
        time.sleep(0.05)
        self._mouse_event(up_flag)

        time.sleep(delay if delay is not None else self.default_delay)

    def click_on_window(
        self,
        hwnd: int,
        client_x: int,
        client_y: int,
        button: str = "left",
        delay: Optional[float] = None,
        attach_thread: bool = False,
    ) -> None:
        """在窗口客户区相对坐标点击。

        Args:
            hwnd: 目标窗口句柄。
            client_x, client_y: 相对于窗口客户区左上角的坐标。
            button: left / right。
            delay: 点击后等待时间。
            attach_thread: 是否通过 AttachThreadInput 把当前线程输入队列
                临时挂接到目标窗口线程。某些受保护窗口（如 Messiah 引擎游戏）
                在非管理员环境下可能借此绕过 UIPI 限制。
        """
        point = ctypes.wintypes.POINT(client_x, client_y)
        ok = self._user32.ClientToScreen(hwnd, ctypes.byref(point))
        if not ok:
            raise RuntimeError("ClientToScreen 转换失败")

        if attach_thread:
            self._click_with_attach(hwnd, point.x, point.y, button=button, delay=delay)
        else:
            self.click(point.x, point.y, button=button, delay=delay)

    def _click_with_attach(
        self,
        hwnd: int,
        screen_x: int,
        screen_y: int,
        button: str = "left",
        delay: Optional[float] = None,
    ) -> None:
        """使用 AttachThreadInput + SetForegroundWindow + SendInput 点击。

        步骤：
        1. 获取目标窗口所在线程 ID。
        2. AttachThreadInput 将当前线程输入队列挂接到目标线程。
        3. SetForegroundWindow 将目标窗口带到前台。
        4. 移动并点击。
        5. Detach。
        """
        target_tid = self._user32.GetWindowThreadProcessId(hwnd, None)
        current_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        try:
            if target_tid and current_tid != target_tid:
                self._user32.AttachThreadInput(current_tid, target_tid, True)
            self._user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
            self.click(screen_x, screen_y, button=button, delay=delay)
        finally:
            if target_tid and current_tid != target_tid:
                self._user32.AttachThreadInput(current_tid, target_tid, False)

    def send_key(self, vk_code: int, delay: Optional[float] = None) -> None:
        """发送一个键盘按键（按下 + 释放）。"""
        self._key_event(vk_code, key_up=False)
        time.sleep(0.05)
        self._key_event(vk_code, key_up=True)
        time.sleep(delay if delay is not None else self.default_delay)

    def _mouse_event(self, flags: int) -> None:
        """发送鼠标按钮事件，SendInput 失败时回退到 Win32 mouse_event API。"""
        if self._send_input_works is not False:
            inp = _INPUT()
            inp.type = INPUT_MOUSE
            inp.ii.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
            self._send_input(inp)
        else:
            self._user32.mouse_event(flags, 0, 0, 0, 0)

    def _key_event(self, vk_code: int, key_up: bool = False) -> None:
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        flags = 0x0002 if key_up else 0
        inp.ii.ki = _KEYBDINPUT(vk_code, 0, flags, 0, None)
        self._send_input(inp)

    def _send_input(self, inp: _INPUT) -> None:
        size = ctypes.sizeof(inp)
        sent = self._user32.SendInput(1, ctypes.byref(inp), size)
        if sent != 1:
            raise RuntimeError("SendInput 调用失败")

    def diagnose(self, timeout: float = 0.5) -> dict:
        """检测当前进程是否真的能通过 SendInput 控制鼠标。

        返回包含移动前后坐标、是否成功、失败原因的 dict，便于在 CLI 中
        给用户明确提示。
        """
        result: dict = {"supported": False, "reason": None}

        pt = ctypes.wintypes.POINT()
        ok = self._user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            result["reason"] = "GetCursorPos 调用失败"
            return result

        start = (pt.x, pt.y)
        result["start_pos"] = start

        # 移动到屏幕中心偏右下，避免原地不动误判；这里只测 SendInput，不走 fallback
        target = (start[0] + 80, start[1] + 60)
        try:
            self._send_input_move(target[0], target[1])
            time.sleep(0.05)
            self._send_input_mouse(MOUSEEVENTF_LEFTDOWN)
            time.sleep(0.05)
            self._send_input_mouse(MOUSEEVENTF_LEFTUP)
            time.sleep(timeout)
        except Exception as exc:
            result["reason"] = f"SendInput 调用异常：{exc}"
            return result

        ok = self._user32.GetCursorPos(ctypes.byref(pt))
        end = (pt.x, pt.y) if ok else None
        result["end_pos"] = end

        # 允许几个像素的舍入误差
        if end is not None and abs(end[0] - target[0]) <= 3 and abs(end[1] - target[1]) <= 3:
            result["supported"] = True
            self._send_input_works = True
        else:
            result["reason"] = (
                f"SendInput 未生效：目标 {target}，实际到达 {end}。"
                "可能是当前会话运行在隔离桌面/远程会话中。"
            )
            self._send_input_works = False

        # 把光标移回起点，避免干扰用户
        try:
            self.click(*start, delay=0.05)
        except Exception:
            pass
        return result

    def _send_input_move(self, x: int, y: int) -> None:
        """仅使用 SendInput 移动鼠标（无 fallback）。"""
        v_left = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        v_top = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        v_width = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        v_height = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        nx = int((x - v_left) * SCREEN_NORMALIZE / v_width)
        ny = int((y - v_top) * SCREEN_NORMALIZE / v_height)

        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.ii.mi = _MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)
        self._send_input(inp)

    def _send_input_mouse(self, flags: int) -> None:
        """仅使用 SendInput 发送鼠标按钮事件（无 fallback）。"""
        inp = _INPUT()
        inp.type = INPUT_MOUSE
        inp.ii.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        self._send_input(inp)


# 常用虚拟键码
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22   # Page Down
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
