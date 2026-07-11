"""用户数据读取器集合。

每个 Reader 负责从游戏 UI 中读取一类用户数据：
- WukuReader：读取武库中已获得的山河器详情
- （后续可扩展 SlotCultivationReader 等）
"""

from shq.scanner.readers.wuku_reader import WukuReader

__all__ = ["WukuReader"]
