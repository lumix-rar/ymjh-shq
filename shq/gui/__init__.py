"""山河器最优摆放 GUI 壳子。

提供基于 tkinter 的图形界面，覆盖"扫描/导入 → 校对 → 配置权重 → 求解 → 查看结果"完整流程。
"""

from __future__ import annotations

__all__ = ["main", "ShqGuiApplication"]

# 延迟导入主窗口，避免在 CLI 导入时初始化 tk

def _get_app_class():
    from shq.gui.app import ShqGuiApplication
    return ShqGuiApplication
