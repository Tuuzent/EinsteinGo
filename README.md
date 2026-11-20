# EinsteinGo · 爱因斯坦棋（Einstein würfelt nicht）博弈程序

纯 Python 3 标准库实现，零第三方依赖。支持**桌面界面（双击 `start_ui.bat` 即开）**、
命令行对局、自对弈基准，以及
**比赛模式：复制外部送来的对方走法（校验后重放，保证两侧状态逐字节一致）**，再由我方
算法（启发式 + 蒙特卡洛树搜索）完成后续决策。

```
start_ui.bat                           # ★ 双击：打开桌面界面（人机对弈 / 比赛模式）
python run_ui.py                       # 同上，命令行启动
python run_demo.py                     # 一局完整演示（含哈希链校验）
python -m einstein_go.cli remote          # 比赛模式：复制对方走法 + 我方算法应对
python -m einstein_go.cli play --red human --blue mcts
python -m einstein_go.cli match --a mcts --b heuristic
python -m pytest                       # 259 个用例，约 10 秒
python scripts/bench_matrix.py --games 20 --nodes 300
```

> **两套解释器的注意点**：本机 PATH 里的 `python`（WorkBuddy 内置 3.13.14）**没有 tkinter**，
> 而系统安装的 Python 3.13.15 有。`start_ui.bat` 会自动挑出能 `import tkinter` 的那个；
> 自己手敲命令时请用 `py -3 run_ui.py`。详见 §十。

---

## 一、规则（来自赛事文档）

- 5×5 棋盘。左上角红方出发区，右下角蓝方出发区；双方各 6 枚棋子，编号 1–6，开局在出发区内**随意摆放**。
- 双方轮流掷骰，走动与骰值对应的棋子；该编号棋子已出局时走"缺号替代"的棋子。
- 红方向右/下/右下，蓝方向左/上/左上，每次一格；目标格有棋子就把它移出（**可以吃本方棋子**）。
- 率先到达对方出发区角点（红到 e5，蓝到 a1），或吃光对方全部棋子，即获胜。**无和棋**。
- 每方 4 分钟/盘；每轮最多 7 盘，甲方第 1、4、5 盘先手，先胜 4 盘者为胜方。

### 出发区形状

文档图 1 里的形状无法从文本读取，按标准 Einstein würfelt nicht 采用**角上 6 格三角**：

```
红方 RED_HOME  = a1 b1 c1 a2 b2 a3     (row + col <= 4)
蓝方 BLUE_HOME = e5 d5 c5 e4 d4 e3     (中心对称镜像)
```

### 规则第 3 条的读法（重要）

文档原文举例：**"假设编号为 4 和 5 的棋子已移出，如果骰子显示为 4，则可以走动编号为 3 或 6 的棋子"**。

3 与 4 差 1，6 与 4 差 2。如果按"全局差值最小"解释，只能走 3，与文档矛盾。
正确读法是**两侧分别取最近**：小于骰值的最近一枚 + 大于骰值的最近一枚，两侧都可以走。
`movegen.resolve_candidates` 按此实现，并有 11 行参数化测试覆盖（含仅剩单枚、单侧缺失等边界）。

### 文档未明确处的默认假设

| # | 假设 | 理由 |
|---|---|---|
| A1 | 出发区内棋子可互相吃，无免疫区 | 规则 5 只说"可以吃本方棋子"，未设区域限制 |
| A2 | 踩到对方角点即刻终局 | 规则 6「率先到达」 |
| A3 | 一手同时"进角+吃光"时 reason 记 `reached_corner` | winner 相同，固定顺序让日志与测试不抖动 |
| A4 | 仅剩单枚棋子时任意骰值都必走它 | 候选集只有它 |
| A5 | 轮空消耗本方计时、弃骰、换手 | 轮空=本方回合的失败结果。**本规则集下轮空不可达** |
| A6 | 无"放弃走子"，每回合必须走一步 | 规则 3 是强制动作 |
| A7 | 计时只算本方「掷骰→落子」区间 | 标准棋钟语义 |
| A8 | 4 分钟是**每盘**，新一局重置 | 规则 8「每盘每方用时」 |
| A9 | 开局 6 个编号完全自由摆放（6! 种） | 规则 2「随意摆放」 |
| A10 | 先手方执红 | 规则未绑定，取赛事惯例 |
| A16 | 落子成胜优先于本手旗倒（只有"未取胜却已超时"才判负） | 避免"用最后一秒赢下却被判负"的荒谬结果 |

