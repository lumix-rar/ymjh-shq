"""游戏规则抽象接口。

山河器的具体属性、评分、生克、区域效果会随游戏版本变化。
后续 Agent 只需实现 RuleSet 即可接入新的游戏数据。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Slot


@dataclass
class Resonance:
    """共鸣/羁绊效果（若后续发现山河器存在套装/共鸣机制时使用）。"""

    name: str
    required_tags: frozenset[str]
    min_count: int
    stats: Dict[str, float]
    description: str = ""


class RuleSet(ABC):
    """游戏规则集合。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """规则集名称。"""

    @abstractmethod
    def can_place(self, shq: Shanheqi, slot: Slot) -> bool:
        """判断山河器能否放入指定孔位（类型限制、玄枢限制、背面中心等）。"""

    @abstractmethod
    def evaluate(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        placement: Placement,
    ) -> Evaluation:
        """计算某个摆放方案的总评分与属性。

        需考虑：
        - 山河器基础评分
        - 词条（素蕴）评分，含特殊效果（起势/承势/倾侧等）
        - 孔位培养评分（不同用户不同）
        - 背面孔位基础减分
        - 五行相生相克连线加成/减分
        - 玄枢山河器对背面区域中心及周围的加成（共贯等级影响）
        - 区域灵鉴效果（按总评分阈值激活）
        - 派生素蕴、套装/共鸣等
        """

    @abstractmethod
    def score(
        self,
        evaluation: Evaluation,
        target: str,
        preference: BuildPreference | None = None,
    ) -> float:
        """根据优化目标与流派偏好对评估结果打分。

        Args:
            target: 优化目标，如 total_score/气血/攻击/治疗量 等。
            preference: 玩家流派偏好，如输出/治疗/承伤，可影响区域权重。
        """

    @abstractmethod
    def unlocked_regions(
        self,
        evaluation: Evaluation,
        lingjian: Lingjian,
    ) -> List[str]:
        """根据当前评分返回已解锁的区域 ID 列表。"""

    @abstractmethod
    def resonances(self) -> List[Resonance]:
        """返回当前规则集支持的所有共鸣/羁绊（若存在）。"""

    @abstractmethod
    def region_priority(
        self,
        preference: BuildPreference,
    ) -> List[str]:
        """根据流派偏好返回区域优先级排序（用于指导求解/展示）。"""
