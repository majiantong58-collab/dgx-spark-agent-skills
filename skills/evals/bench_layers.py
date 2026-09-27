"""逐层基准测试：Tier 0 / 0.5 / 1 各自单独计时与显存。

**每层必须独立进程运行**——同进程会让三层共占显存，并互相污染冷启动与模型加载耗时。
本脚本每次调用产出**一个进程的一份样本**（1 个冷启动 + N 个稳态），
由外层 bash 重复调用后聚合出区间（见 docs/local_tier_benchmark.json）。

口径定义（写死，避免各文档各写各的）
------------------------------------
* `cold_start_s`   — 从**进程启动**（本模块 import 时刻）到该层**首次产出结果**。
                     含解释器启动、import、CUDA 初始化、模型加载、首次推理。
* `steady_state_ms`— **模型已加载后**单次调用的墙钟。与冷启动差好几个数量级，
                     故两者必须分列，不可合成一个数。
* `vram_*`         — 单位 MiB（1024^2 字节）。纯 CPU 层为 null（**不填 0**）。
  - `after_load`   — 模型加载完成后的已分配显存
  - `peak`         — 稳态循环期间 `reset_peak_memory_stats` 后的峰值
  - `after`        — **推理全部结束后**的已分配显存（证明是否持续增长，即能否长跑）

输出：stdout 一行 JSON；同时写 `skills/evals/bench_raw_<layer>.json`（可用 `--out-dir` 改）。

⚠️ 前置条件（**权重不入库，脚本入库**）
--------------------------------------
本脚本**不能直接跑**，需先准备两类权重到 `models/` 下（该目录已被 `.gitignore` 排除，
单文件最大 4 GB，超 GitHub 100 MB 上限，故不入库）：

    models/yolo11n.pt                  5.6 MB   Tier 0
    models/Qwen3-VL-2B-Instruct/       4.3 GB   Tier 1（13 个文件）

获取方式见 `docs/DELIVERY.md` 的部署说明，或直接跑仓库内的下载脚本
`scripts/fetch_ms.sh`（ModelScope 通道，实测约 30 MB/s，推荐）。

⚠️ 前置条件之二：**测试图也不入库**
------------------------------------
本脚本默认的测试图是 `assets/real_photos/0df3783c8f95cdb8ec50264df1216167.jpg`
（1280×960，6 人实拍）。该目录含**可辨认的真实工人人脸，当事人未同意公开发布**，
故被 `.gitignore` 排除，**克隆后不存在**。

因此：**下游无法逐位复现本文件记录的数值**，只能复现**方法与口径**。
要跑本脚本，请任选其一：
  * 用 `--photo <你的图>` 指定自己的工业场景图；或
  * 自行放一张同尺寸（1280×960）的车间照片到上述路径。
`docs/local_tier_benchmark.json` 里的数字是在**上面那张图**上测得的，换图后
冷启动耗时可比、稳态耗时会随图像内容与 token 数变化。

**必须在仓库根目录执行**，否则相对路径解析会失败。
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

T_START = time.perf_counter()  # 进程启动基准点，必须放在所有重 import 之前

# 本文件位于 skills/evals/，故仓库根是 parents[2]
REPO = Path(__file__).resolve().parents[2]
SELF_DIR = Path(__file__).resolve().parent

PHOTO = REPO / "assets" / "real_photos" / "0df3783c8f95cdb8ec50264df1216167.jpg"
YOLO_W = REPO / "models" / "yolo11n.pt"
VLM_DIR = REPO / "models" / "Qwen3-VL-2B-Instruct"
WARM_N = 5

MIB = 1024 * 1024


def _mib(x: float) -> float:
    return round(x / MIB, 1)


def _env() -> dict[str, object]:
    import torch

    props = torch.cuda.get_device_properties(0)
    return {
        "machine": f"{platform.machine()} / {platform.system()} {platform.release()}",
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability()),
        "vram_total_mb": _mib(props.total_memory),
        "torch": torch.__version__,
        "cuda_arch_list": torch.cuda.get_arch_list(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def bench_tier0() -> dict:
    import torch
    from ultralytics import YOLO

    model = YOLO(str(YOLO_W))
    torch.cuda.synchronize()
    ms = model(str(PHOTO), device=0, verbose=False)  # 首次 → 决定冷启动
    torch.cuda.synchronize()
    cold = time.perf_counter() - T_START
    vram_after_load = _mib(torch.cuda.memory_allocated())

    torch.cuda.reset_peak_memory_stats()
    steady = []
    for _ in range(WARM_N):
        torch.cuda.synchronize()
        t = time.perf_counter()
        model(str(PHOTO), device=0, verbose=False)
        torch.cuda.synchronize()
        steady.append(round((time.perf_counter() - t) * 1000, 2))

    return {
        "layer": "tier0",
        "component": "YOLO11n (COCO person 检测, GPU)",
        "cold_start_s": round(cold, 3),
        "steady_state_ms": steady,
        "vram_after_load_mb": vram_after_load,
        "vram_peak_mb": _mib(torch.cuda.max_memory_allocated()),
        "vram_after_mb": _mib(torch.cuda.memory_allocated()),
        "model_file_bytes": YOLO_W.stat().st_size,
        "sanity": {"detections_first_call": len(ms[0].boxes)},
    }


def bench_tier0_5() -> dict:
    sys.path.insert(0, str(REPO / "skills" / "safety-hazard-detection" / "scripts"))
    import cv2

    from ppe_color_probe import BLUE_COVERALL_RANGES, PpeParams, detect_ppe

    params = PpeParams(helmet_ranges=BLUE_COVERALL_RANGES, vest_ranges=BLUE_COVERALL_RANGES)
    img = cv2.imread(str(PHOTO))
    boxes = [(908, 0, 1122, 557), (25, 129, 396, 910), (856, 102, 921, 325)]
    res = detect_ppe(img, boxes, params)  # 首次 → 决定冷启动
    cold = time.perf_counter() - T_START

    steady = []
    for _ in range(WARM_N):
        t = time.perf_counter()
        detect_ppe(img, boxes, params)
        steady.append(round((time.perf_counter() - t) * 1000, 2))

    return {
        "layer": "tier0_5",
        "component": "颜色/几何启发式 (CPU, OpenCV+numpy, 无模型)",
        "cold_start_s": round(cold, 3),
        "steady_state_ms": steady,
        "vram_after_load_mb": None,
        "vram_peak_mb": None,
        "vram_after_mb": None,
        "model_file_bytes": 0,
        "sanity": {"hits_first_call": len(res.hits)},
        "notes": "纯 CPU，不占显存，故 vram_* 一律 null（不估算）。"
                 "hits 数为本次固定传入 3 个人形框所得，非召回率。",
    }


def bench_tier1() -> dict:
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor

    proc = AutoProcessor.from_pretrained(str(VLM_DIR))
    model = AutoModelForImageTextToText.from_pretrained(
        str(VLM_DIR), dtype=torch.bfloat16, device_map="cuda:0"
    )
    vram_after_load = _mib(torch.cuda.memory_allocated())

    img = Image.open(PHOTO).convert("RGB")
    msgs = [{"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": "画面里有几个人？是否都戴了防护帽、穿了防护服？"}]}]
    text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[text], images=[img], return_tensors="pt").to(model.device)

    out = model.generate(**inputs, max_new_tokens=200, do_sample=False)  # 首次 → 冷启动
    torch.cuda.synchronize()
    cold = time.perf_counter() - T_START

    torch.cuda.reset_peak_memory_stats()
    steady, n_tok = [], []
    for _ in range(WARM_N):
        torch.cuda.synchronize()
        t = time.perf_counter()
        o = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        torch.cuda.synchronize()
        steady.append(round((time.perf_counter() - t) * 1000, 2))
        n_tok.append(int(o.shape[1] - inputs["input_ids"].shape[1]))

    size = sum(f.stat().st_size for f in VLM_DIR.rglob("*") if f.is_file())
    return {
        "layer": "tier1",
        "component": "Qwen3-VL-2B-Instruct bf16 (本地 VLM, GPU)",
        "cold_start_s": round(cold, 3),
        "steady_state_ms": steady,
        "vram_after_load_mb": vram_after_load,
        "vram_peak_mb": _mib(torch.cuda.max_memory_allocated()),
        "vram_after_mb": _mib(torch.cuda.memory_allocated()),
        "model_dir_bytes": size,
        "sanity": {
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "new_tokens_per_run": n_tok,
            "max_new_tokens": 200,
        },
    }


LAYERS = {"tier0": bench_tier0, "tier0_5": bench_tier0_5, "tier1": bench_tier1}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layer", required=True, choices=sorted(LAYERS))
    ap.add_argument("--out-dir", default=str(SELF_DIR),
                    help="原始样本输出目录，默认与脚本同目录（skills/evals/）")
    ap.add_argument("--photo", default=None,
                    help="测试图路径。默认用 assets/real_photos/ 下那张实拍图，"
                         "但该目录因隐私不入库、克隆后不存在——请用本参数指定自备图片")
    args = ap.parse_args()

    global PHOTO
    if args.photo:
        PHOTO = Path(args.photo).resolve()
    if not PHOTO.is_file():
        raise SystemExit(
            f"测试图不存在：{PHOTO}\n"
            "该图因含真实工人人脸、未获公开发布授权而不入库（assets/real_photos/ 被 .gitignore 排除）。\n"
            "请用 --photo 指定自备的工业场景图片后重跑。"
        )

    try:
        env = _env()
    except Exception as exc:  # noqa: BLE001
        env = {"env_error": f"{type(exc).__name__}: {exc}"}

    result = LAYERS[args.layer]()
    payload = {
        "env": env,
        "result": result,
        "warm_n_per_process": WARM_N,
        "cold_start_definition": "进程启动(模块 import 时刻) → 该层首次产出结果",
        "vram_unit": "MiB (1024^2 bytes)",
    }
    print(json.dumps(payload, ensure_ascii=False))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"bench_raw_{args.layer}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
