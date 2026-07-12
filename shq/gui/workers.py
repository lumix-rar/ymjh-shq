"""后台工作线程：扫描与求解。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from shq.gui.utils import MessageType, WorkerQueue
from shq.models import BuildPreference, Lingjian
from shq.scanner import (
    OCRBackend,
    RapidOCRBackend,
    SlotCultivationReader,
    WukuReader,
)
from shq.scanner.exceptions import ScanInterruptedError
from shq.scanner.manual_importer import ManualImporter
from shq.scanner.ocr_scanner import EasyOCRBackend, PlaceholderOCRBackend
from shq.solver import LocalSearchSolver
from shq.rules import YMJHDefaultRuleSet


class BaseWorker(threading.Thread):
    """工作线程基类，统一通过 WorkerQueue 回传消息。"""

    def __init__(self, queue: WorkerQueue):
        super().__init__(daemon=True)
        self.worker_queue = queue
        self.stop_event = threading.Event()
        self._stopped = threading.Event()

    def log(self, message: str) -> None:
        self.worker_queue.put(MessageType.LOG, message)

    def progress(self, current: int, total: int) -> None:
        self.worker_queue.put(
            MessageType.PROGRESS, {"current": current, "total": total}
        )

    def done(self, payload: Any) -> None:
        self.worker_queue.put(MessageType.DONE, payload)

    def error(self, exc: Exception) -> None:
        self.worker_queue.put(MessageType.ERROR, str(exc))

    def request_stop(self) -> None:
        """请求停止当前任务（协作式）。"""
        self.stop_event.set()

    def is_stopped(self) -> bool:
        return self.stop_event.is_set() or self._stopped.is_set()


class ScanWorker(BaseWorker):
    """武库或灵鉴扫描工作线程。"""

    SCAN_WUKU = "wuku"
    SCAN_SLOT = "slot"

    def __init__(
        self,
        queue: WorkerQueue,
        scan_type: str,
        ocr_backend_name: str = "rapidocr",
        output_dir: Optional[Path] = None,
        output_path: Optional[Path] = None,
        auto_resize: bool = True,
    ):
        super().__init__(queue)
        self.scan_type = scan_type
        self.ocr_backend_name = ocr_backend_name
        self.output_dir = output_dir
        self.output_path = output_path
        self.auto_resize = auto_resize

    def run(self) -> None:
        try:
            backend = _create_ocr_backend(self.ocr_backend_name)
            if isinstance(backend, PlaceholderOCRBackend):
                raise RuntimeError(
                    "扫描必须使用真实 OCR 后端，请选择 rapidocr 或 easyocr"
                )

            if self.is_stopped():
                self.log("扫描已取消")
                return

            if self.scan_type == self.SCAN_WUKU:
                self._scan_wuku(backend)
            elif self.scan_type == self.SCAN_SLOT:
                self._scan_slot(backend)
            else:
                raise ValueError(f"未知扫描类型：{self.scan_type}")
        except ScanInterruptedError:
            self.log("扫描已取消")
        except Exception as exc:
            self.error(exc)

    def _scan_wuku(self, backend: OCRBackend) -> None:
        self.log("开始扫描武库...")
        reader = WukuReader(
            ocr_backend=backend,
            output_dir=self.output_dir,
            progress_callback=lambda msg: self.log(msg),
            auto_resize=self.auto_resize,
            stop_event=self.stop_event,
        )
        result = reader.read(reconcile=True)
        if self.is_stopped():
            self.log("武库扫描被用户中断")
            return
        output = reader.scanner.save(result, self.output_path)
        self.log(f"武库扫描完成：{len(result.shanheqis)} 个山河器")
        self.done(
            {
                "scan_type": self.SCAN_WUKU,
                "output": str(output),
                "shanheqis": result.shanheqis,
                "low_confidence": result.low_confidence,
            }
        )

    def _scan_slot(self, backend: OCRBackend) -> None:
        self.log("开始扫描灵鉴孔位培养...")
        reader = SlotCultivationReader(
            ocr_backend=backend,
            output_dir=self.output_dir,
            progress_callback=lambda msg: self.log(msg),
            auto_resize=self.auto_resize,
            stop_event=self.stop_event,
        )
        result = reader.read(output_path=self.output_path)
        if self.is_stopped():
            self.log("灵鉴扫描被用户中断")
            return
        self.log(
            f"灵鉴扫描完成：{len(result.lingjian.regions)} 个区域，"
            f"未解锁 {len(result.scan_result.locked_region_ids)} 个"
        )
        self.done(
            {
                "scan_type": self.SCAN_SLOT,
                "output": str(result.output_path),
                "lingjian": result.lingjian,
            }
        )


class SolveWorker(BaseWorker):
    """摆放求解工作线程。"""

    def __init__(
        self,
        queue: WorkerQueue,
        shqs: list,
        lingjian: Lingjian,
        preference: BuildPreference,
        target: str,
        rules_path: Optional[Path] = None,
        max_iterations: int = 2000,
    ):
        super().__init__(queue)
        self.shqs = shqs
        self.lingjian = lingjian
        self.preference = preference
        self.target = target
        self.rules_path = rules_path
        self.max_iterations = max_iterations

    def run(self) -> None:
        try:
            self.log("开始求解最优摆放...")
            rules = YMJHDefaultRuleSet(rules_path=self.rules_path)
            solver = LocalSearchSolver(
                max_iterations=self.max_iterations,
                progress_callback=lambda cur, total: self.progress(cur, total),
                stop_event=self.stop_event,
            )
            solution = solver.solve(
                self.shqs,
                self.lingjian,
                rules,
                self.target,
                self.preference,
            )
            if self.is_stopped():
                self.log("求解被用户中断，返回当前最优解")
            self.log(
                f"求解完成，总评分 {solution.evaluation.total_score:.1f}，"
                f"目标分 {rules.score(solution.evaluation, self.target, self.preference):.1f}"
            )
            self.done(
                {
                    "solution": solution,
                    "rules": rules,
                }
            )
        except Exception as exc:
            self.error(exc)


def _create_ocr_backend(name: str) -> OCRBackend:
    if name == "easyocr":
        return EasyOCRBackend()
    if name == "rapidocr":
        return RapidOCRBackend()
    return PlaceholderOCRBackend()


def list_available_ocr_backends() -> list[str]:
    """返回当前环境已安装的 OCR 后端名称列表。"""
    backends: list[str] = []
    try:
        import rapidocr_onnxruntime  # noqa: F401
        backends.append("rapidocr")
    except Exception:
        pass
    try:
        import easyocr  # noqa: F401
        backends.append("easyocr")
    except Exception:
        pass
    return backends
