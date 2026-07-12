"""扫描器相关异常。"""

from __future__ import annotations


class ScanInterruptedError(Exception):
    """用户点击停止时抛出的异常，用于协作式中断扫描流程。"""

    def __init__(self, message: str = "扫描被用户中断"):
        super().__init__(message)
