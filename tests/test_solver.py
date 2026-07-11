"""求解器单元测试。"""

from __future__ import annotations

import threading

from shq.models import (
    BuildPreference,
    Element,
    Evaluation,
    Lingjian,
    Placement,
    Quality,
    Region,
    Shanheqi,
    ShanheqiType,
    Slot,
    SlotPosition,
    Solution,
)
from shq.rules import YMJHDefaultRuleSet
from shq.solver import LocalSearchSolver


def _slot(region_id: str, number: int, slot_id: str) -> Slot:
    return Slot(
        id=slot_id,
        region_id=region_id,
        number=number,
        position=SlotPosition.NORMAL,
    )


def _shq(shq_id: str, element: Element, base_score: float) -> Shanheqi:
    return Shanheqi(
        id=shq_id,
        name=shq_id,
        quality=Quality.SIMPLE,
        element=element,
        shanheqi_type=ShanheqiType.NORMAL,
        base_score=base_score,
    )


def test_local_search_stop_event():
    """局部搜索在收到停止信号后应提前结束并返回可行解。"""
    region = Region(
        id="test",
        name="test",
        slots=[_slot("test", 1, "s1"), _slot("test", 2, "s2")],
        connections=[],
    )
    lingjian = Lingjian(regions=[region])
    shqs = [
        _shq("a", Element.METAL, 100),
        _shq("b", Element.WATER, 200),
    ]
    rules = YMJHDefaultRuleSet()

    stop_event = threading.Event()
    # 延迟 50ms 后触发停止
    timer = threading.Timer(0.05, stop_event.set)
    timer.start()

    solver = LocalSearchSolver(
        max_iterations=10000, stop_event=stop_event
    )
    solution = solver.solve(
        shqs, lingjian, rules, "total_score", BuildPreference(build="综合")
    )

    assert isinstance(solution, Solution)
    assert isinstance(solution.evaluation, Evaluation)
    assert solution.evaluation.total_score > 0
    timer.join()
