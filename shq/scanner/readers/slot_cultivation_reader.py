"""灵鉴孔位培养读取器。

将「导航到灵鉴、切换区域、打开孔位培养面板、读取每个孔位额外加分」
封装为独立 Reader，与 WukuReader 保持一致的架构。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from shq.models import Lingjian, Region
from shq.scanner.exceptions import ScanInterruptedError
from shq.scanner.lingjian_navigator import LingjianNavigator
from shq.scanner.ocr_scanner import OCRBackend, RapidOCRBackend
from shq.scanner.slot_cultivation_scanner import (
    RegionCultivationResult,
    SlotCultivationScanResult,
    SlotCultivationScanner,
)
from shq.scanner.topology_loader import RegionCalibration, Topology, TopologyLoader
from shq.scanner.window_capture import ROI

ProgressCallback = Optional[Callable[[str], None]]


@dataclass
class SlotCultivationReaderResult:
    """读取器返回的完整结果。"""

    lingjian: Lingjian
    scan_result: SlotCultivationScanResult
    output_path: Optional[Path] = None


class SlotCultivationReader:
    """读取灵鉴各区域孔位培养加分。"""

    def __init__(
        self,
        topology: Optional[Topology] = None,
        ocr_backend: Optional[OCRBackend] = None,
        confidence_threshold: float = 0.5,
        output_dir: Optional[Path] = None,
        progress_callback: ProgressCallback = None,
        auto_resize: bool = True,
        stop_event: Optional[threading.Event] = None,
    ):
        self.backend = ocr_backend or RapidOCRBackend()
        self.topology = topology or TopologyLoader().load()
        self.output_dir = output_dir or Path.cwd() / "lingjian_scan"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.progress_callback = progress_callback
        self.stop_event = stop_event

        self.navigator = LingjianNavigator(
            topology=self.topology,
            ocr_backend=self.backend,
            auto_resize=auto_resize,
            stop_event=stop_event,
        )
        self.scanner = SlotCultivationScanner(
            ocr_backend=self.backend,
            confidence_threshold=confidence_threshold,
            output_dir=self.output_dir,
        )

    def _notify(self, msg: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(msg)

    def _check_stopped(self) -> None:
        """若用户请求停止，则抛出 ScanInterruptedError。"""
        if self.stop_event is not None and self.stop_event.is_set():
            raise ScanInterruptedError()

    # ------------------------------------------------------------------
    # 生产读取
    # ------------------------------------------------------------------
    def read(
        self,
        output_path: Optional[Path] = None,
        dry_run: bool = False,
    ) -> SlotCultivationReaderResult:
        """读取所有已解锁区域的孔位培养加分。

        Args:
            output_path: 结果保存路径，默认 ./lingjian_scan/slot_cultivation.json。
            dry_run: 若 True，则只截图/标注/OCR，不执行会改变游戏状态的点击
                （实际仍需要导航与切换区域以查看面板，因此 dry_run 主要用于人工核对）。

        Returns:
            SlotCultivationReaderResult。
        """
        self._notify("[灵鉴] 导航到灵鉴界面")
        if not self.navigator.navigate_to_lingjian():
            raise RuntimeError("导航到灵鉴界面失败")

        scan_result = SlotCultivationScanResult()

        for region in self.topology.lingjian.regions:
            self._check_stopped()
            self._notify(f"[灵鉴] 读取区域：{region.name}")
            calibration = self.topology.get_region_calibration(region.id)
            rr = self._read_region(region, calibration, dry_run=dry_run)
            scan_result.region_results.append(rr)
            if rr.locked:
                scan_result.locked_region_ids.append(region.id)
                self._notify(f"[灵鉴] 区域 {region.name} 未解锁")

        # 保存截图记录
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        debug_dir = self.output_dir / f"debug_{timestamp}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        # TODO: 保存调试用截图

        target = output_path or self.output_dir / "slot_cultivation.json"
        self.scanner.save_result(scan_result, target)
        self._notify(f"[灵鉴] 孔位培养结果已保存：{target}")

        return SlotCultivationReaderResult(
            lingjian=Lingjian(
                regions=[
                    self._apply_scores(rr, self.topology.lingjian.get_region(rr.region_id))
                    for rr in scan_result.region_results
                ]
            ),
            scan_result=scan_result,
            output_path=target,
        )

    def _read_region(
        self,
        region: Region,
        calibration: Optional[RegionCalibration],
        dry_run: bool = False,
    ) -> RegionCultivationResult:
        """读取单个区域。"""
        self._check_stopped()
        print(f"\n[读取] 区域：{region.name}")

        # 1. 切换到目标区域
        if not dry_run:
            ok = self.navigator.select_region(region.name, calibration=calibration)
            if not ok:
                # 下拉框可能仍处于展开状态，检查列表中是否真的没有目标区域
                img = self.navigator.capture()
                buttons = self.navigator.detect_region_buttons(img, expanded=True)
                if region.name not in buttons:
                    print(f"[读取] 区域 {region.name} 未解锁，跳过")
                    return RegionCultivationResult(
                        region_id=region.id,
                        region_name=region.name,
                        locked=True,
                    )
                return RegionCultivationResult(
                    region_id=region.id,
                    region_name=region.name,
                    locked=False,
                    low_confidence=[
                        {"reason": "failed_to_select_region"}
                    ],
                )
        else:
            # dry-run 模式：仅尝试 OCR 当前截图中的区域名以确认位置
            img = self.navigator.capture()
            current = self.navigator.detect_current_region(img)
            if current != region.name:
                print(f"[dry-run] 当前未在 {region.name}，跳过")
                return RegionCultivationResult(
                    region_id=region.id,
                    region_name=region.name,
                    locked=False,
                    low_confidence=[{"reason": "dry_run_region_not_selected"}],
                )

        # 2. 打开孔位培养面板；若失败再检测是否未解锁
        if not dry_run:
            if not self.navigator.click_cultivation_button(calibration=calibration):
                img = self.navigator.capture()
                if self.navigator.is_region_locked(img):
                    print(f"[读取] 区域 {region.name} 未解锁，跳过")
                    return RegionCultivationResult(
                        region_id=region.id,
                        region_name=region.name,
                        locked=True,
                    )
                return RegionCultivationResult(
                    region_id=region.id,
                    region_name=region.name,
                    locked=False,
                    low_confidence=[{"reason": "failed_to_open_cultivation_panel"}],
                )

        # 3. 读取面板
        img = self.navigator.capture()
        calib = calibration or RegionCalibration(region_id=region.id)
        if calib.panel_roi is None:
            h, w = img.shape[:2]
            calib.panel_roi = ROI(
                name=f"{region.id}_panel",
                x=0,
                y=int(h * 0.15),
                width=int(w * 0.48),
                height=int(h * 0.75),
            )
        rr = self.scanner.read_region(
            img,
            region,
            calib,
            panel_open=True,
        )
        self._notify(
            f"[灵鉴] {region.name} 读取完成，"
            f"{len(rr.slots)} 个孔位，低置信 {len(rr.low_confidence)} 条"
        )

        # 4. 关闭面板
        if not dry_run:
            self.navigator.close_cultivation_panel()

        return rr

    # ------------------------------------------------------------------
    # 校准模式
    # ------------------------------------------------------------------
    def calibrate(
        self,
        output_path: Optional[Path] = None,
    ) -> Path:
        """运行校准流程，为每个区域探测候选 ROI 并输出校准 JSON。

        输出文件默认：./lingjian_scan/lingjian_topology_calibrated.json
        用户审核后可替换 data/lingjian_topology.json。
        """
        if not self.navigator.navigate_to_lingjian():
            raise RuntimeError("导航到灵鉴界面失败")

        calibrated_regions: List[dict] = []

        for region in self.topology.lingjian.regions:
            calibration = self.topology.get_region_calibration(region.id)
            print(f"\n[校准] 区域：{region.name}")

            ok = self.navigator.select_region(region.name, calibration=calibration)
            if not ok:
                print(f"[校准] 无法切换到 {region.name}，跳过")
                continue

            # 探测左侧下拉框按钮坐标（收起状态下当前显示的区域名）
            img = self.navigator.capture()
            current = self.navigator.detect_current_region(img)
            list_button = None
            if current:
                buttons_closed = self.navigator.detect_region_buttons(img, expanded=False)
                list_button = buttons_closed.get(current)

            # 打开培养面板；失败则检测是否未解锁
            if not self.navigator.click_cultivation_button(calibration=calibration):
                img = self.navigator.capture()
                if self.navigator.is_region_locked(img):
                    print(f"[校准] 区域 {region.name} 未解锁，跳过")
                    calibrated_regions.append(
                        {
                            "id": region.id,
                            "name": region.name,
                            "locked": True,
                            "list_button": self._serialize_point(list_button),
                            "cultivation_button": None,
                            "panel_roi": None,
                            "slots": [],
                        }
                    )
                else:
                    print(f"[校准] 无法打开 {region.name} 的培养面板，跳过")
                continue

            img = self.navigator.capture()
            panel_roi = calibration.panel_roi if calibration else None
            calib_data = self.scanner.calibrate_panel(
                img, region.id, panel_roi=panel_roi
            )

            # 关闭面板
            self.navigator.close_cultivation_panel()

            # 组装校准输出：把检测到的编号作为该区域实际孔位
            numbers = list(calib_data.get("number_candidates", []))
            numbers.sort(key=lambda c: (c["y"], c["x"]))

            slots = []
            for idx, cand in enumerate(numbers, start=1):
                slots.append(
                    {
                        "id": f"{region.id}_slot_{idx}",
                        "region_id": region.id,
                        "number": cand["parsed_number"],
                    }
                )

            calibrated_regions.append(
                {
                    "id": region.id,
                    "name": region.name,
                    "locked": False,
                    "list_button": self._serialize_point(list_button),
                    "cultivation_button": self._serialize_point(
                        calibration.cultivation_button if calibration else None
                    ),
                    "panel_roi": calib_data.get("panel_roi"),
                    "slots": slots,
                    "raw_texts": calib_data.get("texts", []),
                    "number_candidates": numbers,
                    "score_candidates": calib_data.get("score_candidates", []),
                }
            )

        target = output_path or self.output_dir / "lingjian_topology_calibrated.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "_comment": "校准候选结果，请人工审核后替换 data/lingjian_topology.json",
            "regions": calibrated_regions,
        }
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[校准完成] 候选配置已保存：{target}")
        return target

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_scores(rr: RegionCultivationResult, region: Optional[Region]) -> Region:
        """将扫描得到的加分回填到 Region 模型中。"""
        if region is None:
            region = Region(id=rr.region_id, name=rr.region_name)

        score_map = {sv.slot_id: sv.score for sv in rr.slots}
        for slot in region.slots:
            slot.cultivation_score = score_map.get(slot.id, 0.0)
        return region

    @staticmethod
    def _serialize_point(value: Optional[Tuple[int, int]]) -> Optional[List[int]]:
        return list(value) if value is not None else None