### 两条可证明的性质（代码注释里也有）

1. **轮空不可达**：任何非终局的在盘棋子恒有 ≥1 个合法目标格（红方在 `(r,c)`，只要不在 `(5,5)`，
   就至少有"向右"或"向下"之一）。所以 `generate_moves` 返回空列表只可能发生在本方已全灭时，
   而那时对局早已终局。`pass_turn` 只是防御性代码与变体规则的挂点。
2. **必然终局**：红方每步使 `r+c` 至少 +1，一枚棋子最多 7 次移动就必须踩到 `r+c=10` 即 `(5,5)` 获胜，
   否则中途被吃。故单方走子数 ≤ 6×7=42，**全局 ply ≤ 84**。
   实测 300 局随机对弈最大 35 手、平均 21 手。`MAX_PLY=300` 的裁决分支永不触发。

---

## 二、目录结构

```
EinsteinGo/
├── run_demo.py                  一键演示
├── pytest.ini                   默认跳过 slow 用例
├── einstein_go/
│   ├── constants.py             坐标/方向/出发区/角点/编码辅助/预计算邻接表
│   ├── errors.py                16 个错误码 + 异常类型（含"谁在何时抛"的注释）
│   ├── zobrist.py               固定种子哈希表（跨进程可复现）
│   ├── board.py                 格名互转与 ASCII 渲染（纯数据层）
│   ├── move.py                  Move（引擎层）/ MoveIntent（协议层）+ 序列化
│   ├── state.py                 Position（不可变）+ GameState + rot180/canonical
│   ├── movegen.py     ① 合法走法生成（resolve_candidates / generate_moves）
│   ├── transition.py  ②③④ 移动执行 / 吃子 / 回合切换 / ScratchBoard
│   ├── terminal.py    ⑤ 胜负判定 + 超时判负 + 安全阀裁决
│   ├── outcome.py               GameResult（构造时拒绝 winner==0 → 结构上无和棋）
│   ├── clock.py                 Real/Fake/Virtual 三种时间源 + TimeBank 只读代理
│   ├── match.py                 7 盘 4 胜轮次、先手序列、提前终止、比分
│   ├── protocol.py              棋谱行/JSON 编解码 + blake2b 哈希链
│   ├── sync.py                  ★ 状态同步层（复制走法 + 五层对账）
│   ├── session.py               GameSession 门面（唯一掷骰入口）
│   ├── players.py               Human/Random/Heuristic/MCTS 对局者 + play_out
│   ├── config.py                权重表与搜索参数（集中调参处）
│   ├── ai/
│   │   ├── features.py          8 个特征（lru_cache 缓存）
│   │   ├── eval.py              evaluate / evaluate_expected / win_in_one
│   │   ├── mcts.py              ★ 带机会节点的 MCTS + 先验 + 预算 + 确定性 tie-break
│   │   └── rng.py               可复现随机源
│   ├── cli/                     main（argparse）/ render / repl（交互循环）
│   └── gui/                     ★ 桌面界面（详见第十节）
│       ├── __init__.py          仅 docstring —— 铁律：不 import 任何 view 子模块
│       ├── model.py             Mode/Phase/GameSetup/难度预设/25 格视图模型
│       ├── controller.py        ★ GameController：状态机 + 无副作用校验 + 线程调度
│       ├── errors_view.py       错误码中文 + 六层对账视图
│       ├── thinker.py           决策器（与线程解耦，可无线程测试）
│       ├── record_io.py         棋谱导出 + 导出后重放自检
│       ├── logbus.py            控制台/文件/内存日志（不裸 print）
│       └── view/                仅本目录允许 import tkinter
│           ├── theme.py         配色/字体回退链/DPI 缩放
│           ├── app.py           ★ App(tk.Tk)：工具栏 + 布局 + after 轮询
│           ├── board_canvas.py  ★ Canvas 棋盘：分层绘制、点击映射、动画
│           ├── side_panel.py    状态/时钟/候选条/棋谱
│           ├── match_panel.py   走法输入 + 六层对账 + 我方走法复制
│           └── widgets.py       圆角矩形/错误条/候选条/结果卡
├── scripts/
│   ├── demo_game.py             完整演示对局 + 整局重放校验
│   ├── match_mode_demo.py       ★ 比赛模式：两侧独立棋盘 + 走法消息同步
│   ├── gui_smoke.py             真实开窗冒烟（用有 tkinter 的解释器跑）
│   └── bench_matrix.py          自对弈基准矩阵
├── start_ui.bat                 ★ 一键启动（纯 ASCII，探测解释器）
├── run_ui.py                    界面入口（DPI 感知 + 容错 import）
└── tests/                       16 个测试文件，259 个用例
```

