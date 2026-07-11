"""GUI 业务控制器：连接界面与后台扫描/求解逻辑。"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Dict, List, Optional

from shq.gui.data_store import DataStore
from shq.gui.dialogs import ShanheqiEditDialog, SlotScoreEditDialog
from shq.gui.utils import MessageType, WorkerQueue, copy_to_clipboard, format_score
from shq.gui.widgets import (
    LogPanel,
    ResultView,
    ShanheqiListView,
    SlotCultivationView,
    StatusBar,
    WeightEditor,
)
from shq.gui.workers import ScanWorker, SolveWorker
from shq.models import BuildPreference, Element, Quality, Shanheqi, ShanheqiType
from shq.rules import YMJHDefaultRuleSet
from shq.scanner.manual_importer import ManualImporter


class AppController:
    """协调 GUI 数据、界面刷新与工作线程。"""

    RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "ymjh_rules.json"

    def __init__(
        self,
        root: tk.Tk,
        store: DataStore,
        log: LogPanel,
        status: StatusBar,
        shq_view: ShanheqiListView,
        slot_view: SlotCultivationView,
        result_view: ResultView,
        weight_editor: WeightEditor,
    ):
        self.root = root
        self.store = store
        self.log = log
        self.status = status
        self.shq_view = shq_view
        self.slot_view = slot_view
        self.result_view = result_view
        self.weight_editor = weight_editor

        self.worker_queue: WorkerQueue = WorkerQueue()
        self._current_worker: Optional[Any] = None
        self._last_solution: Optional[Any] = None
        self.on_solution_ready: Optional[Callable[[], None]] = None
        self._build_weights: Dict[str, Dict[str, float]] = {}
        self._region_name_map: Dict[str, str] = {}

        self._load_build_weights()
        self._setup_weight_editor()
        self._load_default_topology()
        self._on_build_changed()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _load_build_weights(self) -> None:
        try:
            rules = json.loads(self.RULES_PATH.read_text(encoding="utf-8"))
            self._build_weights = dict(rules.get("build_weights", {}))
        except Exception as exc:
            self.log.log(f"加载 build_weights 失败：{exc}", level="error")
            self._build_weights = {}

    def _load_default_topology(self) -> None:
        try:
            self.store.lingjian = self.store.load_topology()
            self._region_name_map = {
                r.id: r.name for r in self.store.lingjian.regions
            }
            self.weight_editor.set_regions(
                [(r.id, r.name) for r in self.store.lingjian.regions]
            )
            self.log.log("默认灵鉴拓扑已加载")
        except Exception as exc:
            self.log.log(f"加载默认拓扑失败：{exc}", level="error")

    def _setup_weight_editor(self) -> None:
        self.weight_editor.build_combo.bind(
            "<<ComboboxSelected>>", self._on_build_changed
        )
        self.weight_editor.target_combo.bind(
            "<<ComboboxSelected>>", self._on_target_changed
        )
        for entry in self.weight_editor.entries.values():
            entry.bind("<KeyRelease>", self._on_weight_edited)

    def start_polling(self) -> None:
        self._poll_queue()

    # ------------------------------------------------------------------
    # 工作线程与队列轮询
    # ------------------------------------------------------------------
    def _poll_queue(self) -> None:
        for msg in self.worker_queue.get_all():
            self._handle_message(msg)
        self.root.after(100, self._poll_queue)

    def _handle_message(self, msg: dict) -> None:
        mtype = msg.get("type")
        payload = msg.get("payload")

        if mtype == MessageType.LOG.value:
            self.log.log(str(payload))
        elif mtype == MessageType.PROGRESS.value:
            current = payload.get("current", 0)
            total = payload.get("total", 100)
            pct = int(current / total * 100) if total > 0 else 0
            self.status.set_progress(pct)
            self.status.set_text(f"求解中... {current}/{total}")
        elif mtype == MessageType.DONE.value:
            self._on_worker_done(payload)
            self.status.stop_progress()
            self.status.set_text("就绪")
        elif mtype == MessageType.ERROR.value:
            self.log.log(f"任务失败：{payload}", level="error")
            messagebox.showerror("任务失败", str(payload), parent=self.root)
            self.status.stop_progress()
            self.status.set_text("就绪")

    def _on_worker_done(self, payload: dict) -> None:
        scan_type = payload.get("scan_type")
        if scan_type == ScanWorker.SCAN_WUKU:
            shanheqis = payload.get("shanheqis", [])
            self.store.shanheqis = shanheqis
            self.store.mark_dirty()
            self.refresh_shq_view()
            self.log.log(f"武库数据已载入：{len(shanheqis)} 个山河器", level="success")
        elif scan_type == ScanWorker.SCAN_SLOT:
            lingjian = payload.get("lingjian")
            if lingjian:
                self.store.lingjian = lingjian
                self.store.mark_dirty()
                self.refresh_slot_view()
                self.log.log("孔位培养数据已载入", level="success")
        elif "solution" in payload:
            solution = payload["solution"]
            rules = payload.get("rules")
            self._show_solution(solution, rules)

    def on_stop(self) -> None:
        if self._current_worker is None or not self._current_worker.is_alive():
            self.log.log("当前没有运行中的任务")
            return
        self.log.log("正在请求停止当前任务...", level="warning")
        self._current_worker.request_stop()

    # ------------------------------------------------------------------
    # 导入/保存
    # ------------------------------------------------------------------
    def on_import_wuku(self) -> None:
        self.log.log("请选择要导入的武库 JSON 文件...")
        path = filedialog.askopenfilename(
            title="导入武库 JSON",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            initialdir=str(Path.cwd() / "wuku_scan"),
        )
        if not path:
            self.log.log("取消导入武库")
            return
        self.log.log(f"正在导入武库：{path}")
        try:
            self.store.load_wuku_json(Path(path))
            self.refresh_shq_view()
            self.log.log(f"已导入武库：{path}（{len(self.store.shanheqis)} 个山河器）", level="success")
        except Exception as exc:
            self.log.log(f"导入武库失败：{exc}", level="error")
            messagebox.showerror("导入失败", str(exc), parent=self.root)

    def on_import_slot_cultivation(self) -> None:
        self.log.log("请选择要导入的孔位培养 JSON 文件...")
        path = filedialog.askopenfilename(
            title="导入孔位培养 JSON",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            initialdir=str(Path.cwd() / "lingjian_scan"),
        )
        if not path:
            self.log.log("取消导入孔位培养")
            return
        self.log.log(f"正在导入孔位培养：{path}")
        try:
            self.store.load_slot_cultivation_json(Path(path))
            self.refresh_slot_view()
            self.log.log(f"已导入孔位培养：{path}", level="success")
        except Exception as exc:
            self.log.log(f"导入孔位培养失败：{exc}", level="error")
            messagebox.showerror("导入失败", str(exc), parent=self.root)

    def on_save_wuku(self) -> None:
        self.log.log("请选择武库保存位置...")
        path = filedialog.asksaveasfilename(
            title="保存武库 JSON",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
            initialfile="owned_shanheqis.json",
            initialdir=str(Path.cwd() / "wuku_scan"),
        )
        if not path:
            self.log.log("取消保存武库")
            return
        self.log.log(f"正在保存武库：{path}")
        try:
            self.store.save_wuku_json(Path(path))
            self.log.log(f"武库已保存：{path}", level="success")
        except Exception as exc:
            self.log.log(f"保存武库失败：{exc}", level="error")

    def on_save_slot_cultivation(self) -> None:
        self.log.log("请选择孔位培养保存位置...")
        path = filedialog.asksaveasfilename(
            title="保存孔位培养 JSON",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
            initialfile="slot_cultivation.json",
            initialdir=str(Path.cwd() / "lingjian_scan"),
        )
        if not path:
            self.log.log("取消保存孔位培养")
            return
        self.log.log(f"正在保存孔位培养：{path}")
        try:
            self.store.export_slot_cultivation_json(Path(path))
            self.log.log(f"孔位培养已保存：{path}", level="success")
        except Exception as exc:
            self.log.log(f"保存孔位培养失败：{exc}", level="error")

    def on_save_all(self) -> None:
        self.log.log("请选择全部数据保存位置...")
        path = filedialog.asksaveasfilename(
            title="保存全部数据",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
            initialfile="shq_data.json",
        )
        if not path:
            self.log.log("取消保存全部数据")
            return
        self.log.log(f"正在保存全部数据：{path}")
        try:
            self.store.save_all(Path(path))
            self.log.log(f"全部数据已保存：{path}", level="success")
        except Exception as exc:
            self.log.log(f"保存失败：{exc}", level="error")

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    def on_scan_wuku(self, ocr_backend_name: str = "rapidocr") -> None:
        if self._current_worker and self._current_worker.is_alive():
            messagebox.showwarning("提示", "已有任务在运行中", parent=self.root)
            return
        self.log.log(f"准备扫描武库（OCR：{ocr_backend_name}）...")
        output_dir = Path.cwd() / "wuku_scan"
        output_path = output_dir / "owned_shanheqis.json"
        self.worker_queue = WorkerQueue()
        self._current_worker = ScanWorker(
            queue=self.worker_queue,
            scan_type=ScanWorker.SCAN_WUKU,
            ocr_backend_name=ocr_backend_name,
            output_dir=output_dir,
            output_path=output_path,
        )
        self.status.start_progress("indeterminate")
        self.status.set_text("正在扫描武库...")
        self._current_worker.start()

    def on_scan_slot_cultivation(
        self, ocr_backend_name: str = "rapidocr"
    ) -> None:
        if self._current_worker and self._current_worker.is_alive():
            messagebox.showwarning("提示", "已有任务在运行中", parent=self.root)
            return
        self.log.log(f"准备扫描灵鉴孔位培养（OCR：{ocr_backend_name}）...")
        output_dir = Path.cwd() / "lingjian_scan"
        output_path = output_dir / "slot_cultivation.json"
        self.worker_queue = WorkerQueue()
        self._current_worker = ScanWorker(
            queue=self.worker_queue,
            scan_type=ScanWorker.SCAN_SLOT,
            ocr_backend_name=ocr_backend_name,
            output_dir=output_dir,
            output_path=output_path,
        )
        self.status.start_progress("indeterminate")
        self.status.set_text("正在扫描灵鉴孔位...")
        self._current_worker.start()

    # ------------------------------------------------------------------
    # 求解
    # ------------------------------------------------------------------
    def on_solve(self) -> None:
        if not self.store.shanheqis:
            messagebox.showwarning("提示", "请先导入或扫描山河器", parent=self.root)
            return
        if self.store.lingjian is None:
            messagebox.showwarning("提示", "请先导入或扫描灵鉴孔位", parent=self.root)
            return

        build = self.weight_editor.build_var.get()
        target = self.weight_editor.target_var.get()
        weights = self.weight_editor.get_weights()
        preference = BuildPreference(build=build, weights=weights)

        self.store.set_preference(preference)
        self.log.log(
            f"开始求解：流派={build}，目标={target}，山河器={len(self.store.shanheqis)} 个"
        )

        self.worker_queue = WorkerQueue()
        self._current_worker = SolveWorker(
            queue=self.worker_queue,
            shqs=self.store.shanheqis,
            lingjian=self.store.lingjian,
            preference=preference,
            target=target,
            rules_path=self.RULES_PATH,
        )
        self.status.start_progress("determinate")
        self.status.set_text("正在求解...")
        self._current_worker.start()

    # ------------------------------------------------------------------
    # 权重编辑
    # ------------------------------------------------------------------
    def _on_build_changed(self, _event: Any = None) -> None:
        """选择流派时自动填充对应权重，并切换合适的优化目标。"""
        build = self.weight_editor.build_var.get()
        if build == "自定义":
            return
        weights = self._build_weights.get(build, {})
        self.weight_editor.set_weights(weights)
        # 综合流派直接最大化正面总分；其他流派按权重加权
        target = "build_score" if build != "综合" else "total_score"
        self.weight_editor.target_var.set(target)

    def _on_target_changed(self, _event: Any = None) -> None:
        """优化目标切换说明：
        - total_score：六区域正面评分总和最高，不看流派。
        - build_score：按右侧区域权重加权求和，权重由流派决定。
        """
        target = self.weight_editor.target_var.get()
        self.log.log(f"优化目标已切换为：{target}")

    def _on_weight_edited(self, _event: Any = None) -> None:
        """用户手动修改任一权重时自动切为自定义流派。"""
        if self.weight_editor.build_var.get() != "自定义":
            self.weight_editor.build_var.set("自定义")

    # ------------------------------------------------------------------
    # 数据编辑
    # ------------------------------------------------------------------
    def on_edit_shanheqi(self) -> None:
        shq_id = self.shq_view.selected_shq_id()
        if shq_id is None:
            return
        shq = next((s for s in self.store.shanheqis if s.id == shq_id), None)
        if shq is None:
            return

        def on_save(updated: Shanheqi) -> None:
            self.refresh_shq_view()
            self.log.log(f"山河器已更新：{updated.name}")

        ShanheqiEditDialog(self.root, shq, on_save=on_save)

    def on_add_shanheqi(self) -> None:
        new_id = f"manual_{len(self.store.shanheqis) + 1:03d}"
        shq = Shanheqi(
            id=new_id,
            name="新山河器",
            quality=Quality.SIMPLE,
            element=Element.METAL,
            base_score=0.0,
        )

        def on_save(updated: Shanheqi) -> None:
            self.store.add_shanheqi(updated)
            self.refresh_shq_view()
            self.log.log(f"已添加山河器：{updated.name}", level="success")

        ShanheqiEditDialog(self.root, shq, on_save=on_save)

    def on_delete_shanheqi(self) -> None:
        shq_id = self.shq_view.selected_shq_id()
        if shq_id is None:
            return
        shq = next((s for s in self.store.shanheqis if s.id == shq_id), None)
        if shq is None:
            return
        if messagebox.askyesno(
            "确认删除", f"确定删除山河器「{shq.name}」吗？", parent=self.root
        ):
            self.store.remove_shanheqi(shq_id)
            self.refresh_shq_view()
            self.log.log(f"已删除山河器：{shq.name}")

    def on_edit_slot(self) -> None:
        slot_id = self.slot_view.selected_slot_id()
        if slot_id is None or self.store.lingjian is None:
            return
        slot = self.store.lingjian.get_slot(slot_id)
        if slot is None:
            return
        region = self.store.lingjian.get_region(slot.region_id)
        region_name = region.name if region else slot.region_id

        def on_save(score: float) -> None:
            slot.cultivation_score = score
            self.store.mark_dirty()
            self.refresh_slot_view()
            self.log.log(f"{region_name} 孔 {slot.number} 培养分已更新为 {score}")

        SlotScoreEditDialog(
            self.root,
            region_name=region_name,
            slot_number=slot.number,
            current_score=slot.cultivation_score,
            on_save=on_save,
        )

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------
    def _show_solution(self, solution: Any, rules: Any) -> None:
        self._last_solution = solution
        report = self._generate_markdown(solution, rules)
        self.result_view.set_content(report)
        if self.on_solution_ready is not None:
            self.on_solution_ready()
        self.log.log("最优摆放方案已生成", level="success")

    def _generate_markdown(self, solution: Any, rules: Any) -> str:
        ev = solution.evaluation
        preference = self.store.preference
        target = solution.target
        score = rules.score(ev, target, preference)

        lines: List[str] = []
        lines.append(f"# {preference.build}流派最优摆放方案")
        lines.append("")
        lines.append(f"**求解器**: {solution.description.split()[0]}")
        lines.append(f"**目标**: {target}")
        lines.append(f"**流派**: {preference.build}")
        lines.append(f"**加权输出分**: `{format_score(score)}`")
        lines.append(f"**总评分**: `{format_score(ev.total_score)}`")
        lines.append("")

        lines.append("## 孔位说明")
        lines.append("")
        lines.append(
            "- **孔 1/2/3/4/5/6**：对应灵鉴界面中「孔位培养」面板显示的序号，"
            "即游戏内标注的 壹、贰、叁、肆、伍、陆。"
        )
        lines.append(
            "- 生成结果中的“孔 1”即表示把该山河器放到灵鉴中序号为 壹 的位置，"
            "以此类推。"
        )
        lines.append("")

        lines.append("## 区域评分")
        lines.append("")
        lines.append("| 区域 | 评分 |")
        lines.append("|---|---|")
        for rid, rscore in ev.region_scores.items():
            rname = self._region_name_map.get(rid, rid)
            lines.append(f"| {rname} | `{format_score(rscore)}` |")
        lines.append("")

        if ev.back_scores:
            lines.append("## 背面 6 号位评分")
            lines.append("")
            lines.append("| 区域 | 评分 |")
            lines.append("|---|---|")
            for rid, bscore in ev.back_scores.items():
                rname = self._region_name_map.get(rid, rid)
                lines.append(f"| {rname} | `{format_score(bscore)}` |")
            lines.append("")

        lines.append("## 正面摆放详情")
        lines.append("")
        shq_map = {shq.id: shq for shq in self.store.shanheqis}
        for region in self.store.lingjian.regions:
            rscore = ev.region_scores.get(region.id, 0.0)
            lines.append(f"### {region.name}（区域分 {format_score(rscore)}）")
            lines.append("")
            for slot in region.front_slots:
                shq_id = solution.placement.mapping.get(slot.id)
                shq = shq_map.get(shq_id)
                if shq:
                    desc = self._describe_shanheqi(shq)
                    lines.append(f"- **孔 {slot.number}**: {desc}")
                else:
                    lines.append(f"- **孔 {slot.number}**: （空）")
            lines.append("")

        if solution.placement.back_mapping:
            lines.append("## 背面摆放详情")
            lines.append("")
            for slot_id, shq_id in solution.placement.back_mapping.items():
                shq = shq_map.get(shq_id)
                if shq:
                    lines.append(f"- **{slot_id}**: {self._describe_shanheqi(shq)}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _describe_shanheqi(shq: Shanheqi) -> str:
        affix_str = " ".join(
            f"{a.element.value if a.element else ''}{a.name}{a.level}"
            for a in shq.affixes
        )
        affix_str = affix_str or "无"
        derived_str = ", ".join(shq.derived_affixes) or "无"
        return (
            f"{shq.quality.value}·{shq.element.value}·{shq.name}Lv{shq.level}"
            f"(基础{int(shq.base_score)} 素蕴[{affix_str}] 派生[{derived_str}])"
        )

    # ------------------------------------------------------------------
    # 视图刷新
    # ------------------------------------------------------------------
    def refresh_shq_view(self) -> None:
        self.shq_view.refresh(self.store.shanheqis)

    def refresh_slot_view(self) -> None:
        self.slot_view.refresh(self.store.lingjian)

    def refresh_all(self) -> None:
        self.refresh_shq_view()
        self.refresh_slot_view()

    # ------------------------------------------------------------------
    # 剪贴板/保存
    # ------------------------------------------------------------------
    def on_copy_result(self) -> None:
        text = self.result_view.get_content()
        copy_to_clipboard(self.root, text)
        self.log.log("结果已复制到剪贴板", level="success")

    def on_save_result_markdown(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存方案报告",
            defaultextension=".md",
            filetypes=[("Markdown 文件", "*.md"), ("文本文件", "*.txt")],
            initialfile="placement_result.md",
        )
        if not path:
            return
        Path(path).write_text(
            self.result_view.get_content(), encoding="utf-8"
        )
        self.log.log(f"报告已保存：{path}", level="success")

    def on_save_result_json(self) -> None:
        if self.store.lingjian is None:
            messagebox.showwarning("提示", "没有灵鉴数据可保存", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            title="保存方案 JSON",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
            initialfile="placement_result.json",
        )
        if not path:
            return

        region_name_map = {r.id: r.name for r in self.store.lingjian.regions}
        if self._last_solution is not None:
            solution = self._last_solution
            placement_result = {
                "正面": {
                    region_name_map.get(r.id, r.id): {
                        slot.number: solution.placement.mapping.get(slot.id)
                        for slot in r.front_slots
                    }
                    for r in self.store.lingjian.regions
                },
                "背面": solution.placement.back_mapping,
            }
            data = {
                "solver": "local_search",
                "target": solution.target,
                "build": self.store.preference.build,
                "score": solution.evaluation.total_score,
                "total_score": solution.evaluation.total_score,
                "region_scores": {
                    region_name_map.get(rid, rid): score
                    for rid, score in solution.evaluation.region_scores.items()
                },
                "back_scores": {
                    region_name_map.get(rid, rid): score
                    for rid, score in solution.evaluation.back_scores.items()
                },
                "placement": placement_result,
            }
        else:
            data = {
                "shanheqis": len(self.store.shanheqis),
                "regions": list(region_name_map.values()),
                "preference": {
                    "build": self.store.preference.build,
                    "weights": dict(self.store.preference.weights),
                },
            }

        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.log.log(f"方案 JSON 已保存：{path}", level="success")

    # ------------------------------------------------------------------
    # 关闭确认
    # ------------------------------------------------------------------
    def on_closing(self) -> bool:
        if self.store.dirty:
            result = messagebox.askyesnocancel(
                "未保存的更改",
                "数据尚未保存，是否保存后再退出？",
                parent=self.root,
            )
            if result is True:
                self.on_save_all()
                return True
            if result is False:
                return True
            return False
        return True
