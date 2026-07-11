"""一梦江湖默认规则实现。

基于用户实测规则与公开攻略：
- 灵鉴区域孔位间有向连线决定五行生克方向。
- 生克效果需起势/承势触发；发起者带起势/承势时效果增强。
- x实山河器使用时自身评分 +5%。
- 同属性孔位双方各 +7.5%。
- 关河道远/骸关断云 6 号位为背面中心，专有玄枢山河器带来额外背面加成。

所有可变数值从 data/ymjh_rules.json 读取，便于版本更新。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shq.config import PROJECT_ROOT
from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Region, Shanheqi, Slot
from shq.rules.interface import Resonance, RuleSet


@dataclass
class _RegionScoreState:
    """评分计算过程中单个区域的中间状态。"""

    slot_scores: Dict[str, float] = field(default_factory=dict)
    back_slot_id: Optional[str] = None
    back_shq_id: Optional[str] = None
    back_bonus_rate: float = 0.0
    front_zero_slot_ids: List[str] = field(default_factory=list)


class YMJHDefaultRuleSet(RuleSet):
    """一梦江湖默认规则集。"""

    DEFAULT_RULES_PATH = PROJECT_ROOT / "data" / "ymjh_rules.json"

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = rules_path or self.DEFAULT_RULES_PATH
        self._rules = json.loads(self.rules_path.read_text(encoding="utf-8"))
        self._element_map = self._rules["elements"]
        self._interaction = self._rules["interaction"]
        self._momentum = self._rules["momentum"]
        self._xshi_rate = float(self._rules.get("xshi_bonus_rate", 0.05))
        self._back_cfg = self._rules.get("back_center", {})
        self._region_rules = self._rules.get("regions", {})
        self._build_weights = self._rules.get("build_weights", {})

    @property
    def name(self) -> str:
        return "ymjh_default"

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def can_place(self, shq: Shanheqi, slot: Slot) -> bool:
        """判断山河器能否放入指定孔位。"""
        if not slot.allowed_tags:
            return True
        return bool(slot.allowed_tags & shq.tags)

    def evaluate(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        placement: Placement,
    ) -> Evaluation:
        """评估一个摆放方案。"""
        shq_map = {shq.id: shq for shq in shqs}
        slot_map = {slot.id: slot for slot in lingjian.all_slots()}
        region_map = {region.id: region for region in lingjian.regions}

        region_scores: Dict[str, float] = {}
        slot_scores: Dict[str, float] = {}
        details: List[str] = []
        states: Dict[str, _RegionScoreState] = {}

        # 1. 计算每个正面区域的分数
        for region in lingjian.regions:
            state = self._evaluate_region(
                region, placement, shq_map, slot_map, details
            )
            states[region.id] = state
            region_scores[region.id] = sum(
                state.slot_scores.get(slot.id, 0.0) for slot in region.front_slots
            )
            slot_scores.update(state.slot_scores)

        # 2. 处理背面 6 号位
        back_scores: Dict[str, float] = {}
        self._apply_back_centers(
            lingjian, placement, shq_map, slot_map, region_scores, slot_scores, back_scores, states, details
        )

        total_score = sum(region_scores.values())
        return Evaluation(
            total_score=total_score,
            region_scores=region_scores,
            slot_scores=slot_scores,
            back_scores=back_scores,
            stats={},
            details=details,
        )

    def score(
        self,
        evaluation: Evaluation,
        target: str,
        preference: BuildPreference | None = None,
    ) -> float:
        """根据优化目标与流派偏好打分。"""
        if target == "total_score":
            return evaluation.total_score

        if target == "build_score" and preference is not None:
            weights = self._build_weights.get(preference.build, {})
            if not weights:
                return evaluation.total_score
            return sum(
                evaluation.region_scores.get(region_id, 0.0) * weight
                for region_id, weight in weights.items()
            )

        return evaluation.stats.get(target, 0.0)

    def unlocked_regions(
        self,
        evaluation: Evaluation,
        lingjian: Lingjian,
    ) -> List[str]:
        """当前无精确解锁阈值，返回所有区域。"""
        return [r.id for r in lingjian.regions]

    def resonances(self) -> List[Resonance]:
        return []

    def region_priority(self, preference: BuildPreference) -> List[str]:
        """根据流派偏好返回区域优先级排序（ID 列表）。"""
        weights = self._build_weights.get(preference.build, {})
        if not weights:
            return [r.id for r in self._region_rules.keys()]
        sorted_regions = sorted(
            weights.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [region_id for region_id, _ in sorted_regions]

    # ------------------------------------------------------------------
    # 评分内部实现
    # ------------------------------------------------------------------
    def _evaluate_region(
        self,
        region: Region,
        placement: Placement,
        shq_map: Dict[str, Shanheqi],
        slot_map: Dict[str, Slot],
        details: List[str],
    ) -> _RegionScoreState:
        """计算单个区域的正面孔位分数。"""
        state = _RegionScoreState()
        front_slots = region.front_slots

        # 初始化：有效基础分
        for slot in front_slots:
            shq_id = placement.mapping.get(slot.id)
            if shq_id:
                shq = shq_map.get(shq_id)
                if shq:
                    state.slot_scores[slot.id] = self._effective_base(shq, slot)
                    continue
            state.slot_scores[slot.id] = 0.0

        # 同属性加成
        for a_num, b_num in region.same_element_pairs:
            a_slot = self._slot_by_number(front_slots, a_num)
            b_slot = self._slot_by_number(front_slots, b_num)
            if not a_slot or not b_slot:
                continue
            a_shq_id = placement.mapping.get(a_slot.id)
            b_shq_id = placement.mapping.get(b_slot.id)
            if not a_shq_id or not b_shq_id:
                continue
            a_shq = shq_map.get(a_shq_id)
            b_shq = shq_map.get(b_shq_id)
            if not a_shq or not b_shq:
                continue
            if a_shq.element.value != b_shq.element.value:
                continue
            bonus_rate = float(self._interaction.get("same_element_bonus_rate", 0.075))
            state.slot_scores[a_slot.id] += self._interaction_base(a_shq) * bonus_rate
            state.slot_scores[b_slot.id] += self._interaction_base(b_shq) * bonus_rate
            details.append(
                f"{region.name} 孔{a_num}↔孔{b_num} 同属性 {a_shq.element.value} 各+{bonus_rate*100:.1f}%"
            )

        # 生克加成
        for conn in region.connections:
            from_slot = slot_map.get(conn.from_slot)
            to_slot = slot_map.get(conn.to_slot)
            if not from_slot or not to_slot:
                continue
            from_shq_id = placement.mapping.get(from_slot.id)
            to_shq_id = placement.mapping.get(to_slot.id)
            if not from_shq_id or not to_shq_id:
                continue
            from_shq = shq_map.get(from_shq_id)
            to_shq = shq_map.get(to_shq_id)
            if not from_shq or not to_shq:
                continue

            relation = self._relation(from_shq.element.value, to_shq.element.value)
            if relation is None:
                continue

            multiplier = self._mutual_multiplier
            if relation == "counter":
                multiplier = -self._mutual_multiplier

            # source 带起势/承势时，生克效果增强
            if self._has_momentum(from_shq):
                momentum_bonus = self._momentum_bonus(from_shq)
                multiplier *= 1.0 + momentum_bonus

            base = self._interaction_base(to_shq)
            bonus = base * multiplier
            state.slot_scores[to_slot.id] += bonus
            details.append(
                f"{region.name} {from_shq.name}({from_shq.element.value})->{to_shq.name}({to_shq.element.value}) "
                f"{relation} {'+' if bonus >= 0 else ''}{bonus:.1f}"
            )

        # 正面专有山河器 0 分
        region_rule = self._region_rules.get(region.id, {})
        back = region_rule.get("back_config")
        if back:
            xuanshu_name = str(back["xuanshu_name"])
            for slot in front_slots:
                shq_id = placement.mapping.get(slot.id)
                if not shq_id:
                    continue
                shq = shq_map.get(shq_id)
                if shq and shq.name == xuanshu_name:
                    state.slot_scores[slot.id] = 0.0
                    state.front_zero_slot_ids.append(slot.id)
                    details.append(f"{region.name} 孔{slot.number} 放置专有{xuanshu_name}，正面计 0 分")

        return state

    def _apply_back_centers(
        self,
        lingjian: Lingjian,
        placement: Placement,
        shq_map: Dict[str, Shanheqi],
        slot_map: Dict[str, Slot],
        region_scores: Dict[str, float],
        slot_scores: Dict[str, float],
        back_scores: Dict[str, float],
        states: Dict[str, _RegionScoreState],
        details: List[str],
    ) -> None:
        """处理关河道远/骸关断云的 6 号位背面中心孔。"""
        used_shq_ids = set(placement.mapping.values())

        for region in lingjian.regions:
            if region.back_config is None:
                continue

            back = region.back_config
            xuanshu_name = back.xuanshu_name
            center_slot = slot_map.get(back.center_slot_id)
            if center_slot is None:
                continue

            # 优先放专有山河器
            xuanshu_candidates = [
                shq for shq in shq_map.values()
                if shq.name == xuanshu_name and shq.id not in used_shq_ids
            ]
            if xuanshu_candidates:
                chosen = max(xuanshu_candidates, key=lambda s: s.base_score)
                back_bonus_rate = float(self._back_cfg.get("专有加成", 0.20))
                details.append(
                    f"{region.name} 6号位放置专有{xuanshu_name}，背面加成 {back_bonus_rate*100:.0f}%"
                )
            else:
                # 从剩余山河器中选择 effective_base 最高的
                remaining = [
                    shq for shq in shq_map.values()
                    if shq.id not in used_shq_ids
                ]
                if not remaining:
                    continue
                chosen = max(
                    remaining,
                    key=lambda s: self._effective_base(s, center_slot),
                )
                back_bonus_rate = float(self._back_cfg.get("非专有加成", 0.05))
                details.append(
                    f"{region.name} 6号位放置 {chosen.name}，背面加成 {back_bonus_rate*100:.0f}%"
                )

            placement.back_mapping[back.center_slot_id] = chosen.id
            state = states[region.id]
            state.back_slot_id = back.center_slot_id
            state.back_shq_id = chosen.id
            state.back_bonus_rate = back_bonus_rate

            # 6 号位山河器自身分数是否计入正面
            if back.back_adds_to_front:
                center_score = self._effective_base(chosen, center_slot)
                region_scores[region.id] += center_score
                slot_scores[back.center_slot_id] = center_score
                details.append(
                    f"{region.name} 6号位 {chosen.name} 分数 {center_score:.1f} 计入正面"
                )

            # 背面加成 = 正面区域总分 × back_bonus_rate，独立输出
            back_bonus = region_scores[region.id] * back_bonus_rate
            back_scores[region.id] = back_bonus
            details.append(
                f"{region.name} 背面加成 {back_bonus:.1f}（正面总分 {region_scores[region.id]:.1f} × {back_bonus_rate*100:.0f}%）"
            )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _effective_base(self, shq: Shanheqi, slot: Slot) -> float:
        """单个山河器在孔位上的有效基础分（含 x实、孔位培养分）。"""
        score = self._interaction_base(shq)
        score += float(slot.cultivation_score)
        return score

    def _interaction_base(self, shq: Shanheqi) -> float:
        """用于生克/同属性计算的基础分（含 x实，不含孔位培养分）。"""
        score = float(shq.base_score)
        if self._has_xshi(shq):
            score *= 1.0 + self._xshi_rate
        return score

    @staticmethod
    def _has_xshi(shq: Shanheqi) -> bool:
        return "x实" in shq.derived_effects

    @staticmethod
    def _has_momentum(shq: Shanheqi) -> bool:
        effects = shq.derived_effects
        return "起势" in effects or "承势" in effects

    def _momentum_bonus(self, shq: Shanheqi) -> float:
        effects = shq.derived_effects
        if "起势" in effects:
            return float(self._momentum.get("起势", 1.45))
        if "承势" in effects:
            return float(self._momentum.get("承势", 2.55))
        return 0.0

    def _relation(self, from_el: str, to_el: str) -> Optional[str]:
        """判断 from_el -> to_el 的五行关系。"""
        if self._element_map["相生"].get(from_el) == to_el:
            return "mutual"
        if self._element_map["相克"].get(from_el) == to_el:
            return "counter"
        return None

    @staticmethod
    def _slot_by_number(slots: List[Slot], number: int) -> Optional[Slot]:
        for slot in slots:
            if slot.number == number:
                return slot
        return None

    @property
    def _mutual_multiplier(self) -> float:
        return float(self._interaction.get("mutual_bonus_rate", 0.15))
