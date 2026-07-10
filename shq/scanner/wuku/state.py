"""武库采集状态管理。

维护已处理 item、OCR 解析结果、滚动指纹等状态，
支持断点续传与进程崩溃恢复。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from shq.models import Shanheqi
from shq.scanner.wuku.detail_reader import DetailData
from shq.scanner.wuku.merger import ShanheqiMerger
from shq.scanner.wuku.models import GridItem


@dataclass
class CollectionState:
    """采集会话状态。"""

    # 最终合并结果
    results: Dict[str, Shanheqi] = field(default_factory=dict)
    # 尚未合并的右面板解析结果（按名字暂存）
    details: Dict[str, DetailData] = field(default_factory=dict)
    # 已点击处理过的 item key
    processed_keys: Set[str] = field(default_factory=set)
    # 每页截图指纹，用于触底检测与恢复（旧字段，保留以兼容历史状态文件）
    scroll_fingerprints: List[str] = field(default_factory=list)
    # 已经见过的 item key 集合，用于滚动触底检测
    seen_item_keys: Set[str] = field(default_factory=set)
    # 当前页码
    current_page: int = 0

    def is_processed(self, key: str) -> bool:
        return key in self.processed_keys

    def mark_processed(self, key: str) -> None:
        self.processed_keys.add(key)

    def mark_seen(self, keys: List[str]) -> None:
        """将一组 item key 标记为已见过（用于滚动触底检测）。"""
        self.seen_item_keys.update(keys)

    def has_new(self, keys: List[str]) -> bool:
        """判断给定 keys 中是否存在尚未见过的 item。"""
        return bool(set(keys) - self.seen_item_keys)

    def add_detail(self, item_name: str, detail: DetailData) -> None:
        """添加一个右面板解析结果。"""
        self.details[item_name] = detail

    def merge_item(self, grid_item: GridItem) -> Optional[Shanheqi]:
        """将左卡 GridItem 与已保存的 DetailData 合并为 Shanheqi。

        如果还没有对应 DetailData，返回 None。
        """
        detail = self.details.get(grid_item.name)
        if detail is None:
            return None
        shq = ShanheqiMerger.merge(grid_item, detail)
        self.results[grid_item.name] = shq
        return shq

    def add_fingerprint(self, fingerprint: str) -> None:
        self.scroll_fingerprints.append(fingerprint)

    def save(self, path: Path) -> None:
        """将状态保存为 JSON。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "results": {k: self._shq_to_dict(v) for k, v in self.results.items()},
            "details": {k: self._detail_to_dict(v) for k, v in self.details.items()},
            "processed_keys": list(self.processed_keys),
            "scroll_fingerprints": self.scroll_fingerprints,
            "seen_item_keys": list(self.seen_item_keys),
            "current_page": self.current_page,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CollectionState":
        """从 JSON 恢复状态。"""
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        state = cls()
        state.results = {k: cls._dict_to_shq(v) for k, v in data.get("results", {}).items()}
        state.details = {k: cls._dict_to_detail(v) for k, v in data.get("details", {}).items()}
        state.processed_keys = set(data.get("processed_keys", []))
        state.scroll_fingerprints = list(data.get("scroll_fingerprints", []))
        state.seen_item_keys = set(data.get("seen_item_keys", []))
        state.current_page = int(data.get("current_page", 0))
        return state

    @staticmethod
    def _shq_to_dict(shq: Shanheqi) -> dict:
        from dataclasses import asdict

        d = asdict(shq)
        d["tags"] = list(shq.tags)
        d["quality"] = shq.quality.value if shq.quality else None
        d["element"] = shq.element.value if shq.element else None
        d["shanheqi_type"] = shq.shanheqi_type.value if shq.shanheqi_type else None
        d["affixes"] = [
            {
                "name": a.name,
                "element": a.element.value if a.element else None,
                "level": a.level,
                "score": a.score,
                "derived": a.derived,
                "effects": [
                    {"name": e.name, "params": e.params, "description": e.description}
                    for e in a.effects
                ],
            }
            for a in shq.affixes
        ]
        return d

    @staticmethod
    def _dict_to_shq(d: dict) -> Shanheqi:
        from shq.models import Affix, AffixEffect, Element, Quality, ShanheqiType

        quality = Quality(d["quality"]) if d.get("quality") else Quality.SIMPLE
        element = Element(d["element"]) if d.get("element") else Element.METAL
        shq_type = ShanheqiType(d["shanheqi_type"]) if d.get("shanheqi_type") else ShanheqiType.NORMAL
        affixes = [
            Affix(
                name=a["name"],
                element=Element(a["element"]) if a.get("element") else None,
                level=a.get("level", 1),
                score=a.get("score", 0.0),
                derived=a.get("derived", False),
                effects=[
                    AffixEffect(
                        name=e["name"],
                        params=e.get("params", {}),
                        description=e.get("description", ""),
                    )
                    for e in a.get("effects", [])
                ],
            )
            for a in d.get("affixes", [])
        ]
        return Shanheqi(
            id=d["id"],
            name=d["name"],
            quality=quality,
            element=element,
            shanheqi_type=shq_type,
            level=d.get("level", 1),
            gongguan_level=d.get("gongguan_level", 0),
            base_score=d.get("base_score", 0.0),
            affixes=affixes,
            stats=d.get("stats", {}),
            tags=frozenset(d.get("tags", [])),
        )

    @staticmethod
    def _detail_to_dict(detail: DetailData) -> dict:
        return {
            "name": detail.name,
            "element": detail.element,
            "level": detail.level,
            "main_stats": detail.main_stats,
            "score": detail.score,
            "affixes": [{"name": a.name, "level": a.level, "score": a.score} for a in detail.affixes],
            "screenshot_path": str(detail.screenshot_path) if detail.screenshot_path else None,
        }

    @staticmethod
    def _dict_to_detail(d: dict) -> DetailData:
        from shq.scanner.wuku.detail_reader import AffixData

        return DetailData(
            name=d["name"],
            element=d.get("element"),
            level=d.get("level", 1),
            main_stats=d.get("main_stats", {}),
            score=d.get("score", 0.0),
            affixes=[AffixData(name=a["name"], level=a["level"], score=a["score"]) for a in d.get("affixes", [])],
            screenshot_path=Path(d["screenshot_path"]) if d.get("screenshot_path") else None,
        )
