"""求解器抽象接口。"""

from abc import ABC, abstractmethod
from typing import List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Solution
from shq.rules import RuleSet


class Solver(ABC):
    """山河器摆放优化求解器。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """求解器名称。"""

    @abstractmethod
    def solve(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None = None,
    ) -> Solution:
        """求解最优摆放方案。"""
