"""贪心启发式求解器。

按某种优先级逐个放置山河器，适合山河器数量较多的快速求解。
不保证全局最优，但运行速度快。
"""

from typing import List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Solution
from shq.rules import RuleSet
from shq.solver.interface import Solver


class GreedySolver(Solver):
    """贪心策略：每次选择能带来最大边际收益的孔位放置山河器。"""

    @property
    def name(self) -> str:
        return "greedy"

    def solve(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None = None,
    ) -> Solution:
        # TODO：当前为占位实现，未考虑生克、背面减分、玄枢加成、区域解锁等全局影响
        placement = Placement()
        remaining = list(shqs)

        for slot in lingjian.all_slots():
            if not remaining:
                break
            best_shq = None
            best_score = float("-inf")
            for shq in remaining:
                if not rules.can_place(shq, slot):
                    continue
                trial = placement.clone()
                trial.mapping[slot.id] = shq.id
                evaluation = rules.evaluate([shq], lingjian, trial)
                score = rules.score(evaluation, target, preference)
                if score > best_score:
                    best_score = score
                    best_shq = shq

            if best_shq:
                placement.mapping[slot.id] = best_shq.id
                remaining.remove(best_shq)

        evaluation = rules.evaluate(shqs, lingjian, placement)
        return Solution(
            placement=placement,
            evaluation=evaluation,
            target=target,
            description=f"greedy solution for {target}",
        )
