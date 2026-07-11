"""按品质扫描武库山河器。

用法：
    python scan_quality.py 朴素
    python scan_quality.py 精巧
    python scan_quality.py 瑰丽
    python scan_quality.py 绝世

脚本会：
1. 导航到武库界面；
2. 点击左上角下拉框选择指定品质；
3. 扫描该品质下的所有山河器格子；
4. 对 OCR 名字错误做兜底补齐；
5. 输出该品质下识别到的山河器名字列表，并与底稿核对 missing/extra。
"""

import argparse
import json
import sys
from pathlib import Path

from shq.scanner.name_resolver import ShanheqiNameResolver
from shq.scanner.ocr_scanner import RapidOCRBackend
from shq.scanner.reconciler import ScanReconciler
from shq.scanner.wuku_navigator import WukuNavigator
from shq.scanner.wuku_scanner import WukuScanner


VALID_QUALITIES = ("朴素", "精巧", "瑰丽", "绝世")


def main() -> None:
    parser = argparse.ArgumentParser(description="按品质扫描武库山河器")
    parser.add_argument(
        "quality",
        choices=VALID_QUALITIES,
        help="要扫描的品质",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "wuku_scan",
        help="截图和结果输出目录（默认：./wuku_scan）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="结果 JSON 路径（默认：{output_dir}/quality_{品质}.json）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="后台 OCR 线程数（默认 4）",
    )
    parser.add_argument(
        "--reconcile-threshold",
        type=float,
        default=0.55,
        help="漏扫补齐名字匹配分数阈值（默认 0.55）",
    )
    args = parser.parse_args()

    if args.output is None:
        args.output = args.output_dir / f"quality_{args.quality}.json"

    print("警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
    print(f"[启动] 准备扫描品质：{args.quality}")

    backend = RapidOCRBackend()

    # 导航到武库
    navigator = WukuNavigator(ocr_backend=backend)
    if not navigator.navigate_to("武库"):
        raise SystemExit("导航到武库界面失败")

    # 扫描指定品质
    scanner = WukuScanner(
        ocr_backend=backend,
        output_dir=args.output_dir,
        parse_workers=args.workers,
    )
    result = scanner.scan_quality(args.quality)

    # 与底稿核对，并做漏扫兜底补齐
    resolver = ShanheqiNameResolver()
    reconciler = ScanReconciler(resolver=resolver, score_threshold=args.reconcile_threshold)
    result.shanheqis, reconciliation_report = reconciler.reconcile(
        args.quality, result.shanheqis, result.low_confidence
    )

    expected = set(resolver.list_by_quality(args.quality))
    detected = {s.name for s in result.shanheqis}
    missing = sorted(expected - detected)
    extra = sorted(detected - expected)

    # 保存结果
    data = {
        "quality": args.quality,
        "shanheqis": [
            {
                "id": s.id,
                "name": s.name,
                "quality": s.quality.value,
                "element": s.element.value,
                "shanheqi_type": s.shanheqi_type.value,
                "level": s.level,
                "gongguan_level": s.gongguan_level,
                "base_score": s.base_score,
                "affixes": [
                    {
                        "name": a.name,
                        "element": a.element.value if a.element else None,
                        "level": a.level,
                        "score": a.score,
                    }
                    for a in s.affixes
                ],
                "derived_affixes": s.derived_affixes,
                "stats": s.stats,
            }
            for s in result.shanheqis
        ],
        "low_confidence": result.low_confidence,
        "reconciliation_report": reconciliation_report,
        "detected_names": sorted(detected),
        "detected_count": len(result.shanheqis),
        "expected_names": sorted(expected),
        "expected_count": len(expected),
        "missing_names": missing,
        "missing_count": len(missing),
        "extra_names": extra,
        "extra_count": len(extra),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[完成] 结果已保存：{args.output}")
    print(f"识别到 {len(result.shanheqis)} 个山河器：")
    for s in result.shanheqis:
        print(f"  - {s.name} ({s.quality.value}, 等级 {s.level}, 评分 {s.base_score})")
    if result.low_confidence:
        print(f"另有 {len(result.low_confidence)} 个低置信记录，请核对。")
    if reconciliation_report:
        filled = [r for r in reconciliation_report if r.get("action") == "已补齐"]
        unresolved = [r for r in reconciliation_report if r.get("action") != "已补齐"]
        if filled:
            print(f"\n漏扫兜底补齐 {len(filled)} 个：")
            for r in filled:
                print(f"  - {r['missing']} <= {r['matched_raw']} (score={r['score']:.2f})")
        if unresolved:
            print(f"\n仍有 {len(unresolved)} 个无法补齐：")
            for r in unresolved:
                print(f"  - {r['missing']} (best_score={r.get('best_score', 0):.2f})")
    if expected:
        print(f"\n底稿中该品质共 {len(expected)} 个：")
        if missing:
            print(f"  漏识别 {len(missing)} 个：{missing}")
        else:
            print("  无遗漏")
        if extra:
            print(f"  多识别/未在底稿中 {len(extra)} 个：{extra}")
    else:
        print("\n底稿中该品质暂无数据，请把检测到的名字补充进 data/shanheqi_master_list.json。")


if __name__ == "__main__":
    main()
