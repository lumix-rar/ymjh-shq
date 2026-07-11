"""GUI 模块单元测试。

本文件只测试不依赖 tkinter 窗口的数据与工具函数，
避免在无显示环境中实例化 GUI 控件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shq.gui.data_store import DataStore, parse_shanheqi_dict
from shq.gui.utils import MessageType, WorkerQueue, format_score
from shq.models import Element, Quality, Shanheqi, ShanheqiType


@pytest.fixture
def sample_shq() -> Shanheqi:
    return Shanheqi(
        id="shq_001",
        name="测试山河器",
        quality=Quality.EXQUISITE,
        element=Element.FIRE,
        shanheqi_type=ShanheqiType.NORMAL,
        level=10,
        gongguan_level=2,
        base_score=1234.5,
        derived_affixes=["起势", "火实"],
        stats={"攻击": 100},
        tags=frozenset(),
    )


def test_format_score():
    assert format_score(1234.0) == "1234"
    assert format_score(1234.5) == "1234.5"


def test_worker_queue_basic():
    q = WorkerQueue()
    q.put(MessageType.LOG, "hello")
    q.put(MessageType.PROGRESS, {"current": 1, "total": 10})
    items = q.get_all()
    assert len(items) == 2
    assert items[0]["type"] == "log"
    assert items[0]["payload"] == "hello"
    assert items[1]["type"] == "progress"


def test_data_store_shanheqi_round_trip(tmp_path: Path, sample_shq: Shanheqi):
    store = DataStore()
    store.shanheqis.append(sample_shq)
    path = tmp_path / "wuku.json"
    store.save_wuku_json(path)

    store2 = DataStore()
    store2.load_wuku_json(path)
    assert len(store2.shanheqis) == 1
    shq = store2.shanheqis[0]
    assert shq.name == "测试山河器"
    assert shq.quality == Quality.EXQUISITE
    assert shq.element == Element.FIRE
    assert shq.base_score == 1234.5
    assert shq.derived_affixes == ["起势", "火实"]


def test_data_store_cultivation_round_trip(tmp_path: Path):
    store = DataStore()
    store.lingjian = store.load_topology()

    cultivation_data = {
        "regions": [
            {
                "region_id": "yiji_meihua",
                "region_name": "驿寄梅花",
                "slots": [
                    {
                        "slot_id": "yiji_meihua_slot_1",
                        "number": 1,
                        "cultivation_score": 3600,
                    },
                    {
                        "slot_id": "yiji_meihua_slot_2",
                        "number": 2,
                        "cultivation_score": 1200,
                    },
                ],
            }
        ]
    }
    path = tmp_path / "slot_cultivation.json"
    path.write_text(json.dumps(cultivation_data), encoding="utf-8")

    store.load_slot_cultivation_json(path)
    slot = store.lingjian.get_slot("yiji_meihua_slot_1")
    assert slot is not None
    assert slot.cultivation_score == 3600.0


def test_parse_shanheqi_dict(sample_shq: Shanheqi):
    data = {
        "id": sample_shq.id,
        "name": sample_shq.name,
        "quality": sample_shq.quality.value,
        "element": sample_shq.element.value,
        "shanheqi_type": sample_shq.shanheqi_type.value,
        "level": sample_shq.level,
        "gongguan_level": sample_shq.gongguan_level,
        "base_score": sample_shq.base_score,
        "derived_affixes": sample_shq.derived_affixes,
    }
    shq = parse_shanheqi_dict(data)
    assert shq.name == sample_shq.name
    assert shq.element == sample_shq.element
    assert shq.quality == sample_shq.quality


def test_gui_modules_importable():
    """确保 GUI 模块可以在无显示环境中导入。"""
    import shq.gui.app
    import shq.gui.controller
    import shq.gui.data_store
    import shq.gui.dialogs
    import shq.gui.main
    import shq.gui.utils
    import shq.gui.widgets
    import shq.gui.workers

    assert shq.gui.main is not None
