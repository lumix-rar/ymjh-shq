"""可复用的 GUI 控件。"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple


class LogPanel(tk.Frame):
    """带时间戳与颜色区分的日志面板。"""

    def __init__(self, parent: tk.Widget, height: int = 10, **kwargs: Any):
        super().__init__(parent, **kwargs)

        self.text = tk.Text(
            self,
            height=height,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.scrollbar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.config(yscrollcommand=self.scrollbar.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.text.tag_config("info", foreground="black")
        self.text.tag_config("warning", foreground="#b35900")
        self.text.tag_config("error", foreground="red")
        self.text.tag_config("success", foreground="green")

    def log(self, message: str, level: str = "info") -> None:
        """追加一条日志。"""
        import datetime

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.text.config(state=tk.NORMAL)
        self.text.insert(tk.END, line, level)
        self.text.config(state=tk.DISABLED)
        self.text.see(tk.END)

    def clear(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.config(state=tk.DISABLED)


class StatusBar(ttk.Frame):
    """底部状态栏，包含状态文本与进度条。"""

    def __init__(self, parent: tk.Widget, **kwargs: Any):
        super().__init__(parent, **kwargs)

        self.label = ttk.Label(self, text="就绪", anchor=tk.W)
        self.progress = ttk.Progressbar(
            self, mode="determinate", orient=tk.HORIZONTAL, length=200
        )

        self.label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress.pack(side=tk.RIGHT, padx=(5, 0))

    def set_text(self, text: str) -> None:
        self.label.config(text=text)

    def start_progress(self, mode: str = "indeterminate") -> None:
        self.progress.config(mode=mode)
        if mode == "indeterminate":
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.config(value=0)

    def stop_progress(self) -> None:
        self.progress.stop()
        self.progress.config(value=0)

    def set_progress(self, value: int) -> None:
        self.progress.config(mode="determinate", value=value)


class ScrollableTreeview(ttk.Frame):
    """带滚动条的 Treeview 封装。"""

    def __init__(
        self,
        parent: tk.Widget,
        columns: List[Tuple[str, str, int]],
        show: str = "headings",
        on_double_click: Optional[Callable[[], None]] = None,
        on_right_click: Optional[Callable[[tk.Event[Any]], None]] = None,
        **kwargs: Any,
    ):
        """columns: [(id, heading, width), ...]。"""
        super().__init__(parent, **kwargs)

        self.tree = ttk.Treeview(
            self, columns=[c[0] for c in columns], show=show
        )
        self.vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.hsb = ttk.Scrollbar(
            self, orient=tk.HORIZONTAL, command=self.tree.xview
        )
        self.tree.configure(
            yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set
        )

        for col_id, heading, width in columns:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, anchor="center")

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        if on_double_click:
            self.tree.bind("<Double-1>", lambda _e: on_double_click())
        if on_right_click:
            self.tree.bind("<Button-3>", on_right_click)
            self.tree.bind("<Button-2>", on_right_click)

    def insert(self, iid: str, values: Tuple[Any, ...], **kwargs: Any) -> None:
        self.tree.insert("", tk.END, iid=iid, values=values, **kwargs)

    def delete(self, iid: str) -> None:
        if self.tree.exists(iid):
            self.tree.delete(iid)

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def selected_iid(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def selected_values(self) -> Optional[Tuple[Any, ...]]:
        iid = self.selected_iid()
        if iid is None:
            return None
        return self.tree.item(iid, "values")

    def update_item(self, iid: str, values: Tuple[Any, ...]) -> None:
        if self.tree.exists(iid):
            self.tree.item(iid, values=values)


class ShanheqiListView(tk.Frame):
    """山河器列表视图。"""

    COLUMNS = [
        ("id", "ID", 80),
        ("name", "名称", 140),
        ("quality", "品质", 60),
        ("element", "五行", 50),
        ("level", "等级", 50),
        ("base_score", "基础分", 70),
        ("type", "类型", 70),
        ("derived", "派生", 120),
    ]

    def __init__(
        self,
        parent: tk.Widget,
        on_double_click: Optional[Callable[[], None]] = None,
        on_right_click: Optional[Callable[[tk.Event[Any]], None]] = None,
        **kwargs: Any,
    ):
        super().__init__(parent, **kwargs)

        self.tree = ScrollableTreeview(
            self,
            columns=self.COLUMNS,
            on_double_click=on_double_click,
            on_right_click=on_right_click,
        )
        self.tree.pack(fill=tk.BOTH, expand=True)

    def refresh(self, shanheqis: List[Any]) -> None:
        self.tree.clear()
        for shq in shanheqis:
            derived_str = ", ".join(shq.derived_affixes) or "无"
            self.tree.insert(
                shq.id,
                (
                    shq.id,
                    shq.name,
                    shq.quality.value,
                    shq.element.value,
                    shq.level,
                    shq.base_score,
                    shq.shanheqi_type.value,
                    derived_str,
                ),
            )

    def selected_shq_id(self) -> Optional[str]:
        return self.tree.selected_iid()


class SlotCultivationView(tk.Frame):
    """灵鉴孔位培养分视图。"""

    COLUMNS = [
        ("region", "区域", 120),
        ("number", "孔位", 50),
        ("score", "培养分", 80),
    ]

    def __init__(
        self,
        parent: tk.Widget,
        on_double_click: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ):
        super().__init__(parent, **kwargs)

        self.tree = ScrollableTreeview(
            self,
            columns=self.COLUMNS,
            on_double_click=on_double_click,
        )
        self.tree.pack(fill=tk.BOTH, expand=True)

    def refresh(self, lingjian: Optional[Any]) -> None:
        self.tree.clear()
        if lingjian is None:
            return
        for region in lingjian.regions:
            for slot in region.slots:
                self.tree.insert(
                    slot.id,
                    (region.name, slot.number, slot.cultivation_score),
                )

    def selected_slot_id(self) -> Optional[str]:
        return self.tree.selected_iid()


class MarkdownRenderer:
    """把 Markdown 文本渲染到 tk.Text 控件中。

    支持的语法：
    - 标题 # / ## / ###
    - 加粗 **text**
    - 行内代码 `text`
    - 无序列表 - / *
    - 表格（含表头加粗）
    """

    def __init__(self, text_widget: tk.Text):
        self.text = text_widget
        self._configure_tags()

    def _configure_tags(self) -> None:
        self.text.tag_config("h1", font=("Microsoft YaHei", 16, "bold"), spacing3=8)
        self.text.tag_config("h2", font=("Microsoft YaHei", 13, "bold"), spacing3=6)
        self.text.tag_config("h3", font=("Microsoft YaHei", 11, "bold"), spacing3=4)
        self.text.tag_config("bold", font=("Consolas", 11, "bold"))
        self.text.tag_config("code", font=("Consolas", 11), foreground="#0066cc")
        self.text.tag_config("li", font=("Consolas", 11))
        self.text.tag_config("table", font=("Consolas", 10))
        self.text.tag_config("table_header", font=("Consolas", 10, "bold"))

    def render(self, content: str) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)

        lines = content.splitlines()
        i = 0
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()

            if stripped.startswith("#"):
                self._render_heading(stripped)
            elif stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                table_lines: list[str] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                self._render_table(table_lines)
                continue
            elif stripped.startswith(("- ", "* ")):
                self._render_list_item(raw)
            elif stripped == "":
                self.text.insert(tk.END, "\n")
            else:
                self._render_paragraph(raw)
            i += 1

        self.text.config(state=tk.DISABLED)

    def _render_heading(self, stripped: str) -> None:
        level = 0
        for char in stripped:
            if char == "#":
                level += 1
            else:
                break
        text = stripped[level:].strip()
        tag = f"h{min(level, 3)}"
        self.text.insert(tk.END, text + "\n", tag)

    def _render_list_item(self, raw: str) -> None:
        stripped = raw.lstrip()
        indent = " " * (len(raw) - len(stripped))
        content = stripped[2:]
        self.text.insert(tk.END, indent + "• ", "li")
        self._insert_rich_text(content)
        self.text.insert(tk.END, "\n", "li")

    def _render_paragraph(self, raw: str) -> None:
        self._insert_rich_text(raw)
        self.text.insert(tk.END, "\n")

    def _insert_rich_text(self, text: str, base_tag: Optional[str] = None) -> None:
        """插入一段可能包含 **加粗** 和 `代码` 的文本。"""
        pattern = re.compile(r"\*\*(.+?)\*\*|\`([^`]+)\`")
        pos = 0
        for match in pattern.finditer(text):
            if match.start() > pos:
                self.text.insert(tk.END, text[pos : match.start()], base_tag)
            if match.group(1) is not None:
                tags = ("bold", base_tag) if base_tag else "bold"
                self.text.insert(tk.END, match.group(1), tags)
            else:
                tags = ("code", base_tag) if base_tag else "code"
                self.text.insert(tk.END, match.group(2), tags)
            pos = match.end()
        if pos < len(text):
            self.text.insert(tk.END, text[pos:], base_tag)

    def _render_table(self, lines: list[str]) -> None:
        """渲染 Markdown 表格。"""
        rows: list[list[str]] = []
        for line in lines:
            cells = [c.strip() for c in line.strip().split("|")]
            # 去掉最外层空单元格
            cells = [c for c in cells if c or c == ""]
            # 去掉首尾空字符串（由 |...| 产生的）
            while cells and cells[0] == "":
                cells.pop(0)
            while cells and cells[-1] == "":
                cells.pop()
            rows.append(cells)

        if len(rows) < 2:
            self._render_paragraph("\n".join(lines))
            return

        header = rows[0]
        # 第二行通常是分隔符，跳过
        data_rows = rows[2:]
        all_rows = [header] + data_rows

        # 计算每列最大宽度（去掉 rich text 标记后）
        widths: list[int] = [0] * len(header)
        for cells in all_rows:
            for idx, cell in enumerate(cells):
                if idx >= len(widths):
                    widths.append(0)
                plain = re.sub(r"\*\*|\`", "", cell)
                widths[idx] = max(widths[idx], len(plain))

        def format_row(cells: list[str], tag: str = "table") -> None:
            self.text.insert(tk.END, "| ", tag)
            for idx, cell in enumerate(cells):
                width = widths[idx] if idx < len(widths) else len(cell)
                self._insert_table_cell(cell, width, tag)
                if idx < len(cells) - 1:
                    self.text.insert(tk.END, " | ", tag)
            self.text.insert(tk.END, " |\n", tag)

        format_row(header, "table_header")
        # 分隔线
        self.text.insert(tk.END, "|", "table")
        for idx, width in enumerate(widths):
            self.text.insert(tk.END, "-" * (width + 2), "table")
            if idx < len(widths) - 1:
                self.text.insert(tk.END, "|", "table")
        self.text.insert(tk.END, "|\n", "table")

        for cells in data_rows:
            format_row(cells)

    def _insert_table_cell(self, cell: str, width: int, tag: str) -> None:
        """插入表格单元格，先插入富文本内容，再用空格补齐宽度。"""
        plain = re.sub(r"\*\*|\`", "", cell)
        padding = width - len(plain)
        self._insert_rich_text(cell, base_tag=tag)
        if padding > 0:
            self.text.insert(tk.END, " " * padding, tag)


class ResultView(tk.Frame):
    """Markdown 结果展示面板。"""

    def __init__(self, parent: tk.Widget, **kwargs: Any):
        super().__init__(parent, **kwargs)

        self.text = tk.Text(
            self,
            wrap=tk.WORD,
            font=("Consolas", 11),
            padx=10,
            pady=10,
        )
        self.scrollbar = ttk.Scrollbar(self, command=self.text.yview)
        self.text.config(yscrollcommand=self.scrollbar.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.renderer = MarkdownRenderer(self.text)

    def set_content(self, content: str) -> None:
        self.renderer.render(content)
        self.text.see("1.0")

    def get_content(self) -> str:
        return self.text.get("1.0", tk.END)

    def clear(self) -> None:
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.config(state=tk.DISABLED)


class WeightEditor(tk.Frame):
    """区域权重编辑器。"""

    def __init__(self, parent: tk.Widget, **kwargs: Any):
        super().__init__(parent, **kwargs)

        self.entries: Dict[str, tk.Entry] = {}
        self.build_var = tk.StringVar(value="综合")
        self.target_var = tk.StringVar(value="build_score")

        top = tk.Frame(self)
        top.pack(fill=tk.X, pady=5)

        tk.Label(top, text="流派：").pack(side=tk.LEFT)
        self.build_combo = ttk.Combobox(
            top,
            textvariable=self.build_var,
            values=["输出", "治疗", "承伤", "综合", "自定义"],
            state="readonly",
            width=10,
        )
        self.build_combo.pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(top, text="优化目标：").pack(side=tk.LEFT)
        self.target_combo = ttk.Combobox(
            top,
            textvariable=self.target_var,
            values=["total_score", "build_score"],
            state="readonly",
            width=12,
        )
        self.target_combo.pack(side=tk.LEFT)

        # 优化目标说明
        self.target_hint = tk.Label(
            self,
            text="total_score = 正面六区域总分最高 ｜ build_score = 按流派权重加权，更贴合输出/治疗/承伤方向",
            fg="gray",
            font=("Microsoft YaHei", 9),
            wraplength=280,
            justify=tk.LEFT,
            anchor=tk.W,
        )
        self.target_hint.pack(fill=tk.X, pady=(0, 5))

        # 权重说明
        self.weight_hint = tk.Label(
            self,
            text="区域权重：数值越高，该区域在 build_score 中越重要；选择流派会自动填充社区推荐权重。",
            fg="gray",
            font=("Microsoft YaHei", 9),
            wraplength=280,
            justify=tk.LEFT,
            anchor=tk.W,
        )
        self.weight_hint.pack(fill=tk.X, pady=(0, 5))

        self.table = tk.Frame(self)
        self.table.pack(fill=tk.BOTH, expand=True, pady=5)

    def set_regions(self, regions: List[Tuple[str, str]]) -> None:
        """regions: [(region_id, region_name), ...]。"""
        for widget in self.table.winfo_children():
            widget.destroy()
        self.entries.clear()

        for idx, (rid, rname) in enumerate(regions):
            row = tk.Frame(self.table)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=rname, width=12, anchor=tk.W).pack(side=tk.LEFT)
            entry = tk.Entry(row, width=10)
            entry.pack(side=tk.LEFT, padx=(5, 0))
            self.entries[rid] = entry

    def get_weights(self) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for rid, entry in self.entries.items():
            try:
                weights[rid] = float(entry.get())
            except ValueError:
                weights[rid] = 0.0
        return weights

    def set_weights(self, weights: Dict[str, float]) -> None:
        for rid, value in weights.items():
            if rid in self.entries:
                self.entries[rid].delete(0, tk.END)
                self.entries[rid].insert(0, str(value))

    def set_custom_mode(self) -> None:
        self.build_var.set("自定义")
