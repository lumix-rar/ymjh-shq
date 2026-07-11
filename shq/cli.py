"""命令行入口。"""

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
    SearchCollector,
    ShanheqiOCR,
    WindowCapture,
    WukuNavigator,
    WukuScanner,
    capture_game_window,
)
from shq.solver import BruteForceSolver, GreedySolver


SOLVERS = {
    "brute": BruteForceSolver,
    "greedy": GreedySolver,
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
        "--target",
        type=str,
        default="total_score",
        help="优化目标，例如 total_score/气血/攻击",
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
        default="greedy",
        choices=list(SOLVERS.keys()),
        help="求解算法",
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
        "--scan-wuku-output",
        type=Path,
        default=None,
        help="武库扫描结果输出 JSON 路径（默认：./wuku_scan/owned_shanheqis.json）",
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


def cmd_scan_wuku(args: argparse.Namespace) -> None:
    """扫描武库中已获得的山河器。"""
    _safe_print("⚠️  警告：自动化点击可能违反游戏用户协议，请自行承担风险。")
    backend = _create_ocr_backend(args.ocr_backend)
    if isinstance(backend, PlaceholderOCRBackend):
        raise SystemExit("扫描武库必须使用真实 OCR 后端，请指定 --ocr-backend rapidocr")

    # 1. 导航到搜寻，读取收集度
    navigator = WukuNavigator(ocr_backend=backend)
    if not navigator.navigate_to("搜寻"):
        raise SystemExit("导航到搜寻界面失败")
    img = capture_game_window(fixed_size=True)
    if img is None:
        raise SystemExit("无法截取游戏窗口")
    owned_total, total = SearchCollector(backend).read(img)
    _safe_print(f"[收集度] {owned_total}/{total}")

    # 2. 导航到武库
    if not navigator.navigate_to("武库"):
        raise SystemExit("导航到武库界面失败")

    # 3. 执行武库扫描
    scanner = WukuScanner(
        ocr_backend=backend,
        confidence_threshold=args.scan_confidence,
        output_dir=args.scan_wuku_output.parent if args.scan_wuku_output else None,
    )
    result = scanner.run()
    output = scanner.save(result, args.scan_wuku_output)
    _safe_print_json(
        {
            "output": str(output),
            "high_confidence": len(result.shanheqis),
            "low_confidence": len(result.low_confidence),
            "total": len(result.shanheqis) + len(result.low_confidence),
            "owned_count_from_search": owned_total,
            "total_count_from_search": total,
        }
    )


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
    elif args.scan_wuku:
        cmd_scan_wuku(args)
    else:
        cmd_solve(args)


if __name__ == "__main__":
    main()
