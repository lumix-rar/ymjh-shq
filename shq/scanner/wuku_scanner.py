"""武库山河器扫描器。

职责单一：在调用方已经导航到武库网格界面的前提下，扫描并解析玩家已获得的山河器。
不处理导航、不读取收集度。

实现为真正的生产者-消费者流水线：
- 主线程（生产者）逐屏点击每一个格子并保存详情截图；
- 后台线程（消费者）在截图过程中就并发 OCR 解析，判断右侧面板是“未获得”还是“等级 X级”，
  已获取则解析属性。

不依赖图标视觉阈值，能稳定识别所有等级（包括 0 级）的已获得山河器。
"""

from __future__ import annotations

import ctypes
import difflib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import ImageGrab

from shq.models import Affix, Element, Quality, Shanheqi, ShanheqiType
from shq.scanner.constants import QUALITY_NAME_TO_ENUM, SUB_TAG_TO_TYPE, TYPE_TO_SUB_TAG
from shq.scanner.input_simulator import InputSimulator
from shq.scanner.name_resolver import ShanheqiNameResolver
from shq.scanner.ocr_scanner import OCRBackend, RapidOCRBackend
from shq.scanner.window_capture import (
    DEFAULT_CLIENT_HEIGHT,
    DEFAULT_CLIENT_WIDTH,
    ROI,
    WindowCapture,
)


# 派生素蕴白名单
DERIVED_AFFIX_NAMES = ("起势", "承势", "金实", "火实", "木实", "水实", "土实")

DETAIL_PANEL_ROI = ROI("detail", 720, 80, 530, 640)
ELEMENT_ICON_ROI = ROI("element", 1090, 90, 70, 70)

MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

# 武库左上角品质下拉框坐标（基于 1334x750 客户区）
QUALITY_DROPDOWN_BUTTON = (140, 119)
QUALITY_OPTION_POS = {
    "全部": (140, 119),
    "朴素": (160, 184),
    "精巧": (160, 255),
    "瑰丽": (160, 326),
    "绝世": (180, 396),
}


