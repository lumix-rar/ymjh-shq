"""暴力搜索求解器。

仅适用于山河器数量 ≤ 12 的小规模场景，保证找到全局最优。
当规模过大时抛出 ValueError，建议使用 LocalSearchSolver。
"""

from __future__ import annotations

import itertools
from typing import List

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Solution
from shq.rules import RuleSet
from shq.solver.interface import Solver


class BruteForceSolver(Solver):
    """通过枚举所有可能摆放寻找最优解。"""

    MAX_SHQS = 12

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
        if len(shqs) > self.MAX_SHQS:
            raise ValueError(
                f"BruteForceSolver 仅支持 {self.MAX_SHQS} 个及以下山河器，"
                f"当前 {len(shqs)} 个，请使用 local_search"
            )

        front_slots = [slot for region in lingjian.regions for slot in region.front_slots]

        best_score = float("-inf")
        best_placement = Placement()
        best_evaluation = Evaluation()

        max_place = min(len(shqs), len(front_slots))

        for count in range(1, max_place + 1):
            for chosen in itertools.combinations(shqs, count):
                for perm in itertools.permutations(chosen):
                    for slot_combo in itertools.permutations(front_slots, count):
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
