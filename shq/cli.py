"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from shq.rules import YMJHDefaultRuleSet
from shq.scanner import (
    EasyOCRBackend,
    InputSimulator,
    ManualImporter,
    NavigationController,
    PlaceholderOCRBackend,
    ProcessFinder,
    RapidOCRBackend,
    ScanResult,
    ShanheqiOCR,
    SlotCultivationReader,
    TopologyLoader,
    WindowCapture,
    WukuNavigator,
    WukuReader,
    capture_game_window,
)
from shq.solver import BruteForceSolver, GreedySolver, LocalSearchSolver


SOLVERS = {
    "brute": BruteForceSolver,
    "greedy": GreedySolver,
    "local_search": LocalSearchSolver,
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="山河器最优摆放求解器")

    # 求解相关参数
    parser.add_argument(
        "--data",
        type=Path,
        help="山河器与灵鉴 JSON 数据文件路径",
    )
    parser.add_argument(
        "--optimize-placement",
        action="store_true",
        help="启用山河器最优摆放优化模式",
    )
    parser.add_argument(
        "--wuku",
        type=Path,
        default=Path.cwd() / "wuku_scan" / "owned_shanheqis.json",
        help="武库扫描结果 JSON 路径（默认 ./wuku_scan/owned_shanheqis.json）",
    )
    parser.add_argument(
        "--slot-cultivation",
        type=Path,
        default=Path.cwd() / "lingjian_scan" / "slot_cultivation.json",
        help="孔位培养扫描结果 JSON 路径（默认 ./lingjian_scan/slot_cultivation.json）",
    )
    parser.add_argument(
        "--topology",
        type=Path,
        default=None,
        help="灵鉴拓扑 JSON 路径（默认 data/lingjian_topology.json）",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help="游戏规则 JSON 路径（默认 data/ymjh_rules.json）",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="total_score",
        help="优化目标，例如 total_score/build_score",
    )
    parser.add_argument(
        "--build",
        type=str,
        default="综合",
        help="玩家流派：输出/治疗/承伤/综合",
    )
    parser.add_argument(
        "--solver",
        type=str,
        default="local_search",
        choices=list(SOLVERS.keys()),
        help="求解算法：local_search（默认）/brute/greedy",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="结果输出 JSON 文件路径",
    )
    parser.add_argument(
        "--print-template",
        action="store_true",
        help="打印数据文件格式模板并退出",
    )

    # 进程查找参数
    parser.add_argument(
        "--find-process",
        action="store_true",
        help="查找一梦江湖进程",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0,
        help="配合 --find-process，最多等待 N 秒直到进程出现",
    )
    parser.add_argument(
        "--all-matches",
        action="store_true",
        help="配合 --find-process，列出所有匹配进程",
    )

    # OCR 截图参数
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="截取一梦江湖窗口并保存到指定路径",
    )
    parser.add_argument(
        "--ocr-sample",
        type=Path,
        default=None,
        help="截取窗口并导出所有 OCR ROI 到指定目录（供人工标注）",
    )
    parser.add_argument(
        "--scan-wuku",
        action="store_true",
        help="扫描武库中已获得的山河器（需 OCR 后端 rapidocr/easyocr）",
    )
    parser.add_argument(
        "--scan-all-owned",
        action="store_true",
        help="一键扫描所有品质下已获得的山河器（含漏扫兜底，推荐）",
    )
    parser.add_argument(
        "--scan-wuku-output",
        type=Path,
        default=None,
        help="武库扫描结果输出 JSON 路径（默认：./wuku_scan/owned_shanheqis.json）",
    )
    parser.add_argument(
        "--scan-slot-cultivation",
        action="store_true",
        help="扫描灵鉴各区域孔位培养加分（需 OCR 后端 rapidocr/easyocr）",
    )
    parser.add_argument(
        "--calibrate-slot-cultivation",
        action="store_true",
        help="校准灵鉴孔位培养 ROI，输出候选配置供人工审核",
    )
    parser.add_argument(
        "--slot-cultivation-output",
        type=Path,
        default=None,
        help="孔位培养扫描结果输出 JSON 路径（默认：./lingjian_scan/slot_cultivation.json）",
    )
    parser.add_argument(
        "--scan-confidence",
        type=float,
        default=0.5,
        help="OCR 置信度阈值，低于此值进入低置信列表等待人工录入（默认 0.5）",
    )
    parser.add_argument(
        "--ocr-backend",
        type=str,
        default="placeholder",
        choices=["placeholder", "easyocr", "rapidocr"],
        help="OCR 引擎（推荐 rapidocr）",
    )

    # 自动化点击参数（⚠️ 存在封号风险，默认不启用）
    parser.add_argument(
        "--click",
        type=str,
        default=None,
        help="点击游戏窗口客户区坐标，格式：x,y（如 1200,400）",
    )
    parser.add_argument(
        "--click-screen",
        type=str,
        default=None,
        help="点击屏幕绝对坐标，格式：x,y（如 1920,1080）",
    )
    parser.add_argument(
        "--click-delay",
        type=float,
        default=0.8,
        help="点击后等待界面响应的时间（秒），默认 0.8 秒",
    )
    parser.add_argument(
        "--resize",
        action="store_true",
        help="强制将游戏窗口调整为默认客户区大小（1334x750）",
    )
    parser.add_argument(
        "--nav-to-wuku",
        action="store_true",
        help="自动导航到山河器-武库界面（需 OCR 后端，默认 placeholder 不生效）",
    )
    parser.add_argument(
        "--auto-collect",
        type=Path,
        default=None,
        help="一键完成：调整窗口→导航到武库→截图，保存到指定目录",
    )
    parser.add_argument(
        "--manual-fallback",
        action="store_true",
        help="自动点击失败时提示用户手动点击并按回车继续",
    )
    parser.add_argument(
        "--diagnose-input",
        action="store_true",
        help="检测当前环境是否支持 SendInput 模拟鼠标",
    )
    parser.add_argument(
        "--attach-input",
        action="store_true",
        help="点击前通过 AttachThreadInput 挂接目标窗口线程（对受保护窗口可能有效）",
    )

    return parser


