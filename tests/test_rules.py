"""YMJHDefaultRuleSet 评分公式单元测试。

用用户在游戏内实测的数字验证评分计算。
"""

from __future__ import annotations

import pytest

from shq.models import (
    Element,
    Lingjian,
    Placement,
    Quality,
    Region,
    Shanheqi,
    ShanheqiType,
    Slot,
    SlotPosition,
)
from shq.rules import YMJHDefaultRuleSet


@pytest.fixture
def rules():
    return YMJHDefaultRuleSet()


def _slot(region_id: str, number: int, slot_id: str | None = None) -> Slot:
    return Slot(
        id=slot_id or f"{region_id}_slot_{number}",
        region_id=region_id,
        number=number,
        position=SlotPosition.NORMAL,
    )


def _shq(
    shq_id: str,
    name: str,
    element: Element,
    base_score: float,
    derived: list[str] | None = None,
) -> Shanheqi:
    return Shanheqi(
        id=shq_id,
        name=name,
        quality=Quality.SIMPLE,
        element=element,
        shanheqi_type=ShanheqiType.NORMAL,
        base_score=base_score,
        derived_affixes=derived or [],
    )


def _make_region(
    region_id: str,
    slot_count: int,
    connections: list[tuple[int, int]],
    same_element_pairs: list[tuple[int, int]] | None = None,
) -> Region:
    slots = [_slot(region_id, i) for i in range(1, slot_count + 1)]
    from shq.models import Connection

    conns = [
        Connection(from_slot=f"{region_id}_slot_{f}", to_slot=f"{region_id}_slot_{t}")
        for f, t in connections
    ]
    return Region(
        id=region_id,
        name=region_id,
        slots=slots,
        connections=conns,
        same_element_pairs=same_element_pairs or [],
    )


def _make_lingjian(*regions: Region) -> Lingjian:
    return Lingjian(regions=list(regions))


