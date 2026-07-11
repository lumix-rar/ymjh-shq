"""打包脚本：使用 PyInstaller 生成单文件可执行程序。

用法：
    python build_exe.py

输出：
    dist/山河器最优摆放求解器.exe

说明：
- 只打包 RapidOCR（ONNX Runtime），不打包 EasyOCR/PyTorch，控制体积。
- data/ 目录（规则、拓扑、编号模板）会被一起打包。
- 如需图标，可在 PyInstaller 命令里加上 --icon=icon.ico
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "山河器最优摆放求解器",
        "--add-data",
        "data;data",
        "--collect-all",
        "rapidocr_onnxruntime",
        "--collect-all",
        "onnxruntime",
        "--exclude-module",
        "easyocr",
        "--exclude-module",
        "torch",
        "--exclude-module",
        "torchvision",
        "--exclude-module",
        "torchaudio",
        "--clean",
        "--noconfirm",
        "gui.py",
    ]
    print("执行命令：")
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