依赖严格单向：`constants → board/move → state → movegen/transition → terminal → ai/* → protocol/sync/session → players/cli`。
`ai/*` 与规则层不感知时间、历史与 I/O（时间只通过 `TimeBank` 注入）。

---

## 三、五个职责的封装

| 职责 | 位置 | 签名 |
|---|---|---|
| ① 合法走法生成 | `movegen.py` | `generate_moves(pos, die=None) -> list[Move]`<br>`resolve_candidates(alive, die) -> tuple[int, ...]` |
| ② 移动执行 | `transition.py` | `apply(pos, mv) -> Position`（走子+吃子+换手+清骰，一次做完） |
| ③ 回合切换 | `transition.py` | `switch_turn(pos)` / `pass_turn(pos)`（squares 不变、side 翻转、die=0） |
| ④ 棋盘状态 | `state.py` | `Position`（frozen + slots，25 长 int tuple + 派生位图） |
| ⑤ 胜负判定 | `terminal.py` | `terminal_after(new_pos, ply) -> GameResult \| None` |

会话层再包一层：`GameSession.roll() / play(mv) / legal_moves() / remaining_ms() / record()`。

### 棋子编码与棋盘表示

```python
0 = 空   +1..+6 = 红 1..6   -1..-6 = 蓝 1..6
# code > 0 即红、abs(code) 即编号 —— 省掉所有 color 分支
```

`Position.squares` 是长度 25 的 int tuple（唯一权威），占位位图与 6 bit 的 `alive` 掩码是派生缓存。
选它而不是二维 list 的三个理由：不可变 → MCTS 节点持引用即快照（零拷贝、失败天然回滚）；
可就地哈希 → 置换表/哈希链/测试断言；单 int 编码 → 位运算 O(1)。

---

## 四、AI：启发式 + MCTS

### 评估函数

先按 180° 旋转把"评估方"统一成红方视角？**不需要**——特征直接以 `(squares, side)` 计算两侧再作差，
因此评估对旋转天然对称（`test_eval_mirror_invariance` 守住），从根本上消灭"蓝方 max/min 写反"。

| 特征 | 含义 | 权重 |
|---|---|---|
| `dist` | 最靠前棋子到角点的切比雪夫距离差 / 4 | +1.20 |
| `dist2` | 第二梯队距离差 / 4 | +0.30 |
| `material` | 子力差 / 6 | +0.50 |
| `mobility` | 6 个骰面下合法走法总数差 / 18 | +0.20 |
| `lose1` | **对手下一手进角概率**（近似致命） | −2.60 |
| `risk` | 对手能吃掉我方领头子的骰面概率 | −0.90 |
| `win1` | 我方下一手进角概率（打折：对手先走一手） | +2.00 |
| `structure` | 双方距离和之差 / 24 | +0.10 |

`evaluate = tanh(1.6 · Σ w·f) ∈ (−1, 1)`。`lose1` 的绝对值必须压过 `dist` 的上限——
"对手一步进角"的终局性是绝对的。`evaluate_expected` 对 6 个骰面分别估值再平均，
用于需要消骰运噪声的场合（成本 6 倍）。

### MCTS 结构

```
Decision(我方, 骰值已掷出) --move--> Chance(对手回合, 骰值未知) --die d--> Decision(对手, d) --move--> …
```

- **根必是决策节点，根下面没有机会节点**。我方掷骰后才决策；在根上再插一层机会节点
  等于把自己的骰子平均掉，棋力会明显退化。
- **机会节点：树内枚举 6 个骰面，rollout 内采样单骰**。骰面均匀且已知，所以机会节点用
  **轮转均衡**（选访问次数最少的子节点）而不是 UCB —— UCB 会偏向"对行棋方有利的那个骰面"，
  把期望值往上抬；轮转均衡保证 `q = w/n` 是期望的无偏估计。
