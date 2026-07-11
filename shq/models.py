"""核心数据模型。

基于调研结果的一梦江湖山河器系统抽象：
- 山河器镶嵌在灵鉴（Lingjian）的区域（Region）孔位（Slot）中。
- 孔位之间存在有向连线（Connection），根据五行相生相克影响被指向孔位的评分。
- 部分区域存在背面区域（如关河道远·隐），背面中心孔位可镶嵌玄枢山河器，获得额外加成。
- 山河器基础评分 = 品质得分 + 词条（素蕴）得分 + 孔位培养得分 + 特殊效果得分等。
- 词条（素蕴）可能带有特殊效果，如起势、承势、倾侧等，会影响佩戴时的最终得分或属性。
- 区域总评分达到阈值可激活灵鉴效果，并解锁下一区域/背面区域。
- 不同区域对不同流派（输出/治疗/承伤）的收益不同。

本模块只定义结构，不硬编码任何游戏数值。所有未知/待确认字段均用 TODO 标注。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Element(Enum):
    """五行属性。"""

    METAL = "金"
    WOOD = "木"
    WATER = "水"
    FIRE = "火"
    EARTH = "土"


class Quality(Enum):
    """山河器品质。"""

    SIMPLE = "朴素"        # TODO：确认颜色/数值对应关系
    EXQUISITE = "精巧"     # TODO
    MAGNIFICENT = "瑰丽"   # TODO
    PEERLESS = "绝世"      # TODO


class ShanheqiType(Enum):
    """山河器类型。"""

    NORMAL = "普通"
    XUANSHU = "玄枢"       # 特殊山河器，镶嵌在背面区域中心有额外加成
    ZHUOYI = "卓异"        # 另一种特殊山河器（界面右上角黄色标记）


class SlotPosition(Enum):
    """孔位在区域中的位置类型。"""

    NORMAL = "普通"
    FRONT = "正面"
    BACK = "背面"          # 背面孔位可能存在基础减分
    CENTER = "中心"        # 玄枢山河器通常镶嵌在中心孔位


@dataclass
class AffixEffect:
    """词条特殊效果。

    例如：起势、承势、倾侧等。具体名称与效果由游戏规则解析。
    """

    name: str
    # 效果参数，由具体效果类型决定
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class Affix:
    """山河器词条（即素蕴）。

    每次共贯赋予一个基础词条；满级3次共贯后可重塑。
    还有可能获得派生词条（额外词缀），派生词条可能带有特殊效果（如起势、承势、倾侧等）。
    """

    name: str = ""                   # 词条名称，如起势、承势、倾侧等
    element: Optional[Element] = None  # TODO：确认词条是否有五行
    level: int = 1                     # 1~3级，级别越高评分越高
    score: float = 0.0                 # TODO：确认词条评分公式
    # 是否为派生素蕴（额外词缀）；起势、承势、倾侧等通常属于派生素蕴
    derived: bool = False
    # 特殊效果（如起势、承势等），通常出现在派生素蕴上
    effects: List[AffixEffect] = field(default_factory=list)


# 兼容性别名：素蕴即词条
Suyun = Affix


@dataclass
class Shanheqi:
    """单个山河器。"""

    id: str
    name: str
    quality: Quality
    element: Element          # 五行属性
    shanheqi_type: ShanheqiType = ShanheqiType.NORMAL
    level: int = 1            # 强化等级
    # TODO：共贯次数/等级，对玄枢山河器尤为重要
    gongguan_level: int = 0
    base_score: float = 0.0   # TODO：基础评分 = 品质得分 + 词条得分 + ...
    affixes: List[Affix] = field(default_factory=list)
    # 派生素蕴名称列表（如起势、承势、金实等），从武库界面直接读取
    derived_affixes: List[str] = field(default_factory=list)
    # TODO：强化、共贯、重塑相关状态
    stats: Dict[str, float] = field(default_factory=dict)  # 属性：气血、攻击、防御等
    # TODO：山河器标签，用于限制某些孔位（如玄枢孔位）
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def suyuns(self) -> List[Affix]:
        """兼容性属性：素蕴列表。"""
        return self.affixes

    @property
    def derived_effects(self) -> List[str]:
        """从派生素蕴名称中解析出的标准化效果名列表。"""
        effects: List[str] = []
        for name in self.derived_affixes:
            if name in ("起势", "承势"):
                effects.append(name)
            elif name.endswith("实") and name[0] in ("金", "木", "水", "火", "土"):
                effects.append("x实")
        return effects

    def has_effect(self, effect: str) -> bool:
        """判断是否带有指定派生效果。"""
        return effect in self.derived_effects


@dataclass
class Slot:
    """灵鉴孔位。"""

    id: str
    region_id: str
    # 孔位在区域内的 1-based 编号，用于匹配规则配置中的连线与同属性对
    number: int = 0
    position: SlotPosition = SlotPosition.NORMAL
    # 是否为背面中心孔位（6号位）
    is_back_center: bool = False
    # TODO：确认孔位是否有类型限制（如只能镶嵌特定种类山河器/玄枢山河器）
    allowed_tags: frozenset[str] = field(default_factory=frozenset)
    # 孔位培养带来的额外评分（不同用户不一致，需从用户数据读取）
    cultivation_score: float = 0.0
    # TODO：确认背面孔位基础减分是否固定比例或固定值
    base_penalty: float = 0.0


@dataclass
class Connection:
    """孔位之间的有向连线。

    方向决定生克判定中的"指向"关系：
    from_slot -> to_slot，若 from 生 to，则 to 获得加成；若 from 克 to，则 to 被减分。
    """

    from_slot: str
    to_slot: str


@dataclass
class RegionEffect:
    """区域灵鉴效果。"""

    name: str
    required_score: float       # 评分达到此值激活
    # TODO：确认效果是属性加成还是其他（气血、攻击、防御、坚韧、振击等）
    stats: Dict[str, float] = field(default_factory=dict)
    description: str = ""


@dataclass
class BackRegionConfig:
    """背面区域（6号位）配置。"""

    xuanshu_name: str          # 专有玄枢山河器名称
    center_slot_id: str        # 背面中心孔位 slot_id
    front_zero_score: bool = True    # 专有山河器放正面时该孔是否拿 0 分
    back_adds_to_front: bool = True  # 6号位山河器分数是否计入正面总分


@dataclass
class Region:
    """灵鉴区域（如驿寄梅花、长烟烽火、关河道远等）。"""

    id: str
    name: str
    slots: List[Slot] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)
    effects: List[RegionEffect] = field(default_factory=list)
    # 同属性加成孔位对（用孔位 number 表示）
    same_element_pairs: List[Tuple[int, int]] = field(default_factory=list)
    # 背面区域配置（如关河道远·隐、骸关断云背面）
    back_config: Optional[BackRegionConfig] = None
    # TODO：解锁下一区域/背面区域所需总评分
    unlock_required_score: Optional[float] = None
    # 关联的背面区域 ID（如关河道远 -> 关河道远·隐）
    back_region_id: Optional[str] = None
    # TODO：该区域对哪些流派收益较高（输出/治疗/承伤）
    recommended_for: List[str] = field(default_factory=list)

    @property
    def front_slots(self) -> List[Slot]:
        """正面孔位列表（不含背面中心孔）。"""
        return [s for s in self.slots if not getattr(s, "is_back_center", False)]


@dataclass
class Lingjian:
    """完整灵鉴，包含所有区域。"""

    regions: List[Region] = field(default_factory=list)

    def all_slots(self) -> List[Slot]:
        slots: List[Slot] = []
        for region in self.regions:
            slots.extend(region.slots)
        return slots

    def get_slot(self, slot_id: str) -> Optional[Slot]:
        for slot in self.all_slots():
            if slot.id == slot_id:
                return slot
        return None

    def get_region(self, region_id: str) -> Optional[Region]:
        for region in self.regions:
            if region.id == region_id:
                return region
        return None


@dataclass
class Placement:
    """一个具体的摆放方案：孔位 -> 山河器。"""

    mapping: Dict[str, str] = field(default_factory=dict)  # slot_id -> shanheqi_id
    # 背面中心孔位（6号位）的放置方案
    back_mapping: Dict[str, str] = field(default_factory=dict)

    def clone(self) -> Placement:
        return Placement(dict(self.mapping), dict(self.back_mapping))


@dataclass
class BuildPreference:
    """玩家流派偏好，用于指导多目标优化。"""

    build: str  # 输出 / 治疗 / 承伤 / 综合
    # TODO：各属性/区域的权重配置
    weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class Evaluation:
    """某个摆放方案的评估结果。"""

    total_score: float = 0.0
    region_scores: Dict[str, float] = field(default_factory=dict)
    # 每个孔位的最终有效评分，用于调试与验证
    slot_scores: Dict[str, float] = field(default_factory=dict)
    # 背面区域额外加成，独立输出，不参与正面优化
    back_scores: Dict[str, float] = field(default_factory=dict)
    stats: Dict[str, float] = field(default_factory=dict)
    details: List[str] = field(default_factory=list)


@dataclass
class Solution:
    """优化结果。"""

    placement: Placement
    evaluation: Evaluation = field(default_factory=Evaluation)
    target: str = ""
    description: str = ""
