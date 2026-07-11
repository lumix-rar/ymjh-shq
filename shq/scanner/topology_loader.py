"""灵鉴拓扑加载器。

从 data/lingjian_topology.json 加载区域、孔位布局以及校准后的 ROI/按钮坐标。
将静态拓扑（Region/Slot 模型）与校准数据（按钮位置、ROI）分离，便于后续
重新标定而不影响核心模型。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shq.config import PROJECT_ROOT
from shq.models import BackRegionConfig, Connection, Lingjian, Region, Slot, SlotPosition
from shq.scanner.window_capture import ROI


@dataclass
class SlotCalibration:
    """单个孔位的静态布局数据。

    拓扑只记录该区域有哪些孔位编号（壹/贰/叁/肆……对应 1/2/3/4……）。
    具体编号在屏幕上的位置以及加分文字，扫描时通过 OCR 动态发现。
    """

    slot_id: str
    number: int


@dataclass
class RegionCalibration:
    """单个区域的校准数据。"""

    region_id: str
    list_button: Optional[Tuple[int, int]] = None
    cultivation_button: Optional[Tuple[int, int]] = None
    panel_roi: Optional[ROI] = None
    slots: List[SlotCalibration] = field(default_factory=list)


@dataclass
class Topology:
    """加载后的完整拓扑：模型对象 + 校准数据。"""

    lingjian: Lingjian
    region_calibrations: Dict[str, RegionCalibration]

    def get_region_calibration(self, region_id: str) -> Optional[RegionCalibration]:
        return self.region_calibrations.get(region_id)

    def get_slot_calibration(
        self, region_id: str, slot_id: str
    ) -> Optional[SlotCalibration]:
        rc = self.region_calibrations.get(region_id)
        if rc is None:
            return None
        for sc in rc.slots:
            if sc.slot_id == slot_id:
                return sc
        return None


class TopologyLoader:
    """加载灵鉴拓扑配置文件。"""

    DEFAULT_PATH = PROJECT_ROOT / "data" / "lingjian_topology.json"
    DEFAULT_RULES_PATH = PROJECT_ROOT / "data" / "ymjh_rules.json"

    def __init__(self, path: Optional[Path] = None, rules_path: Optional[Path] = None):
        self.path = path or self.DEFAULT_PATH
        self.rules_path = rules_path or self.DEFAULT_RULES_PATH
        self._rules: Optional[dict] = None

    def _load_rules(self) -> dict:
        if self._rules is None:
            self._rules = json.loads(self.rules_path.read_text(encoding="utf-8"))
        return self._rules

    def load(self) -> Topology:
        """加载拓扑文件，返回模型对象与校准数据。"""
        data = json.loads(self.path.read_text(encoding="utf-8"))
        rules = self._load_rules()
        region_calibrations: Dict[str, RegionCalibration] = {}
        regions: List[Region] = []

        for item in data.get("regions", []):
            region_id = str(item["id"])
            slots = [self._parse_slot(s, region_id) for s in item.get("slots", [])]
            region = Region(
                id=region_id,
                name=str(item.get("name", "")),
                slots=slots,
                connections=[],
                effects=[],
                unlock_required_score=None,
                back_region_id=None,
                recommended_for=[],
            )
            self._apply_region_rules(region, rules)
            regions.append(region)

            rc = RegionCalibration(
                region_id=region_id,
                list_button=self._parse_point(item.get("list_button")),
                cultivation_button=self._parse_point(item.get("cultivation_button")),
                panel_roi=self._parse_roi(item.get("panel_roi")),
                slots=[
                    self._parse_slot_calibration(s)
                    for s in item.get("slots", [])
                ],
            )
            region_calibrations[region_id] = rc

        return Topology(
            lingjian=Lingjian(regions=regions),
            region_calibrations=region_calibrations,
        )

    def save(self, topology: Topology, path: Optional[Path] = None) -> None:
        """将拓扑（含校准数据）写回 JSON 文件。"""
        target = path or self.path
        data: Dict[str, List[dict]] = {"regions": []}

        for region in topology.lingjian.regions:
            rc = topology.region_calibrations.get(region.id)
            region_data = {
                "id": region.id,
                "name": region.name,
                "list_button": self._serialize_point(rc.list_button if rc else None),
                "cultivation_button": self._serialize_point(
                    rc.cultivation_button if rc else None
                ),
                "panel_roi": self._serialize_roi(rc.panel_roi if rc else None),
                "slots": [
                    self._serialize_slot_calibration(sc, region.id)
                    for sc in (rc.slots if rc else [])
                ],
            }
            data["regions"].append(region_data)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 解析辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_slot(item: dict, region_id: str) -> Slot:
        return Slot(
            id=str(item["id"]),
            region_id=region_id,
            number=int(item.get("number", 0)),
            position=SlotPosition[item.get("position", "NORMAL").upper()],
            allowed_tags=frozenset(item.get("allowed_tags", [])),
            cultivation_score=float(item.get("cultivation_score", 0)),
            base_penalty=float(item.get("base_penalty", 0)),
        )

    @staticmethod
    def _parse_slot_calibration(item: dict) -> SlotCalibration:
        return SlotCalibration(
            slot_id=str(item["id"]),
            number=int(item.get("number", 0)),
        )

    def _apply_region_rules(self, region: Region, rules: dict) -> None:
        """从 ymjh_rules.json 中读取该区域的连线、同属性对、背面配置并回填到 Region。"""
        region_rules = rules.get("regions", {}).get(region.id)
        if not region_rules:
            return

        number_to_slot = {slot.number: slot for slot in region.slots if slot.number > 0}

        # 若规则声明了背面中心孔但拓扑中未包含，则自动创建
        back = region_rules.get("back_config")
        if back:
            center_number = int(back.get("center_slot_number", 0))
            if center_number > 0 and center_number not in number_to_slot:
                slot_id = f"{region.id}_slot_{center_number}"
                center_slot = Slot(
                    id=slot_id,
                    region_id=region.id,
                    number=center_number,
                    position=SlotPosition.CENTER,
                    is_back_center=True,
                )
                region.slots.append(center_slot)
                number_to_slot[center_number] = center_slot

        # 有向连线
        for from_num, to_num in region_rules.get("connections", []):
            from_slot = number_to_slot.get(from_num)
            to_slot = number_to_slot.get(to_num)
            if from_slot and to_slot:
                region.connections.append(
                    Connection(from_slot=from_slot.id, to_slot=to_slot.id)
                )

        # 同属性加成对
        region.same_element_pairs = [
            tuple(pair) for pair in region_rules.get("same_element_pairs", [])
        ]

        # 背面中心孔位配置
        if back:
            center_number = int(back.get("center_slot_number", 0))
            center_slot = number_to_slot.get(center_number)
            if center_slot:
                center_slot.is_back_center = True
                region.back_config = BackRegionConfig(
                    xuanshu_name=str(back["xuanshu_name"]),
                    center_slot_id=center_slot.id,
                    front_zero_score=bool(back.get("front_zero_score", True)),
                    back_adds_to_front=bool(back.get("back_adds_to_front", True)),
                )

    @staticmethod
    def _parse_point(value: Optional[list]) -> Optional[Tuple[int, int]]:
        if value is None or not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        return int(value[0]), int(value[1])

    @staticmethod
    def _parse_roi(value: Optional[dict]) -> Optional[ROI]:
        if value is None:
            return None
        return ROI(
            name=str(value.get("name", "")),
            x=int(value["x"]),
            y=int(value["y"]),
            width=int(value["width"]),
            height=int(value["height"]),
            description=str(value.get("description", "")),
        )

    # ------------------------------------------------------------------
    # 序列化辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _serialize_point(value: Optional[Tuple[int, int]]) -> Optional[List[int]]:
        return list(value) if value is not None else None

    @staticmethod
    def _serialize_roi(value: Optional[ROI]) -> Optional[dict]:
        if value is None:
            return None
        return {
            "name": value.name,
            "x": value.x,
            "y": value.y,
            "width": value.width,
            "height": value.height,
            "description": value.description,
        }

    @staticmethod
    def _serialize_slot_calibration(sc: SlotCalibration, region_id: str) -> dict:
        return {
            "id": sc.slot_id,
            "region_id": region_id,
            "number": sc.number,
        }