- **符号约定**：每节点存自己 owner 视角的值，negamax 翻转只在"走子边"发生一次
  （`Decision.edge_sign=+1`，`Chance.edge_sign=-1`）。选择时比较 `edge_sign · child.q`，
  把这个值翻回本节点视角 —— 漏掉这一步等于替对手挑最优走法（实现这类博弈最常见的 bug）。
- **四阶段**：Select（PUCT，`c_puct=1.4`）→ Expand（算先验、展开骰面）→ Simulate（贪心 0.6 + 随机）→ Backprop。
- **启发式的四个用途**（不是二选一）：截断叶子估值、扩展时的走法先验、极短时间/单走法/必胜的直返、
  纯启发式基线对照。
- **时间预算**：`allot = clamp(剩余 / max(20, 40-ply), 60, 3000) ms`，`deadline = now + allot - 30ms`；
  每 64 次模拟或每 8ms 检查一次；`node_limit` 用于单测/基准的确定性。
  实测 ~28,000 次模拟/秒（单核），3000ms 预算 ≈ 8 万次模拟。
- **可复现**：`SearchConfig.seed` 固定后同局面必出同走法。
  rollout 的"虚拟骰"用 `derive(seed,"rollout")` 的独立 RNG，绝不污染对局 RNG。

### 掷骰归属（唯一契约）

`GameSession.roll()` 是**唯一**掷骰入口，`die != 0` 时抛 `DIE_ALREADY_ROLLED`；
AI 侧只断言 `pos.die != 0`，**绝不掷骰**。这样才不会有"AI 掷一次 + 驱动层再掷一次"
导致实际使用的骰值与日志/对手视图不一致——这是最难查的一类 bug。

---

## 五、状态同步层（"复制走法"）

定位：对手发来走法（棋子编号 + 目标格，可带骰值）→ 本地**校验 + 重放**，
而不是把对方棋盘镜像翻转过来。本层同时服务网络对局、赛事记录、断线重连与复盘。

```python
new_state, report = apply_remote_move(state, "3c1-d1@3", SyncMode.STRICT)
if not report.ok:
    print(report.format())      # 结构化错误 + 逐项对账明细
```

**五层对账**

| 层 | 内容 | 错误码 |
|---|---|---|
| L0 前置 | 对局未结束 / 阵营匹配 / `ply` 连续 / 骰值（本地未掷则采纳对方宣告的 `@die`） | `GAME_ALREADY_OVER`、`NOT_YOUR_TURN`、`REPLAY_OUT_OF_ORDER`、`DIE_NOT_ROLLED`、`DIE_PIECE_MISMATCH` |
| L1 几何 | 编号在盘 / 起点（缺省则推断）/ 邻接 / 方向 / 骰值-编号一致 / 最终合法性总闸 | `PIECE_ALREADY_CAPTURED`、`SRC_MISMATCH`、`NOT_ADJACENT`、`ILLEGAL_DIRECTION`、`ILLEGAL_MOVE` |
| L2 快照 | 走前完整指纹（squares/masks/alive/side/die/zhash） | — |
| L3 执行 | 直接 `apply` 生成新对象 → **不可变天然回滚，失败零污染** | — |
| L4 对账 | C1 起点清空 / C2 终点为本方子 / C3 子力守恒（本方减 0/1、对方减 0/1、总减 ≤1）/ C3b 仅一个编号位变化 / C4 被吃子归属 / C5 已换手 / C6 骰值已消耗 / C7 仅两格变化 / C8 增量哈希未漂移 | `SYNC_DESYNC` |
| L5 哈希链 | `blake2b(prev ‖ "piece:src>dst@die\|zhash")` 逐手串联 | `HASH_CHAIN_BROKEN` |

**失败即返回原 state**，上层可重发、判负或断线重连。
**STRICT / LENIENT 两种模式**：严格模式任何不符即拒；容错模式**只允许在"唯一可确定"的维度修正**
（起点反查、骰值缺省填充），且**绝不替对方猜一个能走的走法**，所有修正都在报告里标 `recovered`。

**整局重放**：`replay(record)` 逐手重放并比对每手 `hash_after`，坏了能定位到具体 ply
（只比最终哈希时，坏了只知道坏了）。

