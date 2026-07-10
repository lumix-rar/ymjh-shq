# 一梦江湖山河器工具 — 交接文档

> 生成时间：2026-07-09（当前会话）
> 交接人：前序 Agent
> 接收人：后续 Agent

## 一、当前会话完成的工作

### 1.1 武库山河器自动采集模块

已按设计实现 `shq/scanner/wuku/` 子包，目标：自动进入武库 → 筛选“全部” → 按页扫描网格 → 识别已获得山河器 → 点击读取右侧面板 → 滚动翻页 → 合并数据 → 导出 JSON。

新增文件：

```
shq/scanner/wuku/
├── __init__.py          # 导出公共类
├── models.py            # GridItem、DetailData、AffixData、BBox、Point
├── config.py            # WukuConfig、ROIConfig（相对窗口比例）
├── grid_detector.py     # GridItemDetector：左卡网格 item 检测
├── detail_reader.py     # DetailPanelReader：右侧面板解析
├── scroll_controller.py # ScrollController：滚轮滚动 + 触底检测
├── ocr_pipeline.py      # OCRPipeline：并发 OCR 解析队列
├── state.py             # CollectionState：HashMap + 断点续传
├── merger.py            # ShanheqiMerger：左右数据合并为 Shanheqi
└── collector.py         # WukuCollector：总控状态机
```

CLI 新增命令：

```bash
python -m shq.cli --collect-wuku ./wuku_output --ocr-backend rapidocr
```

可选参数：
- `--wuku-workers N`：OCR 并发线程数，默认 4
- `--wuku-resume PATH`：断点续传状态文件
- `--wuku-overlap-rows N`：页间重叠行数，默认 1
- `--attach-input`：点击前挂接目标窗口线程

### 1.2 基于实际截图的关键发现

已通过管理员权限截取 16+ 张武库界面截图并分析：

- **布局**：山河器列表是左侧双列网格。
- **已获得判断**：左卡 item 上出现绿色 `X级` 文字即为已获得；未获得没有等级文字。
- **派生素蕴**：右侧面板“派生素蕴”区域不显示具体内容，但左卡 item 下方有棕褐色标签（如“起势”）。
- **特殊等级**：item 图标右上角小图标，红色为“玄枢”，黄色/橙色为“卓异”。
- **右侧面板**：包含名称、元素图标、等级、主属性、评分、基础素蕴列表。
- **滚动**：鼠标滚轮有效；每次约 `-1200` 滚轮刻度移动约 1 行；触底后画面不再变化。
- **元素**：金木水火土，显示在右侧面板名称右侧。

### 1.3 当前状态

- `pytest -q`：全部 38 个测试通过（含新增 wuku 单元测试）。
- **JSON 序列化问题已修复**：`shq/scanner/wuku/state.py` 中 `_shq_to_dict()` 现在把 `tags` 序列化为 `list`，加载时再恢复为 `frozenset`。
- **网格 item 识别已修复并验证**：`GridItemDetector` 改为先检测 item 左侧蓝色图标，再以图标为锚点拟合完整网格，cell 边框完整、不漏 item；对特殊等级图标（如红色“玄枢”）不敏感。
- **派生素蕴标签已能识别**：通过颜色定位棕褐标签区域 + 模板匹配，当前模板只有 `起势`；OCR 对超小标签文字不敏感，因此模板匹配是主要识别路径。
- **滚动翻页存在异常**： `--collect-wuku` 端到端运行时，滚动没有真正移动列表，仅翻 2～3 页就误判触底，导致实际只扫描了第一页附近的未获得 item，最终采集 0 条或少量数据。
- **导航标签点击偶发异常**：`NavigationController.ensure_in_wuku()` 有时能正确点击“武库”并进入，有时会出现 y 偏移累积，把点击落到“搜寻”标签上。当前已进入武库时可直接运行采集，否则可能需要手动点选。

## 二、已知问题与待办

### 高优先级

1. **修复滚动翻页异常**
   - 文件：`shq/scanner/wuku/scroll_controller.py`、`shq/scanner/wuku/collector.py`
   - 现象：`--collect-wuku` 运行时列表几乎不滚动，2～3 页后就触发触底检测，最终只扫描了开头几页。
   - 可能原因：`ScrollController.scroll_one_page()` 的滚轮刻度、方向或窗口焦点不对；触底指纹判断阈值/逻辑过于敏感。
   - 建议：先单独用 `--diagnose-input` 确认滚轮事件确实生效；再用 `pages/page_*.png` 对比滚动前后的画面差异，确认指纹相似度计算是否正确。

