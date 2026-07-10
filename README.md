# 一梦江湖 · 山河器最优摆放求解器

为 PC 端《一梦江湖》玩家提供山河器自动扫描与最优摆放推荐的小工具。

> 当前状态：`0.1.0` — 项目骨架已建立，核心抽象接口已完成，OCR 扫描器占位实现已就绪。
> **重要：游戏规则、山河器数据、灵鉴布局等具体数值尚未填充，全部以 TODO 占位。**

## 山河器系统说明（基于公开攻略调研）

山河器是《一梦江湖》中通过山河罗盘获取、镶嵌在**灵鉴**孔位中的养成系统：
- 灵鉴分为多个**区域**（如驿寄梅花、长烟烽火、戍客怀归、黄泉夜渡、关河道远等）。
- 每个区域包含若干**孔位**，孔位之间存在**有向连线**。
- 部分区域存在**背面区域**（如关河道远·隐），背面**中心孔位**可镶嵌**玄枢山河器**，获得额外加成。
- 山河器具有**五行属性**（金、木、水、火、土）和**品质**（朴素、精巧、瑰丽、绝世）。
- 根据连线方向，相邻山河器之间会产生**五行生克**效果：相生加分，相克减分。
- 山河器基础评分由品质得分、素蕴（词条）得分等组成；**孔位培养**可额外加分（不同用户数据不同）。
- 满级 3 次共贯后可获得**派生素蕴**（额外词缀），派生素蕴可能带有特殊效果（如起势、承势、倾侧等），会进一步影响最终得分或属性。
- 区域总评分达到阈值可激活灵鉴效果，并解锁下一区域/背面区域。
- 不同区域对不同**流派**（输出/治疗/承伤）的收益不同，求解时需按玩家偏好调整权重。

本工具的目标就是：根据玩家拥有的山河器与孔位培养状态，自动推荐灵鉴孔位最优摆放方案。

## 数据采集方案：OCR

由于 pktmon 抓包在部分 Windows 环境下不稳定且需要管理员权限，本项目采用**截图 + OCR** 方案获取游戏数据：
1. 通过 `ProcessFinder` 定位 `wyclx64.exe` 进程，获取窗口句柄。
2. 使用 Windows API 截取游戏窗口图像（DPI 感知 + 客户区坐标）。
3. 裁剪出山河器列表、灵鉴区域、属性面板等 ROI。
4. 调用 OCR 引擎（RapidOCR / EasyOCR 等）识别文字。
5. 解析为 `Shanheqi`、`Lingjian` 等数据模型。

基础方案仅读取屏幕像素，**不涉及内存读取、注入或自动化点击**。

### 自动化点击（可选，有风险）

为处理山河器数量多、需要切换标签页等场景，项目也提供了基于 Windows `SendInput` 的坐标点击能力：

```bash
# 点击游戏窗口客户区坐标 (1200, 400) 后截图
python -m shq.cli --click 1200,400 --snapshot shanheqi_lingjian.png

# 点击屏幕绝对坐标
python -m shq.cli --click-screen 1500,600

# 点击前先把当前线程输入队列挂接到目标窗口线程（对受保护窗口可能有效）
python -m shq.cli --click 1200,400 --attach-input

# 检测当前环境是否支持 SendInput（会短暂移动鼠标）
python -m shq.cli --diagnose-input
```

⚠️ **风险提示**：自动化点击/按键可能违反《一梦江湖》用户协议，存在封号风险。该功能默认不启用，只有显式传入 `--click` 或 `--click-screen` 时才会执行。请自行评估风险后使用。

截图时会自动将一梦江湖窗口切换到前台；如果切换失败，请手动确保游戏窗口可见后再截图。

⚠️ **权限提示**：
- `SendInput` / `mouse_event` / `SetCursorPos` 已经是 Windows 用户态最底层的鼠标注入 API。
- **一梦江湖客户端会拦截普通用户权限下的模拟输入**；自动化点击功能**必须以管理员权限启动终端**后运行本工具，否则鼠标不会动。
- 导航到武库时默认已启用 `AttachThreadInput` + `SetForegroundWindow`。
- 若点击位置有偏差（例如点到了相邻的「灵鉴」），脚本会自动检测实际高亮标签并校准 y 轴偏移。
- 若仍无法点击，请使用 `--manual-fallback` 手动点击后按回车继续。

## 项目结构