### 运行示例

```
$ python -m einstein_go.cli remote --nodes 300
比赛模式演示  我方=蓝(B)(MCTS, nodes=300)  对方=红(R)(启发式)  种子=7
开局一致性 ✓  开局 zhash=fc88c1cc6f8739b7

[ply 1] 对方(R) 掷骰 3 → 发来走法 3c1c2@3
  复制并校验: 成功
  两侧状态一致 ✓  zhash=53c2ae16ebcd61e0

[ply 2] 我方(B) 掷骰 2 → 决策 2d4d3@2
  MCTS: 300 次模拟 / 41ms
    2d4-d3@2 n=123 q=-0.171 p=0.123
    2d4-c3@2 n=112 q=-0.071 p=0.446
  两侧状态一致 ✓  zhash=edd95f4926914192
...
对局结束: 红方胜（reached_corner，第 17 手）  共 17 手
我方 哈希链尾 7a4104c398ef9a1c874359b23fe57ea0
对方 哈希链尾 7a4104c398ef9a1c874359b23fe57ea0
整局哈希链一致 ✓  HASH CHAIN OK
```

两侧各自持有一副独立棋盘，每传一手都断言 `squares / side / die / 指纹 / 哈希链`逐字节一致——
这就是"复制走法前后状态一致"的可执行证明（`scripts/match_mode_demo.py`）。

---

## 六、计时与赛制

- `Clock` 注入时间源：`RealTime`（对局）/ `FakeTime`（单测推进）/ `VirtualTime`（基准按节点折算，**不 sleep**）。
- `roll()` 起表、`play()` 落子扣时；旗倒 → `TIMEOUT`，判负。
- `Match`：`FIRST_PLAYER_OF_GAME = {1:A, 2:B, 3:B, 4:A, 5:A, 6:B, 7:B}`，先手执红，先胜 4 盘提前终止，
  每盘重置双方 240000ms。7 盘 4 胜结构上不会出现平局（3:3 后第 7 盘必为 4:3）。

---

## 七、验证结果

### 单元测试

```
python -m pytest            # 170 passed in ~6s（3 个 slow 用例默认跳过）
python -m pytest -m slow    # 自对弈基准用例
```

覆盖重点：`resolve_candidates` 11 行参数化表、红蓝方向对称、吃己方子时清"被吃者"编号位、
`zhash` 增量==全量、`ScratchBoard` 与 `Position` 200 局全字段对账、300+ 局随机对弈必然终局、
同步层 20 个用例（正常/越界/方向/非邻接/已出局/骰值/起点/重复/乱序/篡改/容错）、
MCTS 的符号与预算、计时与赛制。

### 基准矩阵（`--games 20 --nodes 300`）

```
matrix                 games  win_rate avg_plies    avg_ms  max_ms  illegal  timeouts
random vs random          20      0.40      22.0         0       0        0         0
heuristic vs random       20      0.95      17.4         0       0        0         0
mcts vs random            20      0.95      17.1        16      93        0         0
mcts vs heuristic         20      0.70      16.4        16     148        0         0
heuristic vs heuristic    20      0.35      17.4         0       1        0         0
```

验收门槛全部通过：`illegal == 0`、mcts vs random ≥ 0.90、mcts vs heuristic ≥ 0.60、
平均每步 ≤ 1000ms。`heuristic vs heuristic` 胜率 0.35（先手方优势 ~0.6）说明红方确实有先手之利，
而 MCTS 把这个优势进一步放大。

### 演示对局

```
python run_demo.py --seed 7 --nodes 800
```

逐步打印棋盘 / 骰值 / 走法 / 状态哈希 / 哈希链前缀，最后从棋谱重放整局并断言
`zhash` 与 `chain_hash` 逐字节一致，输出 `HASH CHAIN OK`。棋谱写入 `output/demo_seed7.jsonl`，
可用 `python -m einstein_go.cli replay output/demo_seed7.jsonl` 复看。

---

## 八、命令行

