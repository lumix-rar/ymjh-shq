"""GUI 内存数据模型与序列化。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from shq.models import (
    Affix,
    AffixEffect,
    BuildPreference,
    Element,
    Lingjian,
    Quality,
    Region,
    Shanheqi,
    ShanheqiType,
    Slot,
    SlotPosition,
)
from shq.scanner.manual_importer import ManualImporter
from shq.scanner.topology_loader import TopologyLoader


@dataclass
class DataStore:
    """内存中的单一数据源，供 GUI 各视图共享。"""

    shanheqis: List[Shanheqi] = field(default_factory=list)
    lingjian: Optional[Lingjian] = None
    preference: BuildPreference = field(
        default_factory=lambda: BuildPreference(build="综合")
    )
    topology_path: Optional[Path] = None
    rules_path: Optional[Path] = None
    dirty: bool = False

    def mark_dirty(self) -> None:
        self.dirty = True

    def mark_clean(self) -> None:
        self.dirty = False

    # ------------------------------------------------------------------
    # 武库山河器
    # ------------------------------------------------------------------
    def load_wuku_json(self, path: Path) -> None:
        """从武库扫描结果 JSON 加载山河器列表。"""
        importer = ManualImporter(path)
        self.shanheqis = importer.scan_shanheqis()
        self.mark_dirty()

    def save_wuku_json(self, path: Path) -> None:
        """将山河器列表保存为 JSON。"""
        data = {
            "shanheqis": [_shanheqi_to_dict(shq) for shq in self.shanheqis],
            "preference": {
                "build": self.preference.build,
                "weights": dict(self.preference.weights),
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.mark_clean()

    def add_shanheqi(self, shq: Shanheqi) -> None:
        self.shanheqis.append(shq)
        self.mark_dirty()

    def remove_shanheqi(self, shq_id: str) -> bool:
        for idx, shq in enumerate(self.shanheqis):
            if shq.id == shq_id:
                self.shanheqis.pop(idx)
                self.mark_dirty()
                return True
        return False

    def update_shanheqi(self, shq_id: str, **kwargs: Any) -> bool:
        for shq in self.shanheqis:
            if shq.id == shq_id:
                for key, value in kwargs.items():
                    if hasattr(shq, key):
                        setattr(shq, key, value)
                self.mark_dirty()
                return True
        return False

    # ------------------------------------------------------------------
    # 灵鉴拓扑与孔位培养
    # ------------------------------------------------------------------
    def load_topology(self, path: Optional[Path] = None) -> Lingjian:
        """加载灵鉴拓扑（可选路径），并返回 Lingjian（不含培养分）。"""
        loader = TopologyLoader(path=path)
        topology = loader.load()
        self.topology_path = path
        return topology.lingjian

    def load_slot_cultivation_json(self, path: Path) -> None:
        """从孔位培养扫描结果 JSON 加载加分，并应用到当前 lingjian。"""
        if self.lingjian is None:
            self.lingjian = self.load_topology(self.topology_path)

        data = json.loads(path.read_text(encoding="utf-8"))
        score_map: Dict[str, float] = {}
        for region in data.get("regions", []):
            for slot in region.get("slots", []):
                score_map[str(slot["slot_id"])] = float(
                    slot.get("cultivation_score", 0.0)
                )

        self.apply_cultivation_scores(score_map)
        self.mark_dirty()

    def apply_cultivation_scores(self, score_map: Dict[str, float]) -> None:
        """将 slot_id → 培养分的映射应用到当前 lingjian。"""
        if self.lingjian is None:
            return
        for slot in self.lingjian.all_slots():
            slot.cultivation_score = score_map.get(slot.id, 0.0)

    def export_slot_cultivation_json(self, path: Path) -> None:
        """将当前灵鉴孔位培养分导出为扫描器兼容 JSON。"""
        if self.lingjian is None:
            raise ValueError("当前没有灵鉴数据")

        data: Dict[str, Any] = {"regions": []}
        for region in self.lingjian.regions:
            slots = []
            for slot in region.slots:
                slots.append(
                    {
                        "slot_id": slot.id,
                        "number": slot.number,
                        "cultivation_score": slot.cultivation_score,
                        "confidence": 1.0,
                        "raw_text": "",
                    }
                )
            data["regions"].append(
                {
                    "region_id": region.id,
                    "region_name": region.name,
                    "locked": False,
                    "slots": slots,
                    "low_confidence": [],
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # 偏好
    # ------------------------------------------------------------------
    def set_preference(self, preference: BuildPreference) -> None:
        self.preference = preference
        self.mark_dirty()

    def build_preference(self) -> BuildPreference:
        return self.preference

    # ------------------------------------------------------------------
    # 整体导入/导出
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "shanheqis": [_shanheqi_to_dict(shq) for shq in self.shanheqis],
            "lingjian": _lingjian_to_dict(self.lingjian) if self.lingjian else None,
            "preference": {
                "build": self.preference.build,
                "weights": dict(self.preference.weights),
            },
        }

    def save_all(self, path: Path) -> None:
        """将山河器、灵鉴、偏好整体保存为 JSON。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.mark_clean()


