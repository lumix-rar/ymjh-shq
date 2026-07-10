"""武库山河器采集总控。

协调导航、网格检测、点击、滚动、OCR 与数据合并，完成武库中
所有已获得山河器的自动采集。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from shq.scanner.input_simulator import InputSimulator
from shq.scanner.navigation_controller import NavigationController
from shq.scanner.ocr_scanner import OCRBackend
from shq.scanner.window_capture import WindowCapture
from shq.scanner.wuku.config import WukuConfig
from shq.scanner.wuku.grid_detector import GridItemDetector
from shq.scanner.wuku.models import BBox, GridItem, Point
from shq.scanner.wuku.ocr_pipeline import OCRPipeline
from shq.scanner.wuku.scroll_controller import ScrollController
from shq.scanner.wuku.state import CollectionState


class WukuCollector:
    """武库山河器采集器。"""

    def __init__(
        self,
        ocr_backend: OCRBackend,
        output_dir: Path,
        config: Optional[WukuConfig] = None,
        resume_path: Optional[Path] = None,
        attach_thread: bool = True,
    ):
        self.ocr = ocr_backend
        self.output_dir = Path(output_dir)
        self.cfg = config or WukuConfig()
        self.resume_path = resume_path
        self.attach_thread = attach_thread

        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "pages").mkdir(exist_ok=True)
        (self.output_dir / "details").mkdir(exist_ok=True)

        self.nav = NavigationController(ocr_backend=ocr_backend, attach_thread=attach_thread)
        self.detector = GridItemDetector(ocr_backend, self.cfg)
        self.state = self._load_state()
        self.pipeline: Optional[OCRPipeline] = None
        self._sim = InputSimulator(default_delay=self.cfg.click_delay)
        self._hwnd: Optional[int] = None
        self._cap: Optional[WindowCapture] = None

    def _load_state(self) -> CollectionState:
        if self.resume_path and self.resume_path.exists():
            return CollectionState.load(self.resume_path)
        return CollectionState()

    def _save_state(self) -> None:
        path = self.resume_path or (self.output_dir / "collection_state.json")
        self.state.save(path)

    def collect(self) -> dict:
        """执行完整采集流程。

        Returns:
            采集结果摘要 dict。
        """
        self.nav.ensure_fixed_size()
        if not self.nav.ensure_in_wuku(manual_fallback=True):
            raise RuntimeError("无法进入武库界面")

        self._cap = self.nav._get_window_capture()
        self._hwnd = self._cap.hwnd
        if self._hwnd is None:
            raise RuntimeError("未获取到游戏窗口句柄")

        if not self._ensure_filter_all():
            raise RuntimeError("无法将筛选栏设置为“全部”")

        self.pipeline = OCRPipeline(self.ocr, self.state, self.cfg)
        scroller = ScrollController(self._hwnd, self.cfg)

        page = self.state.current_page
        while True:
            print(f"\n[第 {page + 1} 页] 截图并检测...")
            screenshot = self.nav.screenshot()
            page_path = self._save_page(screenshot, page)

            # 检测 acquired items
            items = self.detector.detect(screenshot)
            # 将所有检测到的 item 加入已见集合，用于滚动触底判断
            self.state.mark_seen([it.unique_key for it in items])
            acquired = [it for it in items if it.is_acquired and not self.state.is_processed(it.unique_key)]
            print(f"  检测到 {len(items)} 个 item，其中 {len(acquired)} 个未处理且已获得")

            for item in acquired:
                self._process_item(item, screenshot)

            # 滚动前保存状态
            self.state.current_page = page
            self._save_state()

            h, w = screenshot.shape[:2]
            scroller.scroll_one_page(w, h, attach_thread=self.attach_thread)
            time.sleep(self.cfg.scroll_delay)

            post_scroll = self.nav.screenshot()
            post_items = self.detector.detect(post_scroll)
            self.state.mark_seen([it.unique_key for it in post_items])
            if scroller.is_at_bottom(post_items):
                print("\n[触底] 滚动到底部，结束翻页")
                break

            page += 1

        print("\n等待 OCR 解析完成...")
        if self.pipeline is not None:
            self.pipeline.wait_for_completion()
            self.pipeline.shutdown()

        # 最终合并：用左卡信息合并所有已有点击的 detail
        self._final_merge()
        self._save_state()

        json_path = self.output_dir / "shanheqis.json"
        self._export_json(json_path)

        return {
            "total_collected": len(self.state.results),
            "output_dir": str(self.output_dir),
            "json_path": str(json_path),
            "state_path": str(self.resume_path or self.output_dir / "collection_state.json"),
        }

    def _ensure_filter_all(self) -> bool:
        """确保当前筛选栏为“全部”。"""
        img = self.nav.screenshot()
        h, w = img.shape[:2]
        fx, fy, fw, fh = self.cfg.filter_roi.abs(w, h)
        roi_img = img[fy : fy + fh, fx : fx + fw]

        results = self.ocr.recognize_with_boxes(roi_img)
        texts = [r.text.strip() for r in results]
        if "全部" in texts:
            return True

        # 如果当前不是“全部”，点击筛选按钮后选择“全部”
        self._sim.click_on_window(
            self._hwnd, fx + fw // 2, fy + fh // 2, attach_thread=self.attach_thread
        )
        time.sleep(0.5)

        # 再次截图确认
        img = self.nav.screenshot()
        roi_img = img[fy : fy + fh, fx : fx + fw]
        results = self.ocr.recognize_with_boxes(roi_img)
        texts = [r.text.strip() for r in results]
        return "全部" in texts

    def _process_item(self, item: GridItem, current_screenshot: np.ndarray) -> None:
        """点击一个 item 并提交详情截图到 OCR 队列。"""
        print(f"  点击 [{item.name}] (等级 {item.level or '?'})...")
        self._sim.click_on_window(
            self._hwnd,
            item.click_point.x,
            item.click_point.y,
            attach_thread=self.attach_thread,
        )
        time.sleep(self.cfg.click_delay)

        detail_img = self.nav.screenshot()
        detail_path = self._save_detail(detail_img, item.name)

        # 提交 OCR
        if self.pipeline is not None:
            self.pipeline.submit(detail_img, item.name, detail_path)

        self.state.mark_processed(item.unique_key)

        # 尝试立即合并（如果 OCR 已完成）
        merged = self.state.merge_item(item)
        if merged:
            print(f"    已合并：{merged.name}，评分 {merged.base_score}")

    def _final_merge(self) -> None:
        """最终合并：对每一个有 detail 的 item 重新构造 GridItem 并合并。"""
        # 这里只需要把 state.details 中尚未合并的项处理掉。
        # 由于我们之前每次点击后都尝试 merge，大部分已经合并。
        # 兜底：如果 detail 存在但 results 中没有，则生成一个最小 GridItem 合并。
        for name, detail in list(self.state.details.items()):
            if name in self.state.results:
                continue
            placeholder = GridItem(
                name=name,
                cell_bbox=BBox(0, 0, 0, 0),
                click_point=Point(0, 0),
                level=detail.level,
                derived_affix=None,
                special_grade=None,
                is_acquired=True,
            )
            self.state.merge_item(placeholder)

    def _save_page(self, img: np.ndarray, page: int) -> Path:
        """保存整页截图。"""
        path = self.output_dir / "pages" / f"page_{page:03d}.png"
        cv2.imwrite(str(path), img)
        return path

    def _save_detail(self, img: np.ndarray, name: str) -> Path:
        """保存详情面板截图。"""
        safe_name = name.replace("/", "_").replace("\\", "_")
        path = self.output_dir / "details" / f"detail_{safe_name}.png"
        cv2.imwrite(str(path), img)
        return path

    def _export_json(self, path: Path) -> None:
        """导出最终结果到 JSON。"""
        data = []
        for shq in self.state.results.values():
            data.append({
                "id": shq.id,
                "name": shq.name,
                "quality": shq.quality.value if shq.quality else None,
                "element": shq.element.value if shq.element else None,
                "shanheqi_type": shq.shanheqi_type.value if shq.shanheqi_type else None,
                "level": shq.level,
                "gongguan_level": shq.gongguan_level,
                "base_score": shq.base_score,
                "affixes": [
                    {
                        "name": a.name,
                        "element": a.element.value if a.element else None,
                        "level": a.level,
                        "score": a.score,
                        "derived": a.derived,
                    }
                    for a in shq.affixes
                ],
                "stats": shq.stats,
            })
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