```
# 双人热座（两个人类）
python -m einstein_go.cli play --red human --blue human

# 人机：机器在蓝方，每步最多 3 秒
python -m einstein_go.cli play --red human --blue mcts

# 机机（快速实验用节点上限代替时间）
python -m einstein_go.cli play --red mcts --blue heuristic --nodes 800

# 7 盘 4 胜
python -m einstein_go.cli match --a mcts --b heuristic --games 7

# 比赛模式：对方走子 → 复制校验 → 我方应对（两侧独立棋盘，逐手断言一致）
python -m einstein_go.cli remote --nodes 800 -v

# 重放棋谱并校验哈希链
python -m einstein_go.cli replay output/demo_seed7.jsonl -v
```

交互提示下输入走法如 `3c1-d2` 或 `3c1d2`（可带 `@骰值`）。命令：`h` 帮助、`b` 重绘、
`m` 合法走法、`r` 棋谱、`q` 退出。人类输入的校验是**无副作用**的（先在状态副本上试算），
所以输错不会重复扣时。

---

## 九、已知限制

- 单线程，无置换表；MCTS 的跨手子树复用未实现（重开树，换取实现简单与零符号风险）。
- 评估权重是手工调的（`config.DEFAULT_WEIGHTS`），未做自动调参；修改后请跑
  `scripts/bench_matrix.py` 回归。
- 出发区形状、先手执红等按本文档第一节的假设实现；若赛事规则不同，只需改
  `constants.RED_HOME` / `MATCH.FIRST_PLAYER_OF_GAME` 与状态同步层的方向表。
- 桌面界面只做了人机对弈与比赛模式；双人热座/机机演示请走命令行，未做悔棋。

---

## 十、桌面界面（`start_ui.bat` 一键启动）

### 10.1 启动

双击项目根目录的 **`start_ui.bat`**：控制台显示所选解释器与运行日志，GUI 另开一个窗口；
关掉窗口后控制台保留输出并 `pause`，方便回看。

```
[EinsteinGo] locating a Python interpreter with tkinter ...
[EinsteinGo] interpreter : py -3
[EinsteinGo] launching GUI ...
[00:06:52] info  新局 · 人机对弈 · 我方执红 · 难度普通 · seed=633429
```

`.bat` 的两个要点：

1. **必须探测解释器**。本机 `python` → `…\binaries\python\versions\3.13.12\python.exe`
   （3.13.14，**无 tkinter**）；`py -3` → `…\Programs\Python\Python313\python.exe`
   （3.13.15，tkinter 8.6）。脚本依次试 `py -3` / `py -3.13` / `python` / `python3`，
   取第一个能 `import tkinter` 的；全都不行则打印安装指引（去 python.org 装官方版并勾选
   "tcl/tk and IDLE"）。
2. **文件内容必须纯 ASCII**。中文 `rem` 注释会被 cmd 按 OEM 代码页解析成乱码命令
   （实测会报 "'本机' 不是内部或外部命令"），所以注释一律用英文。
   `for` 块在解析阶段就展开 `%VAR%`，因此块内只**写** `PYEXE`、块外才**读**它。
   脚本最后 `chcp 65001` + `PYTHONIOENCODING=utf-8`，让日志里的 `✓ / ✗ / →` 不会
   在 cp936 控制台上抛 `UnicodeEncodeError`。

命令行等价：`py -3 run_ui.py`；`python run_ui.py --self-test` 可在**没有 tkinter** 的
解释器上验证控制器链路（排查环境问题用）。

### 10.2 人机对弈

- 顶部工具栏：`模式`（人机对弈 / 比赛模式）、`我方执`（红 / 蓝）、`难度`（轻松 / 普通 / 认真 → 思考 400/900/1800 ms）、
  `新局`、`掷骰`、`导出棋谱`。
- 进入你的回合会自动掷骰并显示点数；**点自己的棋子 → 高亮合法目标 → 点目标落子**。
  空目标画绿点，可吃的目标用**整格红描边**（不能画中心圆点——会被棋子盖住、也会挡住数字），
  上一步的起点/终点染淡琥珀色，被吃时目标格红环闪三下。
- **两处动画**：骰子是 Canvas 画的点阵，掷出时 0.38 秒内快速换面后停住；
  棋子走动时从起点平滑滑到终点（0.25 秒 ease-out，中段微微放大做出"抬起"感），
  飞行期间起点与终点都留空，由独立的 `fly` 图层独占绘制，避免重影。
- 上一手之后不能走动的己方棋子会**淡显**（深色数字 + 浅底），能走的保持饱满配色。
- 右侧：阶段与骰子、双方剩余时间（走时方加粗）、已出局编号、上一手、AI 决策
  （前三候选的走法 / 访问数 `n` / Q 值，条形长度 = 访问数占首位的比例），底部棋谱。
