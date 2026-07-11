"""手动导入：从 JSON 读取山河器与灵鉴数据。

这是目前最稳定、最合规的获取方式：
- 用户在游戏内打开山河器/灵鉴界面。
- 截图或整理数据后保存为 JSON。
- 本扫描器读取并转换为模型对象。

TODO：数据格式尚未确定，需后续根据实际可获取的字段定义。
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from shq.models import (
    Affix,
    AffixEffect,
    BuildPreference,
    Connection,
    Element,
    Lingjian,
    Quality,
    Region,
    RegionEffect,
    Shanheqi,
    ShanheqiType,
    Slot,
    SlotPosition,
)
from shq.scanner.interface import Scanner


class ManualImporter(Scanner):
    """从 JSON 文件导入山河器列表或灵鉴配置。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def name(self) -> str:
        return f"manual_importer({self.path})"

    def scan_shanheqis(self) -> List[Shanheqi]:
        """读取用户拥有的山河器列表。"""
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # TODO：确认实际数据字段结构
        return [_parse_shanheqi(item) for item in data.get("shanheqis", data if isinstance(data, list) else [])]

    def scan_lingjian(self) -> Lingjian:
        """读取灵鉴配置（区域、孔位、连线、效果）。"""
        data = json.loads(self.path.read_text(encoding="utf-8"))
        # TODO：确认实际数据字段结构
        return _parse_lingjian(data.get("lingjian", data))

    def scan_preference(self) -> BuildPreference:
        """读取玩家流派偏好。"""
        data = json.loads(self.path.read_text(encoding="utf-8"))
        pref = data.get("preference", {"build": "综合"})
        return BuildPreference(
            build=pref.get("build", "综合"),
            weights=dict(pref.get("weights", {})),
        )

    def scan(self) -> List[Shanheqi]:
        """Scanner 接口默认返回山河器列表。"""
        return self.scan_shanheqis()


def _parse_shanheqi(item: dict) -> Shanheqi:
    """将 JSON 字典解析为 Shanheqi。"""
    # TODO：根据实际数据格式调整字段映射
    # 兼容旧字段 suyuns 和新字段 affixes
    affix_data = item.get("affixes") or item.get("suyuns", [])
    return Shanheqi(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        quality=_parse_quality(item.get("quality", "SIMPLE")),
        element=_parse_element(item.get("element", "METAL")),
        shanheqi_type=_parse_shanheqi_type(item.get("shanheqi_type", "NORMAL")),
        level=int(item.get("level", 1)),
        gongguan_level=int(item.get("gongguan_level", 0)),
        base_score=float(item.get("base_score", 0)),
        affixes=[_parse_affix(s) for s in affix_data],
        derived_affixes=list(item.get("derived_affixes", [])),
        stats=dict(item.get("stats", {})),
        tags=frozenset(item.get("tags", [])),
    )


def _parse_quality(value: str) -> Quality:
    """支持英文枚举名或中文品质名。"""
    try:
        return Quality[value.upper()]
    except KeyError:
        for member in Quality:
            if member.value == value:
                return member
        raise ValueError(f"无法解析品质：{value}")


def _parse_element(value: str) -> Element:
    """支持英文枚举名或中文五行名。"""
    try:
        return Element[value.upper()]
    except KeyError:
        for member in Element:
            if member.value == value:
                return member
        raise ValueError(f"无法解析五行：{value}")


def _parse_shanheqi_type(value: str) -> ShanheqiType:
    """支持英文枚举名或中文类型名。"""
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


def _parse_lingjian(item: dict) -> Lingjian:
    return Lingjian(
        regions=[_parse_region(r) for r in item.get("regions", [])],
    )


def _parse_region(item: dict) -> Region:
    return Region(
        id=str(item["id"]),
        name=str(item.get("name", "")),
        slots=[_parse_slot(s) for s in item.get("slots", [])],
        connections=[_parse_connection(c) for c in item.get("connections", [])],
        effects=[_parse_region_effect(e) for e in item.get("effects", [])],
        unlock_required_score=float(item["unlock_required_score"]) if "unlock_required_score" in item else None,
        back_region_id=item.get("back_region_id"),
        recommended_for=list(item.get("recommended_for", [])),
    )


def _parse_slot(item: dict) -> Slot:
    return Slot(
        id=str(item["id"]),
        region_id=str(item["region_id"]),
        position=SlotPosition[item.get("position", "NORMAL").upper()],
        allowed_tags=frozenset(item.get("allowed_tags", [])),
        cultivation_score=float(item.get("cultivation_score", 0)),
        base_penalty=float(item.get("base_penalty", 0)),
    )


def _parse_connection(item: dict) -> Connection:
    return Connection(
        from_slot=str(item["from"]),
        to_slot=str(item["to"]),
    )


def _parse_region_effect(item: dict) -> RegionEffect:
    return RegionEffect(
        name=str(item.get("name", "")),
        required_score=float(item["required_score"]),
        stats=dict(item.get("stats", {})),
        description=str(item.get("description", "")),
    )
