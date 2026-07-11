"""用户数据读取器集合。

每个 Reader 负责从游戏 UI 中读取一类用户数据：
- WukuReader：读取武库中已获得的山河器详情
- SlotCultivationReader：读取灵鉴各区域孔位培养加分
"""

from shq.scanner.readers.slot_cultivation_reader import SlotCultivationReader
from shq.scanner.readers.wuku_reader import WukuReader

__all__ = ["WukuReader", "SlotCultivationReader"]
