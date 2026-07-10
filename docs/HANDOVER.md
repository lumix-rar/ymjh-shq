# 一梦江湖山河器工具 — 交接文档

> 生成时间：2026-07-09（当前会话）
> 交接人：前序 Agent
> 接收人：后续 Agent

## 一、任务目标

为 PC 端《一梦江湖》开发一个小工具，能够：

1. **自动采集**玩家拥有的所有山河器数据（名称、品质、五行、等级、共贯等级、素蕴、派生素蕴等）。
2. **自动采集**玩家灵鉴布局（区域、孔位、连线、孔位培养、背面区域、玄枢等）。
3. 基于真实游戏规则，给出**山河器最优摆放解**，支持输出/治疗/承伤/综合等流派偏好。

当前处于项目初始化与 OCR 自动采集流程阶段，核心求解逻辑、游戏规则数值全部以 TODO 占位，等待真实数据填充。

## 二、当前已具备的基础

### 2.1 项目结构

```
shq/
├── models.py              # 核心数据模型（Shanheqi、Lingjian、Region、Slot、Connection、五行、品质等）
├── rules/
│   ├── interface.py       # RuleSet 抽象
│   └── ymjh_default.py    # 一梦江湖规则占位实现（全 TODO）
├── scanner/
│   ├── interface.py       # Scanner 抽象
│   ├── ocr_scanner.py     # OCR 扫描器（ShanheqiOCR、RapidOCRBackend、EasyOCRBackend）
│   ├── navigation_controller.py  # 山河器界面导航（resize、OCR 识标签、点击武库、界面判断）
│   ├── window_capture.py  # 窗口定位、截图、固定客户区大小 1334x750
│   ├── input_simulator.py # Windows SendInput 坐标点击
│   ├── process_finder.py  # 查找 wyclx64.exe 进程
│   └── manual_importer.py # 手动 JSON 导入
├── solver/
│   ├── interface.py       # Solver 抽象
│   ├── brute_force.py     # 暴力搜索占位
│   └── greedy.py          # 贪心求解占位
├── cli.py                 # 统一命令行入口
└── config.py              # 进程/窗口匹配规则

tests/                     # 单元测试（当前 23 个全过）
docs/
├── ARCHITECTURE.md
├── TODO.md
└── HANDOVER.md            # 本文档
```

### 2.2 已实现的关键能力

- **统一命令入口**：
  ```bash
  python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr
  ```
  流程：调整窗口到 1334×750 → OCR 识别右侧导航标签 → 点击“武库” → 检测到高亮切到“武库”后截图保存。

- **OCR 引擎**：默认推荐 `rapidocr-onnxruntime`（已写入 `requirements.txt`），兼容 Python 3.14；可选 EasyOCR。

- **武库界面判断**：`NavigationController._is_in_wuku()` 改为通过右侧导航标签的**高亮背景亮度**判断当前子界面，已用实际截图验证可正确区分“搜寻”和“武库”。

- **多显示器坐标修复**：`InputSimulator.move_to()` 已改用虚拟桌面指标（`SM_CXVIRTUALSCREEN` 等）对 `SendInput` 绝对坐标归一化。

- **测试**：`pytest -q` 当前 23 passed。

## 三、调研结论（基于公开攻略，需后续验证）

山河器系统不是棋盘，而是：

- **灵鉴**由多个**区域**组成（驿寄梅花、长烟烽火、戍客怀归、黄泉夜渡、关河道远等）。
- 每个区域有若干**孔位**，孔位间有**有向连线**。
- 山河器有**五行**（金木水火土）和**品质**（朴素/精巧/瑰丽/绝世）。
- 山河器基础评分 = 品质得分 + 素蕴得分；共贯 3 次后可获得**派生素蕴**（起势、承势、倾侧等）。
- 孔位培养（思归石）会给对应孔位额外加分，**不同用户不同**。
- 相邻孔位按连线方向产生**五行生克**：相生被指向者 +15% 基础评分，相克 -15%（比例待验证）。
- 部分区域有**背面区域**，背面孔位本身会**降分**；背面中心孔位镶嵌**玄枢**山河器有额外加成，且玄枢共贯等级影响周围评分。
- 区域总评分达到阈值才激活人物属性 / 解锁下一区域。
- 不同区域对输出/治疗/承伤的收益不同，求解需按玩家偏好调整权重。

