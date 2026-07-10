"""CollectionState 单元测试。"""

import tempfile
from pathlib import Path

from shq.models import Element, Quality, Shanheqi
from shq.scanner.wuku.detail_reader import DetailData
from shq.scanner.wuku.models import BBox, GridItem, Point
from shq.scanner.wuku.state import CollectionState


def test_state_processed_and_merge():
    state = CollectionState()
    grid_item = GridItem(
        name="伏威刀",
        cell_bbox=BBox(0, 0, 100, 100),
        click_point=Point(50, 50),
        level=10,
        derived_affix="起势",
        is_acquired=True,
    )
    detail = DetailData(name="伏威刀", element="水", level=10, score=1420)

    assert not state.is_processed(grid_item.unique_key)
    state.mark_processed(grid_item.unique_key)
    assert state.is_processed(grid_item.unique_key)

    state.add_detail("伏威刀", detail)
    shq = state.merge_item(grid_item)
    assert shq is not None
    assert shq.name == "伏威刀"
    assert "伏威刀" in state.results


def test_state_save_and_load():
    state = CollectionState()
    state.results["伏威刀"] = Shanheqi(
        id="wuku_伏威刀",
        name="伏威刀",
        quality=Quality.SIMPLE,
        element=Element.METAL,
    )
    state.mark_processed("伏威刀#10级#起势")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
        state.save(path)
        loaded = CollectionState.load(path)

        assert "伏威刀" in loaded.results
        assert "伏威刀#10级#起势" in loaded.processed_keys
