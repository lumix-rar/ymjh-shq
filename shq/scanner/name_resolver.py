"""山河器名字归一化解析器。

基于本地维护的全量山河器名字底稿，把 OCR 识别出的可能有误的名字
（例如“缤铁雪花”被错识为“铁雪花”）映射回标准名字。

匹配策略：
- 先应用已知 OCR 错误别名表。
- 再在期望品质（或全量）候选池中做混合打分匹配：
  SequenceMatcher.ratio + 归一化 Levenshtein 距离 + 字符 Jaccard + 子串奖励。
- 汉明距离不适合中文 OCR（丢字/多字/错字），因此不使用。
"""

import difflib
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 已知高频 OCR 错误：先硬校正，减少模糊匹配的不确定性。
OCR_NAME_ALIASES: Dict[str, str] = {
    "铁雪花": "缤铁雪花",
    "尾凤头": "螭尾凤头",
    "竹节": "竹节锏",
    "竹节铜": "竹节锏",
    "酒胸胆": "酒酣胸胆",
    "酒醋胸胆": "酒酣胸胆",
}


def _normalize(text: str) -> str:
    """只保留中文字符，用于名字比较。"""
    return "".join(ch for ch in text if "一" <= ch <= "鿿")


def _levenshtein(a: str, b: str) -> int:
    """计算两个字符串的编辑距离。"""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _name_score(detected: str, candidate: str) -> float:
    """混合打分，范围 [0, 1]。"""
    detected = _normalize(detected)
    candidate = _normalize(candidate)

    if not detected or not candidate:
        return 0.0
    if detected == candidate:
        return 1.0

    seq_ratio = difflib.SequenceMatcher(None, detected, candidate).ratio()

    lev = _levenshtein(detected, candidate)
    max_len = max(len(detected), len(candidate))
    norm_lev = 1.0 - lev / max_len if max_len else 1.0

    set_d, set_c = set(detected), set(candidate)
    union = set_d | set_c
    jaccard = len(set_d & set_c) / len(union) if union else 0.0

    # 子串奖励：OCR 常漏首字或尾字
    sub_bonus = 0.12 if detected in candidate or candidate in detected else 0.0

    score = 0.45 * seq_ratio + 0.30 * norm_lev + 0.25 * jaccard + sub_bonus
    return min(score, 1.0)


class ShanheqiNameResolver:
    """山河器名字归一化解析器。"""

    def __init__(self, master_path: Optional[Path] = None):
        if master_path is None:
            master_path = Path(__file__).parents[2] / "data" / "shanheqi_master_list.json"
        self.master_path = master_path
        self.qualities: Dict[str, List[str]] = {}
        self.sub_tags: Dict[str, Dict[str, List[str]]] = {}
        self._name_to_quality: Dict[str, str] = {}
        self._name_to_sub_tag: Dict[str, str] = {}
        self._all_names: List[str] = []
        self._load()

    def _load(self) -> None:
        if not self.master_path.exists():
            return
        data = json.loads(self.master_path.read_text(encoding="utf-8"))
        for quality, value in data.get("qualities", {}).items():
            if isinstance(value, list):
                self.qualities[quality] = value
                for name in value:
                    self._name_to_quality[name] = quality
                    self._all_names.append(name)
            elif isinstance(value, dict):
                # 绝世按子标签分类
                self.sub_tags[quality] = {}
                for sub_tag, names in value.items():
                    self.sub_tags[quality][sub_tag] = names
                    for name in names:
                        self._name_to_quality[name] = quality
                        self._name_to_sub_tag[name] = sub_tag
                        self._all_names.append(name)

    def resolve(
        self,
        detected_name: str,
        expected_quality: Optional[str] = None,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """把 OCR 识别出的名字映射为标准名字。

        Args:
            detected_name: OCR 识别出的原始名字。
            expected_quality: 当前扫描的品质。强烈建议传入，以避免跨品质重名误匹配。

        Returns:
            (canonical_name, quality, sub_tag)
            如果无法映射，canonical_name 返回原名字，quality/sub_tag 为 None。
        """
        if not detected_name:
            return detected_name, None, None

        # 1. 应用已知 OCR 错误别名表
        aliased = OCR_NAME_ALIASES.get(detected_name, detected_name)

        # 2. 在期望品质的候选池中查找
        candidates = self._candidates_for(aliased, expected_quality)
        if aliased in candidates:
            return (
                aliased,
                expected_quality or self._name_to_quality.get(aliased),
                self._sub_tag_for(aliased, expected_quality),
            )

        # 3. 模糊匹配
        if not candidates:
            return detected_name, None, None

        best: Optional[Tuple[str, float]] = None
        for cand in candidates:
            score = _name_score(aliased, cand)
            if best is None or score > best[1]:
                best = (cand, score)

        if best and best[1] >= 0.60:
            canonical = best[0]
            quality = expected_quality or self._name_to_quality.get(canonical)
            sub_tag = self._sub_tag_for(canonical, expected_quality)
            return canonical, quality, sub_tag

        # 4. 如果别名表已修改但 fuzzy 仍未命中，仍返回别名结果
        if aliased != detected_name and aliased in self._name_to_quality:
            return (
                aliased,
                expected_quality or self._name_to_quality.get(aliased),
                self._sub_tag_for(aliased, expected_quality),
            )

        return detected_name, None, None

    def _sub_tag_for(
        self, name: str, expected_quality: Optional[str]
    ) -> Optional[str]:
        """返回名字在指定品质下的子标签（主要用于绝世）。"""
        if expected_quality and expected_quality in self.sub_tags:
            for sub_tag, names in self.sub_tags[expected_quality].items():
                if name in names:
                    return sub_tag
        return self._name_to_sub_tag.get(name)

    def _candidates_for(
        self, detected_name: str, expected_quality: Optional[str]
    ) -> List[str]:
        """返回用于匹配的候选名字列表。"""
        if expected_quality and expected_quality in self.qualities:
            return list(self.qualities[expected_quality])
        if expected_quality and expected_quality in self.sub_tags:
            result: List[str] = []
            for names in self.sub_tags[expected_quality].values():
                result.extend(names)
            return result
        return list(self._all_names)

    def name_score(self, detected_name: str, canonical_name: str) -> float:
        """公开打分函数，供 reconciler 使用。"""
        return _name_score(detected_name, canonical_name)

    def list_by_quality(self, quality: str) -> List[str]:
        """返回指定品质下的所有标准名字。"""
        if quality in self.qualities:
            return list(self.qualities[quality])
        if quality in self.sub_tags:
            result = []
            for names in self.sub_tags[quality].values():
                result.extend(names)
            return result
        return []

    def expected_count(self, quality: str) -> int:
        """返回指定品质在底稿中的总数。"""
        return len(self.list_by_quality(quality))
