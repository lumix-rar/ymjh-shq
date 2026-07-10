"""武库采集配置。

所有坐标均使用相对于窗口客户区的比例，便于适配不同分辨率。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class ROIConfig:
    """相对窗口客户区的 ROI 配置。"""

    x: float
    y: float
    width: float
    height: float

    def abs(self, window_width: int, window_height: int) -> Tuple[int, int, int, int]:
        """返回绝对坐标 (x, y, w, h)。"""
        x = int(self.x * window_width)
        y = int(self.y * window_height)
        w = int(self.width * window_width)
        h = int(self.height * window_height)
        return x, y, w, h


@dataclass
class WukuConfig:
    """武库采集的可配置参数。"""

    # 区域配置（相对窗口）
    grid_roi: ROIConfig = field(
        default_factory=lambda: ROIConfig(x=0.03, y=0.18, width=0.42, height=0.75)
    )
    filter_roi: ROIConfig = field(
        default_factory=lambda: ROIConfig(x=0.05, y=0.08, width=0.15, height=0.10)
    )
    detail_roi: ROIConfig = field(
        default_factory=lambda: ROIConfig(x=0.51, y=0.13, width=0.43, height=0.75)
    )

    # 网格 item 尺寸（相对窗口）
    item_cell_width: float = 0.187
    item_cell_height: float = 0.160  # 实测约 120px (750 高度下)
    items_per_row: int = 2

    # 滚动配置
    scroll_delta: int = -1200       # 一次滚动的滚轮刻度总量
    overlap_rows: int = 1           # 页间保留重叠行数
    bottom_no_new_items_count: int = 2  # 连续 N 页没有新 item 出现才认为触底

    # OCR 并发
    ocr_workers: int = 4

    # 等待时间（秒）
    click_delay: float = 0.8        # 点击后等待右面板渲染
    scroll_delay: float = 0.5       # 滚动后等待稳定

    # 派生素蕴候选词，用于辅助 OCR 后处理
    derived_affix_candidates: Tuple[str, ...] = (
        "起势",
        "承势",
        "火实",
        "水实",
        "木实",
        "金实",
        "土实",
    )

    # 特殊等级右上角小图标颜色（BGR），用于快速分类
    # 实际检测时会放宽阈值，这里仅作参考
    special_grade_colors: Dict[str, Tuple[int, int, int]] = field(default_factory=dict)


