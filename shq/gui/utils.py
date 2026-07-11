"""GUI 通用工具函数与队列消息协议。"""

from __future__ import annotations

import enum
import queue
import tkinter as tk
from typing import Any, Callable, Optional


class MessageType(enum.Enum):
    """工作线程向主线程回传的消息类型。"""

    LOG = "log"
    PROGRESS = "progress"
    DONE = "done"
    ERROR = "error"


class WorkerQueue:
    """简单封装：工作线程写入，主线程轮询读取。"""

    def __init__(self) -> None:
        self._q: queue.Queue[dict] = queue.Queue()

    def put(self, msg_type: MessageType, payload: Any) -> None:
        self._q.put({"type": msg_type.value, "payload": payload})

    def get_all(self) -> list[dict]:
        items: list[dict] = []
        while True:
            try:
                items.append(self._q.get_nowait())
            except queue.Empty:
                break
        return items


def safe_tk_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[Any]:
    """捕获 tkinter 调用中常见的 TclError（如窗口已销毁）。"""
    try:
        return func(*args, **kwargs)
    except tk.TclError:
        return None


def format_score(value: float) -> str:
    """统一分数显示格式。"""
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def set_entry_value(entry: tk.Entry, value: str) -> None:
    """安全设置 Entry 内容并清空原有内容。"""
    safe_tk_call(entry.delete, 0, tk.END)
    safe_tk_call(entry.insert, 0, value)


def copy_to_clipboard(root: tk.Tk, text: str) -> None:
    """复制文本到系统剪贴板。"""
    root.clipboard_clear()
    root.clipboard_append(text)


def is_admin() -> bool:
    """检测当前进程是否以管理员权限运行（仅 Windows 有效）。"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
