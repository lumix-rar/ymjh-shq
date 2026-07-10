"""全局配置常量与默认值。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TESTS_DIR = PROJECT_ROOT / "tests"

# 一梦江湖进程匹配规则（Windows 不区分大小写）
# 实际观察：PC 端主进程为 wyclx64.exe（网易楚留香/一梦江湖引擎），窗口标题含"一梦江湖"。
# 后续若客户端升级或渠道服不同，可在此扩展。
YMJH_PROCESS_RULE = {
    "names": ["wyclx64.exe", "ymjh.exe", "ymjh2.exe"],
    "window_titles": ["一梦江湖", "楚留香"],
    "exe_keywords": ["wyclx", "ymjh"],
}
