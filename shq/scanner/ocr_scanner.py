"""OCR 扫描器：通过截图识别山河器与灵鉴数据。

数据流：
1. 定位一梦江湖窗口（基于进程或窗口标题）。
2. 截取游戏窗口图像。
3. 裁剪出山河器列表、灵鉴区域、属性面板等 ROI。
4. 调用 OCR 引擎识别文字。
5. 将识别结果解析为 shq.models 中的数据对象。

注意：
- 本模块仅读取屏幕像素，不访问游戏内存、不注入、不模拟点击。
- 具体 ROI 坐标、OCR 预处理方式、解析规则都需要根据实际游戏界面校准。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from shq.models import BuildPreference, Element, Lingjian, Quality, Shanheqi
from shq.scanner.interface import Scanner
from shq.scanner.window_capture import ROI, WindowCapture, capture_game_window


@dataclass
class OCRResult:
    """OCR 识别结果，包含文字、置信度和边界框。"""

    text: str
    confidence: float
    # 边界框：左上角、右上角、右下角、左下角（相对于输入图像）
    bbox: Optional[List[Tuple[int, int]]] = None

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        """计算边界框中心点。"""
        if not self.bbox or len(self.bbox) < 4:
            return None
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        return (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))


class OCRBackend(ABC):
    """OCR 引擎抽象。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称。"""

    @abstractmethod
    def recognize_with_boxes(self, img: np.ndarray) -> List[OCRResult]:
        """识别图像中的文字，返回带边界框的结果。"""

    def recognize(self, img: np.ndarray) -> List[Tuple[str, float]]:
        """识别图像中的文字（兼容旧接口）。

        Returns:
            识别结果列表，每项为 (文字, 置信度)。
        """
        return [(r.text, r.confidence) for r in self.recognize_with_boxes(img)]


class PlaceholderOCRBackend(OCRBackend):
    """占位 OCR 引擎：不识别，仅保存 ROI 图像供人工标注。"""

    @property
    def name(self) -> str:
        return "placeholder"

    def recognize_with_boxes(self, img: np.ndarray) -> List[OCRResult]:
        return [OCRResult("TODO: OCR_ENGINE_NOT_CONFIGURED", 0.0, None)]


class EasyOCRBackend(OCRBackend):
    """EasyOCR 后端（需安装 easyocr）。"""

    def __init__(self, languages: Tuple[str, ...] = ("ch_sim", "en")):
        self.languages = languages
        self._reader: Optional[object] = None

    @property
    def name(self) -> str:
        return "easyocr"

    def _get_reader(self):
        if self._reader is None:
            try:
                import easyocr
            except ImportError as e:
                raise RuntimeError(
                    "未安装 easyocr。请运行：pip install easyocr"
                ) from e
            self._reader = easyocr.Reader(list(self.languages))
        return self._reader

    def recognize_with_boxes(self, img: np.ndarray) -> List[OCRResult]:
        reader = self._get_reader()
        # easyocr 接收 BGR 图像或路径
        # 结果格式：([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], text, confidence)
        results = reader.readtext(img)
        return [
            OCRResult(
                text=text,
                confidence=float(conf),
                bbox=[(int(x), int(y)) for x, y in box],
            )
            for box, text, conf in results
        ]


class RapidOCRBackend(OCRBackend):
    """RapidOCR 后端（基于 ONNX Runtime，轻量，推荐）。"""

    def __init__(self):
        self._ocr: Optional[object] = None

    @property
    def name(self) -> str:
        return "rapidocr"

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as e:
                raise RuntimeError(
                    "未安装 rapidocr-onnxruntime。请运行：pip install rapidocr-onnxruntime"
                ) from e
            self._ocr = RapidOCR()
        return self._ocr

    def recognize_with_boxes(self, img: np.ndarray) -> List[OCRResult]:
        ocr = self._get_ocr()
        # RapidOCR 结果格式：[[[x1,y1],[x2,y1],[x2,y2],[x1,y2]], text, confidence]
        results, _ = ocr(img)
        if results is None:
            return []
        return [
            OCRResult(
                text=text,
                confidence=float(conf),
                bbox=[(int(x), int(y)) for x, y in box],
            )
            for box, text, conf in results
        ]


class ShanheqiOCR(Scanner):
    """山河器 OCR 扫描器。"""

    def __init__(self, backend: Optional[OCRBackend] = None):
        self.backend = backend or PlaceholderOCRBackend()

    @property
    def name(self) -> str:
        return f"shanheqi_ocr({self.backend.name})"

    def scan(self) -> List[Shanheqi]:
        """扫描玩家拥有的山河器列表。"""
        img = capture_game_window()
        if img is None:
            raise RuntimeError("无法截取一梦江湖窗口，请确保游戏已运行且可见")

        # TODO：根据实际游戏界面确定山河器列表 ROI
        rois = self._detect_shanheqi_rois(img)
        results: List[Shanheqi] = []
        for idx, roi in enumerate(rois):
            cropped = roi.crop(img)
            texts = self.backend.recognize(cropped)
            shq = self._parse_shanheqi(texts, idx)
            if shq:
                results.append(shq)
        return results

    def scan_lingjian(self) -> Lingjian:
        """扫描灵鉴布局（区域、孔位、连线）。"""
        # TODO：实现灵鉴界面截图与 ROI 识别
        return Lingjian(regions=[])

    def scan_preference(self) -> BuildPreference:
        """扫描玩家流派偏好（或从配置文件读取）。"""
        # TODO：实现流派偏好识别/配置读取
        return BuildPreference(build="综合")

    @staticmethod
    def _detect_shanheqi_rois(img: np.ndarray) -> List[ROI]:
        """检测山河器列表中每个条目所在的 ROI。

        TODO：当前为占位实现，需根据实际界面坐标或图像特征确定。
        """
        # 占位：返回整个图像作为一个 ROI
        h, w = img.shape[:2]
        return [ROI(name="shanheqi_list", x=0, y=0, width=w, height=h, description="TODO")]

    @staticmethod
    def _parse_shanheqi(texts: List[Tuple[str, float]], idx: int) -> Optional[Shanheqi]:
        """从 OCR 文本解析单个山河器。

        TODO：当前为占位实现，需根据实际识别内容解析：
        - 山河器名称
        - 品质（朴素/精巧/瑰丽/绝世）
        - 五行（金/木/水/火/土）
        - 等级、共贯等级
        - 素蕴词条（名称、等级、派生效果）
        """
        joined = " ".join(t for t, _ in texts)
        return Shanheqi(
            id=f"ocr_shq_{idx}",
            name=joined[:50] or "TODO",
            quality=Quality.SIMPLE,
            element=Element.METAL,
            base_score=0.0,
        )

    def save_snapshot(self, output_dir: str | Path) -> Path:
        """截图并保存，供人工标注 ROI。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        img = capture_game_window()
        if img is None:
            raise RuntimeError("无法截取一梦江湖窗口")

        path = output_dir / "game_snapshot.png"
        cv2.imwrite(str(path), img)
        return path

    def save_rois(self, output_dir: str | Path) -> List[Path]:
        """截图并保存所有 ROI，供人工检查/OCR 训练。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        img = capture_game_window()
        if img is None:
            raise RuntimeError("无法截取一梦江湖窗口")

        saved: List[Path] = []
        rois = self._detect_shanheqi_rois(img)
        for roi in rois:
            cropped = roi.crop(img)
            path = output_dir / f"{roi.name}.png"
            cv2.imwrite(str(path), cropped)
            saved.append(path)
        return saved


def recognize_text_in_image(img_path: str | Path, backend_name: str = "placeholder") -> List[Tuple[str, float]]:
    """便捷函数：对单张图片运行 OCR。"""
    img = cv2.imread(str(img_path))
    if img is None:
        raise RuntimeError(f"无法读取图片：{img_path}")

    if backend_name == "easyocr":
        backend: OCRBackend = EasyOCRBackend()
    else:
        backend = PlaceholderOCRBackend()

    return backend.recognize(img)
