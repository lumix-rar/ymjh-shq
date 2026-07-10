"""暴力搜索求解器。

适用于山河器数量较少或孔位较少的场景，保证找到全局最优。
当组合爆炸时，应使用启发式/ILP 求解器。
"""

import itertools
from typing import Dict, List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Solution
from shq.rules import RuleSet
from shq.solver.interface import Solver


class BruteForceSolver(Solver):
    """通过枚举所有可能摆放寻找最优解。"""

    @property
    def name(self) -> str:
        return "brute_force"

    def solve(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None = None,
    ) -> Solution:
        # TODO：当前为占位实现，未考虑区域解锁、背面减分、玄枢加成、生克等复杂约束
        best_score = float("-inf")
        best_placement = Placement()
        best_evaluation = Evaluation()

        slots = lingjian.all_slots()
        max_place = min(len(shqs), len(slots))

        for count in range(1, max_place + 1):
            for chosen in itertools.combinations(shqs, count):
                for perm in itertools.permutations(chosen):
                    for slot_combo in itertools.permutations(slots, count):
                        placement = Placement()
                        valid = True
                        for shq, slot in zip(perm, slot_combo):
                            if not rules.can_place(shq, slot):
                                valid = False
                                break
                            placement.mapping[slot.id] = shq.id
                        if not valid:
                            continue
                        evaluation = rules.evaluate(list(chosen), lingjian, placement)
                        score = rules.score(evaluation, target, preference)
                        if score > best_score:
                            best_score = score
                            best_placement = placement.clone()
                            best_evaluation = evaluation

        return Solution(
            placement=best_placement,
            evaluation=best_evaluation,
            target=target,
            description=f"best {target} score via brute force",
        )