**重要约束**：所有未知数值、公式、布局均使用 TODO 占位，**禁止瞎编数据**。

## 四、已尝试的工作与结果

| 尝试 | 结果 | 备注 |
|------|------|------|
| 网络搜索山河器系统机制 | 成功 | 见 `docs/TODO.md` 调研结果与 README 说明 |
| pktmon 抓包获取数据 | 放弃 | 已按用户要求清理所有抓包逻辑与 `.etl` 文件 |
| 固定窗口大小 1334×750 | 成功 | `WindowCapture.ensure_client_size()` |
| OCR 识别右侧导航标签 | 成功 | RapidOCR 可稳定识别“搜寻/复归/灵鉴/武库” |
| 基于高亮背景判断当前子界面 | 成功 | 已在 `debug_current.png` 上验证 |
| 确认自动化点击需要管理员权限 | 完成 | 普通用户权限下三种输入方式全灭；管理员权限下点击生效 |
| 自动校准导航标签 y 偏移 | 完成 | 点击后检测实际高亮标签，计算 offset_y 并修正后续点击 |
| 放弃强制 resize | 完成 | 一梦江湖窗口拒绝 `SetWindowPos` 调整大小，改为按实际窗口尺寸计算坐标 |
| 增加输入诊断 & 手动降级 | 完成 | `--diagnose-input` 只检测真实 `SendInput`；`--manual-fallback` 让用户手动点击后按回车继续 |
| 尝试 `AttachThreadInput` 绕过 UIPI | 完成 | 现已成为 `NavigationController` 默认行为；但核心限制是管理员权限 |
| 增加点击链路调试脚本 | 完成 | `debug_click.py` 可逐步定位 `SendInput` 在哪一步失效 |
| 清理临时调试文件 | 完成 | 已删除 `debug_*.png`、`shanheqi_ui.png`、`.etl` 等 |
| 更新 README / TODO | 完成 | RapidOCR 改为默认推荐，增加权限提示 |

## 五、当前阻塞点

1. **输入注入需要管理员权限**
   - 用户本地测试证明：普通用户权限下 `SendInput` / `mouse_event` / `SetCursorPos` 对一梦江湖窗口完全无效；以管理员权限运行后点击生效。
   - 因此**脚本必须以管理员权限运行**才能进行自动化点击。

2. **截图坐标与实际可点击区域存在纵向偏移**
   - 管理员权限下点击到了「灵鉴」而非「武库」，说明 OCR/截图坐标系和游戏实际响应区域在 y 轴上有偏移。
   - 已加入自动校准：点击后检测实际高亮标签，计算并修正 y 偏移。

3. **游戏窗口拒绝被强制 resize**
   - `SetWindowPos` 无法将一梦江湖窗口调整为 `1334x750`。
   - 已放弃固定分辨率方案，改为根据窗口实际大小按比例计算坐标。

2. **缺少武库界面真实截图**
   - 当前所有截图都是“搜寻”界面，尚未拿到“武库”界面截图。
   - 无法标定山河器列表、筛选/排序按钮、滚动条等 ROI。

## 六、下一步工作清单

### 高优先级（建议按顺序执行）

1. **在本地交互式终端验证输入注入能力**
   ```bash
   # 先自检，会短暂移动鼠标
   python -m shq.cli --diagnose-input

   # 若自检通过，再尝试完整导航
   python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr
   ```
   - 若 `--diagnose-input` 显示支持，但 `--auto-collect` 仍点不到游戏，加 `--attach-input`：
     ```bash
     python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr --attach-input
     ```
   - 若仍失败，用 `--manual-fallback` 手动点击武库后按回车继续：
     ```bash
     python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr --manual-fallback
     ```

2. **标定武库界面 ROI**
   - 山河器列表区域（左侧还是中间？网格还是列表？）。
   - “全部/品质/等级/排序”等筛选/排序控件位置。
   - 滚动条位置与翻页逻辑（山河器可能很多，需要滚动）。
   - 单个山河器条目的文字区域：名称、品质、五行、等级、共贯等级、素蕴、派生素蕴。

