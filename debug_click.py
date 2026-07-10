"""逐步复现 nav-to-wuku 中的点击链路，定位 SendInput 失效点。"""
import ctypes
import ctypes.wintypes
import time

from shq.config import YMJH_PROCESS_RULE
from shq.scanner.input_simulator import InputSimulator
from shq.scanner.window_capture import WindowCapture


def find_hwnd():
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


def get_cursor_pos():
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def main():
    hwnd = find_hwnd()
    if hwnd is None:
        print("未找到游戏窗口")
        return

    cap = WindowCapture(hwnd)
    sim = InputSimulator(default_delay=0.3)

    print(f"[0] 初始鼠标位置: {get_cursor_pos()}")

    # Step 1: 纯 SendInput 点击屏幕坐标（模拟 diagnose-input 路径）
    print("\n[1] 直接 SendInput 点击屏幕 (500, 500)...")
    before = get_cursor_pos()
    sim.click(500, 500)
    after = get_cursor_pos()
    print(f"    移动前 {before} -> 移动后 {after}")

    # Step 2: 调整窗口大小
    print("\n[2] 调整窗口大小到 1334x750...")
    ok = cap.ensure_client_size(1334, 750)
    size = cap.get_client_size()
    rect = cap.get_rect()
    print(f"    调整结果: {ok}, 当前大小: {size}")
    print(f"    客户区矩形: left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}")
    print(f"    鼠标位置: {get_cursor_pos()}")

    # Step 2.5: 显式确保窗口在屏幕内
    print("\n[2.5] 显式调用 ensure_on_screen...")
    ok = cap.ensure_on_screen()
    rect = cap.get_rect()
    print(f"    结果: {ok}")
    print(f"    客户区矩形: left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}")
    print(f"    鼠标位置: {get_cursor_pos()}")

    # Step 3: bring_to_front
    print("\n[3] bring_to_front...")
    ok = cap.bring_to_front(wait=0.5)
    print(f"    bring_to_front 结果: {ok}")
    print(f"    鼠标位置: {get_cursor_pos()}")

    # Step 4: 截图
    print("\n[4] 截图...")
    img = cap.capture(bring_to_front=False)
    print(f"    截图结果: {img is not None}, shape: {img.shape if img is not None else None}")
    print(f"    鼠标位置: {get_cursor_pos()}")

    # Step 5: 点击窗口客户区坐标（模拟 nav-to-wuku 路径）
    rect = cap.get_rect()  # 重新获取，因为 resize 可能改变了窗口位置
    client_x = rect.width - 60  # 右侧导航栏附近
    client_y = rect.height // 2
    screen_x, screen_y = rect.left + client_x, rect.top + client_y
    print(f"\n[5] 窗口客户区矩形: left={rect.left}, top={rect.top}, width={rect.width}, height={rect.height}")
    print(f"    点击窗口客户区 ({client_x}, {client_y}) -> 屏幕 ({screen_x}, {screen_y})")
    print(f"    虚拟屏幕: {ctypes.windll.user32.GetSystemMetrics(76)},{ctypes.windll.user32.GetSystemMetrics(77)} {ctypes.windll.user32.GetSystemMetrics(78)}x{ctypes.windll.user32.GetSystemMetrics(79)}")

    # 5a: 纯 SendInput
    print("\n[5a] 用 SendInput 点击...")
    before = get_cursor_pos()
    sim.click_on_window(hwnd, client_x, client_y, attach_thread=False)
    after = get_cursor_pos()
    print(f"    移动前 {before} -> 移动后 {after}")

    # 5b: AttachThreadInput + SendInput
    print("\n[5b] 用 AttachThreadInput + SendInput 点击...")
    before = get_cursor_pos()
    sim.click_on_window(hwnd, client_x, client_y, attach_thread=True)
    after = get_cursor_pos()
    print(f"    移动前 {before} -> 移动后 {after}")

    # 5c: 直接用 Win32 mouse_event（AutoHotkey SendEvent 模式用的就是这个）
    print("\n[5c] 用 SetCursorPos + mouse_event 点击...")
    before = get_cursor_pos()
    user32 = ctypes.windll.user32
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFT DOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFT UP
    time.sleep(0.3)
    after = get_cursor_pos()
    print(f"    移动前 {before} -> 移动后 {after}")


if __name__ == "__main__":
    main()
