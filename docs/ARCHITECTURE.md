# 山河器求解器架构设计

## 1. 目标

自动获取玩家拥有的山河器数据，并在给定灵鉴孔位/连线结构中搜索最优摆放方案，使目标属性或总评分最大化。

## 2. 核心抽象

### 2.1 数据模型（`shq.models`）

- `Element`：五行（金、木、水、火、土）。
- `Quality`：山河器品质（朴素、精巧、瑰丽、绝世）。
- `Suyun`：素蕴词条。
- `Shanheqi`：单个山河器，含 ID、名称、品质、五行、等级、基础评分、素蕴、属性。
- `Slot`：灵鉴孔位，含所属区域、培养评分、类型限制。
- `Connection`：孔位之间的有向连线（生克判定方向：from → to）。
- `RegionEffect`：区域灵鉴效果（评分阈值激活）。
- `Region`：灵鉴区域，含孔位、连线、效果、解锁条件。
- `Lingjian`：完整灵鉴，包含所有区域。
- `Placement`：摆放方案，slot_id → shanheqi_id。
- `Evaluation`：方案评估结果（总评分、各区域评分、属性、计算详情）。
- `Solution`：优化结果。

### 2.2 游戏规则（`shq.rules`）

- `RuleSet` 抽象接口隔离游戏版本差异。
- 实现者需提供：
  1. `can_place`：山河器能否放入指定孔位（类型/玄枢限制）。
  2. `evaluate`：完整评估一个摆放方案（基础评分、生克、区域效果等）。
  3. `score`：根据优化目标打分。
  4. `unlocked_regions`：根据评分判断已解锁区域。
  5. `resonances`：共鸣/羁绊（若存在）。

### 2.3 数据采集（`shq.scanner`）

- `Scanner` 接口支持多种数据来源。
- 当前提供：
  - `ProcessFinder`：定位游戏进程。
  - `WindowCapture`：截取游戏窗口图像（DPI 感知、客户区坐标、可固定大小）。
  - `ShanheqiOCR`：OCR 扫描山河器与灵鉴数据（占位实现，ROI 待校准）。
  - `InputSimulator`：基于 `SendInput` 的坐标点击。
  - `NavigationController`：截图 → OCR 识别导航标签 → 点击切换界面。
  - `ManualImporter`：JSON 手动导入。
- 预留：
  - 更精确的 ROI 检测与图像预处理。
  - EasyOCR / PaddleOCR 后端集成。

### 2.4 优化求解（`shq.solver`）

- `Solver` 接口支持多种算法。
- 已实现占位：`BruteForceSolver`、`GreedySolver`。
- 预留：ILP、遗传算法、模拟退火等。

## 3. 数据流

```
游戏客户端界面
       │
       ▼
  WindowCapture  ──►  游戏窗口截图（numpy BGR）
       │
       ▼
  ShanheqiOCR    ──►  ROI 裁剪 → OCR 识别 → 解析
       │
       ▼
  List[Shanheqi] + Lingjian
       │
       ▼
  Solver 层      ──►  搜索 Placement
       │
       ▼
  RuleSet 层     ──►  评估合法性 & 评分
       │
       ▼
  Solution       ──►  CLI / GUI 展示
```

## 4. 扩展指南

### 添加新的游戏规则

1. 继承 `RuleSet`。
2. 实现放置、评估、打分、解锁判断、共鸣方法。
3. 在 `shq/rules/__init__.py` 导出。

### 添加新的数据来源

1. 实现 `Scanner` 接口。
2. 返回 `List[Shanheqi]` 或 `Lingjian`。
3. 在 CLI 中注册使用。

### 添加新的求解算法

1. 实现 `Solver` 接口。
2. 返回 `Solution`。
3. 在 `shq/cli.py` 的 `SOLVERS` 字典中注册。