2. **修复导航标签点击偏移**
   - 文件：`shq/scanner/navigation_controller.py`
   - 现象：`ensure_in_wuku()` 自动点击“武库”时，y 偏移会累积，导致点中“搜寻”。
   - 建议：检查 `click_on_window` 的坐标转换（客户区 vs 屏幕坐标），以及 `_nav_offset_y` 的更新逻辑，避免偏移累加。

3. **坐标精度校准**
   - `collector.py` 中点击 item 后直接点击 `cell_bbox.center`，但实际游戏响应区域可能与截图坐标存在 y 轴偏移。
   - 建议复用 `NavigationController._nav_offset_y` 的校准思路，或点击前加上经验偏移量。

4. **ROI 比例需根据实际窗口大小验证**
   - `WukuConfig` 中的 `grid_roi`、`detail_roi`、`filter_roi` 基于 1334×750 截图估算。
   - 若窗口实际大小不同，需确认相对比例是否仍然准确。

### 中低优先级

- 补充更多派生素蕴标签模板：目前只有 `起势.png`，后续遇到“承势/火实/水实/木实/金实/土实”时需要新增模板并验证。
- 优化 `GridItemDetector` 对特殊等级（玄枢/卓异）的颜色识别，目前只是简单阈值。
- 处理 OCR 识别错误：如“无咎”被识别成“无”，“酒酣胸胆”被识别成“酒胸胆”。
- 修复元素识别：`DetailPanelReader._extract_element()` 当前从 OCR 文本中找“金木水火土”，但元素实际是以图标显示在右面板名称右侧，导致所有 item 元素 fallback 为“金”。
- 完善品质推断：当前 `merger.py` 默认 `Quality.SIMPLE`，因为右面板未直接显示品质。
- 支持从 `CollectionState` 恢复后继续采集（断点续传逻辑已写但需验证）。
- 增加采集结果与游戏内实际评分的对比校准。

## 三、关键代码位置速查

| 功能 | 文件 | 关键类/函数 |
|------|------|-------------|
| 总控采集流程 | `shq/scanner/wuku/collector.py` | `WukuCollector.collect()` |
| 左卡网格检测 | `shq/scanner/wuku/grid_detector.py` | `GridItemDetector.detect()` |
| 右面板解析 | `shq/scanner/wuku/detail_reader.py` | `DetailPanelReader.parse()` |
| 滚动控制 | `shq/scanner/wuku/scroll_controller.py` | `ScrollController.scroll_one_page()` |
| 并发 OCR | `shq/scanner/wuku/ocr_pipeline.py` | `OCRPipeline.submit()` |
| 数据合并 | `shq/scanner/wuku/merger.py` | `ShanheqiMerger.merge()` |
| 状态保存 | `shq/scanner/wuku/state.py` | `CollectionState.save()/load()` |
| CLI 入口 | `shq/cli.py` | `cmd_collect_wuku()` |
| 数据模型 | `shq/models.py` | `Shanheqi`、`Affix` |

## 四、推荐的验证命令

```bash
# 1. 确认输入注入可用（必须以管理员权限运行）
python -m shq.cli --diagnose-input

# 2. 运行测试
python -m pytest -q

# 3. 单页网格检测可视化（不滚动、不点击，只验证 item 分割）
python -c "
from shq.scanner.window_capture import capture_game_window
from shq.scanner.ocr_scanner import RapidOCRBackend
from shq.scanner.wuku.grid_detector import GridItemDetector
import cv2
img = capture_game_window(bring_to_front=True, fixed_size=True)
det = GridItemDetector(RapidOCRBackend())
items = det.detect(img)
print('detected', len(items), 'acquired', sum(1 for i in items if i.is_acquired))
"

# 4. 端到端采集（滚动异常未修复前可能只能扫前几页）
python -m shq.cli --collect-wuku ./wuku_test --ocr-backend rapidocr --attach-input
```

## 五、注意事项

- **必须管理员权限**：对一梦江湖窗口的 `SendInput` 输入注入需要管理员权限。
- **自动化风险**：可能违反游戏用户协议，README 与 CLI 中已保留免责声明。
- **不要瞎编数据**：所有未经验证的数值、公式仍用 TODO 占位；本次采集模块只读取屏幕像素，不读内存、不注入。
- **当前阻塞点**：滚动翻页异常导致 `--collect-wuku` 无法完成全量扫描，需在修复滚动后再进行真实环境端到端验证。
