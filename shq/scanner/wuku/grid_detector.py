"""武库网格 item 检测器。

通过图像分割先精确检测左卡每个 item 的边框，再对每个 cell 单独 OCR，
从而准确提取名称、等级、派生素蕴标签和特殊等级。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from shq.scanner.ocr_scanner import OCRBackend, OCRResult
from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.models import BBox, GridItem, Point


class GridItemDetector:
    """检测武库网格中的山河器条目。"""

    # 派生素蕴标签模板目录；文件名用 ASCII，通过映射得到中文标签
    _TEMPLATE_DIR = Path(__file__).parent / "templates"
    _TEMPLATE_LABELS = {
        "qishi": "起势",
        "chengshi": "承势",
        "huoshi": "火实",
        "shuishi": "水实",
        "mushi": "木实",
        "jinshi": "金实",
        "tushi": "土实",
    }

    def __init__(self, ocr_backend: OCRBackend, config: Optional[WukuConfig] = None):
        self.ocr = ocr_backend
        self.cfg = config or WukuConfig()
        self._derived_templates: Dict[str, np.ndarray] = self._load_templates()

    def detect(self, img: np.ndarray) -> List[GridItem]:
        """从完整窗口截图中检测所有 item。

        Args:
            img: BGR 格式的完整窗口截图。

        Returns:
            识别到的 GridItem 列表，按从上到下、从左到右排序。
        """
        h, w = img.shape[:2]
        gx, gy, gw, gh = self.cfg.grid_roi.abs(w, h)
        grid_img = img[gy : gy + gh, gx : gx + gw]
        if grid_img.size == 0:
            return []

        cells = self._detect_cells(grid_img)
        items: List[GridItem] = []
        for idx, (cx, cy, cw, ch) in enumerate(cells):
            # 转回完整窗口坐标
            cell_bbox = BBox(x=gx + cx, y=gy + cy, width=cw, height=ch)
            item = self._parse_cell(img, cell_bbox)
            if item:
                items.append(item)

        return items

    def _detect_cells(self, grid_img: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """在网格 ROI 内检测每个 item 卡片的矩形边框。

        策略：先检测每个 item 左侧的方形图标（蓝色背景方框），再以图标为锚点
        拟合出完整网格，从而得到不缺失边界的 cell。

        返回列表元素为 (x, y, w, h)，按从上到下、从左到右排序。
        """
        gh, gw = grid_img.shape[:2]
        mid_x = gw // 2

        icons = self._detect_item_icons(grid_img)
        if len(icons) < 2:
            return []

        # 按 y 聚类成行
        icons.sort(key=lambda b: b[1])
        rows: List[List[Tuple[int, int, int, int]]] = []
        y_tol = int(gw * 0.08)
        for icon in icons:
            placed = False
            for row in rows:
                if abs(icon[1] - row[-1][1]) <= y_tol:
                    row.append(icon)
                    placed = True
                    break
            if not placed:
                rows.append([icon])

        # 计算水平分隔线：取每行图标中心 y 的上下中点
        row_centers = [int(np.mean([ic[1] + ic[3] / 2 for ic in row])) for row in rows]
        row_tops = [0]
        for i in range(len(row_centers) - 1):
            row_tops.append((row_centers[i] + row_centers[i + 1]) // 2)
        row_bottoms = row_tops[1:] + [gh]

        cells: List[Tuple[int, int, int, int]] = []
        for row_idx, row in enumerate(rows):
            top = row_tops[row_idx]
            bottom = row_bottoms[row_idx]
            height = bottom - top

            # 补齐缺失列
            if len(row) == 1:
                x = row[0][0]
                row = ([row[0], None] if x < mid_x else [None, row[0]])

            # 左列 cell：从网格左边缘到中垂线
            if row[0]:
                cells.append((0, top, mid_x, height))
            # 右列 cell：从中垂线到网格右边缘
            if len(row) > 1 and row[1]:
                cells.append((mid_x, top, gw - mid_x, height))

        cells.sort(key=lambda b: (b[1], b[0]))
        return cells

    def _detect_item_icons(self, grid_img: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """检测网格中每个 item 左侧的方形图标。"""
        gh, gw = grid_img.shape[:2]
        hsv = cv2.cvtColor(grid_img, cv2.COLOR_BGR2HSV)
        lower_blue = np.array([90, 20, 30])
        upper_blue = np.array([130, 180, 180])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        icons: List[Tuple[int, int, int, int]] = []
        for cnt in contours:
            x, y, iw, ih = cv2.boundingRect(cnt)
            aspect = iw / max(ih, 1)
            area = iw * ih
            if 0.7 <= aspect <= 1.4 and 800 <= area <= 12000:
                icons.append((x, y, iw, ih))
        return icons

    def _parse_cell(self, img: np.ndarray, cell_bbox: BBox) -> Optional[GridItem]:
        """从单个 item 卡片中解析信息。"""
        h, w = img.shape[:2]
        x1 = max(0, cell_bbox.x)
        y1 = max(0, cell_bbox.y)
        x2 = min(w, cell_bbox.x + cell_bbox.width)
        y2 = min(h, cell_bbox.y + cell_bbox.height)
        cell_img = img[y1:y2, x1:x2]
        if cell_img.size == 0:
            return None

        # OCR 范围不要取整个列宽（背景太多会干扰小字识别），
        # 而是在 cell 内定位到左侧图标后，向右取内容区域。
        ocr_roi = self._find_content_roi(cell_img)
        ocr_x1 = x1 + ocr_roi[0]
        ocr_y1 = y1 + ocr_roi[1]
        ocr_img = cell_img[ocr_roi[1] : ocr_roi[1] + ocr_roi[3], ocr_roi[0] : ocr_roi[0] + ocr_roi[2]]

        results = self.ocr.recognize_with_boxes(ocr_img)
        if not results:
            return None

        # 把 OCR 坐标转回完整窗口坐标
        for r in results:
            if r.bbox:
                r.bbox = [(p[0] + ocr_x1, p[1] + ocr_y1) for p in r.bbox]

        name: Optional[str] = None
        level: Optional[int] = None
        derived_affix: Optional[str] = None
        level_pattern = re.compile(r"(\d+)级")

        for r in results:
            text = r.text.strip()
            if not text:
                continue

            # 等级
            m = level_pattern.match(text)
            if m:
                level = int(m.group(1))
                continue

            # 派生素蕴：先尝试 OCR 直接命中
            if text in self.cfg.derived_affix_candidates:
                derived_affix = text
                continue

            # 名称：取最长文本
            if name is None or len(text) > len(name):
                name = text

        if not name:
            return None

        # 如果 OCR 没识别到标签，用模板匹配兜底
        if derived_affix is None and level is not None:
            derived_affix = self._detect_derived_affix(img, cell_bbox)

        click_point = cell_bbox.center
        special_grade = self._detect_special_grade(img, cell_bbox)

        return GridItem(
            name=name,
            cell_bbox=cell_bbox,
            click_point=click_point,
            level=level,
            derived_affix=derived_affix,
            special_grade=special_grade,
            is_acquired=level is not None,
        )

    def _find_content_roi(self, cell_img: np.ndarray) -> Tuple[int, int, int, int]:
        """在 cell 内定位左侧图标，返回包含图标+文字+标签的紧凑 ROI。"""
        ch, cw = cell_img.shape[:2]
        hsv = cv2.cvtColor(cell_img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([90, 20, 30]), np.array([130, 180, 180]))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        icon_x, icon_y, icon_w, icon_h = 0, 0, int(cw * 0.35), ch
        for cnt in contours:
            x, y, iw, ih = cv2.boundingRect(cnt)
            aspect = iw / max(ih, 1)
            area = iw * ih
            if 0.7 <= aspect <= 1.4 and 500 <= area <= 10000:
                icon_x, icon_y, icon_w, icon_h = x, y, iw, ih
                break

        # 内容区域：从图标左边缘开始，向右覆盖文字区（约图标宽度的 3.5 倍）
        roi_w = min(cw - icon_x, int(icon_w * 4.2))
        roi_h = ch
        return (icon_x, 0, roi_w, roi_h)

    def _load_templates(self) -> Dict[str, np.ndarray]:
        """加载派生素蕴标签模板。"""
        templates: Dict[str, np.ndarray] = {}
        if not self._TEMPLATE_DIR.exists():
            return templates
        for path in self._TEMPLATE_DIR.glob("*.png"):
            try:
                data = path.read_bytes()
                arr = np.frombuffer(data, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                label = self._TEMPLATE_LABELS.get(path.stem)
                if label and img is not None:
                    templates[label] = img
            except Exception:
                continue
        return templates

    def _detect_derived_affix(self, img: np.ndarray, cell_bbox: BBox) -> Optional[str]:
        """通过颜色定位棕褐标签区域，再用模板匹配识别派生素蕴。"""
        if not self._derived_templates:
            return None

        h, w = img.shape[:2]
        # 取 cell 底部 35% 区域作为标签候选区
        tag_y1 = max(0, int(cell_bbox.y + cell_bbox.height * 0.65))
        tag_y2 = min(h, cell_bbox.y + cell_bbox.height)
        tag_x1 = max(0, cell_bbox.x)
        tag_x2 = min(w, cell_bbox.x + cell_bbox.width)
        roi = img[tag_y1:tag_y2, tag_x1:tag_x2]
        if roi.size == 0:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower_brown = np.array([10, 40, 60])
        upper_brown = np.array([35, 180, 180])
        mask = cv2.inRange(hsv, lower_brown, upper_brown)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        cnt = max(contours, key=cv2.contourArea)
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 18 or ch < 8:
            return None

        tag_crop = roi[y : y + ch, x : x + cw]

        best_label: Optional[str] = None
        best_score = -1.0
        gray_crop = cv2.cvtColor(tag_crop, cv2.COLOR_BGR2GRAY)
        for label, tmpl in self._derived_templates.items():
            if tmpl is None or tmpl.size == 0:
                continue
            tmpl_resized = cv2.resize(tmpl, (cw, ch), interpolation=cv2.INTER_AREA)
            gray_tmpl = cv2.cvtColor(tmpl_resized, cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(gray_crop, gray_tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_label = label

        if best_score >= 0.65:
            return best_label
        return None

    def _detect_special_grade(self, img: np.ndarray, cell_bbox: BBox) -> Optional[str]:
        """检测 item 图标右上角小图标，判断是否为玄枢/卓异。"""
        h, w = img.shape[:2]
        icon_x = max(0, cell_bbox.x)
        icon_y = max(0, cell_bbox.y)
        icon_w = int(cell_bbox.width * 0.35)
        icon_h = int(cell_bbox.height * 0.5)

        if icon_x + icon_w > w or icon_y + icon_h > h:
            return None

        icon_img = img[icon_y : icon_y + icon_h, icon_x : icon_x + icon_w]
        if icon_img.size == 0:
            return None

        corner_w = max(8, icon_w // 3)
        corner_h = max(8, icon_h // 3)
        corner = icon_img[0:corner_h, icon_w - corner_w : icon_w]
        if corner.size == 0:
            return None

        mean_color = corner.mean(axis=(0, 1))  # BGR
        b, g, r = mean_color

        if r > 150 and g < 100 and b < 100:
            return "玄枢"
        if r > 150 and g > 120 and b < 100:
            return "卓异"
        return None


def _bbox_center(result: OCRResult) -> Tuple[int, int]:
    """计算 OCR 结果边界框中心。"""
    if not result.bbox:
        return (0, 0)
    xs = [p[0] for p in result.bbox]
    ys = [p[1] for p in result.bbox]
    return (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))