def _load_lingjian_for_optimization(
    topology_path: Optional[Path],
    rules_path: Optional[Path],
    cultivation_path: Path,
) -> "Lingjian":
    """加载灵鉴拓扑、应用规则、回填孔位培养分。"""
    from shq.models import Lingjian

    loader = TopologyLoader(
        path=topology_path,
        rules_path=rules_path,
    )
    topology = loader.load()
    lingjian = topology.lingjian

    if not cultivation_path.exists():
        return lingjian

    data = json.loads(cultivation_path.read_text(encoding="utf-8"))
    score_map: dict[str, float] = {}
    for region_result in data.get("regions", []):
        for slot in region_result.get("slots", []):
            score_map[str(slot["slot_id"])] = float(slot.get("cultivation_score", 0.0))

    for region in lingjian.regions:
        for slot in region.slots:
            slot.cultivation_score = score_map.get(slot.id, 0.0)

    return lingjian


def cmd_optimize_placement(args: argparse.Namespace) -> None:
    """山河器最优摆放优化入口。"""
    from shq.models import BuildPreference

    if not args.wuku.exists():
        raise SystemExit(f"--wuku 文件不存在：{args.wuku}")

    # 1. 加载山河器
    importer = ManualImporter(args.wuku)
    shqs = importer.scan_shanheqis()
    if not shqs:
        raise SystemExit(f"未从 {args.wuku} 中读取到山河器")

    # 2. 加载灵鉴拓扑与培养分
    lingjian = _load_lingjian_for_optimization(
        topology_path=args.topology,
        rules_path=args.rules,
        cultivation_path=args.slot_cultivation,
    )

    # 3. 偏好与规则
    preference = BuildPreference(build=args.build)
    rules = YMJHDefaultRuleSet(rules_path=args.rules)

    # 4. 求解
    solver = SOLVERS[args.solver]()
    solution = solver.solve(shqs, lingjian, rules, args.target, preference)

    # 5. 组装结果
    region_name_map = {r.id: r.name for r in lingjian.regions}
    placement_result = {
        "正面": {
            region_name_map.get(r.id, r.id): {
                slot.number: solution.placement.mapping.get(slot.id)
                for slot in r.front_slots
            }
            for r in lingjian.regions
        },
        "背面": solution.placement.back_mapping,
    }

    result = {
        "solver": solver.name,
        "target": solution.target,
        "build": preference.build,
        "score": rules.score(solution.evaluation, solution.target, preference),
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
        "description": solution.description,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_solve(args: argparse.Namespace) -> None:
    if not args.data:
        raise SystemExit("--data 是求解所必需的")

    importer = ManualImporter(args.data)
    shqs = importer.scan_shanheqis()
    lingjian = importer.scan_lingjian()
    preference = importer.scan_preference()
    # 命令行 --build 可覆盖文件中的偏好
    preference.build = args.build

    rules = YMJHDefaultRuleSet()
    solver = SOLVERS[args.solver]()

    solution = solver.solve(shqs, lingjian, rules, args.target, preference)

    result = {
        "solver": solver.name,
        "target": solution.target,
        "build": preference.build,
        "score": rules.score(solution.evaluation, solution.target, preference),
        "placement": solution.placement.mapping,
        "evaluation": {
            "total_score": solution.evaluation.total_score,
            "region_scores": solution.evaluation.region_scores,
            "stats": solution.evaluation.stats,
        },
        "description": solution.description,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_print_json(data: dict) -> None:
    """尝试以 UTF-8 输出 JSON，若终端编码不支持则回退到 ASCII。"""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(data, ensure_ascii=True, indent=2))


def cmd_find_process(args: argparse.Namespace) -> None:
    finder = ProcessFinder.for_ymjh()
    if args.wait > 0:
        info = finder.wait_for_process(timeout=args.wait)
    elif args.all_matches:
        infos = finder.find(multiple=True)
        if isinstance(infos, list) and infos:
            result = {"found": True, "count": len(infos), "processes": [i.to_dict() for i in infos]}
        else:
            result = {"found": False, "count": 0, "processes": []}
        _safe_print_json(result)
        return
    else:
        info = finder.find_ymjh()

    if info:
        _safe_print_json({"found": True, "process": info.to_dict()})
    else:
        _safe_print_json({"found": False, "process": None})


def print_template() -> None:
    template = {
        "_comment": "数据文件格式模板，所有数值均为示例/占位，请替换为真实游戏数据",
        "preference": {"build": "综合", "weights": {}},
        "shanheqis": [
            {
                "id": "shq_001",
                "name": "示例山河器",
                "quality": "PEERLESS",
                "element": "METAL",
                "shanheqi_type": "NORMAL",
                "level": 50,
                "gongguan_level": 3,
                "base_score": 0.0,
                "affixes": [
                    {
                        "name": "起势",
                        "element": "METAL",
                        "level": 3,
                        "score": 0.0,
                        "derived": True,
                        "effects": [
                            {"name": "起势", "params": {}, "description": ""}
                        ]
                    }
                ],
                "stats": {"气血": 0.0, "攻击": 0.0},
                "tags": []
            }
        ],
        "lingjian": {
            "regions": [
                {
                    "id": "region_001",
                    "name": "驿寄梅花",
                    "slots": [
                        {
                            "id": "slot_001",
                            "region_id": "region_001",
                            "position": "NORMAL",
                            "allowed_tags": [],
                            "cultivation_score": 0.0,
                            "base_penalty": 0.0
                        }
                    ],
                    "connections": [
                        {"from": "slot_001", "to": "slot_002"}
                    ],
                    "effects": [
                        {"name": "效果示例", "required_score": 0.0, "stats": {}, "description": ""}
                    ],
                    "unlock_required_score": 0.0,
                    "back_region_id": None,
                    "recommended_for": []
                }
            ]
        }
    }
    print(json.dumps(template, ensure_ascii=False, indent=2))


def cmd_snapshot(args: argparse.Namespace) -> None:
    """截取一梦江湖窗口并保存。"""
    output_path = args.snapshot or Path.cwd() / "ymjh_snapshot.png"
    img = capture_game_window()
    if img is None:
        raise SystemExit("无法截取一梦江湖窗口，请确保游戏已运行且可见")

    import cv2
    cv2.imwrite(str(output_path), img)
    print(f"截图已保存：{output_path}")


def cmd_ocr_sample(args: argparse.Namespace) -> None:
    """导出 OCR 识别 ROI，供人工标注。"""
    output_dir = args.ocr_sample or Path.cwd() / "ocr_samples"
    scanner = ShanheqiOCR()
    paths = scanner.save_rois(output_dir)
    print(f"已导出 {len(paths)} 个 ROI 到：{output_dir}")
    for p in paths:
        print(f"  - {p}")


def _cmd_scan_owned(args: argparse.Namespace, reconcile: bool) -> tuple[Path, ScanResult]:
    """扫描武库已获得的山河器，返回输出路径和结果。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
    backend = _create_ocr_backend(args.ocr_backend)
    if isinstance(backend, PlaceholderOCRBackend):
        raise SystemExit("扫描武库必须使用真实 OCR 后端，请指定 --ocr-backend rapidocr")

    reader = WukuReader(
        ocr_backend=backend,
        confidence_threshold=args.scan_confidence,
        output_dir=args.scan_wuku_output.parent if args.scan_wuku_output else None,
    )
    result = reader.read(reconcile=reconcile)
    output = reader.scanner.save(result, args.scan_wuku_output)
    return output, result


def cmd_scan_wuku(args: argparse.Namespace) -> None:
    """扫描武库中已获得的山河器（JSON 摘要输出）。"""
    output, result = _cmd_scan_owned(args, reconcile=True)
    _safe_print_json(
        {
            "output": str(output),
            "high_confidence": len(result.shanheqis),
            "low_confidence": len(result.low_confidence),
            "total": len(result.shanheqis),
            "owned_count_from_search": result.screenshots.get("_owned_total"),
            "total_count_from_search": result.screenshots.get("_total"),
            "quality_summary": result.quality_summary,
        }
    )


def cmd_scan_all_owned(args: argparse.Namespace) -> None:
    """一键扫描所有已获得的山河器，输出完整数据并打印人类可读摘要。"""
    output, result = _cmd_scan_owned(args, reconcile=True)

    print(f"\n[完成] 所有品质扫描完毕")
    print(f"输出文件：{output}")
    print(f"总计获得：{len(result.shanheqis)} 个山河器")
    for quality in ("朴素", "精巧", "瑰丽", "绝世"):
        summary = result.quality_summary.get(quality, {})
        detected = summary.get("detected", 0)
        expected = summary.get("expected", 0)
        reconciled = summary.get("reconciled", 0)
        print(f"  {quality}：{detected}/{expected} 个", end="")
        if reconciled:
            print(f"（其中 {reconciled} 个由漏扫兜底补齐）", end="")
        print()
    if result.low_confidence:
        print(f"低置信记录：{len(result.low_confidence)} 条")

    # 将收集度也写入 screenshots 字段，供下游读取
    result.screenshots["output"] = str(output)


def cmd_scan_slot_cultivation(args: argparse.Namespace) -> None:
    """扫描灵鉴各区域孔位培养加分。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
    backend = _create_ocr_backend(args.ocr_backend)
    if isinstance(backend, PlaceholderOCRBackend):
        raise SystemExit("扫描孔位培养必须使用真实 OCR 后端，请指定 --ocr-backend rapidocr")

    reader = SlotCultivationReader(
        ocr_backend=backend,
        confidence_threshold=args.scan_confidence,
        output_dir=args.slot_cultivation_output.parent
        if args.slot_cultivation_output
        else None,
    )
    result = reader.read(output_path=args.slot_cultivation_output)

    _safe_print_json(
        {
            "output": str(result.output_path),
            "regions": len(result.scan_result.region_results),
            "locked_regions": result.scan_result.locked_region_ids,
            "low_confidence": sum(
                len(rr.low_confidence) for rr in result.scan_result.region_results
            ),
        }
    )


def cmd_calibrate_slot_cultivation(args: argparse.Namespace) -> None:
    """校准灵鉴孔位培养 ROI。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
    backend = _create_ocr_backend(args.ocr_backend)
    if isinstance(backend, PlaceholderOCRBackend):
        raise SystemExit("校准必须使用真实 OCR 后端，请指定 --ocr-backend rapidocr")

    reader = SlotCultivationReader(
        ocr_backend=backend,
        output_dir=args.slot_cultivation_output.parent
        if args.slot_cultivation_output
        else None,
    )
    output = reader.calibrate(output_path=args.slot_cultivation_output)
    print(f"校准候选配置已保存：{output}")
    print("请人工审核后，将其内容合并到 data/lingjian_topology.json")


def _parse_click_coord(s: str) -> tuple[int, int]:
    """解析 x,y 坐标字符串。"""
    parts = s.split(",")
    if len(parts) != 2:
        raise SystemExit(f"坐标格式错误：{s}，应为 x,y")
    return int(parts[0].strip()), int(parts[1].strip())


def _get_game_hwnd() -> Optional[int]:
    """定位一梦江湖窗口句柄。"""
    from shq.config import YMJH_PROCESS_RULE

    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"] and proc.info["name"].lower() in [
                n.lower() for n in YMJH_PROCESS_RULE.get("names", [])
            ]:
                hwnd = WindowCapture.find_by_pid(proc.info["pid"])
                if hwnd:
                    return hwnd
    except Exception:
        pass

    for title in YMJH_PROCESS_RULE.get("window_titles", []):
        hwnd = WindowCapture.find_by_title(title)
        if hwnd:
            return hwnd

    return None


def _maybe_click(args: argparse.Namespace) -> None:
    """根据命令行参数执行点击操作。"""
    if args.click_screen:
        _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
        x, y = _parse_click_coord(args.click_screen)
        sim = InputSimulator(default_delay=args.click_delay)
        sim.click(x, y)
        print(f"已点击屏幕坐标：({x}, {y})")
        return

    if args.click:
        _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
        x, y = _parse_click_coord(args.click)
        hwnd = _get_game_hwnd()
        if hwnd is None:
            raise SystemExit("未找到一梦江湖窗口，无法执行点击")

        sim = InputSimulator(default_delay=args.click_delay)
        sim.click_on_window(hwnd, x, y, attach_thread=args.attach_input)
        print(f"已点击窗口客户区坐标：({x}, {y})")


def cmd_diagnose_input(args: argparse.Namespace) -> None:
    """检测当前环境是否支持 SendInput 模拟鼠标。"""
    sim = InputSimulator(default_delay=0.3)
    print("正在检测 SendInput 鼠标控制能力（会短暂移动你的鼠标）...")
    result = sim.diagnose(timeout=0.3)
    _safe_print_json(result)
    if result.get("supported"):
        print("结论：当前环境支持自动化点击，可直接使用 --auto-collect / --nav-to-wuku")
    else:
        print(f"结论：当前环境不支持自动化点击。原因：{result.get('reason')}")
        print("建议：使用 --manual-fallback 参数，手动点击后按回车继续。")


def cmd_resize(args: argparse.Namespace) -> None:
    """强制调整游戏窗口客户区大小。"""
    hwnd = _get_game_hwnd()
    if hwnd is None:
        raise SystemExit("未找到一梦江湖窗口")
    cap = WindowCapture(hwnd)
    ok = cap.ensure_client_size()
    if ok:
        size = cap.get_client_size()
        print(f"窗口已调整为：{size}")
    else:
        raise SystemExit("窗口调整失败")


def cmd_nav_to_wuku(args: argparse.Namespace) -> None:
    """自动导航到武库界面。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")

    backend = _create_ocr_backend(args.ocr_backend)
    ctrl = NavigationController(ocr_backend=backend, attach_thread=args.attach_input)
    ctrl.ensure_fixed_size()

    ok = ctrl.ensure_in_wuku(manual_fallback=args.manual_fallback)
    if ok:
        print("已导航到武库界面")
    else:
        raise SystemExit("导航到武库界面失败")

    if args.snapshot is not None:
        cmd_snapshot(args)


def _safe_print(text: str) -> None:
    """尝试以 UTF-8 输出，若终端编码不支持则回退到 ASCII。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "ignore").decode("ascii"))


def cmd_auto_collect(args: argparse.Namespace) -> None:
    """一键采集流程：调整窗口 → 导航到武库 → 截图。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")

    output_dir = args.auto_collect
    output_dir.mkdir(parents=True, exist_ok=True)

    backend = _create_ocr_backend(args.ocr_backend)
    ctrl = NavigationController(ocr_backend=backend, attach_thread=args.attach_input)

    print("[1/3] 调整窗口大小...")
    if not ctrl.ensure_fixed_size():
        raise SystemExit("调整窗口大小失败")
    size = ctrl._get_window_capture().get_client_size()
    print(f"      窗口大小：{size}")

    print("[2/3] 导航到武库界面...")
    if not ctrl.ensure_in_wuku(manual_fallback=args.manual_fallback):
        raise SystemExit("导航到武库界面失败")

    print("[3/3] 截图保存...")
    img = ctrl.screenshot()

    import cv2
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"wuku_{timestamp}.png"
    cv2.imwrite(str(path), img)
    print(f"      已保存：{path}")


def _create_ocr_backend(name: str):
    """根据名称创建 OCR 后端。"""
    if name == "easyocr":
        return EasyOCRBackend()
    if name == "rapidocr":
        return RapidOCRBackend()
    return PlaceholderOCRBackend()


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.print_template:
        print_template()
    elif args.diagnose_input:
        cmd_diagnose_input(args)
    elif args.find_process:
        cmd_find_process(args)
    elif args.auto_collect is not None:
        cmd_auto_collect(args)
    elif args.resize:
        cmd_resize(args)
    elif args.nav_to_wuku:
        cmd_nav_to_wuku(args)
    elif args.click or args.click_screen:
        _maybe_click(args)
        if args.snapshot is not None:
            cmd_snapshot(args)
    elif args.snapshot is not None:
        cmd_snapshot(args)
    elif args.ocr_sample is not None:
        cmd_ocr_sample(args)
    elif args.scan_all_owned:
        cmd_scan_all_owned(args)
    elif args.scan_wuku:
        cmd_scan_wuku(args)
    elif args.scan_slot_cultivation:
        cmd_scan_slot_cultivation(args)
    elif args.calibrate_slot_cultivation:
        cmd_calibrate_slot_cultivation(args)
    elif args.optimize_placement:
        cmd_optimize_placement(args)
    else:
        cmd_solve(args)


if __name__ == "__main__":
    main()