class TestMomentumEffects:
    """起势/承势效果验证。"""

    def test_qishi_both_ends_mutual(self, rules: YMJHDefaultRuleSet):
        """起势金 1720 -> 起势水 1720，总得分 4072，水变 2352。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "起势金", Element.METAL, 1720.0, ["起势"])
        shq2 = _shq("s2", "起势水", Element.WATER, 1720.0, ["起势"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(4072.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(2352.0, abs=0.5)

    def test_qishi_as_source_mutual(self, rules: YMJHDefaultRuleSet):
        """起势水 2060 -> 木 4920，总得分 8788，木变 6728。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "起势水", Element.WATER, 2060.0, ["起势"])
        shq2 = _shq("s2", "木", Element.WOOD, 4920.0)
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(8788.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(6728.0, abs=0.5)

    def test_qishi_as_target_mutual(self, rules: YMJHDefaultRuleSet):
        """金 2060 -> 起势水 2060，总得分 4429，水变 2369。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "金", Element.METAL, 2060.0)
        shq2 = _shq("s2", "起势水", Element.WATER, 2060.0, ["起势"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(4429.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(2369.0, abs=0.5)

    def test_qishi_as_target_wood_to_fire(self, rules: YMJHDefaultRuleSet):
        """木 4920 -> 起势火 4620，总得分 10233，火变 5313。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "木", Element.WOOD, 4920.0)
        shq2 = _shq("s2", "起势火", Element.FIRE, 4620.0, ["起势"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(10233.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(5313.0, abs=0.5)

    def test_no_momentum_no_interaction(self, rules: YMJHDefaultRuleSet):
        """木 4920 -> 火 2300，无起势/承势，无加成，总得分 7220。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "木", Element.WOOD, 4920.0)
        shq2 = _shq("s2", "火", Element.FIRE, 2300.0)
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(7220.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(2300.0, abs=0.5)

    def test_chengshi_as_target_mutual(self, rules: YMJHDefaultRuleSet):
        """木 4920 -> 火承势 3000，总得分 8370，火承势变 3450。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "木", Element.WOOD, 4920.0)
        shq2 = _shq("s2", "火承势", Element.FIRE, 3000.0, ["承势"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(8370.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(3450.0, abs=0.5)

    def test_chengshi_as_source_no_relation(self, rules: YMJHDefaultRuleSet):
        """火承势 3000 -> 木 4920，火不指向木（无生克），无加成，总得分 7920。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "火承势", Element.FIRE, 3000.0, ["承势"])
        shq2 = _shq("s2", "木", Element.WOOD, 4920.0)
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(7920.0, abs=0.5)


class TestXshiEffect:
    """x实自身加成验证。"""

    def test_xshi_as_source(self, rules: YMJHDefaultRuleSet):
        """金实 1270 -> 起势水 1720，金实变 1333，水变 1978，总得分 3311。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "金实", Element.METAL, 1270.0, ["金实"])
        shq2 = _shq("s2", "起势水", Element.WATER, 1720.0, ["起势"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(3311.0, abs=0.5)
        assert ev.slot_scores["test_slot_1"] == pytest.approx(1333.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(1978.0, abs=0.5)

    def test_xshi_as_target_no_relation(self, rules: YMJHDefaultRuleSet):
        """起势水 1720 -> 金实 1270，无直接生克，金实变 1333，总得分 3053。"""
        region = _make_region("test", 2, [(1, 2)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "起势水", Element.WATER, 1720.0, ["起势"])
        shq2 = _shq("s2", "金实", Element.METAL, 1270.0, ["金实"])
        placement = Placement(mapping={"test_slot_1": "s1", "test_slot_2": "s2"})

        ev = rules.evaluate([shq1, shq2], lingjian, placement)

        assert ev.total_score == pytest.approx(3053.0, abs=0.5)
        assert ev.slot_scores["test_slot_2"] == pytest.approx(1333.0, abs=0.5)


class TestSameElementBonus:
    """同属性加成验证。"""

    def test_huangquan_same_element(self, rules: YMJHDefaultRuleSet):
        """黄泉夜渡孔1与孔4同属性，双方各+7.5%。"""
        region = _make_region("test", 4, [(2, 4), (4, 3)], same_element_pairs=[(1, 4)])
        lingjian = _make_lingjian(region)
        shq1 = _shq("s1", "金", Element.METAL, 1000.0)
        shq2 = _shq("s2", "水", Element.WATER, 1000.0)
        shq3 = _shq("s3", "木", Element.WOOD, 1000.0)
        shq4 = _shq("s4", "金", Element.METAL, 1000.0)
        placement = Placement(
            mapping={
                "test_slot_1": "s1",
                "test_slot_2": "s2",
                "test_slot_3": "s3",
                "test_slot_4": "s4",
            }
        )

        ev = rules.evaluate([shq1, shq2, shq3, shq4], lingjian, placement)

        # 孔1和孔4同属性金，各+7.5%
        assert ev.slot_scores["test_slot_1"] == pytest.approx(1075.0, abs=0.5)
        assert ev.slot_scores["test_slot_4"] == pytest.approx(1075.0, abs=0.5)


class TestBackCenter:
    """背面 6 号位规则验证。"""

    def test_guanhe_xuanshu_not_counted_to_front(self, rules: YMJHDefaultRuleSet):
        """关河道远 6 号位空山寂不计入正面，背面加成 20%。"""
        from shq.models import BackRegionConfig

        region = _make_region("guanhe", 5, [(1, 2), (2, 3), (3, 4), (4, 5), (5, 1)])
        region.back_config = BackRegionConfig(
            xuanshu_name="空山寂",
            center_slot_id="guanhe_slot_6",
            front_zero_score=True,
            back_adds_to_front=False,
        )
        region.slots.append(
            Slot(id="guanhe_slot_6", region_id="guanhe", number=6, position=SlotPosition.CENTER, is_back_center=True)
        )
        lingjian = _make_lingjian(region)
        shqs = [
            _shq("s1", "空山寂", Element.METAL, 5000.0),
            _shq("s2", "普通金", Element.METAL, 1000.0),
            _shq("s3", "普通水", Element.WATER, 1000.0),
            _shq("s4", "普通木", Element.WOOD, 1000.0),
            _shq("s5", "普通火", Element.FIRE, 1000.0),
            _shq("s6", "普通土", Element.EARTH, 1000.0),
        ]
        placement = Placement(
            mapping={
                "guanhe_slot_1": "s2",
                "guanhe_slot_2": "s3",
                "guanhe_slot_3": "s4",
                "guanhe_slot_4": "s5",
                "guanhe_slot_5": "s6",
            }
        )

        ev = rules.evaluate(shqs, lingjian, placement)

        # 正面 5 个普通山河器各 1000 分 = 5000
        assert ev.region_scores["guanhe"] == pytest.approx(5000.0, abs=0.5)
        # 背面加成 = 5000 * 20% = 1000
        assert ev.back_scores["guanhe"] == pytest.approx(1000.0, abs=0.5)
        # 6 号位分数不计入正面
        assert "guanhe_slot_6" not in ev.slot_scores or ev.slot_scores.get("guanhe_slot_6") == 0.0

    def test_haiguan_xuanshu_counted_to_front(self, rules: YMJHDefaultRuleSet):
        """骸关断云 6 号位残秋刃计入正面，背面加成 20%。"""
        from shq.models import BackRegionConfig

        region = _make_region("haiguan", 5, [(1, 2), (1, 5), (2, 3), (5, 4)])
        region.back_config = BackRegionConfig(
            xuanshu_name="残秋刃",
            center_slot_id="haiguan_slot_6",
            front_zero_score=True,
            back_adds_to_front=True,
        )
        region.slots.append(
            Slot(id="haiguan_slot_6", region_id="haiguan", number=6, position=SlotPosition.CENTER, is_back_center=True)
        )
        lingjian = _make_lingjian(region)
        shqs = [
            _shq("s1", "残秋刃", Element.METAL, 5000.0),
            _shq("s2", "普通金", Element.METAL, 1000.0),
            _shq("s3", "普通水", Element.WATER, 1000.0),
            _shq("s4", "普通木", Element.WOOD, 1000.0),
            _shq("s5", "普通火", Element.FIRE, 1000.0),
            _shq("s6", "普通土", Element.EARTH, 1000.0),
        ]
        placement = Placement(
            mapping={
                "haiguan_slot_1": "s2",
                "haiguan_slot_2": "s3",
                "haiguan_slot_3": "s4",
                "haiguan_slot_4": "s5",
                "haiguan_slot_5": "s6",
            }
        )

        ev = rules.evaluate(shqs, lingjian, placement)

        # 正面 5 个普通山河器 5000 + 6 号位残秋刃 5000 = 10000
        assert ev.region_scores["haiguan"] == pytest.approx(10000.0, abs=0.5)
        # 背面加成 = 10000 * 20% = 2000
        assert ev.back_scores["haiguan"] == pytest.approx(2000.0, abs=0.5)
