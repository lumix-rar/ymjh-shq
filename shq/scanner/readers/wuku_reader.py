"""武库山河器读取器。

将「导航到武库并读取用户已获得山河器详情」封装为独立模块，
与后续并行的「孔位培养读取器」等保持一致的架构。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from shq.scanner.name_resolver import ShanheqiNameResolver
from shq.scanner.ocr_scanner import OCRBackend, RapidOCRBackend
from shq.scanner.reconciler import ScanReconciler
from shq.scanner.search_collector import SearchCollector
from shq.scanner.wuku_navigator import WukuNavigator
from shq.scanner.wuku_scanner import ScanResult, WukuScanner
from shq.scanner.window_capture import capture_game_window


class WukuReader:
    """读取武库中用户已获得的山河器详情。"""

    def __init__(
        self,
        ocr_backend: Optional[OCRBackend] = None,
        confidence_threshold: float = 0.5,
        output_dir: Optional[Path] = None,
        parse_workers: int = 4,
        reconcile_threshold: float = 0.55,
    ):
        self.backend = ocr_backend or RapidOCRBackend()
        self.navigator = WukuNavigator(ocr_backend=self.backend)
        self.scanner = WukuScanner(
            ocr_backend=self.backend,
            confidence_threshold=confidence_threshold,
            output_dir=output_dir,
            parse_workers=parse_workers,
        )
        self.reconcile_threshold = reconcile_threshold

    def _navigate_to_wuku(self) -> bool:
        """导航到武库界面。"""
        return self.navigator.navigate_to("武库")

    def read_quality(self, quality: str, reconcile: bool = True) -> ScanResult:
        """读取指定品质下已获得的山河器。

        Args:
            quality: 目标品质，必须是 朴素/精巧/瑰丽/绝世 之一。
            reconcile: 是否启用底稿漏扫兜底补齐。

        Returns:
            该品质扫描结果。
        """
        if not self._navigate_to_wuku():
            raise RuntimeError("导航到武库界面失败")
        result = self.scanner.scan_quality(quality, reconcile=False)

        if reconcile:
            resolver = ShanheqiNameResolver()
            reconciler = ScanReconciler(
                resolver=resolver, score_threshold=self.reconcile_threshold
            )
            result.shanheqis, result.reconciliation_report = reconciler.reconcile(
                quality, result.shanheqis, result.low_confidence
            )
        return result

    def read(self, reconcile: bool = True) -> ScanResult:
        """读取所有品质下已获得的山河器，并附加收集度信息。

        流程：
        1. 导航到「搜寻」界面，读取总收集度；
        2. 导航到「武库」界面；
        3. 扫描全部四个品质并合并结果；
        4. 将收集度写入 result.screenshots 供下游使用。

        Args:
            reconcile: 是否启用底稿漏扫兜底补齐。

        Returns:
            完整扫描结果。
        """
        # 1. 读取收集度
        if not self.navigator.navigate_to("搜寻"):
            raise RuntimeError("导航到搜寻界面失败")
        img = capture_game_window(fixed_size=True)
        if img is None:
            raise RuntimeError("无法截取游戏窗口")
        owned_total, total = SearchCollector(self.backend).read(img)

        # 2. 扫描武库
        if not self._navigate_to_wuku():
            raise RuntimeError("导航到武库界面失败")
        result = self.scanner.run(reconcile=reconcile)

        # 3. 将收集度附加到结果中
        result.screenshots["_owned_total"] = owned_total
        result.screenshots["_total"] = total
        return result
