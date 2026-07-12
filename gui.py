"""项目根目录便捷启动脚本：python gui.py

启动时会显示一个 tkinter 加载窗口，在导入重型依赖时展示进度条与提示，
缓解首次打开慢的体感。该方式比 PyInstaller splash 更稳定。
"""

from __future__ import annotations


def _create_loading_window():
    """创建居中的无边框加载窗口，返回 (root, update_callback, close_callback)。"""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("启动中...")
    root.geometry("480x240")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#1e232d")

    # 居中显示
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - 480) // 2
    y = (sh - 240) // 2
    root.geometry(f"+{x}+{y}")

    frame = tk.Frame(root, bg="#1e232d")
    frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)

    title = tk.Label(
        frame,
        text="山河器最优摆放求解器",
        font=("Microsoft YaHei", 18, "bold"),
        bg="#1e232d",
        fg="#ffffff",
    )
    title.pack(pady=(10, 5))

    subtitle = tk.Label(
        frame,
        text="首次启动需要解压资源，请耐心等待",
        font=("Microsoft YaHei", 11),
        bg="#1e232d",
        fg="#b0b8c8",
    )
    subtitle.pack(pady=(0, 20))

    progress_var = tk.DoubleVar(value=0)
    progress = ttk.Progressbar(
        frame,
        variable=progress_var,
        maximum=100,
        length=420,
        mode="determinate",
    )
    progress.pack(pady=10)

    status_var = tk.StringVar(value="正在初始化...")
    status = tk.Label(
        frame,
        textvariable=status_var,
        font=("Microsoft YaHei", 10),
        bg="#1e232d",
        fg="#d0d8e8",
    )
    status.pack(pady=10)

    root.update()

    def update_status(text: str, value: int) -> None:
        status_var.set(text)
        progress_var.set(value)
        root.update()

    def close() -> None:
        try:
            root.destroy()
        except tk.TclError:
            pass

    return root, update_status, close


def main() -> None:
    root, update_status, close_loading = _create_loading_window()

    try:
        update_status("正在加载界面组件...", 10)
        import tkinter as tk  # noqa: F401
        from tkinter import ttk  # noqa: F401

        update_status("正在加载图像处理库...", 30)
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401

        update_status("正在加载 OCR 引擎...", 55)
        import onnxruntime  # noqa: F401

        update_status("正在加载 RapidOCR...", 70)
        import rapidocr_onnxruntime  # noqa: F401

        update_status("正在加载求解器...", 85)
        from shq.gui.app import main as app_main

        update_status("正在启动主界面...", 95)
    finally:
        close_loading()

    app_main()


if __name__ == "__main__":
    main()
