"""枚举指定品质分类下的全部山河器名字。

用法：
    python list_quality_names.py 朴素

只滚动网格并用 OCR 识别格子名字，不点击、不解析详情面板。
输出一个名字列表 JSON，供人工校对后填入底稿。
"""

import argparse
import json
from pathlib import Path

from shq.scanner.ocr_scanner import RapidOCRBackend
from shq.scanner.wuku_navigator import WukuNavigator
from shq.scanner.wuku_scanner import WukuScanner


VALID_QUALITIES = ("朴素", "精巧", "瑰丽", "绝世")


def main() -> None:
    parser = argparse.ArgumentParser(description="枚举指定品质下的全部山河器名字")
    parser.add_argument(
        "quality",
        choices=VALID_QUALITIES,
        help="要枚举的品质",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "wuku_scan",
        help="截图输出目录（默认：./wuku_scan）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="结果 JSON 路径（默认：{output_dir}/quality_names_{品质}.json）",
    )
    args = parser.parse_args()

    if args.output is None:
        args.output = args.output_dir / f"quality_names_{args.quality}.json"

    print(f"[启动] 枚举品质：{args.quality}")

    backend = RapidOCRBackend()
    navigator = WukuNavigator(ocr_backend=backend)
    if not navigator.navigate_to("武库"):
        raise SystemExit("导航到武库界面失败")

    scanner = WukuScanner(ocr_backend=backend, output_dir=args.output_dir)
    scanner._prepare_window()
    scanner._select_quality(args.quality)
    scanner._scroll_to_top()

    seen_names: set[str] = set()
    all_cells: list[dict] = []
    prev_hash: str | None = None
    no_progress = 0
    step = 0
    max_steps = 60

    while step < max_steps:
        grid_img = scanner._capture(f"grid_names_{step:02d}")
        cells = scanner._detect_cells(grid_img)

        top_name = next((c.name for c in cells if c.name), None)
        print(f"[第 {step} 屏] 顶部：{top_name}，格子数：{len(cells)}")

        for cell in cells:
            if not cell.name:
                continue
            if cell.name in seen_names:
                continue
            seen_names.add(cell.name)
            all_cells.append(
                {
                    "name": cell.name,
                    "step": step,
                    "col": cell.col,
                    "row": cell.row_in_screen,
                    "center_x": cell.center_x,
                    "center_y": cell.center_y,
                }
            )

        grid_hash = scanner._grid_hash(grid_img)
        if prev_hash is not None:
            dist = scanner._hash_distance(grid_hash, prev_hash)
            print(f"       hash 距离：{dist}")
            if dist <= 5:
                no_progress += 1
                if no_progress >= 2:
                    print("[结束] 已到底部")
                    break
            else:
                no_progress = 0
        prev_hash = grid_hash

        scanner._scroll_grid(-3)
        step += 1

    data = {
        "quality": args.quality,
        "unique_names": sorted(seen_names),
        "unique_count": len(seen_names),
        "cells": all_cells,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[完成] 共枚举到 {len(seen_names)} 个独特名字")
    print(f"结果保存：{args.output}")
    print("名字列表：")
    for name in sorted(seen_names):
        print(f"  - {name}")


if __name__ == "__main__":
    main()
