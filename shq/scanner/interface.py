"""扫描器抽象接口。"""

from abc import ABC, abstractmethod
from typing import List

from shq.models import Shanheqi


class Scanner(ABC):
    """山河器数据来源接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """扫描器名称。"""

    @abstractmethod
    def scan(self) -> List[Shanheqi]:
        """返回扫描到的所有山河器数据。"""