- 非法操作走棋盘下方的提示条（2.6 秒自动消失，重复时叠 `·+N`），**不弹模态框**；
  终局用面板内结果卡 + 棋盘中央横幅，不锁焦点。

### 10.3 比赛模式

切到 `比赛模式` 后棋盘下方出现对账面板，有**两条等价的路**可以替对方落子：

**A. 直接在棋盘上代走（默认，不用打字）**

1. 对方掷出点数后，点面板里的 `对方骰值` 数字按钮（1–6）——这就是"对方报了几点"；
   懒得问就点`随机`。选错了可以直接改（未走子前随时覆盖）。
2. 棋盘上对方的棋子立刻变成可点状态：**点对方棋子 → 点高亮目标**即可。
   这一步和人类走自己的棋完全一样的交互，只是作用在对方阵营。
3. 落子时程序把这一手拼成 `3c1d1@3` 这样的文本，**仍然走下面那套六层对账**，
   所以"棋盘代走"与"粘贴走法"在引擎眼里是同一件事，校验强度不打折。

**B. 粘贴走法（远程对局/复盘用）**

1. 把对手的走法粘进输入框（`4a1b2@3`，`@骰值` 可省——省了会从本地反查），点`校验`（回车亦可）；
2. 面板逐行显示 **L0 前置 → L1 几何 → L2 快照 → L3 执行 → L4 走后对账 → L5 哈希链**
   的通过/失败/跳过状态，失败时下方打印具体是哪一项、哪一格、哈希从多少变到多少；
3. 校验通过则复制成功，我方 AI 立刻接手落子，`我方走法` 一栏给出 `to_compact()` 文本，
   点`复制`直接进剪贴板，回给对手。

> 两条路共用 `_apply_remote()` 这一个落地点：棋盘代走先 `mv.to_compact()` 再进同步层，
> 因此"复制走法前后状态一致"的保证对两种输入方式都成立（`test_match_board_control_commit_runs_six_layers`）。
> 对方回合并未设定骰值时点棋子，会提示「先选对方骰值（1–6），再点对方棋子代走」。

面板里的"通过"是引擎真跑出来的 `VerifyReport`，不是前端拼的文案——和 CLI 的
`apply_remote_move` 完全同一条路径。

### 10.4 界面层的三条硬约束

| 约束 | 原因 | 守门测试 |
|---|---|---|
| 纯逻辑层**不许 import tkinter** | pytest 跑在无 tkinter 的解释器上，一旦污染整批测试会崩 | `test_gui_import_guard.py`（子进程断言 `'tkinter' not in sys.modules`） |
| 非法走法**绝不进 `session.play()`** | `play()` 先 `clock.stop_turn()` 再校验，非法走法会让本回合时钟提前停走且保留骰值 = 白送无限思考时间 | `test_commit_illegal_target_does_not_touch_clock` |
| worker 线程**只拿不可变快照** | tkinter 控件与 `GameSession` 只归主线程；跨线程碰控件会随机崩溃且无 traceback | `poll()` 的 token 校验 + `test_new_game_cancels_running_search` |

MCTS 在后台线程里跑（`Thread` + `Queue` + `queue.Queue` 回收），主线程每 30 ms `poll()` 落子、
每 200 ms `tick()` 检查旗倒；`mcts.choose_move(..., cancel=Event)` 让"思考中点新局/关窗"
能在一次模拟内退出（引擎为此新增一个可选关键字参数，不传则行为不变）。

### 10.5 测试与冒烟

```
python -m pytest                     # 259 个用例（含 87 个界面层用例，零 tkinter 依赖）
python -m pytest -m slow             # 自对弈基准用例
py -3 scripts/gui_smoke.py           # 真实开窗冒烟（有 tkinter 的解释器）
```

`gui_smoke.py` 断言 canvas 上 item 数量、`piece`/`bg`/`hl` 三个 tag 非空、飞行动画建出
2 个 `fly` 图元（棋子块 + 数字）、以及骰子 1–6 每个点数画对 pip 数；没有图形会话时
（Windows 服务 / Session 0）降级为 `SKIP` 并返回 0，不假装通过也不阻塞。

