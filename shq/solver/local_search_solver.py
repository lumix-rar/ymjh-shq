"""局部搜索求解器。

贪心构造初始解，然后通过 swap / move / insert-remove 邻域搜索改进。
适合 30-50 个山河器规模，运行速度快于精确求解。
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional

from shq.models import BuildPreference, Evaluation, Lingjian, Placement, Shanheqi, Slot, Solution
from shq.rules import RuleSet
from shq.solver.interface import Solver

ProgressCallback = Optional[Callable[[int, int], None]]
StopEvent = Optional["threading.Event"]


class LocalSearchSolver(Solver):
    """基于局部搜索的启发式求解器。"""

    def __init__(
        self,
        max_iterations: int = 2000,
        seed: Optional[int] = None,
        progress_callback: ProgressCallback = None,
        stop_event: StopEvent = None,
    ):
        self.max_iterations = max_iterations
        self.seed = seed
        self._rng = random.Random(seed)
        self.progress_callback = progress_callback
        self.stop_event = stop_event

    @property
    def name(self) -> str:
        return "local_search"

    def solve(
        self,
        shqs: List[Shanheqi],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None = None,
    ) -> Solution:
        front_slots = [slot for region in lingjian.regions for slot in region.front_slots]

        # 1. 贪心初始解
        placement = self._greedy_init(shqs, front_slots, lingjian, rules, target, preference)

        # 2. 局部搜索
        placement = self._local_search(
            placement, shqs, front_slots, lingjian, rules, target, preference
        )

        evaluation = rules.evaluate(shqs, lingjian, placement)
        score = rules.score(evaluation, target, preference)

        return Solution(
            placement=placement,
            evaluation=evaluation,
            target=target,
            description=f"local_search score={score:.1f}",
        )

    def _greedy_init(
        self,
        shqs: List[Shanheqi],
        front_slots: List[Slot],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None,
    ) -> Placement:
        """按有效基础分从高到低贪心放置。"""
        sorted_shqs = sorted(shqs, key=lambda s: s.base_score, reverse=True)
        placement = Placement()

        for shq in sorted_shqs:
            best_slot: Optional[Slot] = None
            best_score = float("-inf")

            for slot in front_slots:
                if slot.id in placement.mapping:
                    continue
                if not rules.can_place(shq, slot):
                    continue

                trial = placement.clone()
                trial.mapping[slot.id] = shq.id
                evaluation = rules.evaluate(shqs, lingjian, trial)
                score = rules.score(evaluation, target, preference)

                if score > best_score:
                    best_score = score
                    best_slot = slot

            if best_slot:
                placement.mapping[best_slot.id] = shq.id

        return placement

    def _local_search(
        self,
        placement: Placement,
        shqs: List[Shanheqi],
        front_slots: List[Slot],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None,
    ) -> Placement:
        """在贪心解基础上做邻域搜索。"""
        best_placement = placement.clone()
        best_evaluation = rules.evaluate(shqs, lingjian, best_placement)
        best_score = rules.score(best_evaluation, target, preference)

        placed_shq_ids = list(best_placement.mapping.values())
        empty_slots = [slot for slot in front_slots if slot.id not in best_placement.mapping]

        no_improve_count = 0
        iteration = 0

        while iteration < self.max_iterations and no_improve_count < 200:
            iteration += 1
            improved = False

            if self.stop_event is not None and self.stop_event.is_set():
                break

            if self.progress_callback is not None and iteration % 50 == 0:
                self.progress_callback(iteration, self.max_iterations)

            operation = self._rng.choice(["swap", "move", "insert_remove"])

            if operation == "swap" and len(placed_shq_ids) >= 2:
                new_placement = self._try_swap(
                    best_placement, shqs, front_slots, lingjian, rules, target, preference
                )
            elif operation == "move" and placed_shq_ids and empty_slots:
                new_placement = self._try_move(
                    best_placement, shqs, front_slots, lingjian, rules, target, preference
                )
            elif operation == "insert_remove" and placed_shq_ids:
                new_placement = self._try_insert_remove(
                    best_placement, shqs, front_slots, lingjian, rules, target, preference
                )
            else:
                new_placement = None

            if new_placement:
                new_evaluation = rules.evaluate(shqs, lingjian, new_placement)
                new_score = rules.score(new_evaluation, target, preference)
                if new_score > best_score + 1e-9:
                    best_placement = new_placement
                    best_evaluation = new_evaluation
                    best_score = new_score
                    placed_shq_ids = list(best_placement.mapping.values())
                    empty_slots = [slot for slot in front_slots if slot.id not in best_placement.mapping]
                    improved = True
                    no_improve_count = 0

            if not improved:
                no_improve_count += 1

        return best_placement

    def _try_swap(
        self,
        placement: Placement,
        shqs: List[Shanheqi],
        front_slots: List[Slot],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None,
    ) -> Optional[Placement]:
        """随机交换两个已放置山河器的位置。"""
        slot_ids = list(placement.mapping.keys())
        if len(slot_ids) < 2:
            return None

        s1, s2 = self._rng.sample(slot_ids, 2)
        trial = placement.clone()
        trial.mapping[s1], trial.mapping[s2] = trial.mapping[s2], trial.mapping[s1]

        # 检查合法性
        shq_map = {shq.id: shq for shq in shqs}
        slot_map = {slot.id: slot for slot in front_slots}
        if not rules.can_place(shq_map[trial.mapping[s1]], slot_map[s1]):
            return None
        if not rules.can_place(shq_map[trial.mapping[s2]], slot_map[s2]):
            return None

        return trial

    def _try_move(
        self,
        placement: Placement,
        shqs: List[Shanheqi],
        front_slots: List[Slot],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None,
    ) -> Optional[Placement]:
        """将一个山河器移到当前空孔位。"""
        placed_slot_ids = list(placement.mapping.keys())
        empty_slot_ids = [slot.id for slot in front_slots if slot.id not in placement.mapping]
        if not placed_slot_ids or not empty_slot_ids:
            return None

        from_slot = self._rng.choice(placed_slot_ids)
        to_slot = self._rng.choice(empty_slot_ids)

        shq_map = {shq.id: shq for shq in shqs}
        slot_map = {slot.id: slot for slot in front_slots}
        shq_id = placement.mapping[from_slot]
        if not rules.can_place(shq_map[shq_id], slot_map[to_slot]):
            return None

        trial = placement.clone()
        del trial.mapping[from_slot]
        trial.mapping[to_slot] = shq_id
        return trial

    def _try_insert_remove(
        self,
        placement: Placement,
        shqs: List[Shanheqi],
        front_slots: List[Slot],
        lingjian: Lingjian,
        rules: RuleSet,
        target: str,
        preference: BuildPreference | None,
    ) -> Optional[Placement]:
        """移除一个山河器，然后尝试把另一个未放置的山河器插入到释放或空孔位。"""
        placed_slot_ids = list(placement.mapping.keys())
        used_shq_ids = set(placement.mapping.values())
        unused_shqs = [shq for shq in shqs if shq.id not in used_shq_ids]
        if not placed_slot_ids or not unused_shqs:
            return None

        remove_slot = self._rng.choice(placed_slot_ids)
        new_shq = self._rng.choice(unused_shqs)

        # 尝试把新山河器放到移除后的孔位，或任意空孔位
        candidate_slots = [slot for slot in front_slots if slot.id == remove_slot or slot.id not in placement.mapping]
        slot_map = {slot.id: slot for slot in front_slots}

        valid_slots = [slot for slot in candidate_slots if rules.can_place(new_shq, slot_map[slot.id])]
        if not valid_slots:
            return None

        to_slot = self._rng.choice(valid_slots).id
        trial = placement.clone()
        del trial.mapping[remove_slot]
        trial.mapping[to_slot] = new_shq.id
        return trial
