"""OCR 并行解析管道。

将详情面板截图投入队列，由线程池并发执行 OCR 与解析，
解析结果写入 CollectionState。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from shq.scanner.ocr_scanner import OCRBackend
from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.detail_reader import DetailPanelReader
from shq.scanner.wuku.state import CollectionState


class OCRPipeline:
    """并发 OCR 解析管道。"""

    def __init__(
        self,
        ocr_backend: OCRBackend,
        state: CollectionState,
        config: Optional[WukuConfig] = None,
        on_error: Optional[Callable[[str, Exception], None]] = None,
    ):
        self.reader = DetailPanelReader(ocr_backend, config)
        self.state = state
        self.cfg = config or WukuConfig()
        self.on_error = on_error
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: List[Future] = []

    def start(self) -> None:
        """启动线程池。"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.cfg.ocr_workers)

    def submit(
        self,
        screenshot: np.ndarray,
        item_name: str,
        screenshot_path: Optional[Path] = None,
    ) -> None:
        """提交一个详情截图到解析队列。"""
        self.start()
        future = self._executor.submit(
            self._parse_one, screenshot, item_name, screenshot_path
        )
        self._futures.append(future)

    def wait_for_completion(self) -> None:
        """等待所有已提交任务完成。"""
        for future in self._futures:
            try:
                future.result()
            except Exception as exc:
                if self.on_error:
                    self.on_error("ocr_task", exc)
        self._futures.clear()

    def shutdown(self) -> None:
        """关闭线程池。"""
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _parse_one(
        self,
        screenshot: np.ndarray,
        item_name: str,
        screenshot_path: Optional[Path],
    ) -> None:
        """解析单个截图并写入状态。"""
        detail = self.reader.parse(screenshot)
        detail.screenshot_path = screenshot_path
        self.state.add_detail(item_name, detail)
