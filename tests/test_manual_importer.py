"""手动导入测试。"""

import json

from shq.models import Element, Quality, ShanheqiType, SlotPosition
from shq.scanner.manual_importer import ManualImporter


def test_import_shanheqis(tmp_path):
    data = {
        "shanheqis": [
            {
                "id": "s1",
                "name": "测试器",
                "quality": "peerless",
                "element": "fire",
                "shanheqi_type": "xuanshu",
                "level": 5,
                "gongguan_level": 3,
                "base_score": 100.0,
                "affixes": [
                    {
                        "name": "起势",
                        "element": "fire",
                        "level": 3,
                        "score": 50.0,
                        "derived": True,
                        "effects": [{"name": "起势", "params": {"bonus": 0.1}}],
                    }
                ],
                "stats": {"气血": 10.0},
                "tags": ["xuanshu"],
            }
        ],
        "lingjian": {"regions": []},
        "preference": {"build": "输出", "weights": {}},
    }
    path = tmp_path / "shq.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    importer = ManualImporter(path)
    shqs = importer.scan_shanheqis()
    assert len(shqs) == 1
    assert shqs[0].quality == Quality.PEERLESS
    assert shqs[0].element == Element.FIRE
    assert shqs[0].shanheqi_type == ShanheqiType.XUANSHU
    assert shqs[0].affixes[0].name == "起势"

    pref = importer.scan_preference()
    assert pref.build == "输出"


def test_import_lingjian(tmp_path):
    data = {
        "shanheqis": [],
        "lingjian": {
            "regions": [
                {
                    "id": "r1",
                    "name": "驿寄梅花",
                    "slots": [
                        {
                            "id": "s1",
                            "region_id": "r1",
                            "position": "back",
                            "cultivation_score": 10.0,
                            "base_penalty": -5.0,
                        }
                    ],
                    "connections": [],
                    "effects": [],
                    "back_region_id": "r1_back",
                    "recommended_for": ["输出"],
                }
            ]
        },
    }
    path = tmp_path / "lingjian.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    importer = ManualImporter(path)
    lingjian = importer.scan_lingjian()
    assert len(lingjian.regions) == 1
    assert lingjian.regions[0].slots[0].position == SlotPosition.BACK
    assert lingjian.regions[0].back_region_id == "r1_back"