def _safe_print(text: str) -> None:
    """兼容 Windows 终端编码的输出。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "ignore").decode("ascii"))


@dataclass
class CellInfo:
    """武库网格中的一个单元格信息。"""

    center_x: int
    center_y: int
    name: str = ""
    level: int = 0
    derived_tags: List[str] = field(default_factory=list)
    raw_texts: List[Tuple[str, float]] = field(default_factory=list)
    min_conf: float = 1.0
    col: int = 0
    row_in_screen: int = 0


@dataclass
class ScanResult:
    """一次武库扫描的结果。"""

    shanheqis: List[Shanheqi] = field(default_factory=list)
    low_confidence: List[dict] = field(default_factory=list)
    screenshots: Dict[str, str] = field(default_factory=dict)


@dataclass
class PendingDetail:
    """等待后台解析的详情截图与对应格子信息。"""

    step: int
    row: int
    col: int
    cell_name: str
    detail_path: Path
    grid_img_path: Path
    center_x: int = 0
    center_y: int = 0


class WukuScanner:
    """武库山河器扫描器。"""

    def __init__(
        self,
        ocr_backend: Optional[OCRBackend] = None,
        confidence_threshold: float = 0.5,
        output_dir: Optional[Path] = None,
        fixed_size: bool = True,
        parse_workers: int = 4,
    ):
        self.backend = ocr_backend or RapidOCRBackend()
        self.conf_threshold = confidence_threshold
        self.output_dir = output_dir or Path.cwd() / "wuku_scan"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fixed_size = fixed_size
        self.parse_workers = max(1, parse_workers)

        self._cap: Optional[WindowCapture] = None
        self._hwnd: Optional[int] = None
        self._sim = InputSimulator(default_delay=0.5)

        # 名字归一化解析器（基于本地底稿校正 OCR 名字错误）
        self._name_resolver = ShanheqiNameResolver()
        self._current_quality: Optional[str] = None

        # 每个消费者线程拥有独立的 OCR 后端
        self._worker_local = threading.local()

    # ------------------------------------------------------------------
    # 窗口 / 截图 / 点击 / 滚动
    # ------------------------------------------------------------------
    def _get_hwnd(self) -> int:
        if self._hwnd is not None:
            return self._hwnd
        from shq.config import YMJH_PROCESS_RULE
        import psutil

        hwnd = None
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                if proc.info["name"] and proc.info["name"].lower() in [
                    n.lower() for n in YMJH_PROCESS_RULE.get("names", [])
                ]:
                    hwnd = WindowCapture.find_by_pid(proc.info["pid"])
                    if hwnd:
                        break
        except Exception:
            pass

        if hwnd is None:
            for title in YMJH_PROCESS_RULE.get("window_titles", []):
                hwnd = WindowCapture.find_by_title(title)
                if hwnd:
                    break

        if hwnd is None:
            raise RuntimeError("未找到一梦江湖窗口")
        self._hwnd = hwnd
        self._cap = WindowCapture(hwnd)
        return hwnd

    def _bring_to_front(self) -> None:
        hwnd = self._get_hwnd()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)

        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)

        attached = False
        try:
            if fg_tid and target_tid and fg_tid != target_tid:
                user32.AttachThreadInput(fg_tid, target_tid, True)
                attached = True
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.SwitchToThisWindow(hwnd, True)
        finally:
            if attached:
                user32.AttachThreadInput(fg_tid, target_tid, False)

        time.sleep(0.5)

    def _ensure_fixed_size(self) -> None:
        if not self.fixed_size:
            return
        cap = self._cap or WindowCapture(self._get_hwnd())
        ok = cap.ensure_client_size(DEFAULT_CLIENT_WIDTH, DEFAULT_CLIENT_HEIGHT)
        if not ok:
            ok = cap.resize_client(DEFAULT_CLIENT_WIDTH, DEFAULT_CLIENT_HEIGHT)
            if not ok:
                raise RuntimeError(
                    f"无法将游戏窗口调整为 {DEFAULT_CLIENT_WIDTH}x{DEFAULT_CLIENT_HEIGHT}"
                )
        size = cap.get_client_size()
        if size != (DEFAULT_CLIENT_WIDTH, DEFAULT_CLIENT_HEIGHT):
            raise RuntimeError(f"窗口大小仍为 {size}，无法固定为基准分辨率")

    def _capture(self, debug_name: Optional[str] = None) -> np.ndarray:
        self._bring_to_front()
        cap = self._cap or WindowCapture(self._get_hwnd())
        rect = cap.get_rect()
        if rect is None:
            raise RuntimeError("无法获取游戏窗口客户区矩形")

        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        if debug_name:
            path = self.output_dir / f"{debug_name}.png"
            cv2.imwrite(str(path), img_cv)
        return img_cv

    def _click_client(self, cx: int, cy: int, delay: float = 0.5) -> None:
        self._bring_to_front()
        self._sim.click_on_window(self._get_hwnd(), cx, cy, attach_thread=True)
        time.sleep(delay)

    def _scroll_grid(self, clicks: int = -3) -> None:
        self._bring_to_front()
        # 先点击网格区域，确保游戏内部焦点在可滚动的列表上
        self._click_client(300, 400, delay=0.3)
        user32 = ctypes.windll.user32
        delta = -WHEEL_DELTA if clicks < 0 else WHEEL_DELTA
        for _ in range(abs(clicks)):
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
            time.sleep(0.15)
        time.sleep(0.5)

    def _select_quality(self, quality: str) -> None:
        """通过左上角下拉框选择指定品质。"""
        if quality not in QUALITY_OPTION_POS:
            raise ValueError(f"不支持的品质：{quality}，可选：{list(QUALITY_OPTION_POS.keys())}")

        _safe_print(f"[品质] 选择：{quality}")
        # 打开下拉框
        self._click_client(QUALITY_DROPDOWN_BUTTON[0], QUALITY_DROPDOWN_BUTTON[1], delay=0.5)
        time.sleep(0.3)
        # 点击目标品质
        pos = QUALITY_OPTION_POS[quality]
        self._click_client(pos[0], pos[1], delay=0.5)
        time.sleep(0.8)  # 等待网格刷新

    def _scroll_to_top(self) -> None:
        """持续向上滚动，直到连续两屏网格画面几乎相同。"""
        _safe_print("[扫描] 滚动到顶部...")
        top_attempts = 0
        max_top_attempts = 20
        prev_top_hash: Optional[str] = None
        while top_attempts < max_top_attempts:
            self._scroll_grid(5)
            time.sleep(0.3)
            top_img = self._capture("_top_check")
            top_hash = self._grid_hash(top_img)
            if prev_top_hash is not None:
                dist = self._hash_distance(top_hash, prev_top_hash)
                if dist <= 5:
                    _safe_print(f"[扫描] 已到达顶部（hash 距离 {dist}）")
                    break
            prev_top_hash = top_hash
            top_attempts += 1
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # 网格扫描
    # ------------------------------------------------------------------
    def _detect_cells(self, img: np.ndarray) -> List[CellInfo]:
        """基于 OCR 文本框聚类，定位武库网格中的每个格子。"""
        grid_x, grid_y, grid_w, grid_h = 60, 140, 500, 560
        grid_crop = img[grid_y : grid_y + grid_h, grid_x : grid_x + grid_w]
        results = self.backend.recognize_with_boxes(grid_crop)

        boxes: List[Tuple[str, float, Tuple[float, float]]] = []
        for r in results:
            if not r.bbox:
                continue
            xs = [p[0] for p in r.bbox]
            ys = [p[1] for p in r.bbox]
            cx = sum(xs) / len(xs) + grid_x
            cy = sum(ys) / len(ys) + grid_y
            boxes.append((r.text, r.confidence, (cx, cy)))

        # 按 y 聚类成行
        boxes.sort(key=lambda b: b[2][1])
        rows: List[List[Tuple[str, float, Tuple[float, float]]]] = []
        for item in boxes:
            _, _, (_, cy) = item
            placed = False
            for row in rows:
                avg_y = sum(b[2][1] for b in row) / len(row)
                if abs(cy - avg_y) < 60:
                    row.append(item)
                    placed = True
                    break
            if not placed:
                rows.append([item])

        cells: List[CellInfo] = []
        for row_idx, row in enumerate(rows):
            row.sort(key=lambda b: b[2][0])
            cols: List[List[Tuple[str, float, Tuple[float, float]]]] = []
            for item in row:
                _, _, (cx, _) = item
                placed = False
                for col in cols:
                    avg_x = sum(b[2][0] for b in col) / len(col)
                    if abs(cx - avg_x) < 80:
                        col.append(item)
                        placed = True
                        break
                if not placed:
                    cols.append([item])

            for col_idx, col in enumerate(cols):
                texts = [t for t, _, _ in col]
                confs = [c for _, c, _ in col]
                joined = "".join(texts)
                min_conf = min(confs) if confs else 1.0
                cell_cx = int(sum(b[2][0] for b in col) / len(col))
                cell_cy = int(sum(b[2][1] for b in col) / len(col))

                has_level = "级" in joined and any(ch.isdigit() for ch in joined)
                level_match = re.search(r"(\d+)级", joined)
                level = int(level_match.group(1)) if level_match else 0

                col_sorted_y = sorted(col, key=lambda b: b[2][1])
                name = ""
                for t, _, _ in col_sorted_y:
                    cleaned = re.sub(r"[^一-龥]", "", t)
                    if (
                        len(cleaned) >= 2
                        and cleaned not in DERIVED_AFFIX_NAMES
                        and not any(ch.isdigit() for ch in t)
                        and "级" not in t
                    ):
                        name = cleaned
                        break
                if not name:
                    for t, _, _ in col_sorted_y:
                        cleaned = re.sub(r"[^一-龥]", "", t)
                        if len(cleaned) >= 2 and cleaned not in DERIVED_AFFIX_NAMES:
                            name = cleaned
                            break

                derived_tags = [d for d in DERIVED_AFFIX_NAMES if d in joined]

                cells.append(
                    CellInfo(
                        center_x=cell_cx,
                        center_y=cell_cy,
                        name=name,
                        level=level,
                        derived_tags=derived_tags,
                        raw_texts=[(t, c) for t, c, _ in col],
                        min_conf=min_conf,
                        col=col_idx,
                        row_in_screen=row_idx,
                    )
                )
        return cells

    @staticmethod
    def _grid_hash(grid_img: np.ndarray) -> str:
        """计算网格区域 dhash，用于判断滚动是否到达底部。"""
        # 武库网格大致区域
        crop = grid_img[140:700, 60:560]
        if crop.size == 0:
            return ""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (17, 16), interpolation=cv2.INTER_AREA)
        bits = (small[:, 1:] > small[:, :-1]).flatten().tolist()
        return "".join("1" if b else "0" for b in bits)

    @staticmethod
    def _hash_distance(a: str, b: str) -> int:
        if len(a) != len(b):
            return 999
        return sum(c1 != c2 for c1, c2 in zip(a, b))

    # ------------------------------------------------------------------
    # 详情解析
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_detail_impl(
        detail_img: np.ndarray,
        cell: CellInfo,
        grid_img: np.ndarray,
        backend: OCRBackend,
        conf_threshold: float,
    ) -> Tuple[Shanheqi, float, List[str]]:
        """解析单张详情截图，不依赖实例状态。"""
        issues: List[str] = []
        texts = backend.recognize(DETAIL_PANEL_ROI.crop(detail_img))
        lines = [t for t, _ in texts]
        confs = [conf for _, conf in texts]
        min_conf = min(confs) if confs else 0.0

        joined = "\n".join(lines)

        # 精确排除：右侧面板出现“未获得/未获取”视为未获取
        if "未获得" in joined or "未获取" in joined:
            return None  # type: ignore[return-value]

        name = cell.name
        if not name and lines:
            name = re.sub(r"[^一-龥]", "", lines[0])
        if not name or len(name) < 2:
            issues.append("未识别到有效名称")
        elif name in DERIVED_AFFIX_NAMES:
            issues.append(f"名称疑似派生素蕴标签：{name}")

        # 解析等级：已获取山河器必显示“等级 X级”，0级也不例外。
        # OCR 可能把“等级”和“X级”分成两行或顺序颠倒，所以用更宽松的方式。
        level = cell.level
        if not level:
            # 优先匹配“等级 X级”或“X级 等级”
            m = re.search(r"等级\s*(\d+)\s*级", joined)
            if not m:
                m = re.search(r"(\d+)\s*级\s*等级", joined)
            if m:
                level = int(m.group(1))
            else:
                # 兜底：找所有“X级”，取数值最小的那个（避免 affix 的 16 级干扰）
                levels = [int(x) for x in re.findall(r"(\d+)\s*级", joined)]
                if levels:
                    level = min(levels)
                else:
                    issues.append("未识别到等级")

        score_matches = re.findall(r"[评平]分[：:]\s*(\d+)", joined)
        score = max((int(s) for s in score_matches), default=0)
        if not score:
            issues.append("未识别到评分")

        stats: Dict[str, float] = {}
        in_stats = False
        for line in lines:
            if "主属性" in line:
                in_stats = True
                continue
            if any(k in line for k in ("专属词条", "评分", "派生素蕴")):
                in_stats = False
                continue
            if in_stats:
                m = re.match(r"(.+?)[：:]\s*([\d\.]+)", line)
                if m:
                    key = m.group(1).strip()
                    if key in ("评分", "平分"):
                        continue
                    stats[key] = float(m.group(2))

        affixes: List[Affix] = []
        for line in lines:
            m = re.match(r"(\d+)级(.)之力[，,]评分[：:]\s*(\d+)", line)
            if m:
                affixes.append(
                    Affix(
                        name=f"{m.group(2)}之力",
                        element=WukuScanner._element_char_to_enum(m.group(2)),
                        level=int(m.group(1)),
                        score=float(m.group(3)),
                    )
                )

        derived: set[str] = set(cell.derived_tags)
        in_derived = False
        for line in lines:
            if "派生素蕴" in line:
                in_derived = True
                continue
            if in_derived:
                found = {d for d in DERIVED_AFFIX_NAMES if d in line}
                derived.update(found)
                if "复归" in line or not line.strip():
                    in_derived = False

        element = WukuScanner._classify_element(detail_img)
        if element is None:
            if affixes:
                elems = [a.element for a in affixes if a.element]
                if elems:
                    element = max(set(elems), key=elems.count)
            if element is None:
                issues.append("未识别到五行")

        # 品质暂未启用颜色校准，不视为解析问题
        quality = None

        shq_type = WukuScanner._detect_special_tag(grid_img, cell.center_x, cell.center_y)
        if shq_type is None:
            shq_type = ShanheqiType.NORMAL

        shq = Shanheqi(
            id=f"wuku_{name}_{level}",
            name=name,
            quality=quality or Quality.SIMPLE,
            element=element or Element.METAL,
            shanheqi_type=shq_type,
            level=level,
            gongguan_level=len(affixes),
            base_score=float(score),
            affixes=affixes,
            derived_affixes=sorted(derived),
            stats=stats,
        )

        if min_conf < conf_threshold:
            issues.append(f"最低 OCR 置信度 {min_conf:.2f} 低于阈值 {conf_threshold}")

        return shq, min_conf, issues

    def _parse_detail(
        self,
        detail_img: np.ndarray,
        cell: CellInfo,
        grid_img: np.ndarray,
    ) -> Tuple[Shanheqi, float, List[str]]:
        return self._parse_detail_impl(
            detail_img, cell, grid_img, self.backend, self.conf_threshold
        )

    @staticmethod
    def _element_char_to_enum(ch: str) -> Optional[Element]:
        mapping = {
            "金": Element.METAL,
            "木": Element.WOOD,
            "水": Element.WATER,
            "火": Element.FIRE,
            "土": Element.EARTH,
        }
        return mapping.get(ch)

    # ------------------------------------------------------------------
    # 五行 / 特殊类型 识别
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_element(detail_img: np.ndarray) -> Optional[Element]:
        crop = ELEMENT_ICON_ROI.crop(detail_img)
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = (hsv[:, :, 2] > 80) & (hsv[:, :, 1] > 40)
        if not np.any(mask):
            return None
        mean_h = float(np.mean(hsv[:, :, 0][mask]))

        if mean_h <= 12 or mean_h >= 168:
            return Element.FIRE
        if 12 < mean_h <= 22:
            return Element.EARTH
        if 22 < mean_h <= 38:
            return Element.METAL
        if 38 < mean_h <= 75:
            return Element.WOOD
        if 75 < mean_h <= 130:
            return Element.WATER
        return None

    @staticmethod
    def _detect_special_tag(img: np.ndarray, cx: int, cy: int) -> Optional[ShanheqiType]:
        # 图标大致区域：文字左侧
        icon_x1 = max(0, cx - 100)
        icon_x2 = min(img.shape[1], cx - 30)
        icon_y1 = max(0, cy - 35)
        icon_y2 = min(img.shape[0], cy + 35)
        icon = img[icon_y1:icon_y2, icon_x1:icon_x2]
        if icon.size == 0:
            return None

        hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
        lower_red1 = np.array([0, 100, 80])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([160, 100, 80])
        upper_red2 = np.array([179, 255, 255])
        red_mask = cv2.inRange(hsv, lower_red1, upper_red1) | cv2.inRange(hsv, lower_red2, upper_red2)

        lower_yellow = np.array([15, 100, 80])
        upper_yellow = np.array([40, 255, 255])
        yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

        red_ratio = float(np.sum(red_mask > 0)) / red_mask.size
        yellow_ratio = float(np.sum(yellow_mask > 0)) / yellow_mask.size

        if red_ratio > 0.05:
            return ShanheqiType.XUANSHU
        if yellow_ratio > 0.05:
            return ShanheqiType.ZHUOYI
        return None

    # ------------------------------------------------------------------
    # 去重
    # ------------------------------------------------------------------
    def _is_duplicate(
        self,
        shq: Shanheqi,
        existing: List[Shanheqi],
    ) -> bool:
        for old in existing:
            if shq.name == old.name and shq.quality == old.quality:
                return True
            if (
                shq.quality == old.quality
                and self._same_fingerprint(shq, old)
                and difflib.SequenceMatcher(None, shq.name, old.name).ratio() >= 0.5
            ):
                return True
        return False

    @staticmethod
    def _same_fingerprint(a: Shanheqi, b: Shanheqi) -> bool:
        if a.level != b.level or a.element != b.element or a.base_score != b.base_score:
            return False
        a_affix = sorted(
            (aff.element.value if aff.element else "", aff.level, aff.score)
            for aff in a.affixes
        )
        b_affix = sorted(
            (aff.element.value if aff.element else "", aff.level, aff.score)
            for aff in b.affixes
        )
        if a_affix != b_affix:
            return False
        a_stats = sorted(a.stats.items())
        b_stats = sorted(b.stats.items())
        if a_stats != b_stats:
            return False
        return True

    # ------------------------------------------------------------------
    # 后台消费者
    # ------------------------------------------------------------------
    def _get_worker_backend(self) -> OCRBackend:
        backend = getattr(self._worker_local, "backend", None)
        if backend is None:
            backend = RapidOCRBackend()
            self._worker_local.backend = backend
        return backend

    def _consume_detail(self, pending: PendingDetail) -> Optional[Tuple[Shanheqi, float, List[str]]]:
        try:
            detail_img = cv2.imread(str(pending.detail_path))
            if detail_img is None:
                return None
            grid_img = cv2.imread(str(pending.grid_img_path))
            if grid_img is None:
                return None

            # 基于本地底稿校正 OCR 名字错误
            cell_name = pending.cell_name
            canonical_name, resolver_quality, resolver_sub_tag = self._name_resolver.resolve(
                cell_name, self._current_quality
            )
            if canonical_name != cell_name:
                _safe_print(f"[名字校正] {cell_name} -> {canonical_name}")
                cell_name = canonical_name

            # 构造 CellInfo，保留原始格子坐标以支持特殊标签检测
            cell = CellInfo(
                center_x=pending.center_x,
                center_y=pending.center_y,
                name=cell_name,
            )
            parsed = self._parse_detail_impl(
                detail_img,
                cell,
                grid_img,
                self._get_worker_backend(),
                self.conf_threshold,
            )
            if parsed is None:
                return None
            shq, conf, issues = parsed
            shq = self._finalize_shanheqi(shq, resolver_quality, resolver_sub_tag)
            return shq, conf, issues
        except Exception as exc:
            _safe_print(f"[解析异常] {pending.cell_name}: {exc}")
            return None

    def _finalize_shanheqi(
        self,
        shq: Shanheqi,
        resolver_quality: Optional[str],
        resolver_sub_tag: Optional[str],
    ) -> Shanheqi:
        """根据当前扫描品质和底稿子标签，修正模型字段。

        子标签以底稿（工程化全集）为准，视觉检测仅作冲突校验：
        - 非绝世品质：强制为普通。
        - 绝世品质：按底稿子标签映射为 普通/卓异/玄枢。
        """
        # 1. 品质：以当前扫描品质为准
        scanned_quality = self._current_quality or resolver_quality
        if scanned_quality and scanned_quality in QUALITY_NAME_TO_ENUM:
            shq.quality = QUALITY_NAME_TO_ENUM[scanned_quality]
        if resolver_quality and scanned_quality and resolver_quality != scanned_quality:
            _safe_print(
                f"[品质冲突] {shq.name}: 扫描品质={scanned_quality}, 底稿品质={resolver_quality}"
            )

        # 2. 子标签：以底稿为准
        if shq.quality != Quality.PEERLESS:
            if shq.shanheqi_type != ShanheqiType.NORMAL:
                _safe_print(
                    f"[子标签修正] {shq.name}: {shq.shanheqi_type.value} 不属于非绝世品质，强制为普通"
                )
                shq.shanheqi_type = ShanheqiType.NORMAL
        else:
            # 绝世品质：优先使用底稿子标签
            expected_sub_tag = resolver_sub_tag or "普通"
            expected_type = SUB_TAG_TO_TYPE.get(expected_sub_tag, ShanheqiType.NORMAL)
            visual_sub_tag = TYPE_TO_SUB_TAG.get(shq.shanheqi_type, "普通")
            if shq.shanheqi_type != expected_type:
                _safe_print(
                    f"[子标签修正] {shq.name}: 视觉={visual_sub_tag}, 底稿={expected_sub_tag}, "
                    f"采用底稿"
                )
                shq.shanheqi_type = expected_type
            elif visual_sub_tag != expected_sub_tag:
                _safe_print(
                    f"[子标签冲突] {shq.name}: 视觉={visual_sub_tag}, 底稿={expected_sub_tag}"
                )

        # 3. ID：包含品质、子标签、名字、等级，避免跨品质重名冲突
        sub_tag = TYPE_TO_SUB_TAG.get(shq.shanheqi_type, "普通")
        shq.id = f"wuku_{shq.quality.value}_{sub_tag}_{shq.name}_{shq.level}"
        return shq

    def _process_parsed(
        self,
        parsed: Optional[Tuple[Shanheqi, float, List[str]]],
        detail_path: Path,
        owned_items: List[Shanheqi],
        low_conf_records: List[dict],
    ) -> bool:
        """处理单个解析结果，返回是否成功识别为有效山河器。

        注意：只要解析出有效详情（非“未获得”），就加入 owned_items。
        low_confidence 列表仅作为审计/兜底使用，不替代 owned_items。
        """
        if parsed is None:
            return False
        shq, conf, issues = parsed
        if self._is_duplicate(shq, owned_items):
            _safe_print(f"[去重] {shq.name} 重复，跳过")
            return False

        owned_items.append(shq)
        _safe_print(
            f"[成功] {shq.name} 评分={shq.base_score} 五行={shq.element.value} "
            f"品质={shq.quality.value}"
        )

        if issues or conf < self.conf_threshold:
            record = self._make_record(shq, conf, issues, detail_path)
            low_conf_records.append(record)
            _safe_print(f"[低置信记录] {shq.name}: {issues}; conf={conf:.2f}")
        return True

    # ------------------------------------------------------------------
    # 主流程：生产者-消费者（真正的流水线）
    # ------------------------------------------------------------------
    def _scan_grid(
        self,
        executor: ThreadPoolExecutor,
        max_steps: int = 60,
        scroll_clicks: int = -3,
    ) -> Tuple[List[Shanheqi], List[dict], int, int, List[dict]]:
        """扫描当前网格直到滚动到底，返回识别结果和点击日志。"""
        seen_names: set[str] = set()
        all_cells_log: List[dict] = []
        prev_grid_hash: Optional[str] = None
        no_progress = 0
        step = 0

        owned_items: List[Shanheqi] = []
        low_conf_records: List[dict] = []
        parsed_count = 0
        pending_count = 0
        futures: Dict["concurrent.futures.Future", PendingDetail] = {}

        while step < max_steps:
            _safe_print(f"\n[扫描] 第 {step} 屏")
            grid_img = self._capture(f"grid_step_{step:02d}")
            cells = self._detect_cells(grid_img)

            top_name = next((c.name for c in cells if c.name), None)
            _safe_print(f"       顶部：{top_name}，本屏格子数：{len(cells)}")

            # 保存本屏网格图，供消费者解析玄枢/卓异/品质
            grid_path = self.output_dir / f"grid_step_{step:02d}.png"
            cv2.imwrite(str(grid_path), grid_img)

            # 逐个点击所有 cell（不管是否看起来已获取）
            for cell in cells:
                if not cell.name:
                    continue

                # 按名字去重：同一个山河器在不同屏滚动后可能再次出现
                if cell.name in seen_names:
                    continue
                seen_names.add(cell.name)

                all_cells_log.append(
                    {
                        "step": step,
                        "col": cell.col,
                        "row": cell.row_in_screen,
                        "name": cell.name,
                    }
                )

                _safe_print(
                    f"   -> 点击 {cell.name} @({cell.center_x},{cell.center_y})"
                )
                self._click_client(cell.center_x, cell.center_y, delay=0.6)
                detail_img = self._capture(
                    f"detail_{step:02d}_{cell.row_in_screen}_{cell.col}"
                )
                detail_path = (
                    self.output_dir
                    / f"detail_{step:02d}_{cell.row_in_screen}_{cell.col}.png"
                )
                cv2.imwrite(str(detail_path), detail_img)

                pending = PendingDetail(
                    step=step,
                    row=cell.row_in_screen,
                    col=cell.col,
                    cell_name=cell.name,
                    detail_path=detail_path,
                    grid_img_path=grid_path,
                    center_x=cell.center_x,
                    center_y=cell.center_y,
                )
                pending_count += 1
                future = executor.submit(self._consume_detail, pending)
                futures[future] = pending

                # 及时处理已完成的解析任务，输出进度并释放内存
                done = [f for f in list(futures.keys()) if f.done()]
                for f in done:
                    pending_done = futures.pop(f)
                    try:
                        parsed = f.result()
                    except Exception as exc:
                        _safe_print(f"[解析异常] {exc}")
                        parsed = None
                    if self._process_parsed(
                        parsed, pending_done.detail_path, owned_items, low_conf_records
                    ):
                        parsed_count += 1

            # 结束条件：网格画面连续两屏几乎不变
            grid_hash = self._grid_hash(grid_img)
            if prev_grid_hash is not None:
                dist = self._hash_distance(grid_hash, prev_grid_hash)
                _safe_print(f"       本屏网格 hash 距离：{dist}")
                if dist <= 5:
                    no_progress += 1
                    if no_progress >= 2:
                        _safe_print("[扫描] 连续两屏网格画面相同，结束")
                        break
                else:
                    no_progress = 0
            prev_grid_hash = grid_hash

            self._scroll_grid(scroll_clicks)
            step += 1

        _safe_print(
            f"\n[解析] 扫描结束，等待后台解析剩余 {len(futures)} 个详情截图..."
        )
        for future in as_completed(futures):
            try:
                parsed = future.result()
            except Exception as exc:
                _safe_print(f"[解析异常] {exc}")
                parsed = None
            pending = futures[future]
            if self._process_parsed(
                parsed, pending.detail_path, owned_items, low_conf_records
            ):
                parsed_count += 1

        _safe_print(
            f"\n[汇总] 解析完成：{parsed_count}/{pending_count}，"
            f"高置信 {len(owned_items)} 个，低置信 {len(low_conf_records)} 个"
        )
        return owned_items, low_conf_records, parsed_count, pending_count, all_cells_log

    def _prepare_window(self) -> None:
        """公共准备：找窗口、调尺寸、置顶。"""
        self._get_hwnd()
        self._ensure_fixed_size()
        self._bring_to_front()

    def _save_scan_result(
        self,
        result: ScanResult,
        all_cells_log: List[dict],
        suffix: str = "",
    ) -> None:
        """保存扫描结果和点击日志。"""
        result.screenshots["all_cells_log"] = str(
            self.output_dir / f"all_cells_log{suffix}.json"
        )
        Path(result.screenshots["all_cells_log"]).write_text(
            json.dumps(all_cells_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def run(self) -> ScanResult:
        """扫描武库全部品质。

        为避免跨品质重名歧义，实际按品质分批扫描后合并结果。
        """
        result = ScanResult()
        for quality in ("朴素", "精巧", "瑰丽", "绝世"):
            _safe_print(f"\n[全量扫描] 开始扫描品质：{quality}")
            quality_result = self.scan_quality(quality)
            result.shanheqis.extend(quality_result.shanheqis)
            result.low_confidence.extend(quality_result.low_confidence)
            result.screenshots.update(quality_result.screenshots)
        return result

    def scan_quality(self, quality: str) -> ScanResult:
        """扫描指定品质分类。"""
        result = ScanResult()
        self._current_quality = quality
        self._prepare_window()
        self._select_quality(quality)
        self._scroll_to_top()

        with ThreadPoolExecutor(max_workers=self.parse_workers) as executor:
            (
                owned_items,
                low_conf_records,
                parsed_count,
                pending_count,
                all_cells_log,
            ) = self._scan_grid(executor)

        result.shanheqis = owned_items
        result.low_confidence = low_conf_records
        self._save_scan_result(result, all_cells_log, suffix=f"_{quality}")
        return result

    def _make_record(
        self,
        shq: Shanheqi,
        conf: float,
        issues: List[str],
        detail_path: Path,
    ) -> dict:
        return {
            "shanheqi": {
                "id": shq.id,
                "name": shq.name,
                "quality": shq.quality.value,
                "element": shq.element.value,
                "shanheqi_type": shq.shanheqi_type.value,
                "level": shq.level,
                "gongguan_level": shq.gongguan_level,
                "base_score": shq.base_score,
                "affixes": [
                    {
                        "name": a.name,
                        "element": a.element.value if a.element else None,
                        "level": a.level,
                        "score": a.score,
                    }
                    for a in shq.affixes
                ],
                "derived_affixes": shq.derived_affixes,
                "stats": shq.stats,
            },
            "confidence": conf,
            "issues": issues,
            "screenshot": str(detail_path),
        }

    def save(self, result: ScanResult, output_path: Optional[Path] = None) -> Path:
        if output_path is None:
            output_path = self.output_dir / "owned_shanheqis.json"

        data = {
            "shanheqis": [
                {
                    "id": s.id,
                    "name": s.name,
                    "quality": s.quality.value,
                    "element": s.element.value,
                    "shanheqi_type": s.shanheqi_type.value,
                    "level": s.level,
                    "gongguan_level": s.gongguan_level,
                    "base_score": s.base_score,
                    "affixes": [
                        {
                            "name": a.name,
                            "element": a.element.value if a.element else None,
                            "level": a.level,
                            "score": a.score,
                        }
                        for a in s.affixes
                    ],
                    "derived_affixes": s.derived_affixes,
                    "stats": s.stats,
                }
                for s in result.shanheqis
            ],
            "low_confidence": result.low_confidence,
            "total_owned": len(result.shanheqis) + len(result.low_confidence),
            "high_confidence_count": len(result.shanheqis),
            "low_confidence_count": len(result.low_confidence),
        }
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _safe_print(f"[保存] 结果已写入：{output_path}")
        return output_path
