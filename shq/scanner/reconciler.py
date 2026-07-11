"""扫描结果兜底与漏扫补齐模块。

扫描结束后，用底稿该品质的 expected set 与 detected set 做对比。
若存在 missing names，在已识别到的物品中寻找名字最相近的记录，
通过名字校正将其补回，并生成 reconciliation report 供人工核对。

注意：本模块只能修复“已点击并已解析，但名字因 OCR 错误未正确归一化”导致的漏扫。
对于“格子根本没被点击”或“详情面板解析为未获得”的情况，需要 Phase 2 的
CellDetector / 面板变化校验来从源头避免。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from shq.models import Shanheqi
from shq.scanner.name_resolver import ShanheqiNameResolver
from shq.scanner.constants import TYPE_TO_SUB_TAG


class ScanReconciler:
    """扫描结果兜底补齐器。"""

    def __init__(
        self,
        resolver: Optional[ShanheqiNameResolver] = None,
        score_threshold: float = 0.55,
    ):
        self.resolver = resolver or ShanheqiNameResolver()
        self.score_threshold = score_threshold

    def reconcile(
        self,
        quality: str,
        owned_items: List[Shanheqi],
        low_conf_records: Optional[List[dict]] = None,
    ) -> Tuple[List[Shanheqi], List[dict]]:
        """对指定品质的扫描结果做兜底补齐。

        在已解析到的物品中寻找与缺失标准名字最相近的记录，校正其名字并更新 ID。
        low_conf_records 目前仅用于构造候选池时的补充参考（未来可扩展为重新解析截图）。

        Returns:
            (owned_items, reconciliation_report)
        """
        expected = set(self.resolver.list_by_quality(quality))
        detected = {s.name for s in owned_items}
        missing = sorted(expected - detected)
        if not missing:
            return owned_items, []

        report: List[dict] = []
        used_indices: set[int] = set()
        pool = self._build_pool(owned_items)

        for miss in missing:
            best_idx: Optional[int] = None
            best_score = 0.0

            for entry in pool:
                idx = entry["owned_index"]
                if idx in used_indices:
                    continue
                score = self.resolver.name_score(miss, entry["raw_name"])
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx is None or best_score < self.score_threshold:
                report.append(
                    {
                        "missing": miss,
                        "action": "未找到可信匹配",
                        "best_score": best_score,
                    }
                )
                continue

            shq = owned_items[best_idx]
            used_indices.add(best_idx)
            old_name = shq.name

            # 校正名字并更新 ID
            shq.name = miss
            sub_tag = TYPE_TO_SUB_TAG.get(shq.shanheqi_type, "普通")
            shq.id = f"wuku_{shq.quality.value}_{sub_tag}_{shq.name}_{shq.level}"

            report.append(
                {
                    "missing": miss,
                    "action": "已补齐",
                    "matched_raw": entry["raw_name"],
                    "matched_old_name": old_name,
                    "score": best_score,
                    "owned_index": best_idx,
                }
            )

        return owned_items, report

    def _build_pool(self, owned_items: List[Shanheqi]) -> List[Dict]:
        """构造名字匹配候选池。

        目前所有已获取项都会进入 owned_items，因此候选池直接取 owned_items 中的名字。
        """
        return [{"owned_index": idx, "raw_name": shq.name} for idx, shq in enumerate(owned_items)]

    def remaining_missing(
        self,
        quality: str,
        owned_items: List[Shanheqi],
    ) -> List[str]:
        """返回经过 reconcile 后仍然缺失的名字。"""
        expected = set(self.resolver.list_by_quality(quality))
        detected = {s.name for s in owned_items}
        return sorted(expected - detected)
