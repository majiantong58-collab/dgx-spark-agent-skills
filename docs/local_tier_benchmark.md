# 本地三层逐层基准测试（人读版）

> **本文件与 `docs/local_tier_benchmark.json` 是逐层性能数字的唯一真值来源。**
> 其他文档（README / DELIVERY / 演示脚本）一律**引用**此处，**不得各写各的**。
> `.md` 的数字与 `.json` **逐字一致**；如有出入，以 `.json` 为准并修正本文件。
>
> 复现：`skills/evals/bench_layers.py`（每层独立进程，重复 3 次）。
> **脚本与原始样本均已入库**；权重不入库（`models/` 被 gitignore），跑前需先按
> `docs/DELIVERY.md` 部署说明或 `scripts/fetch_ms.sh` 准备好权重。

## 元信息

| 字段 | 值 |
|---|---|
| `benchmark_date` | 2026-09-27 |
| **`same_machine_same_round`** | **true**（同一台机、同一轮完成，下游可引用） |
| `machine` | AMD64 / Windows 11 |
| `gpu` | NVIDIA GeForce RTX 5060 Laptop GPU |
| `compute_capability` | [12, 0]（sm_120 Blackwell） |
| `vram_total_mb` | 8150.6 |
| `driver` | 591.91 |
| `torch` | 2.11.0+cu128 |
| `cuda_arch_list` | sm_75 / sm_80 / sm_86 / sm_90 / sm_100 / **sm_120** |
| `python` | 3.12.10 |
| `vram_unit` | MiB (1024^2 bytes) |

**两个时间口径（不可混成一个数——冷启动几秒、稳态几十毫秒，差好几个数量级）**
- `cold_start_s` — **进程启动到首次出结果**，含解释器启动、import、CUDA 初始化、模型加载、首次推理
- `steady_state_ms` — **模型已加载后**单次调用墙钟

所有时间字段均为 **`[min, max]` 区间**，不给单点。三层各自**独立进程**运行，互不干扰显存与加载耗时。

## 三层结果

| 层 | 组件 | `cold_start_s` | `steady_state_ms` | `runs` | 稳态样本数 |
|---|---|---|---|---|---|
| **tier0** | YOLO11n（COCO person 检测, GPU） | **[3.976, 4.147]** | **[14.29, 51.42]** | 3 | 15 |
| **tier0_5** | 颜色/几何启发式（CPU, OpenCV+numpy, 无模型） | **[1.862, 1.894]** | **[16.12, 18.58]** | 3 | 15 |
| **tier1** | Qwen3-VL-2B-Instruct bf16（本地 VLM, GPU） | **[19.362, 20.638]** | **[9046.6, 10603.29]**（≈ 9.05–10.60 s） | 3 | 15 |

## 显存（单位 MiB）

| 层 | `vram_after_load_mb` | `vram_peak_mb` | `vram_after_mb` |
|---|---|---|---|
| **tier0** | 42.1 | **59.8** | 42.1 |
| **tier0_5** | `null` | `null` | `null` |
| **tier1** | 4059.0 | **4546.9** | 4096.3 |

- **`tier0_5` 三个字段一律 `null`**：纯 CPU、零模型，不占显存。**按约定不估算、不填 0。**
- **`vram_after_mb` 是「能否长跑」的证据**：tier0 推理后**完全回落到加载后水平**（42.1）；
  tier1 推理后为 **4096.3**，比加载后的 4059.0 **高 37.3 MiB，未完全回落**
  （PyTorch 分配器缓存所致，非必然泄漏），**长跑前建议加监控**。

## 波动说明（有多少报多少，不掩盖）

1. **tier0 的稳态区间是双峰的，且可解释**：每个进程内**稳态第 1 次调用恒为 ~43–51 ms**，
   第 2 次起落到 **~14–16 ms**。三个进程各自复现（44.08 / 42.78 / 51.42 ms 开头），
   是**进程内首次稳态调用仍受 CUDA 分配器与图预热影响的系统性现象，不是随机离群**。
   **区间已包含该效应，未剔除**——因为它会真实地出现在每个新进程的第一次调用上。
   若只关心完全预热后的值，参考区间为 **[14.29, 17.41]**。
2. **tier0_5 极稳**：15 个样本全落在 [16.12, 18.58]，无预热效应，验证了「纯 CPU 无状态」的预期。
3. **tier1 稳态极差 1556.69 ms**（9046.6–10603.29），相对波动约 **17%**；
   生成长度固定为 **180 tokens**（`max_new_tokens=200`），故波动来自推理本身而非输出长度差异。

## 与早前口头数字的差异（如实并列，不抹平）

| 指标 | 早前对话中的值 | 本次实测 | 差异原因 |
|---|---|---|---|
| tier1 冷启动 | 3.11 s（仅模型加载） | **[19.362, 20.638] s** | **口径不同**：3.11 s 只是 `from_pretrained`；本口径含解释器启动、transformers import 与首次推理 |
| tier1 稳态 | 13.9 s / 261 tokens | **[9046.6, 10603.29] ms** / 180 tokens | **生成长度不同**：早前上限 400、实生成 261；本次上限 200、实生成 180 |
| tier0 稳态 | 10–13 ms | **[14.29, 51.42] ms** | 早前为 3 次乐观样本（且未含每个新进程的首次调用）；本次 15 样本含 n=5 预热门槛 |
| tier0 显存峰值 | 90 MB | **59.8 MiB** | 早前 90 MB 为 `reserved` 口径；本次为 `max_memory_allocated`。**两个口径，不可直接比** |

## 磁盘

本次测量结束时 **C: 剩余 53 G**（924 G 总量，已用 95%）。

## 复现命令

```bash
# 前置 1：权重不入库，需先获取：
#   bash scripts/fetch_ms.sh     （Tier 1，4.3 GB，约 2.5 分钟）
#   bash scripts/fetch_yolo.sh   （Tier 0，5.4 MB）
# 前置 2：测试图不入库（见下方说明），需自备或改用 --photo 指定
mkdir -p /tmp/bench_runs
for L in tier0 tier0_5 tier1; do
  for I in 1 2 3; do
    .venv/Scripts/python.exe skills/evals/bench_layers.py --layer $L \
        --out-dir /tmp/bench_runs > /tmp/bench_runs/$L-$I.json
  done
done
```

> 原始样本 `skills/evals/bench_raw_<layer>.json` 是**证据**，勿覆盖。
> 复跑时请用 `--out-dir` 指到别处（如 `/tmp/bench_runs`），以免冲掉已入库存档的那份。