```
shq/
├── models.py              # 核心数据模型（山河器、灵鉴、区域、孔位、连线、五行）
├── rules/
│   ├── interface.py       # 游戏规则抽象接口（RuleSet）
│   └── ymjh_default.py    # 一梦江湖规则占位实现
├── scanner/
│   ├── interface.py       # 数据扫描器接口
│   ├── manual_importer.py # 手动 JSON 导入
│   ├── process_finder.py  # 定位一梦江湖进程
│   ├── window_capture.py  # 游戏窗口截图
│   └── ocr_scanner.py     # OCR 扫描器占位实现
├── solver/
│   ├── interface.py       # 求解器接口
│   ├── brute_force.py     # 暴力搜索
│   └── greedy.py          # 贪心启发式
├── cli.py                 # 命令行入口
└── config.py              # 配置

data/                      # 用户数据（空，不存放瞎编数据）
tests/                     # 单元测试
docs/                      # 设计文档
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 查找一梦江湖进程
python -m shq.cli --find-process

# 3. 截取游戏窗口（用于人工标注 ROI）
python -m shq.cli --snapshot ymjh_snapshot.png

# 4. 导出 OCR 识别区域（占位实现，当前导出整张截图）
python -m shq.cli --ocr-sample ./ocr_samples

# 5. 查看数据文件格式模板
python -m shq.cli --print-template

# 6. 运行测试
pytest
```

## OCR 配置

默认使用占位 OCR 后端，不会真正识别文字，仅保存 ROI 图像。

推荐使用 **RapidOCR**（已写入 `requirements.txt`，体积小且支持 Python 3.14）：
```bash
python -m shq.cli --ocr-sample ./ocr_samples --ocr-backend rapidocr
```

如需启用 EasyOCR：
```bash
pip install easyocr
python -m shq.cli --ocr-sample ./ocr_samples --ocr-backend easyocr
```

### 固定窗口大小

为保证所有 ROI 和点击坐标稳定，工具会自动把游戏窗口客户区调整为 `1334x750`（可在 `shq/scanner/window_capture.py` 中修改 `DEFAULT_CLIENT_WIDTH/HEIGHT`）。

```bash
# 手动调整窗口大小
python -m shq.cli --resize
```

### 一键采集流程

`--auto-collect` 会把整个流程串起来：

1. 自动导航到武库界面
2. 截图保存到指定目录

> 注意：一梦江湖窗口通常无法被脚本强制调整大小，因此不再固定 `1334x750`；
> 所有 ROI 坐标均按窗口当前实际大小按比例计算。

```bash
# 占位 OCR 后端（不会真正识别标签，只执行截图）
python -m shq.cli --auto-collect ./captures

# 使用 RapidOCR 真正导航并截图（推荐，需要管理员权限）
python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr

# 使用 EasyOCR 真正导航并截图
python -m shq.cli --auto-collect ./captures --ocr-backend easyocr

# 若自动点击完全失效，手动点击武库后按回车继续
python -m shq.cli --auto-collect ./captures --ocr-backend rapidocr --manual-fallback
```

后续会把 OCR 识别山河器列表也加进这个流程，最终目标是：

```bash
python -m shq.cli --auto-collect ./captures --ocr-backend easyocr --output shanheqis.json
```

### 手动分步命令（调试用）

```bash
python -m shq.cli --resize
python -m shq.cli --nav-to-wuku --ocr-backend rapidocr --snapshot wuku.png
```

## 已知机制（基于公开攻略调研）

- 灵鉴区域（至少 5 个）：驿寄梅花、长烟烽火、戍客怀归、黄泉夜渡、关河道远。
- 玩家社区推荐的培养/镶嵌优先级：长烟烽火 > 关河道远 > 戍客怀归 > 黄泉夜渡 > 驿寄梅花（3-5-2-4-1）。
- 五行生克：相生为金→水→木→火→土→金，被指向者加分；相克为金→木→土→水→火→金，被指向者减分；攻略记载比例为 ±15%，**待验证**。
- 山河器品质：朴素、精巧、瑰丽、绝世。
- 素蕴：共贯获得，分 3 级；派生素蕴为额外词缀，可能含起势/承势/倾侧等特殊效果。
- 孔位培养：消耗思归石，不同用户培养程度不同，会直接影响评分。
- 背面区域：关河道远·隐等，中心孔位可镶嵌玄枢山河器；玄枢共贯等级会影响周围评分；背面孔位本身可能降低分数。

## 后续工作

参见 [docs/TODO.md](docs/TODO.md)。
