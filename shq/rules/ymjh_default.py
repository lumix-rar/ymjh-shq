"""一梦江湖默认规则占位实现。

目前仅提供框架；具体数值、评分公式、生克计算、区域效果需要后续 Agent 根据游戏资料填充。
建议数据来源：
1. 游戏内灵鉴界面截图 + OCR/人工录入。
2. 官方攻略站或玩家 Wiki 的表格。
3. 游戏客户端本地配置（如有明文或可被解析的资源文件）。

TODO 清单：
- [ ] 确认山河器品质得分表（朴素/精巧/瑰丽/绝世）
- [ ] 确认基础素蕴评分公式（等级、五行、组合）
- [ ] 确认派生素蕴规则：触发条件、数量、是否可重塑
- [ ] 确认派生素蕴特殊效果（起势/承势/倾侧等）的名称、触发条件与数值
- [ ] 确认五行生克评分加成/减分比例（当前攻略记载为 ±15%，需验证）
- [ ] 确认灵鉴各区域孔位布局与连线方向
- [ ] 确认区域灵鉴效果与解锁评分
- [ ] 确认孔位培养评分规则
- [ ] 确认背面孔位基础减分规则
- [ ] 确认玄枢山河器加成规则（共贯等级影响范围、中心孔位要求）
- [ ] 确认流派优先区域（输出/治疗/承伤）
"""

from typing import List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Slot
from shq.rules.interface import Resonance, RuleSet


class YMJHDefaultRuleSet(RuleSet):
    """默认规则集：后续需替换为真实游戏数据。"""

    @property
    def name(self) -> str:
        return "ymjh_default"

    def can_place(self, shq: Shanheqi, slot: Slot) -> bool:
        """占位：仅检查标签限制与玄枢类型限制。"""
        # TODO：实现真实放置限制
        # - 玄枢山河器只能放背面区域中心孔位
        # - 某些孔位可能只允许特定类型山河器
        if not slot.allowed_tags:
            return True
        return bool(slot.allowed_tags & shq.tags)

    def evaluate(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        placement: Placement,
    ) -> Evaluation:
        """占位：简单累加基础评分，未实现生克、背面减分、玄枢加成、区域效果、词条特殊效果。"""
        # TODO：实现完整评分逻辑
        total = 0.0
        details: List[str] = []
        region_scores: dict[str, float] = {}

        shq_map = {shq.id: shq for shq in shqs}
        for region in lingjian.regions:
            region_score = 0.0
            for slot in region.slots:
                shq_id = placement.mapping.get(slot.id)
                if not shq_id:
                    continue
                shq = shq_map.get(shq_id)
                if not shq:
                    continue
                # TODO：加入背面孔位减分、玄枢加成、生克加成、词条特殊效果（起势/承势/倾侧等）
                region_score += shq.base_score + slot.cultivation_score + slot.base_penalty
            region_scores[region.id] = region_score
            total += region_score

        return Evaluation(
            total_score=total,
            region_scores=region_scores,
            stats={},
            details=details,
        )

    def score(
        self,
        evaluation: Evaluation,
        target: str,
        preference: BuildPreference | None = None,
    ) -> float:
        """占位：以总评分或目标属性作为分数。"""
        # TODO：根据 preference.build 调整区域/属性权重
        if target == "total_score":
            return evaluation.total_score
        return evaluation.stats.get(target, 0.0)

    def unlocked_regions(
        self,
        evaluation: Evaluation,
        lingjian: Lingjian,
    ) -> List[str]:
        """占位：返回所有区域（未实现解锁逻辑）。"""
        # TODO：根据 evaluation.region_scores 与 region.unlock_required_score 判断是否解锁
        return [r.id for r in lingjian.regions]

    def resonances(self) -> List[Resonance]:
        """占位：返回空列表。"""
        return []

    def region_priority(self, preference: BuildPreference) -> List[str]:
        """占位：返回区域 ID 列表。"""
        # TODO：根据输出/治疗/承伤返回推荐优先级，需要传入灵鉴数据
        return []