# ----------------------------------------------------------------------
# 序列化辅助
# ----------------------------------------------------------------------
def _shanheqi_to_dict(shq: Shanheqi) -> dict:
    return {
        "id": shq.id,
        "name": shq.name,
        "quality": shq.quality.value,
        "element": shq.element.value,
        "shanheqi_type": shq.shanheqi_type.value,
        "level": shq.level,
        "gongguan_level": shq.gongguan_level,
        "base_score": shq.base_score,
        "affixes": [_affix_to_dict(a) for a in shq.affixes],
        "derived_affixes": list(shq.derived_affixes),
        "stats": dict(shq.stats),
        "tags": list(shq.tags),
    }


def _affix_to_dict(affix: Affix) -> dict:
    return {
        "name": affix.name,
        "element": affix.element.value if affix.element else None,
        "level": affix.level,
        "score": affix.score,
        "derived": affix.derived,
        "effects": [_affix_effect_to_dict(e) for e in affix.effects],
    }


def _affix_effect_to_dict(effect: AffixEffect) -> dict:
    return {
        "name": effect.name,
        "params": dict(effect.params),
        "description": effect.description,
    }


def _lingjian_to_dict(lingjian: Lingjian) -> dict:
    return {"regions": [_region_to_dict(r) for r in lingjian.regions]}


def _region_to_dict(region: Region) -> dict:
    return {
        "id": region.id,
        "name": region.name,
        "slots": [_slot_to_dict(s) for s in region.slots],
        "connections": [
            {"from": c.from_slot, "to": c.to_slot} for c in region.connections
        ],
        "effects": [
            {
                "name": e.name,
                "required_score": e.required_score,
                "stats": dict(e.stats),
                "description": e.description,
            }
            for e in region.effects
        ],
        "unlock_required_score": region.unlock_required_score,
        "back_region_id": region.back_region_id,
        "recommended_for": list(region.recommended_for),
        "same_element_pairs": [list(p) for p in region.same_element_pairs],
        "back_config": _back_config_to_dict(region.back_config)
        if region.back_config
        else None,
    }


def _slot_to_dict(slot: Slot) -> dict:
    return {
        "id": slot.id,
        "region_id": slot.region_id,
        "number": slot.number,
        "position": slot.position.value,
        "allowed_tags": list(slot.allowed_tags),
        "cultivation_score": slot.cultivation_score,
        "base_penalty": slot.base_penalty,
        "is_back_center": slot.is_back_center,
    }


def _back_config_to_dict(back: Any) -> dict:
    return {
        "xuanshu_name": back.xuanshu_name,
        "center_slot_id": back.center_slot_id,
        "front_zero_score": back.front_zero_score,
        "back_adds_to_front": back.back_adds_to_front,
    }


# ----------------------------------------------------------------------
# 反序列化辅助（用于编辑后重建对象）
# ----------------------------------------------------------------------
def parse_shanheqi_dict(item: dict) -> Shanheqi:
    """从字典构造 Shanheqi，兼容枚举名与中文值。"""
    return Shanheqi(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        quality=_parse_quality(item.get("quality", "SIMPLE")),
        element=_parse_element(item.get("element", "METAL")),
        shanheqi_type=_parse_shanheqi_type(item.get("shanheqi_type", "NORMAL")),
        level=int(item.get("level", 1)),
        gongguan_level=int(item.get("gongguan_level", 0)),
        base_score=float(item.get("base_score", 0)),
        affixes=[_parse_affix(a) for a in item.get("affixes", [])],
        derived_affixes=list(item.get("derived_affixes", [])),
        stats=dict(item.get("stats", {})),
        tags=frozenset(item.get("tags", [])),
    )


def _parse_quality(value: str) -> Quality:
    try:
        return Quality[value.upper()]
    except KeyError:
        for member in Quality:
            if member.value == value:
                return member
        raise ValueError(f"无法解析品质：{value}")


def _parse_element(value: str) -> Element:
    try:
        return Element[value.upper()]
    except KeyError:
        for member in Element:
            if member.value == value:
                return member
        raise ValueError(f"无法解析五行：{value}")


def _parse_shanheqi_type(value: str) -> ShanheqiType:
    try:
        return ShanheqiType[value.upper()]
    except KeyError:
        for member in ShanheqiType:
            if member.value == value:
                return member
        raise ValueError(f"无法解析山河器类型：{value}")


def _parse_affix(item: dict) -> Affix:
    element_value = item.get("element")
    return Affix(
        name=str(item.get("name", "")),
        element=_parse_element(element_value) if element_value else None,
        level=int(item.get("level", 1)),
        score=float(item.get("score", 0)),
        derived=bool(item.get("derived", False)),
        effects=[_parse_affix_effect(e) for e in item.get("effects", [])],
    )


def _parse_affix_effect(item: dict) -> AffixEffect:
    return AffixEffect(
        name=str(item.get("name", "")),
        params=dict(item.get("params", {})),
        description=str(item.get("description", "")),
    )
