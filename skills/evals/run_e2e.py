"""A4 端到端最小通路 + token 采集。

链路：路由 → 隐患识别（StepFun 视觉）→ 报告组装 → Markdown 渲染。

用法：
    .venv/Scripts/python.exe skills/evals/run_e2e.py [--offline]

`--offline` 只跑不依赖网络的合成图生成与结构自检，不产生 API 调用。

产出（`--offline` 时一律改写 `offline-*` 前缀，**绝不覆盖真实产物**）：
    skills/evals/assets/*.png            测试图（程序合成，来源见 a4-baseline.json）
    skills/evals/results/a4-sample-report.md
    skills/evals/results/a4-baseline.json

🔴 凭据只从仓库根 .env 读，绝不进入本文件的输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).resolve().parent / "assets"
RESULTS = Path(__file__).resolve().parent / "results"

for sub in ("safety-hazard-detection", "inspection-orchestrator", "inspection-report"):
    sys.path.insert(0, str(ROOT / "skills" / sub / "scripts"))

import dedupe_tracks as dt  # noqa: E402
import detect_hazards as dh  # noqa: E402
import route as rt  # noqa: E402
from assemble_sections import build_report  # noqa: E402
from render_markdown import render  # noqa: E402

# 40 条用例 × 4 臂 —— A5 对照评测的调用总量口径（comparison-design.md §1/§2）
EVAL_CASES = 40
EVAL_ARMS = 4


def synth_workshop(path: Path, *, size: tuple[int, int] = (1280, 720)) -> Path:
    """程序合成一张车间场景图（**非真实照片**）。

    刻意画入两类可判定信号：通道被料箱占压、一名作业人员未戴安全帽。

    ⚠️ 本函数产出的图像**不是真实工业照片**，不得作为识别准确率的证据，
    只用于打通链路与采集 token 基线。真实素材需另取可商用图源并登记授权。
    """
    from PIL import Image, ImageDraw

    w, h = size
    img = Image.new("RGB", size, (58, 62, 68))
    d = ImageDraw.Draw(img)

    # 背景墙 + 地平线
    d.rectangle([0, 0, w, int(h * 0.55)], fill=(74, 78, 84))
    d.rectangle([0, int(h * 0.55), w, h], fill=(120, 118, 112))
    for x in range(0, w, 160):  # 墙面板缝
        d.line([(x, 0), (x, int(h * 0.55))], fill=(66, 70, 76), width=2)

    # 右侧储罐 + 罐底积液（EQUIP-LEAK 信号）
    d.rectangle([w - 330, 150, w - 150, 430], fill=(150, 152, 156), outline=(96, 98, 102), width=3)
    d.ellipse([w - 340, 120, w - 140, 180], fill=(168, 170, 174), outline=(96, 98, 102), width=3)
    d.ellipse([w - 300, 430, w - 120, 470], fill=(46, 52, 40))

    # 地面通道黄黑警示带
    for i in range(0, w, 90):
        d.polygon(
            [(i, 560), (i + 45, 560), (i - 20, 610), (i - 65, 610)],
            fill=(214, 176, 40) if (i // 90) % 2 == 0 else (40, 40, 42),
        )

    # 通道上的料箱堆（ACCESS-BLOCKED 信号）
    for idx, (bx, by, bw, bh) in enumerate([(150, 470, 120, 90), (280, 470, 120, 90), (215, 380, 120, 90)]):
        shade = 142 - idx * 10
        d.rectangle([bx, by, bx + bw, by + bh], fill=(shade, 108, 62), outline=(92, 66, 36), width=3)
        d.line([(bx, by + bh // 2), (bx + bw, by + bh // 2)], fill=(92, 66, 36), width=2)

    # 作业人员 A：**未戴安全帽**（裸露头部圆）
    ax, ay = 700, 360
    d.rectangle([ax, ay + 46, ax + 44, ay + 150], fill=(38, 76, 150))       # 躯干
    d.rectangle([ax + 4, ay + 150, ax + 18, ay + 215], fill=(52, 54, 58))   # 左腿
    d.rectangle([ax + 26, ay + 150, ax + 40, ay + 215], fill=(52, 54, 58))  # 右腿
    d.ellipse([ax + 6, ay, ax + 40, ay + 38], fill=(226, 186, 152))         # 头部，安全帽缺失

    # 作业人员 B：**戴安全帽**（对照组）
    bx2, by2 = 880, 372
    d.rectangle([bx2, by2 + 46, bx2 + 40, by2 + 145], fill=(150, 82, 40))
    d.rectangle([bx2 + 4, by2 + 145, bx2 + 18, by2 + 205], fill=(52, 54, 58))
    d.rectangle([bx2 + 22, by2 + 145, bx2 + 36, by2 + 205], fill=(52, 54, 58))
    d.ellipse([bx2 + 6, by2 + 8, bx2 + 34, by2 + 36], fill=(226, 186, 152))
    d.pieslice([bx2, by2 - 2, bx2 + 40, by2 + 38], 180, 360, fill=(240, 200, 40))  # 安全帽

    # 地面散落物料（HOUSEKEEPING 信号）
    for sx, sy, sr in [(470, 630, 14), (520, 650, 9), (600, 640, 11), (960, 645, 13)]:
        d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(96, 88, 72))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def _aggregate(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """单次均值等汇总——**只统计真实成功的调用**，失败调用单列。"""
    ok = [c for c in calls if c["ok"]]
    n = len(ok) or 1
    return {
        "n_calls": len(calls),
        "n_ok": len(ok),
        "n_failed": len(calls) - len(ok),
        "prompt_tokens_mean": round(sum(c["prompt_tokens"] for c in ok) / n, 2),
        "completion_tokens_mean": round(sum(c["completion_tokens"] for c in ok) / n, 2),
        "total_tokens_mean": round(sum(c["total_tokens"] for c in ok) / n, 2),
        "total_tokens_sum": sum(c["total_tokens"] for c in ok),
        "image_bytes_mean": round(sum(c["image_bytes"] for c in ok) / n, 1),
        "base64_chars_mean": round(sum(c["base64_chars"] for c in ok) / n, 1),
        "latency_ms_mean": round(sum(c["latency_ms"] for c in ok) / n, 1),
        "latency_ms_max": max((c["latency_ms"] for c in ok), default=0),
    }


def probe_arm_overhead(probe_case: dict[str, Any]) -> list[dict[str, Any]]:
    """真调一次**极短**的文本请求，量出各臂 skill 载荷的 prompt token 开销。

    四臂的外推不能都用同一个数——B/C 臂要背着整份 SKILL.md 与 references 进场。
    这里用 max_tokens 压到下限以最小化成本，只取 prompt_tokens。
    """
    from run_comparison import build_prompt, _chat

    probes: list[dict[str, Any]] = []
    for arm in ("A", "B", "C", "D"):
        payload = build_prompt(probe_case, arm)  # type: ignore[arg-type]
        _, usage, latency = _chat(payload, probe_case["input"], max_tokens=dh.MIN_SAFE_MAX_TOKENS)
        probes.append(
            {"arm": arm, "skill_payload_chars": len(payload), "latency_ms": latency, **usage}
        )
        print(f"      arm {arm}: payload={len(payload)} chars → prompt_tokens={usage['prompt_tokens']}")
    return probes


def _extrapolate(agg: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    """按 40 条用例 × 4 臂 = 160 次调用外推总量。

    每臂的 prompt 开销用 `probe_arm_overhead` 的**实测值**（A 臂最小、B/C 臂最大），
    completion 开销用视觉调用的实测均值——**上界口径**，因为视觉 CoT 明显长于纯文本判定。
    """
    calls_per_arm = EVAL_CASES
    by_arm: dict[str, Any] = {}
    total_prompt = total_completion = 0
    for probe in probes:
        prompt = probe["prompt_tokens"]
        completion = round(agg["completion_tokens_mean"])
        by_arm[probe["arm"]] = {
            "skill_payload_chars": probe["skill_payload_chars"],
            "prompt_tokens_per_call": prompt,
            "completion_tokens_per_call_assumed": completion,
            "calls": calls_per_arm,
            "total_tokens": (prompt + completion) * calls_per_arm,
        }
        total_prompt += prompt * calls_per_arm
        total_completion += completion * calls_per_arm

    calls = EVAL_CASES * EVAL_ARMS
    return {
        "basis": f"{EVAL_CASES} 条用例 × {EVAL_ARMS} 臂 = {calls} 次调用（每用例每臂 1 次）",
        "calls": calls,
        "by_arm": by_arm,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "measured_inputs": {
            "prompt_tokens_per_arm": "实测（probe_arm_overhead，文本探测）",
            "completion_tokens_per_call": (
                f"取视觉调用实测均值 {round(agg['completion_tokens_mean'])}，**上界口径**——"
                "评测用例是文本判定，CoT 应显著短于视觉识别"
            ),
        },
        "caveat": "上界估算；A5 应以真实运行值替换",
        "with_3_runs": (total_prompt + total_completion) * 3,
        "three_runs_note": "comparison-design.md §2 要求每用例重复 ≥3 次时的总量",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A4 端到端最小通路 + token 采集")
    parser.add_argument("--offline", action="store_true", help="不调 API，只跑结构自检")
    parser.add_argument("--no-probe", action="store_true", help="跳过四臂 prompt 开销探测")
    args = parser.parse_args(argv)

    # v2：默认输入改用**真实照片**。
    #
    # 合成插画这条路已被实测证伪：COCO 检测器对扁平矢量图基本无效——
    # 在 synthetic_workshop.png 上它只产出 1 个误检框（`sports ball` 0.378，
    # 打在地面碎屑上），画面里的两个人物**全部漏检**；换仓库内另一张合成图
    # 同样是垃圾输出（`airplane` 0.455 / `traffic light` 0.277）。
    # 同一检测器在真实照片上表现正常（ultralytics 自带 bus.jpg 命中
    # bus 0.94 + person ×4，置信度 0.62~0.89）。
    #
    # 因此合成图**保留不删**（标注为「v1 素材，检测器对其无效」），仅作历史留档，
    # 不再作为默认输入。找不到真实照片时回退到合成图，保证链路仍可跑通。
    _real = sorted((ROOT / "assets" / "real_photos").glob("*.jpg"))
    image = _real[0] if _real else synth_workshop(ASSETS / "synthetic_workshop.png")
    print(f"[1/5] 合成测试图：{image}")

    payload = {
        "site": "合成样张 · 非真实点位",
        "text": "车间照片，帮我看看有没有安全隐患，并出一份巡检报告",
        "cloud_authorized": True,  # Tier 2 需显式授权，否则被安全边界压回本地
        "frames": [str(image)],
    }
    inp = rt.normalize_input(payload)
    decisions = rt.enforce_safety_boundary(rt.plan_routes(inp), inp)
    print(f"[2/5] 路由：{[d.skill for d in decisions]}（tier={[d.tier for d in decisions]}）")

    calls: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    if args.offline:
        print("[3/5] --offline：跳过 StepFun 调用")
    else:
        findings, call = dh.detect_via_cloud(
            image, task_id=inp.task_id, frame_id="frame_0001"
        )
        calls.append({**call.to_dict(), "findings_count": len(findings)})
        print(
            f"[3/5] StepFun ok={call.ok} tokens={call.total_tokens} "
            f"(prompt={call.prompt_tokens} completion={call.completion_tokens}) "
            f"字段={call.answer_field} findings={len(findings)}"
            + (f" err={call.error}" if call.error else "")
        )

    # 去重与合并（safety-hazard-detection SKILL.md 第 5 步）：同一目标重复命中只留一条，
    # 否则报告会重复计数。被合并的条目不丢弃，留痕在幸存条目的 `merged_from` 里。
    # 入参按帧分组——本次只有一帧，故包一层。
    raw_count = len(findings)
    findings = dt.merge_detections([findings])
    if raw_count != len(findings):
        print(
            f"[3b/5] 去重合并：{raw_count} → {len(findings)} 条"
            f"（重复条目留痕于 merged_from：{[m['hit_count'] for m in findings]}）"
        )

    result = rt.assemble_result(inp, decisions, findings)
    built = build_report(result["findings"], meta={**result, "partial": result["partial"]})
    markdown = render(built)
    RESULTS.mkdir(parents=True, exist_ok=True)
    # --offline 是自检路径，产物一律带 offline- 前缀：a4-* 是真实运行证据，
    # 被自检覆盖后无法区分「跑过真调用」与「只跑了离线骨架」（历史 bug，勿回退）。
    prefix = "offline-" if args.offline else "a4-"
    report_path = RESULTS / f"{prefix}sample-report.md"
    report_path.write_text(markdown, encoding="utf-8")
    print(f"[4/5] 报告：{report_path}（items={built['summary']['total']}）")

    probes: list[dict[str, Any]] = []
    if args.offline or args.no_probe:
        print("[4b/5] 跳过四臂 prompt 开销探测")
    else:
        from run_comparison import load_cases

        probe_cases = load_cases([str(ROOT / "skills/*/evals/cases.jsonl")])
        print(f"[4b/5] 四臂 prompt 开销探测（{len(probe_cases)} 条用例中取 1 条）")
        probes.extend(probe_arm_overhead(probe_cases[0]))

    agg = _aggregate(calls)
    ledger = {
        "task": "A4 端到端打通 · token 基线",
        "offline": args.offline,  # True 表示本文件不含真实调用，不可作为基线引用
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": calls[0]["model"] if calls else None,
        "endpoint_host": "api.stepfun.com",
        "task_id": inp.task_id,
        "assets": [
            {
                "file": image.name,
                "width": calls[0]["image_width"] if calls else None,
                "height": calls[0]["image_height"] if calls else None,
                "bytes": calls[0]["image_bytes"] if calls else None,
                "sha256_16": calls[0]["image_sha256"] if calls else None,
                "provenance": "程序合成（Pillow 绘制，非真实照片）",
                "generator": "skills/evals/run_e2e.py::synth_workshop",
                "license": "本仓库自产，无第三方素材权利",
                "usable_as_accuracy_evidence": False,
            }
        ],
        "calls": calls,
        "arm_prompt_probes": probes,
        "aggregate": agg,
        "extrapolation_160": _extrapolate(agg, probes),
        "pipeline": {
            "routes": result["routes"],
            "findings": result["findings"],
            "partial": result["partial"],
            "report_summary": built["summary"],
            "report_path": str(report_path.relative_to(ROOT)),
        },
    }
    out = RESULTS / f"{prefix}baseline.json"
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[5/5] token 基线：{out}")
    return 0 if (args.offline or all(c["ok"] for c in calls)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
