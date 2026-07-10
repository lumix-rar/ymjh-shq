"""ShanheqiMerger 单元测试。"""

from shq.models import Affix, Element, ShanheqiType
from shq.scanner.wuku.detail_reader import AffixData, DetailData
from shq.scanner.wuku.merger import ShanheqiMerger
from shq.scanner.wuku.models import BBox, GridItem, Point


def test_merge_basic():
    grid_item = GridItem(
        name="伏威刀",
        cell_bbox=BBox(0, 0, 100, 100),
        click_point=Point(50, 50),
        level=10,
        derived_affix="起势",
        special_grade=None,
        is_acquired=True,
    )
    detail = DetailData(
        name="伏威刀",
        element="水",
        level=10,
        main_stats={"气血上限": 219, "外功防御": 4},
        score=1420,
        affixes=[
            AffixData(name="水之力", level=2, score=800),
            AffixData(name="金之力", level=1, score=160),
        ],
    )

    shq = ShanheqiMerger.merge(grid_item, detail)

    assert shq.name == "伏威刀"
    assert shq.element == Element.WATER
    assert shq.level == 10
    assert shq.base_score == 1420
    assert shq.shanheqi_type == ShanheqiType.NORMAL
    assert len(shq.affixes) == 3  # 2 基础 + 1 派生
    assert shq.affixes[-1].name == "起势"
    assert shq.affixes[-1].derived is True


def test_merge_xuanshu():
    grid_item = GridItem(
        name="玄枢测试",
        cell_bbox=BBox(0, 0, 100, 100),
        click_point=Point(50, 50),
        level=10,
        derived_affix=None,
        special_grade="玄枢",
        is_acquired=True,
    )
    detail = DetailData(name="玄枢测试", element="火", level=10, score=100)

    shq = ShanheqiMerger.merge(grid_item, detail)
    assert shq.shanheqi_type == ShanheqiType.XUANSHU
    assert shq.element == Element.FIRE
