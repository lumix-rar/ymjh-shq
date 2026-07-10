"""wuku 内部模型单元测试。"""

from shq.scanner.wuku.models import BBox, GridItem, Point


def test_grid_item_unique_key():
    item = GridItem(
        name="伏威刀",
        cell_bbox=BBox(0, 0, 100, 100),
        click_point=Point(50, 50),
        level=10,
        derived_affix="起势",
        is_acquired=True,
    )
    assert item.unique_key == "伏威刀#10级#起势"


def test_grid_item_unique_key_unacquired():
    item = GridItem(
        name="乱离长刀",
        cell_bbox=BBox(0, 0, 100, 100),
        click_point=Point(50, 50),
        level=None,
        derived_affix=None,
        is_acquired=False,
    )
    assert item.unique_key == "乱离长刀"


def test_bbox_center():
    bbox = BBox(x=10, y=20, width=30, height=40)
    center = bbox.center
    assert center.x == 25
    assert center.y == 40
