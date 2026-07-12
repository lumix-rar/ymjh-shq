"""山河器最优摆放 GUI 主窗口。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from shq.gui.controller import AppController
from shq.gui.data_store import DataStore
from shq.gui.widgets import (
    LogPanel,
    ResultView,
    ShanheqiListView,
    SlotCultivationView,
    StatusBar,
    WeightEditor,
)
from shq.gui.workers import list_available_ocr_backends


class ShqGuiApplication:
    """山河器最优摆放 GUI 应用。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("山河器最优摆放求解器 v1.0.0")
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        self.store = DataStore()

        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_log_and_status()

        self.controller = AppController(
            root=self.root,
            store=self.store,
            log=self.log_panel,
            status=self.status_bar,
            shq_view=self.shq_view,
            slot_view=self.slot_view,
            result_view=self.result_view,
            weight_editor=self.weight_editor,
        )
        self.controller.start_polling()
        self.controller.on_solution_ready = self._switch_to_result_tab

        # 尝试加载默认扫描结果（如果存在）
        self._try_load_defaults()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="导入武库 JSON", command=lambda: self.controller.on_import_wuku())
        file_menu.add_command(label="导入孔位培养 JSON", command=lambda: self.controller.on_import_slot_cultivation())
        file_menu.add_separator()
        file_menu.add_command(label="保存武库 JSON", command=lambda: self.controller.on_save_wuku())
        file_menu.add_command(label="保存孔位培养 JSON", command=lambda: self.controller.on_save_slot_cultivation())
        file_menu.add_command(label="保存全部", command=lambda: self.controller.on_save_all())
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_closing)
        menubar.add_cascade(label="文件(F)", menu=file_menu)

        scan_menu = tk.Menu(menubar, tearoff=0)
        scan_menu.add_command(
            label="一键扫描武库",
            command=lambda: self.controller.on_scan_wuku(
                self.ocr_var.get(), self.auto_resize_var.get()
            ),
        )
        scan_menu.add_command(
            label="一键扫描灵鉴",
            command=lambda: self.controller.on_scan_slot_cultivation(
                self.ocr_var.get(), self.auto_resize_var.get()
            ),
        )
        menubar.add_cascade(label="扫描(S)", menu=scan_menu)

        solve_menu = tk.Menu(menubar, tearoff=0)
        solve_menu.add_command(label="一键生成方案", command=lambda: self.controller.on_solve())
        solve_menu.add_separator()
        solve_menu.add_command(label="停止当前任务", command=lambda: self.controller.on_stop())
        menubar.add_cascade(label="求解(R)", menu=solve_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助(H)", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(
            toolbar,
            text="一键扫描武库",
            command=lambda: self.controller.on_scan_wuku(
                self.ocr_var.get(), self.auto_resize_var.get()
            ),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            toolbar,
            text="一键扫描灵鉴",
            command=lambda: self.controller.on_scan_slot_cultivation(
                self.ocr_var.get(), self.auto_resize_var.get()
            ),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            toolbar,
            text="导入武库 JSON",
            command=lambda: self.controller.on_import_wuku(),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            toolbar,
            text="导入孔位 JSON",
            command=lambda: self.controller.on_import_slot_cultivation(),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            toolbar,
            text="一键生成",
            command=lambda: self.controller.on_solve(),
        ).pack(side=tk.LEFT, padx=(15, 2))
        ttk.Button(
            toolbar,
            text="停止",
            command=lambda: self.controller.on_stop(),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Label(toolbar, text="OCR：").pack(side=tk.LEFT, padx=(20, 0))
        available_ocrs = list_available_ocr_backends()
        self.ocr_var = tk.StringVar(value=available_ocrs[0] if available_ocrs else "")
        ocr_combo = ttk.Combobox(
            toolbar,
            textvariable=self.ocr_var,
            values=available_ocrs,
            state="readonly",
            width=10,
        )
        ocr_combo.pack(side=tk.LEFT)

        self.auto_resize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar,
            text="自动调整游戏窗口大小",
            variable=self.auto_resize_var,
        ).pack(side=tk.LEFT, padx=(15, 0))

        if not available_ocrs:
            ttk.Label(
                toolbar,
                text="（未检测到可用 OCR，扫描功能不可用）",
                foreground="red",
            ).pack(side=tk.LEFT, padx=(5, 0))

    def _build_main_area(self) -> None:
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧 Notebook：数据/结果
        self.left_notebook = ttk.Notebook(main_frame)
        self.left_notebook.grid(row=0, column=0, sticky="nsew")

        self.shq_view = ShanheqiListView(
            self.left_notebook,
            on_double_click=lambda: self.controller.on_edit_shanheqi(),
            on_right_click=self._on_shq_right_click,
        )
        self.left_notebook.add(self.shq_view, text="山河器")

        self.slot_view = SlotCultivationView(
            self.left_notebook,
            on_double_click=lambda: self.controller.on_edit_slot(),
        )
        self.left_notebook.add(self.slot_view, text="灵鉴孔位")

        self.result_container = ttk.Frame(self.left_notebook)
        self.result_container.grid_rowconfigure(1, weight=1)
        self.result_container.grid_columnconfigure(0, weight=1)

        result_btn_frame = ttk.Frame(self.result_container)
        result_btn_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        ttk.Button(
            result_btn_frame,
            text="复制报告",
            command=lambda: self.controller.on_copy_result(),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            result_btn_frame,
            text="保存 Markdown",
            command=lambda: self.controller.on_save_result_markdown(),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            result_btn_frame,
            text="保存 JSON",
            command=lambda: self.controller.on_save_result_json(),
        ).pack(side=tk.LEFT, padx=2)

        self.result_view = ResultView(self.result_container)
        self.result_view.grid(row=1, column=0, sticky="nsew")
        self.left_notebook.add(self.result_container, text="结果")

        # 右侧权重编辑
        self.weight_editor = WeightEditor(main_frame)
        self.weight_editor.grid(row=0, column=1, sticky="ns", padx=(5, 0))

        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=0)

    def _build_log_and_status(self) -> None:
        self.log_panel = LogPanel(self.root, height=12)
        self.log_panel.pack(fill=tk.X, padx=5, pady=(0, 5))

        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, padx=5, pady=(0, 5))

    def _on_shq_right_click(self, event: Any) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="编辑", command=self.controller.on_edit_shanheqi)
        menu.add_command(label="删除", command=self.controller.on_delete_shanheqi)
        menu.post(event.x_root, event.y_root)

    def _try_load_defaults(self) -> None:
        from pathlib import Path

        wuku_path = Path.cwd() / "wuku_scan" / "owned_shanheqis.json"
        slot_path = Path.cwd() / "lingjian_scan" / "slot_cultivation.json"
        loaded = False
        if wuku_path.exists():
            try:
                self.store.load_wuku_json(wuku_path)
                self.controller.refresh_shq_view()
                self.log_panel.log(f"已自动加载武库：{wuku_path}")
            except Exception as exc:
                self.log_panel.log(f"自动加载武库失败：{exc}", level="warning")
        if slot_path.exists():
            try:
                self.store.load_slot_cultivation_json(slot_path)
                self.controller.refresh_slot_view()
                self.log_panel.log(f"已自动加载孔位培养：{slot_path}")
            except Exception as exc:
                self.log_panel.log(
                    f"自动加载孔位培养失败：{exc}", level="warning"
                )

    def _switch_to_result_tab(self) -> None:
        """生成完成后自动切换到结果标签页。"""
        self.left_notebook.select(self.result_container)

    def _show_about(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            "关于",
            "山河器最优摆放求解器 v1.0.0\n\n"
            "基于实测规则与局部搜索算法，"
            "支持一键扫描、导入、权重配置与方案生成。\n\n"
            "作者：辰星换灯影",
            parent=self.root,
        )

    def _show_usage(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            "使用说明",
            "欢迎使用山河器最优摆放求解器 v1.0.0！\n\n"
            "【限制】本工具仅适用于 Windows PC 端《一梦江湖》官方客户端，"
            "不支持模拟器、云游戏或其他平台。\n\n"
            "1. 进入游戏，打开【山河器-灵鉴】界面并保持不动。\n"
            "2. 如需自动扫描：确保游戏窗口可见，选择右上角 OCR 引擎，"
            "点击“一键扫描武库”或“一键扫描灵鉴”。\n"
            "3. 如已有 JSON 数据：点击“导入武库 JSON”或“导入孔位 JSON”。\n"
            "4. 在“山河器”和“灵鉴孔位”标签页核对数据，双击可编辑。\n"
            "5. 在右侧选择流派与权重，点击“一键生成”获得最优摆放方案。\n\n"
            "提示：扫描过程请勿移动/点击游戏窗口，以免识别失败。\n\n"
            "作者：辰星换灯影",
            parent=self.root,
        )

    def _on_closing(self) -> None:
        if self.controller.on_closing():
            self.root.destroy()


def main() -> None:
    from tkinter import messagebox
    from shq.gui.utils import is_admin

    def _close_splash() -> None:
        """关闭 PyInstaller 启动画面（非打包环境忽略）。"""
        try:
            import pyi_splash  # type: ignore

            pyi_splash.close()
        except Exception:
            pass

    root = tk.Tk()
    root.withdraw()

    if not is_admin():
        result = messagebox.askyesno(
            "需要管理员权限",
            "检测到当前未以管理员权限运行。\n\n"
            "自动化点击游戏窗口、读取后台进程等功能通常需要管理员权限，"
            "否则可能出现“找不到窗口”或“点击无效”。\n\n"
            "建议按以下步骤重新启动：\n"
            "1. 关闭当前窗口；\n"
            "2. 右键点击命令行/PowerShell/快捷方式；\n"
            "3. 选择“以管理员身份运行”；\n"
            "4. 执行：python -m shq.gui\n\n"
            "是否立即退出并按管理员方式重新启动？",
            parent=root,
        )
        if result:
            root.destroy()
            return

    app = ShqGuiApplication(root)
    root.after(200, app._show_usage)
    root.deiconify()
    _close_splash()
    root.mainloop()


if __name__ == "__main__":
    main()
