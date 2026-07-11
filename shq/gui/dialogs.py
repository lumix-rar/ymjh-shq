"""编辑弹窗。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Any, List, Optional

from shq.models import Element, Quality, Shanheqi, ShanheqiType


class ShanheqiEditDialog(tk.Toplevel):
    """编辑单个山河器属性的弹窗。"""

    def __init__(
        self,
        parent: tk.Widget,
        shq: Shanheqi,
        on_save: Optional[Callable[[Shanheqi], None]] = None,
    ):
        super().__init__(parent)
        self.shq = shq
        self.on_save = on_save
        self.title(f"编辑山河器 - {shq.name}")
        self.geometry("360x420")
        self.transient(parent)
        self.grab_set()

        self._result: Optional[Shanheqi] = None

        self._build_form()
        self._load_values()

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )

    def _build_form(self) -> None:
        self.form = tk.Frame(self)
        self.form.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.fields: dict[str, Any] = {}
        rows: List[tuple[str, str, Any]] = [
            ("name", "名称", tk.Entry(self.form)),
            (
                "quality",
                "品质",
                ttk.Combobox(
                    self.form,
                    values=[q.value for q in Quality],
                    state="readonly",
                    width=12,
                ),
            ),
            (
                "element",
                "五行",
                ttk.Combobox(
                    self.form,
                    values=[e.value for e in Element],
                    state="readonly",
                    width=12,
                ),
            ),
            ("level", "等级", tk.Entry(self.form)),
            ("base_score", "基础分", tk.Entry(self.form)),
            (
                "shanheqi_type",
                "类型",
                ttk.Combobox(
                    self.form,
                    values=[t.value for t in ShanheqiType],
                    state="readonly",
                    width=12,
                ),
            ),
            ("derived_affixes", "派生素蕴", tk.Entry(self.form)),
        ]

        for idx, (key, label, widget) in enumerate(rows):
            tk.Label(self.form, text=label, width=10, anchor=tk.W).grid(
                row=idx, column=0, pady=5, sticky="w"
            )
            widget.grid(row=idx, column=1, pady=5, sticky="ew")
            self.fields[key] = widget

        self.form.grid_columnconfigure(1, weight=1)

        tk.Label(
            self.form,
            text="派生素蕴用半角逗号分隔，如：起势,金实",
            fg="gray",
            font=("Microsoft YaHei", 9),
        ).grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _load_values(self) -> None:
        self.fields["name"].insert(0, self.shq.name)
        self.fields["quality"].set(self.shq.quality.value)
        self.fields["element"].set(self.shq.element.value)
        self.fields["level"].insert(0, str(self.shq.level))
        self.fields["base_score"].insert(0, str(self.shq.base_score))
        self.fields["shanheqi_type"].set(self.shq.shanheqi_type.value)
        self.fields["derived_affixes"].insert(
            0, ", ".join(self.shq.derived_affixes)
        )

    def _on_save(self) -> None:
        try:
            self.shq.name = self.fields["name"].get().strip()
            self.shq.quality = _parse_enum(
                Quality, self.fields["quality"].get()
            )
            self.shq.element = _parse_enum(
                Element, self.fields["element"].get()
            )
            self.shq.level = int(self.fields["level"].get())
            self.shq.base_score = float(self.fields["base_score"].get())
            self.shq.shanheqi_type = _parse_enum(
                ShanheqiType, self.fields["shanheqi_type"].get()
            )
            raw = self.fields["derived_affixes"].get()
            self.shq.derived_affixes = [
                s.strip() for s in raw.replace("，", ",").split(",") if s.strip()
            ]
        except Exception as exc:
            messagebox.showerror("数据错误", f"保存失败：{exc}", parent=self)
            return

        self._result = self.shq
        if self.on_save:
            self.on_save(self.shq)
        self.destroy()


def _parse_enum(enum_cls, value: str):
    """优先按枚举名解析，否则按中文 value 解析。"""
    try:
        return enum_cls[value.upper()]
    except KeyError:
        for member in enum_cls:
            if member.value == value:
                return member
    raise ValueError(f"无法解析 {enum_cls.__name__}：{value}")

    def get_result(self) -> Optional[Shanheqi]:
        return self._result


class SlotScoreEditDialog(tk.Toplevel):
    """编辑单个孔位培养分的弹窗。"""

    def __init__(
        self,
        parent: tk.Widget,
        region_name: str,
        slot_number: int,
        current_score: float,
        on_save: Optional[Callable[[float], None]] = None,
    ):
        super().__init__(parent)
        self.title(f"编辑培养分 - {region_name} 孔 {slot_number}")
        self.geometry("280x140")
        self.transient(parent)
        self.grab_set()

        self.on_save = on_save
        self._result: Optional[float] = None

        tk.Label(self, text="培养分：").pack(pady=(10, 0))
        self.entry = tk.Entry(self)
        self.entry.insert(0, str(current_score))
        self.entry.pack(pady=5)
        self.entry.select_range(0, tk.END)
        self.entry.focus_set()

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=5)
        ttk.Button(btn_frame, text="保存", command=self._on_save).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(
            side=tk.LEFT, padx=5
        )

        self.bind("<Return>", lambda _e: self._on_save())

    def _on_save(self) -> None:
        try:
            score = float(self.entry.get())
        except ValueError:
            messagebox.showerror("数据错误", "培养分必须是数字", parent=self)
            return
        self._result = score
        if self.on_save:
            self.on_save(score)
        self.destroy()

    def get_result(self) -> Optional[float]:
        return self._result