3. **实现山河器列表 OCR 解析**
   - 完善 `ShanheqiOCR._detect_shanheqi_rois()` 和 `_parse_shanheqi()`。
   - 将识别结果存入 `Shanheqi` 模型并导出 JSON。

4. **采集灵鉴布局**
   - 进入“灵鉴”界面，截图并标定各区域、孔位、连线。
   - 实现 `ShanheqiOCR.scan_lingjian()`，输出 `Lingjian(regions=[...])`。
   - 注意背面区域、玄枢孔位、孔位培养分数的识别。

5. **填充游戏规则**
   - 在 `shq/rules/ymjh_default.py` 中实现真实评分逻辑：
     - 品质得分表
     - 素蕴评分（等级、五行、组合）
     - 派生素蕴规则（起势/承势/倾侧等触发条件与数值）
     - 五行生克 ±15% 是否准确、方向如何由连线决定
     - 孔位培养加分
     - 背面孔位减分
     - 玄枢加成（共贯等级影响范围）
     - 区域评分阈值与解锁判断
     - 输出/治疗/承伤流派权重

6. **实现求解器**
   - 基于真实 `RuleSet.score()` 实现精确/启发式求解。
   - 推荐先用 `pulp` 等 ILP 库，小数据可用暴力，大数据需剪枝/缓存/并行。

### 中低优先级

- 提供手动 JSON 录入模板与校验。
- 可视化灵鉴布局与推荐摆放（GUI / 图片标注）。
- 增量扫描：只识别新增/变更的山河器。
- 结果与游戏内实际数值对比校准。
- 日志、配置文件、打包 exe。

## 七、关键代码位置速查

| 功能 | 文件 | 关键类/函数 |
|------|------|-------------|
| 统一采集命令 | `shq/cli.py` | `cmd_auto_collect()` |
| 导航/点击武库 | `shq/scanner/navigation_controller.py` | `NavigationController.ensure_in_wuku()`、`_detect_selected_nav_label()` |
| OCR 后端 | `shq/scanner/ocr_scanner.py` | `RapidOCRBackend`、`EasyOCRBackend`、`ShanheqiOCR` |
| 窗口截图/Resize | `shq/scanner/window_capture.py` | `WindowCapture`、`DEFAULT_CLIENT_WIDTH/HEIGHT` |
| 输入模拟 | `shq/scanner/input_simulator.py` | `InputSimulator.click_on_window()` |
| 数据模型 | `shq/models.py` | `Shanheqi`、`Lingjian`、`Region`、`Slot`、`Quality`、`Element` |
| 游戏规则 | `shq/rules/ymjh_default.py` | `YMJHDefaultRuleSet` |
| 求解器 | `shq/solver/` | `BruteForceSolver`、`GreedySolver` |

## 八、注意事项

- **不要瞎编数据**：任何未经验证的数值、公式、布局都用 TODO 占位。
- **所有坐标必须基于截图实时计算**：当前固定窗口为 1334×750，但每次运行前会检查并调整。
- **OCR 推荐 RapidOCR**：`pip install rapidocr-onnxruntime`；EasyOCR 体积大、首次需下载模型。
- **自动化点击风险**：可能违反游戏用户协议，务必在 README 提示中保留免责声明。
- **权限问题**：若游戏以高完整性运行，脚本可能需要管理员权限才能注入输入。
- **输入注入限制**：`SendInput` 已是用户态最底层 API；若仍被拦截，可试 `--attach-input`，或改用 `--manual-fallback` 手动点击。再往下需要驱动级方案，超出本项目范围。

## 九、推荐的首次验证命令

```bash
# 1. 确认能找到进程
python -m shq.cli --find-process

# 2. 固定窗口并截图（验证窗口/截图链路）
python -m shq.cli --resize
python -m shq.cli --snapshot ymjh_current.png

# 3. 以管理员权限运行一键采集（验证导航+点击）
python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr

# 4. 运行测试
python -m pytest -q
```
