"""进程查找器：定位一梦江湖 PC 客户端进程。

本模块仅用于**发现**游戏进程，为后续数据采集（截图/OCR/内存读取）提供目标。
默认使用可配置的进程名、窗口标题、可执行路径关键字进行匹配。
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

import psutil


@dataclass
class ProcessMatchRule:
    """进程匹配规则。"""

    names: List[str] = field(default_factory=list)          # 进程名，例如 ["ymjh.exe"]
    window_titles: List[str] = field(default_factory=list)  # 窗口标题子串，例如 ["一梦江湖"]
    exe_keywords: List[str] = field(default_factory=list)   # 可执行路径关键字，例如 ["ymjh"]

    def is_empty(self) -> bool:
        return not (self.names or self.window_titles or self.exe_keywords)


@dataclass
class ProcessInfo:
    """一梦江湖进程信息。"""

    pid: int
    name: str
    exe_path: str
    window_titles: List[str] = field(default_factory=list)
    create_time: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "exe_path": self.exe_path,
            "window_titles": self.window_titles,
            "create_time": self.create_time,
        }


class ProcessFinder:
    """Windows 进程查找器。"""

    def __init__(self, rule: Optional[ProcessMatchRule] = None):
        self.rule = rule or ProcessMatchRule()

    @classmethod
    def for_ymjh(cls) -> "ProcessFinder":
        """创建默认的一梦江湖进程查找器。"""
        from shq.config import YMJH_PROCESS_RULE

        return cls(ProcessMatchRule(**YMJH_PROCESS_RULE))

    def list_processes(self) -> List[ProcessInfo]:
        """枚举所有可访问进程及其窗口标题。"""
        pid_to_titles = _collect_window_titles()
        result: List[ProcessInfo] = []
        for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
            try:
                info = ProcessInfo(
                    pid=proc.info["pid"],
                    name=proc.info["name"] or "",
                    exe_path=proc.info["exe"] or "",
                    window_titles=pid_to_titles.get(proc.info["pid"], []),
                    create_time=proc.info["create_time"],
                )
                result.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return result

    def find(
        self,
        rule: Optional[ProcessMatchRule] = None,
        multiple: bool = False,
    ) -> Optional[ProcessInfo] | List[ProcessInfo]:
        """按规则查找进程。

        Args:
            rule: 匹配规则，None 则使用构造时传入的规则。
            multiple: 是否返回所有匹配项。

        Returns:
            单个 ProcessInfo，或匹配列表（multiple=True）。未找到返回 None 或空列表。
        """
        rule = rule or self.rule
        if rule.is_empty():
            raise ValueError("Process match rule is empty")

        matches: List[ProcessInfo] = []
        priorities: List[int] = []
        for info in self.list_processes():
            priority = _match_priority(info, rule)
            if priority > 0:
                matches.append(info)
                priorities.append(priority)

        if multiple:
            return matches
        if not matches:
            return None

        # 优先级：进程名精确匹配 > 可执行路径关键字匹配 > 窗口标题匹配
        best_idx = max(range(len(matches)), key=lambda i: priorities[i])
        return matches[best_idx]

    def find_ymjh(self) -> Optional[ProcessInfo]:
        """查找一梦江湖主进程。"""
        return self.find()

    def wait_for_process(
        self,
        timeout: float = 30.0,
        interval: float = 0.5,
        rule: Optional[ProcessMatchRule] = None,
    ) -> Optional[ProcessInfo]:
        """等待进程出现。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.find(rule=rule)
            if found:
                return found
            time.sleep(interval)
        return None


def _match_priority(info: ProcessInfo, rule: ProcessMatchRule) -> int:
    """返回匹配优先级，数值越大越优先。0 表示不匹配。"""
    name_lower = info.name.lower()
    exe_lower = info.exe_path.lower()
    titles_lower = [t.lower() for t in info.window_titles]

    # 进程名精确匹配优先级最高
    if rule.names:
        if any(name_lower == n.lower() for n in rule.names):
            return 3
    # 可执行路径关键字匹配次之
    if rule.exe_keywords:
        if any(k.lower() in exe_lower for k in rule.exe_keywords):
            return 2
    # 窗口标题匹配最低（可能误匹配浏览器等）
    if rule.window_titles:
        if any(k.lower() in t for k in rule.window_titles for t in titles_lower):
            return 1
    return 0


def _collect_window_titles() -> dict[int, List[str]]:
    """使用 ctypes 收集每个进程 PID 拥有的可见窗口标题。"""
    pid_to_titles: dict[int, List[str]] = {}

    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_callback(hwnd, _extra):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if title:
                pid_to_titles.setdefault(pid.value, []).append(title)
        return True

    user32.EnumWindows(enum_callback, None)
    return pid_to_titles
