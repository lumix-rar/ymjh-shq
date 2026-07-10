"""模型层基础测试。"""

from shq.models import (
    Affix,
    AffixEffect,
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
)


def test_shanheqi_creation():
    shq = Shanheqi(
        id="test",
        name="测试",
        quality=Quality.PEERLESS,
        element=Element.FIRE,
        shanheqi_type=ShanheqiType.XUANSHU,
        level=10,
        gongguan_level=3,
        base_score=100.0,
    )
    assert shq.element == Element.FIRE
    assert shq.shanheqi_type == ShanheqiType.XUANSHU


def test_affix_with_effect():
    effect = AffixEffect(name="起势", params={"bonus": 0.1}, description="示例效果")
    affix = Affix(name="起势", element=Element.FIRE, level=3, score=50.0, derived=True, effects=[effect])
    assert affix.name == "起势"
    assert affix.derived is True
    assert affix.effects[0].name == "起势"


def test_slot_position():
    slot = Slot(id="s1", region_id="r1", position=SlotPosition.BACK, base_penalty=-10.0)
    assert slot.position == SlotPosition.BACK
    assert slot.base_penalty == -10.0


def test_lingjian_all_slots():
    slot1 = Slot(id="s1", region_id="r1")
    slot2 = Slot(id="s2", region_id="r1")
    region = Region(id="r1", name="测试区域", slots=[slot1, slot2])
    lingjian = Lingjian(regions=[region])
    assert len(lingjian.all_slots()) == 2
    assert lingjian.get_slot("s1") is slot1
    assert lingjian.get_region("r1") is region


def test_placement_clone():
    p = Placement({"s1": "shq_1"})
    cloned = p.clone()
    cloned.mapping["s2"] = "shq_2"
    assert "s2" not in p.mapping


def test_build_preference():
    pref = BuildPreference(build="治疗", weights={"长烟烽火": 1.5})
    assert pref.build == "治疗"
