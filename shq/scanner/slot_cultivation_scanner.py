"""灵鉴孔位培养扫描器。

职责：在调用方已经导航到灵鉴某区域并打开「孔位培养」面板后，
识别每个编号孔位的额外加分（cultivation_score）。

读取策略：
- 左侧主面板（孔位布局区域）会显示孔位编号（壹、贰、叁、肆……）；
- 扫描器先定位所有编号位置，为每个编号建立 Slot；
- 再在每个编号下方/附近查找「孔位评分：+XXXX」加分文字；
- 若某编号附近没有检测到加分文字，则 cultivation_score 记为 0。

校准模式：
- 对左侧主面板进行 OCR，输出检测到的孔位编号 ROI 以及加分文字 ROI，
  自动把加分文字归到最近的编号下方。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from shq.models import Region, Slot
from shq.scanner.ocr_scanner import OCRBackend, OCRResult, PlaceholderOCRBackend
from shq.scanner.topology_loader import RegionCalibration, SlotCalibration
from shq.scanner.window_capture import ROI


# 灵鉴孔位编号模板目录：按孔位数分子目录（2~6）
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "lingjian_number_templates"
_NUMBER_TEMPLATE_NAMES = ["yi", "er", "san", "si", "wu", "liu"]
_NUMBER_NAME_TO_CHAR = {
    "yi": "壹",
    "er": "贰",
    "san": "叁",
    "si": "肆",
    "wu": "伍",
    "liu": "陆",
}
_NUMBER_CHAR_TO_INT = {
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
}


@dataclass
class SlotCultivationValue:
    """单个孔位的读取结果。"""

    slot_id: str
    number: int
    score: float
    confidence: float
    raw_text: str


@dataclass
class RegionCultivationResult:
    """单个区域的孔位培养扫描结果。"""

    region_id: str
    region_name: str
    locked: bool = False
    slots: List[SlotCultivationValue] = field(default_factory=list)
    low_confidence: List[dict] = field(default_factory=list)


@dataclass
class SlotCultivationScanResult:
    """完整扫描结果。"""

    region_results: List[RegionCultivationResult] = field(default_factory=list)
    screenshots: Dict[str, str] = field(default_factory=dict)
    locked_region_ids: List[str] = field(default_factory=list)


# 加分数值正则：支持 +3600、3600、3,600、评分 3600、提升3600、评分提升3600、孔位评分：+3600 等
_SCORE_TEXT_PATTERN = re.compile(r"孔位评分\s*[：:]\s*\+?\s*([\d,]+)")
_SCORE_PATTERNS = [
    re.compile(r"\+?\s*([\d,]+)\s*分"),
    re.compile(r"\+\s*([\d,]+)"),
    re.compile(r"([\d,]+)\s*分"),
    re.compile(r"评分\s*[：:]?\s*([\d,]+)"),
    re.compile(r"评分提升\s*([\d,]+)"),
    re.compile(r"提升\s*([\d,]+)"),
    re.compile(r"培养\s*[：:]?\s*\+?\s*([\d,]+)"),
]

# 灵鉴孔位编号：壹、贰、叁、肆、伍、陆、柒、捌、玖、拾
_SLOT_NUMBER_CHARS = set("壹贰叁肆伍陆柒捌玖拾")
_SLOT_NUMBER_MAP = {
    "壹": 1,
    "一": 1,
    "1": 1,
    "贰": 2,
    "二": 2,
    "2": 2,
    "叁": 3,
    "三": 3,
    "3": 3,
    "肆": 4,
    "四": 4,
    "4": 4,
    "伍": 5,
    "五": 5,
    "5": 5,
    "陆": 6,
    "六": 6,
    "6": 6,
    "柒": 7,
    "七": 7,
    "7": 7,
    "捌": 8,
    "八": 8,
    "8": 8,
    "玖": 9,
    "九": 9,
    "9": 9,
    "拾": 10,
    "十": 10,
    "10": 10,
}


class SlotCultivationScanner:
    """灵鉴孔位培养扫描器。"""

    def __init__(
        self,
        ocr_backend: Optional[OCRBackend] = None,
        confidence_threshold: float = 0.5,
        output_dir: Optional[Path] = None,
    ):
        self.backend = ocr_backend or PlaceholderOCRBackend()
        self.conf_threshold = confidence_threshold
        self.output_dir = output_dir or Path.cwd() / "lingjian_scan"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 生产读取
    # ------------------------------------------------------------------
    def read_region(
        self,
        img: np.ndarray,
        region: Region,
        calibration: RegionCalibration,
        panel_open: bool = True,
    ) -> RegionCultivationResult:
        """读取单个区域的孔位培养加分。

        流程：
        1. 用图像处理检测左侧面板中的所有孔位编号方块；
        2. OCR 检测所有加分文字（孔位评分：+XXXX）；
        3. 按拓扑中定义的孔位数量，把检测到的方块按位置排序后依次对应编号 1..N；
        4. 对每个方块，找最近的加分文字，未找到 cultivation_score 记为 0。
        """
        result = RegionCultivationResult(
            region_id=region.id, region_name=region.name
        )

        if not panel_open or calibration.panel_roi is None:
            result.low_confidence.append(
                {
                    "region_id": region.id,
                    "reason": "panel_not_open_or_not_calibrated",
                }
            )
            return result

        panel_img = calibration.panel_roi.crop(img)
        self._save_debug(panel_img, f"{region.id}_panel.png")

        # 1. 检测所有编号方块和加分文字
        expected_count = len(calibration.slots)
        score_texts = self._detect_score_texts(panel_img, calibration.panel_roi)

        # 优先使用模板匹配识别编号（对艺术字/发光更鲁棒）
        number_detections = self._detect_slot_numbers_by_template(
            panel_img, expected_count
        )
        if len(number_detections) == expected_count:
            squares = [(x, y, w, h) for _, x, y, w, h, _ in number_detections]
        else:
            # 模板匹配失败时回退到边缘检测
            raw_squares = self._detect_slot_squares(panel_img, calibration.panel_roi)
            squares = self._select_best_squares(raw_squares, expected_count)
            if len(squares) != expected_count:
                result.low_confidence.append(
                    {
                        "region_id": region.id,
                        "reason": "slot_count_mismatch",
                        "expected": expected_count,
                        "detected": len(squares),
                        "template_detected": len(number_detections),
                        "raw_detected": len(raw_squares),
                    }
                )

        if not squares:
            return result

        # 2. 把检测到的方块与拓扑中的 number 对应
        slot_calibs = sorted(calibration.slots, key=lambda s: s.number)
        if len(number_detections) == expected_count:
            # 模板匹配已给出 number，直接按 number 对应
            number_to_square = {
                number: (x, y, w, h) for number, x, y, w, h, _ in number_detections
            }
            for sc in slot_calibs:
                square = number_to_square.get(sc.number)
                if square is None:
                    result.slots.append(
                        SlotCultivationValue(
                            slot_id=sc.slot_id,
                            number=sc.number,
                            score=0.0,
                            confidence=0.0,
                            raw_text="",
                        )
                    )
                    continue
                sx, sy, sw, sh = square
                value, conf, raw_text = self._read_score_near_square(
                    sx, sy, sw, sh, score_texts
                )
                result.slots.append(
                    SlotCultivationValue(
                        slot_id=sc.slot_id,
                        number=sc.number,
                        score=value if value is not None else 0.0,
                        confidence=conf,
                        raw_text=raw_text,
                    )
                )
                if value is None and raw_text:
                    result.low_confidence.append(
                        {
                            "region_id": region.id,
                            "slot_id": sc.slot_id,
                            "reason": "score_text_found_but_parse_failed",
                            "raw_text": raw_text,
                        }
                    )
        else:
            # 回退：按几何位置排序，依次对应 1..N
            panel_cx = panel_img.shape[1] / 2
            panel_cy = panel_img.shape[0] / 2

            def _vec(item):
                x, y, w, h = item
                return (x + w / 2 - panel_cx, y + h / 2 - panel_cy)

            def _cross(a, b):
                return a[0] * b[1] - a[1] * b[0]

            def _dot(a, b):
                return a[0] * b[0] + a[1] * b[1]

            anchor = min(squares, key=lambda s: s[1] + s[3] / 2)
            anchor_vec = _vec(anchor)

            def _rel_angle(item):
                v = _vec(item)
                return math.atan2(-_cross(anchor_vec, v), _dot(anchor_vec, v)) % (
                    2 * math.pi
                )

            sorted_squares = sorted(squares, key=_rel_angle)
            for idx, sc in enumerate(slot_calibs):
                if idx >= len(sorted_squares):
                    result.slots.append(
                        SlotCultivationValue(
                            slot_id=sc.slot_id,
                            number=sc.number,
                            score=0.0,
                            confidence=0.0,
                            raw_text="",
                        )
                    )
                    continue

                sx, sy, sw, sh = sorted_squares[idx]
                value, conf, raw_text = self._read_score_near_square(
                    sx, sy, sw, sh, score_texts
                )
                result.slots.append(
                    SlotCultivationValue(
                        slot_id=sc.slot_id,
                        number=sc.number,
                        score=value if value is not None else 0.0,
                        confidence=conf,
                        raw_text=raw_text,
                    )
                )
                if value is None and raw_text:
                    result.low_confidence.append(
                        {
                            "region_id": region.id,
                            "slot_id": sc.slot_id,
                            "reason": "score_text_found_but_parse_failed",
                            "raw_text": raw_text,
                        }
                    )

        return result

    def _read_score_near_square(
        self,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        score_texts: List[Tuple[str, int, int, int, int, float]],
    ) -> tuple[Optional[float], float, str]:
        """读取某个编号方块附近的加分文字。"""
        square_cx = sx + sw // 2
        square_bottom = sy + sh

        best = None
        best_dist = float("inf")
        for text, x, y, w, h, conf in score_texts:
            score_cx = x + w // 2
            score_cy = y + h // 2
            dx = abs(score_cx - square_cx)
            dy = score_cy - square_bottom
            if dy < -20:  # 加分文字不应在方块上方
                continue
            dist = dx * 0.5 + max(0, dy)
            if dist < best_dist:
                best_dist = dist
                best = (text, conf)

        if best is None or best_dist > 150:
            return None, 0.0, ""

        raw_text, conf = best
        score = self._parse_score(raw_text)
        if score is None:
            return None, 0.0, raw_text
        return score, conf, raw_text

    def _detect_slot_numbers_by_template(
        self,
        panel_img: np.ndarray,
        expected_count: int,
    ) -> List[Tuple[int, int, int, int, int, float]]:
        """使用模板匹配定位面板中的孔位编号。

        返回 [(number, x, y, w, h, confidence)]，坐标相对 panel_img。
        若对应孔位数的模板目录不存在，返回空列表，调用方应回退到图像检测。
        """
        templates = self._load_number_templates(expected_count)
        if not templates:
            return []

        target_names = _NUMBER_TEMPLATE_NAMES[:expected_count]
        candidates: List[dict] = []
        for num_name in target_names:
            imgs = templates.get(num_name)
            if not imgs:
                continue
            candidates.extend(self._match_number_candidates(panel_img, imgs, num_name))

        assigned = self._nms_assign_candidates(candidates, target_names)
        results: List[Tuple[int, int, int, int, int, float]] = []
        for num_name in target_names:
            if num_name not in assigned:
                continue
            c = assigned[num_name]
            number = _NUMBER_CHAR_TO_INT[_NUMBER_NAME_TO_CHAR[num_name]]
            results.append((number, c["x"], c["y"], c["w"], c["h"], c["conf"]))
        return sorted(results, key=lambda r: r[0])

    @staticmethod
    def _load_number_templates(expected_count: int) -> Dict[str, List[np.ndarray]]:
        """加载数字模板图像，包含同数字在不同孔位数/状态（激活/未激活）下的变体。"""
        templates: Dict[str, List[np.ndarray]] = {}
        if not _TEMPLATE_DIR.exists():
            return templates
        # 加载所有按孔位数分子目录中的模板，增加状态多样性
        for subdir in _TEMPLATE_DIR.iterdir():
            if not subdir.is_dir() or not subdir.name.isdigit():
                continue
            for name in _NUMBER_TEMPLATE_NAMES[:expected_count]:
                path = subdir / f"{name}.png"
                if path.exists():
                    img = cv2.imread(str(path))
                    if img is not None:
                        templates.setdefault(name, []).append(img)
        return templates

    @staticmethod
    def _match_number_candidates(
        panel_img: np.ndarray,
        templates: List[np.ndarray],
        num_name: str,
        top_k: int = 3,
    ) -> List[dict]:
        """对一组模板做多尺度匹配，返回候选检测框。"""
        candidates: List[dict] = []
        scales = np.linspace(0.6, 1.5, 20)
        for template in templates:
            for scale in scales:
                resized = cv2.resize(
                    template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                )
                th, tw = resized.shape[:2]
                if th > panel_img.shape[0] or tw > panel_img.shape[1]:
                    continue
                result = cv2.matchTemplate(panel_img, resized, cv2.TM_CCOEFF_NORMED)
                for _ in range(top_k):
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val < 0.45:
                        break
                    x = max_loc[0]
                    y = max_loc[1]
                    # 过滤掉几乎没有纹理的匹配（避免纯黑/纯背景误检）
                    patch = panel_img[y : y + th, x : x + tw]
                    if patch.size == 0 or np.std(patch) < 15:
                        result[max_loc[1], max_loc[0]] = 0
                        continue
                    if SlotCultivationScanner._patch_edge_density(patch) < 0.03:
                        result[max_loc[1], max_loc[0]] = 0
                        continue
                    candidates.append(
                        {
                            "name": num_name,
                            "x": x,
                            "y": y,
                            "w": tw,
                            "h": th,
                            "conf": float(max_val),
                            "scale": float(scale),
                        }
                    )
                    # 抑制邻域，避免同一峰重复
                    half_h = max(th // 2, 1)
                    half_w = max(tw // 2, 1)
                    y1 = max(0, max_loc[1] - half_h)
                    y2 = min(result.shape[0], max_loc[1] + half_h + 1)
                    x1 = max(0, max_loc[0] - half_w)
                    x2 = min(result.shape[1], max_loc[0] + half_w + 1)
                    result[y1:y2, x1:x2] = 0
        return candidates

    @staticmethod
    def _nms_assign_candidates(
        candidates: List[dict],
        target_names: List[str],
        iou_threshold: float = 0.3,
    ) -> Dict[str, dict]:
        """对候选框做 NMS 贪心分配，确保每个数字只保留一个最佳框。"""
        candidates = sorted(candidates, key=lambda c: c["conf"], reverse=True)
        assigned: Dict[str, dict] = {}
        picked_boxes: List[Tuple[float, float, float, float]] = []

        def box_of(c):
            return (c["x"], c["y"], c["w"], c["h"])

        def iou(a, b):
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            inter_x1 = max(ax, bx)
            inter_y1 = max(ay, by)
            inter_x2 = min(ax + aw, bx + bw)
            inter_y2 = min(ay + ah, by + bh)
            if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
                return 0.0
            inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            return inter / (aw * ah + bw * bh - inter)

        for c in candidates:
            if c["name"] in assigned:
                continue
            bb = box_of(c)
            if any(iou(bb, pb) > iou_threshold for pb in picked_boxes):
                continue
            assigned[c["name"]] = c
            picked_boxes.append(bb)
            if set(assigned.keys()) >= set(target_names):
                break
        return assigned

    def _detect_slot_squares(
        self,
        panel_img: np.ndarray,
        panel_roi: ROI,
    ) -> List[Tuple[int, int, int, int]]:
        """通过边缘检测定位面板中的孔位编号方块。

        返回 [(x, y, w, h)]，坐标为相对 panel_img 的坐标（未加 panel_roi 偏移）。
        """
        gray = cv2.cvtColor(panel_img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        h, w = panel_img.shape[:2]
        panel_cx, panel_cy = w / 2, h / 2
        center_radius = min(w, h) * 0.28
        min_area = int(h * w * 0.005)
        max_area = int(h * w * 0.10)

        candidates: List[Tuple[int, int, int, int]] = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            aspect = bw / max(bh, 1)
            if not (min_area < area < max_area and 0.75 < aspect < 1.35):
                continue

            # 过滤掉面板中心的装饰/圆盘
            cx, cy = x + bw / 2, y + bh / 2
            dist_to_center = ((cx - panel_cx) ** 2 + (cy - panel_cy) ** 2) ** 0.5
            if dist_to_center < center_radius:
                continue

            candidates.append((x, y, bw, bh))

        # 按面积从大到小排序，丢弃几乎完全包含在更大框内的小框
        candidates = sorted(candidates, key=lambda r: r[2] * r[3], reverse=True)
        filtered: List[Tuple[int, int, int, int]] = []
        for x, y, bw, bh in candidates:
            area = bw * bh
            contained = False
            for fx, fy, fw, fh in filtered:
                ix = max(0, min(x + bw, fx + fw) - max(x, fx))
                iy = max(0, min(y + bh, fy + fh) - max(y, fy))
                inter = ix * iy
                # 若当前框 80% 以上面积被已有大框包含，则丢弃
                if inter / max(area, 1) > 0.8:
                    contained = True
                    break
                # 若与已有大框高度重叠，也丢弃
                union = area + fw * fh - inter
                if union > 0 and inter / union > 0.5:
                    contained = True
                    break
            if not contained:
                filtered.append((x, y, bw, bh))

        return filtered

    def _select_best_squares(
        self,
        candidates: List[Tuple[int, int, int, int]],
        expected_count: int,
    ) -> List[Tuple[int, int, int, int]]:
        """从候选方块中选出最可能的 N 个真实孔位方块。

        策略：真实孔位方块面积相近，且围绕面板中心分布。
        按面积排序后，选择面积最集中的 N 个连续窗口。
        """
        if len(candidates) <= expected_count:
            return candidates

        # 按面积排序
        sorted_by_area = sorted(candidates, key=lambda s: s[2] * s[3])
        areas = [s[2] * s[3] for s in sorted_by_area]

        best_start = 0
        best_var = float("inf")
        for i in range(len(sorted_by_area) - expected_count + 1):
            window = areas[i : i + expected_count]
            var = float(np.var(window))
            if var < best_var:
                best_var = var
                best_start = i

        return sorted_by_area[best_start : best_start + expected_count]

    def _detect_score_texts(
        self,
        panel_img: np.ndarray,
        panel_roi: ROI,
    ) -> List[Tuple[str, int, int, int, int, float]]:
        """在左侧主面板中检测所有「孔位评分：+XXXX」类加分文字。

        返回 [(text, x, y, w, h, confidence)]，坐标为相对 panel_img 的坐标。
        """
        results = self.backend.recognize_with_boxes(panel_img)
        score_texts: List[Tuple[str, int, int, int, int, float]] = []
        for r in results:
            if not r.bbox:
                continue
            text = r.text.replace(" ", "")
            if not self._looks_like_score_text(text):
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            x1, y1 = min(xs), min(ys)
            x2, y2 = max(xs), max(ys)
            score_texts.append(
                (
                    text,
                    x1,
                    y1,
                    x2 - x1,
                    y2 - y1,
                    r.confidence or 0.0,
                )
            )
        return score_texts

    @staticmethod
    def _looks_like_score_text(text: str) -> bool:
        """判断 OCR 文字是否像加分文字。"""
        if "孔位评分" in text:
            return True
        if "评分" in text and re.search(r"\+", text):
            return True
        return False

    @staticmethod
    def _detect_slot_numbers(
        panel_img: np.ndarray,
        panel_roi: ROI,
        backend: OCRBackend,
    ) -> List[Tuple[int, int, int, int, int, float]]:
        """检测左侧主面板中的孔位编号 ROI。

        返回 [(number, x, y, w, h, confidence)]，坐标为相对原图的绝对坐标。
        支持中文大写数字（壹贰叁肆……）以及阿拉伯数字。
        """
        results = backend.recognize_with_boxes(panel_img)
        numbers: List[Tuple[int, int, int, int, int, float]] = []
        for r in results:
            if not r.bbox:
                continue
            text = r.text.replace(" ", "")
            number = SlotCultivationScanner._parse_slot_number(text)
            if number is None:
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            x1, y1 = min(xs), min(ys)
            x2, y2 = max(xs), max(ys)
            numbers.append(
                (
                    number,
                    x1 + panel_roi.x,
                    y1 + panel_roi.y,
                    x2 - x1,
                    y2 - y1,
                    r.confidence or 0.0,
                )
            )
        return numbers

    @staticmethod
    def _patch_edge_density(patch: np.ndarray, shrink: float = 0.1) -> float:
        """计算图像块内部（避开外框）的 Canny 边缘占比。"""
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        y1 = int(h * shrink)
        y2 = int(h * (1 - shrink))
        x1 = int(w * shrink)
        x2 = int(w * (1 - shrink))
        inner = gray[y1:y2, x1:x2]
        if inner.size == 0:
            return 0.0
        edges = cv2.Canny(inner, 50, 150)
        return float(np.count_nonzero(edges) / inner.size)

    @staticmethod
    def _parse_slot_number(text: str) -> Optional[int]:
        """从 OCR 文字中解析孔位编号。

        优先匹配单个中文大写数字（壹/贰/叁/肆……），其次匹配孤立的阿拉伯数字。
        若文本像加分文字（含 +、分、评分等），则直接跳过，避免把 +3600 误当编号 3。
        """
        # 先排除明显的加分/非编号文字
        if any(kw in text for kw in ("孔位评分", "评分", "分", "+", "提升")):
            return None

        # 优先单个中文大写数字
        cleaned = "".join(ch for ch in text if ch in _SLOT_NUMBER_MAP)
        if len(cleaned) == 1:
            return _SLOT_NUMBER_MAP[cleaned]

        # 兼容 OCR 把编号和周围文字连起来的情况，如 "壹孔位"
        for ch in text:
            if ch in _SLOT_NUMBER_MAP:
                return _SLOT_NUMBER_MAP[ch]
        return None

    @staticmethod
    def _parse_score(text: str) -> Optional[float]:
        """从 OCR 文字中解析加分数值。"""
        # 优先匹配「孔位评分：+3600」格式
        match = _SCORE_TEXT_PATTERN.search(text)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                pass

        for pattern in _SCORE_PATTERNS:
            match = pattern.search(text)
            if match:
                raw = match.group(1).replace(",", "")
                try:
                    return float(raw)
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------
    # 校准 / 探测
    # ------------------------------------------------------------------
    def calibrate_panel(
        self,
        img: np.ndarray,
        region_id: str,
        panel_roi: Optional[ROI] = None,
    ) -> dict:
        """检测左侧主面板中的孔位编号和加分文字，返回供标定。

        输出包含：
        - number_candidates: 检测到的编号 ROI 列表；
        - score_candidates: 检测到的加分文字 ROI 列表；
        - texts: 所有 OCR 原始文字。
        """
        if panel_roi is None:
            h, w = img.shape[:2]
            panel_roi = ROI(
                name=f"{region_id}_panel",
                x=0,
                y=int(h * 0.15),
                width=int(w * 0.48),
                height=int(h * 0.75),
            )

        panel_img = panel_roi.crop(img)
        results = self.backend.recognize_with_boxes(panel_img)

        texts = []
        score_candidates = []
        number_candidates = []
        for r in results:
            if not r.bbox:
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            x1, y1 = min(xs), min(ys)
            x2, y2 = max(xs), max(ys)
            entry = {
                "text": r.text,
                "x": x1 + panel_roi.x,
                "y": y1 + panel_roi.y,
                "w": x2 - x1,
                "h": y2 - y1,
                "confidence": r.confidence,
            }
            texts.append(entry)

            text_clean = r.text.replace(" ", "")

            # 加分文字
            if self._looks_like_score_text(text_clean):
                score = self._parse_score(text_clean)
                score_candidates.append(
                    {
                        **entry,
                        "parsed_score": score,
                    }
                )

            # 孔位编号
            number = self._parse_slot_number(text_clean)
            if number is not None:
                number_candidates.append(
                    {
                        **entry,
                        "parsed_number": number,
                    }
                )

        return {
            "region_id": region_id,
            "panel_roi": {
                "name": panel_roi.name,
                "x": panel_roi.x,
                "y": panel_roi.y,
                "width": panel_roi.width,
                "height": panel_roi.height,
            },
            "texts": texts,
            "number_candidates": number_candidates,
            "score_candidates": score_candidates,
        }

    # ------------------------------------------------------------------
    # 调试与保存
    # ------------------------------------------------------------------
    def _save_debug(self, img: np.ndarray, filename: str) -> Optional[Path]:
        if self.output_dir is None:
            return None
        path = self.output_dir / filename
        try:
            cv2.imwrite(str(path), img)
            return path
        except Exception:
            return None

    def save_result(
        self,
        result: SlotCultivationScanResult,
        output_path: Optional[Path] = None,
    ) -> Path:
        """将扫描结果保存为 JSON。"""
        target = output_path or self.output_dir / "slot_cultivation.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "regions": [
                {
                    "region_id": rr.region_id,
                    "region_name": rr.region_name,
                    "locked": rr.locked,
                    "slots": [
                        {
                            "slot_id": sv.slot_id,
                            "number": sv.number,
                            "cultivation_score": sv.score,
                            "confidence": sv.confidence,
                            "raw_text": sv.raw_text,
                        }
                        for sv in rr.slots
                    ],
                    "low_confidence": rr.low_confidence,
                }
                for rr in result.region_results
            ],
            "locked_region_ids": result.locked_region_ids,
            "screenshots": result.screenshots,
        }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
