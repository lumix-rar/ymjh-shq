"""武库采集内部数据模型。

这些模型仅用于 scanner/wuku/ 子包内部，描述从截图中识别出的
山河器条目、右侧面板信息以及素蕴数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class Point:
    """窗口客户区坐标点。"""

    x: int
    y: int


@dataclass
class BBox:
    """窗口客户区内的矩形包围盒。"""

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Point:
        return Point(self.x + self.width // 2, self.y + self.height // 2)

    def to_slice(self) -> Tuple[slice, slice]:
        """转换为 numpy 切片 (y, x)。"""
        return (
            slice(self.y, self.y + self.height),
            slice(self.x, self.x + self.width),
        )


@dataclass
class AffixData:
    """从右侧面板识别出的素蕴条目。"""

    name: str = ""          # 如：水之力、金之力
    level: int = 1          # 1~3 级
    score: float = 0.0      # 评分


@dataclass
class GridItem:
    """左卡网格中识别出的一个山河器条目。

    包含是否已获得、等级、派生素蕴名称等可直接从网格卡片读取的信息。
    """

    name: str
    cell_bbox: BBox
    click_point: Point
    level: Optional[int] = None          # 绿色 X 级文字，未获得为 None
    derived_affix: Optional[str] = None  # 左卡棕褐色标签，如“起势”
    special_grade: Optional[str] = None  # 玄枢 / 卓异
    is_acquired: bool = False

    @property
    def unique_key(self) -> str:
        """用于去重和状态跟踪的 key。

        山河器名字在游戏内唯一，但这里保留 level 和 derived_affix
        作为后缀，以便未来扩展或复核。
        """
        parts = [self.name]
        if self.level is not None:
            parts.append(f"{self.level}级")
        if self.derived_affix:
            parts.append(self.derived_affix)
        return "#".join(parts)


@dataclass
class DetailData:
    """点击山河器后，右侧面板识别出的详细信息。"""

    name: str
    element: Optional[str] = None
    level: int = 1
    main_stats: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    affixes: List[AffixData] = field(default_factory=list)
    screenshot_path: Optional[Path] = None
