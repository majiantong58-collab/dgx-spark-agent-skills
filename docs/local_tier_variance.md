# 本地三层流水线：可引用数字与方差台账

> 准则：**能引用确定性数字就引确定性数字；墙钟时间一律给区间，不给单点。**
> 视频一旦播出数字就固化了——审查询 `docs/local_tier_metrics.json` 对不上，
> 比数字不漂亮严重得多。

## 1. 可以对外引用的数字

### ✅ 首选：`tier_calls`（确定性）

三轮独立重复运行，**完全一致，零波动**：

```
tier0: 3   tier0_5: 2   tier1: 2   tier2: 0
```

这是**输入决定的，不是计时决定的**，可放心引用。落盘于
`docs/local_tier_metrics.json`，原始记录见 `docs/local_tier_variance.jsonl`。

### ✅ 区间：墙钟时间（**不得给单点**）

| 项 | 区间（3 轮实测） |
|---|---|
| 三张照片合计 | **23.11 – 33.68 s** |
| 照片1（6 人，触发 Tier 1） | **14.35 – 25.20 s** |
| 照片2（1 人，触发 Tier 1） | **8.32 – 8.64 s** |
| 照片3（无人，短路） | **0.11 – 0.16 s** |

照片1 的极差达 **1.76×**（14.35 → 25.20 s），**是 Tier 1 单次推理（约 13.9 s）的波动主导的**。
报单点值等于随机挑一个数。

### ✅ 区间：分层加速比（**不要再用「155 倍」「202 倍」这类单点**）

照片3 短路（0.11–0.16 s、0 次 Tier 1）vs 照片1（14.35–25.20 s、1 次 Tier 1）：

> **加速比区间 ≈ 90× – 229×**

引用时写区间。**更稳的表述是避开比值，直接给两个绝对量**：
「无人的帧 0.1 秒、零 Tier 1 调用；有人的帧 14–25 秒、一次 Tier 1 调用」。

### ✅ 单点可用（硬件与模型加载，重复测得稳定）

```
capability (12, 0) · torch 2.11.0+cu128 · arch_list 含 sm_120
VLM 冷启动 3.11 s · 显存 allocated 3.96 GB · 峰值 4.44 GB
Tier 1 单次推理 13.90 s / 261 tokens / 18.8 tok/s
```

## 2. 方差台账（新旧并列，**不套用旧数**）

机器可读版：`docs/local_tier_variance.jsonl`（**只追加，不覆盖**）。
逐次运行的完整原始产物：`models/runs/<tag>-run<N>.json`。

| # | 时间 | 来源文件 | 照片1 | 照片2 | 照片3 | 合计 |
|---|---|---|---|---|---|---|
| ① | 14:1x 首轮 | ⚠️ **已被覆盖，不在盘上** | 21.76 | 9.18 | 0.14 | 31.08 |
| ② | 14:1x 假指控修复后 | ⚠️ **已被覆盖，不在盘上** | 21.96 | 7.75 | 0.13 | 29.84 |
| ③ | 14:20 阈值统一后 | `models/pipeline_results.json`（旧 main 最后一次写入，已停止更新） | 28.34 | 9.30 | 0.14 | 37.78 |
| ④ | 本轮 run1 | `models/runs/v2a-run1.json` | 25.20 | 8.32 | 0.16 | **33.68** |
| ⑤ | 本轮 run2 | `models/runs/v2a-run2.json` | 14.97 | 8.59 | 0.11 | **23.67** |
| ⑥ | 本轮 run3 | `models/runs/v2a-run3.json` | 14.35 | 8.64 | 0.12 | **23.11** |
| ⑦ | 本轮 legacy 对照 | `models/runs/legacydemo-run1.json` | 25.73 | 9.83 | 0.15 | 35.71 |

**① 与 ② 不在盘上**：它们由旧版 `main()` 写入 `models/pipeline_results.json`，
被后续运行**覆盖**了，现已无法复核——**只能作为对话记录，不得引用**。
这正是本次改造 `main()` 为「逐次落盘 + 只追加台账」的原因。

**七个样本的墙钟全部落在 23.11 – 37.78 s**，`tier_calls` 七次全部相同。

## 3. 演示用的 `--legacy-severity` 开关（已实现）

演示需要一镜讲「**修复前会冤枉人，修复后不会**」，但旧行为已被修掉、无法重演。
现提供：

```bash
.venv/Scripts/python.exe skills/safety-hazard-detection/scripts/local_tier_pipeline.py \
    --legacy-severity --runs 1 --tag legacydemo
```

- **默认关闭**（`action="store_true"`）。
- 帮助文本与注释均写明**「仅供对照演示与回归验证，禁止用于生产」**。
- 启用时终端打印醒目警告框，产物打上 `"severity_mode": "legacy-demo"`。
- **legacy 运行不写 `docs/local_tier_metrics.json`**，防止演示模式污染对外数字。

**实测复现一致**：legacy 模式下照片1 的 `person#0/#2/#3` 回到 `warning`
（与修复前记录**逐条一致**），照片2 的 `person#0` 亦为 `warning`；
正常模式下同一批人全部为 `uncertain`。**这一镜现在可以现场跑出对比。**

## 4. 标注图版本结论

**`assets/real_photos/annotated/ppe_photo1_blue.jpg` 是「假指控修复之前」的产物，且它无法用于展示该修复。**

**判据一（时间戳）**：该图生成于 **14:13:00**，而 severity 修复落在
`local_tier_pipeline.py` 的 **14:19:37** —— 早 6.5 分钟，确属修复前。

**判据二（更关键）**：`ppe_color_probe.visualize()` **根本不绘制 severity**——
它只画 `f"{h.kind} {h.zone_coverage:.0%}"`（如 `helmet 46%`）。
因此**这批标注图上不存在 warning 标记**，你给的那条判据（「看有没有 warning 标记」）
在这批图上不适用。**它们既不能证明修复前、也不能证明修复后。**

**结论与建议**：
- 该图可用作「Tier 0.5 颜色掩膜长什么样」的可视化说明（它的本意正是这个）；
- **不可**用作「假指控修复」的证据——那一镜请改用 `--legacy-severity` 现场跑对比，
  或引用本文 §3 的修复前/后对照表；
- 若要静态图，需在 `visualize()` 中补画 severity 才能满足该用途（**本轮未改**）。

## 5. 复核命令

```bash
# 全量台账（只追加）
cat docs/local_tier_variance.jsonl
# 逐次原始产物
ls models/runs/
# 证据文件未被篡改
md5sum -c <baseline>.md5
```
