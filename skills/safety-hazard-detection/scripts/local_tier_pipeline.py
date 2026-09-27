"""Tier 0 / 0.5 / 1 本地分层巡检流水线。

把三个独立的本地组件接成一条链，并按 `tier_budget` 的判据决定是否升级：

  Tier 0    YOLO11n（COCO，GPU）      → person 框、人数
  Tier 0.5  颜色/几何启发式            → PPE 初判 + 置信度（便宜、确定性、可解释）
  升级判据  tier_budget.next_tier      → 决定是否调用 Tier 1
  Tier 1    Qwen3-VL-2B（bf16，GPU）   → 逐人复核，**仅在有争议的帧上调用**

设计要点
--------
* **模型只加载一次**（模块级单例）。VLM 冷启动 3.1s、单帧推理约 14s，
  每帧重载不可接受。
* Tier 0.5 的 confidence 是**色块覆盖率代理值，不是校准概率**。它只用来喂
  分级判据，不能当作「正确的概率」对外表述。
* 无人的帧直接短路返回，**不触发 Tier 1**——这是分层省钱的主要来源。
* 最终结果经 `route.assemble_result` 组装，确保与编排层契约一致。

已知边界（不要粉饰）
--------------------
* Tier 0.5 是颜色/几何启发式，**黄箱子会被判成安全帽**，且对白色着装几乎无召回。
* COCO 检测器没有「防尘帽 / 防静电服」类别，Tier 0 只提供人形框。
* 人数以 Tier 1 为准，但**不宣称精确计数**（实测 YOLO 6 人 vs VLM 5 人，未裁决）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inspection-orchestrator" / "scripts"))

from ppe_color_probe import (  # noqa: E402
    BLUE_COVERALL_RANGES,
    PpeParams,
    _yolo_person_boxes,
    detect_ppe,
    visualize,
)

import route  # noqa: E402
import tier_budget  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
YOLO_WEIGHTS = REPO / "models" / "yolo11n.pt"
VLM_DIR = REPO / "models" / "Qwen3-VL-2B-Instruct"

# 实拍场景为电子厂无尘车间（蓝色防尘帽 + 蓝色防静电服），非工地
SITE_PARAMS = PpeParams(helmet_ranges=BLUE_COVERALL_RANGES, vest_ranges=BLUE_COVERALL_RANGES)

VLM_PROMPT = "画面里有几个人？他们是否都佩戴了防护帽、穿着防护服？逐个说明。"

_vlm_cache: dict[str, Any] = {}


def _load_vlm() -> tuple[Any, Any]:
    """加载本地 VLM，进程内只做一次。"""
    if "model" not in _vlm_cache:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        proc = AutoProcessor.from_pretrained(str(VLM_DIR))
        model = AutoModelForImageTextToText.from_pretrained(
            str(VLM_DIR), dtype=torch.bfloat16, device_map="cuda:0"
        )
        _vlm_cache.update(model=model, processor=proc, load_s=time.perf_counter())
    return _vlm_cache["model"], _vlm_cache["processor"]


def _ask_vlm(image_path: str, prompt: str = VLM_PROMPT) -> tuple[str, float]:
    """向 Tier 1 提一个真问题，返回（原话回答, 耗时秒）。"""
    import torch
    from PIL import Image

    model, proc = _load_vlm()
    img = Image.open(image_path).convert("RGB")
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
    text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[text], images=[img], return_tensors="pt").to(model.device)
    t = time.perf_counter()
    out = model.generate(**inputs, max_new_tokens=400, do_sample=False)
    torch.cuda.synchronize()
    dt = time.perf_counter() - t
    n_in = inputs["input_ids"].shape[1]
    return proc.batch_decode(out[:, n_in:], skip_special_tokens=True)[0], dt


def run_frame(
    image_path: str,
    *,
    text: str = "隐患排查：防尘帽 防静电服 作业",
    legacy_severity: bool = False,
) -> dict[str, Any]:
    """跑完一张图的 Tier 0 → 0.5 → (按需) 1，返回对齐编排层契约的结果。

    Args:
        legacy_severity: **仅供对照演示与回归验证，禁止用于生产。**
            置 True 时重现 v2 修复**之前**的 severity 判定（`conf < REVIEW` → `warning`），
            即「便宜层会冤枉穿戴合规的人」的旧行为。默认 False。
            使用该模式跑出的产物必须标注 `severity_mode: legacy-demo`，
            以免被误当作生产结果引用。
    """
    calls = {"tier0": 0, "tier0_5": 0, "tier1": 0, "tier2": 0}
    timings: dict[str, float] = {}
    findings: list[dict[str, Any]] = []

    # ---- Tier 0：人形框 ----
    t = time.perf_counter()
    boxes = _yolo_person_boxes(image_path)
    timings["tier0_ms"] = (time.perf_counter() - t) * 1000
    calls["tier0"] = 1

    # ---- 短路：无人的帧不进入 Tier 0.5，也不触发任何升级 ----
    # 这是**设计使然，不是碰巧**：判定链的顺序是「Tier 0 先说有没有人，
    # 有人才谈 PPE」。画面里没有人 ⇒ 不存在 PPE 合规问题 ⇒ 无可升级的结论。
    # 依据 escalation-policy.md §2：升级由「置信度临界 / 冲突 / 需自然语言描述」
    # 触发，三者都以「存在一个待判定的结论」为前提；无人的帧不产生 findings，
    # 因此 next_tier 根本不会被调用（下面 findings 为空即为证）。
    # 这条短路是分层省钱的唯一确定性来源，且完全由输入决定，可复现。
    if not boxes:
        timings["total_ms"] = (time.perf_counter() - t) * 1000
        timings["short_circuit"] = "no_person: 未进入 Tier 0.5，未调用 Tier 1"
        return _assemble(image_path, text, findings, calls, timings, vlm_answer=None)

    # ---- Tier 0.5：颜色/几何启发式 ----
    t = time.perf_counter()
    img = cv2.imread(image_path)
    ppe = detect_ppe(img, boxes, SITE_PARAMS)
    timings["tier0_5_ms"] = (time.perf_counter() - t) * 1000
    calls["tier0_5"] = 1

    by_person: dict[int, dict[str, float]] = {}
    for h in ppe.hits:
        by_person.setdefault(h.person_index, {})[h.kind] = h.zone_coverage

    needs_review = False
    for i, box in enumerate(boxes):
        got = by_person.get(i, {})
        # 置信度代理：取最弱一环的覆盖率。缺项记 0——「没找到」就是没有把握。
        # 注意 0 的含义是「本层没有证据」，**不是**「该人员未佩戴」。
        conf = round(min(got.get("helmet", 0.0), got.get("vest", 0.0)), 4)
        uncertain = conf < tier_budget.ACCEPT_CONFIDENCE
        needs_review = needs_review or uncertain

        # severity 与升级判据**共用同一个阈值** tier_budget.ACCEPT_CONFIDENCE（0.75）。
        #
        # 为什么必须统一：若 severity 另立一套规则（例如「找到就给 info」），
        # 系统里就会同时存在两套阈值，**它们迟早漂移**——一处改了另一处没改，
        # 行为变得不可解释、不可验证。一条阈值只有一条规则。
        #
        # 为什么 conf=0.15 不能算 info：本层只有 15% 的把握。
        # 说 info 等于「没问题、不用管」。安全场景里**假安心与假指控同样危险**：
        # 假指控冤枉一个合规的人；**假安心会放走一个真的违规的人**——
        # 而后者才是这套系统存在的意义。
        #
        # 由此得出本层的定位，记住这句话：
        #   **便宜层不下最终结论，它的职责是「决定要不要叫贵的层」，不是宣布结果。**
        # 所以「便宜层几乎永远不出 info」不是 bug，而是对的事实。
        #
        # 本层的能力边界同样是**单向**的：能看到蓝色才说明「有」，
        # 看不到蓝色什么也说明不了——它本来就看不见白色着装
        # （实测白色掩膜 11.7% 覆盖率、17 个噪声块，墙面与机柜全在其中，
        #  对白色人员的召回为 0）。「没找到」不构成「未佩戴」的证据。
        # 故本层**绝不允许**输出 warning / critical —— 除非 Tier 1 确认。
        if legacy_severity:
            # 【仅供对照演示与回归验证，禁止用于生产】
            # v2 修复前的旧规则：只看置信度的落点，忽略「本层根本没有正面证据」这一事实。
            # 后果：对白色着装（本层召回为 0）的合规人员输出 warning —— 冤枉穿戴合规的人。
            severity = "warning" if conf < tier_budget.REVIEW_CONFIDENCE else "info"
        else:
            severity = "info" if conf >= tier_budget.ACCEPT_CONFIDENCE else "uncertain"

        findings.append({
            "kind": "ppe_compliance",
            "tier": 0,
            "person_index": i,
            "box": [int(v) for v in box],
            "cap_found": "helmet" in got,
            "coverall_found": "vest" in got,
            "confidence": conf,
            "uncertain": uncertain,
            "severity": severity,
            "severity_basis": f"conf={conf} vs ACCEPT={tier_budget.ACCEPT_CONFIDENCE}",
            "severity_rule": (
                "【legacy-demo】v2 修复前的旧规则：conf < REVIEW 即 warning"
                if legacy_severity
                else "tier0.5 与升级判据共用 ACCEPT_CONFIDENCE；低于它一律 uncertain，不下最终结论"
            ),
            "source": "safety-hazard-detection",
            "source_skill": "safety-hazard-detection",
        })

    # ---- 升级判据 ----
    weakest = min(f["confidence"] for f in findings)
    nxt = tier_budget.next_tier(0, weakest)
    allowed = tier_budget.should_escalate_to_cloud(
        nxt - 1, weakest, tier_budget.BudgetState(), cloud_authorized=False
    )
    timings["weakest_conf"] = weakest
    timings["next_tier"] = nxt
    timings["cloud_allowed"] = allowed

    # ---- Tier 1：仅在需要复核时调用一次（帧级，不是人级）----
    vlm_answer = None
    if needs_review and nxt >= 1:
        t = time.perf_counter()
        vlm_answer, gen_s = _ask_vlm(image_path)
        timings["tier1_s"] = gen_s
        calls["tier1"] = 1
        cv2.imwrite(
            str(Path(image_path).parent / "annotated" / (Path(image_path).stem + "_tier05.jpg")),
            visualize(img, ppe, boxes),
        )

    timings["total_ms"] = sum(v for k, v in timings.items() if k.endswith("_ms"))
    return _assemble(image_path, text, findings, calls, timings, vlm_answer)


def _assemble(
    image_path: str, text: str, findings: list[dict[str, Any]],
    calls: dict[str, int], timings: dict[str, Any], vlm_answer: str | None,
) -> dict[str, Any]:
    """走 route 的正规入口组装，保证契约一致。"""
    payload = {"frames": [image_path], "text": text, "site": "电子厂车间（实拍）"}
    inp = route.normalize_input(payload)
    decisions = route.enforce_safety_boundary(route.plan_routes(inp), inp)
    result = route.assemble_result(inp, decisions, findings)
    result["tier_calls"] = calls
    result["timings"] = timings
    result["tier1_answer"] = vlm_answer
    # 云端未授权时 route 会把 tier 2 压回本地，这里显式记下实际未走 Tier 2
    result["tier2_used"] = calls["tier2"] > 0
    # disclaimers 由 route.assemble_result 提供且必须逐字保留（它的单一来源是
    # inspection-report/references/output-schema.md §4），此处不得删改
    return result


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Tier 0/0.5/1 本地分层流水线。每次运行把**原始产物**落盘到 models/runs/，"
                    "并向 docs/local_tier_variance.jsonl **只追加**一条方差记录（不覆盖历史）。"
    )
    ap.add_argument("--runs", type=int, default=1, help="重复运行次数，用于量墙钟波动")
    ap.add_argument("--tag", default=None, help="本次运行标签，默认用 UTC 时间戳")
    ap.add_argument(
        "--legacy-severity",
        action="store_true",
        help="【仅供对照演示与回归验证，禁止用于生产】重现 v2 修复前的 severity 判定"
             "（conf < REVIEW 即 warning），即「便宜层冤枉穿戴合规人员」的旧行为。默认关闭。",
    )
    args = ap.parse_args()

    tag = args.tag or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    mode = "legacy-demo" if args.legacy_severity else "v2"
    if args.legacy_severity:
        print("!" * 72)
        print("!! --legacy-severity 已启用：正在重现 v2 修复**之前**的旧行为。")
        print("!! 仅供对照演示与回归验证，本模式产物不得作为生产结果引用。")
        print("!" * 72)

    photos = sorted((REPO / "assets" / "real_photos").glob("*.jpg"))
    (REPO / "assets" / "real_photos" / "annotated").mkdir(exist_ok=True)
    (REPO / "models" / "runs").mkdir(parents=True, exist_ok=True)

    for run_i in range(1, args.runs + 1):
        out = []
        for p in photos:
            t = time.perf_counter()
            r = run_frame(str(p), legacy_severity=args.legacy_severity)
            r["wall_clock_s"] = round(time.perf_counter() - t, 2)
            r["severity_mode"] = mode
            out.append(r)
            print("[%s run%d] %-44s %6.2fs  tier_calls=%s  findings=%d"
                  % (tag, run_i, Path(p).name[:44], r["wall_clock_s"], r["tier_calls"],
                     len(r["findings"])))
            for f in r["findings"]:
                print("        person#%s conf=%.3f uncertain=%s sev=%s cap=%s coverall=%s"
                      % (f["person_index"], f["confidence"], f["uncertain"], f["severity"],
                         f["cap_found"], f["coverall_found"]))

        tot = {k: sum(r["tier_calls"][k] for r in out)
               for k in ("tier0", "tier0_5", "tier1", "tier2")}
        total_s = round(sum(r["wall_clock_s"] for r in out), 2)

        # 逐次运行的**原始产物**：每次一个文件，不覆盖，便于回溯与复核
        (REPO / "models" / "runs" / ("%s-run%d.json" % (tag, run_i))).write_text(
            json.dumps({
                "tag": tag, "run": run_i, "severity_mode": mode,
                "wall_clock_total_s": total_s, "tier_calls_total": tot, "results": out,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 方差台账：**只追加**。新旧数值并列留存，绝不套用旧数覆盖。
        with (REPO / "docs" / "local_tier_variance.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tag": tag, "run": run_i, "severity_mode": mode,
                "wall_clock_total_s": total_s, "tier_calls_total": tot,
                "per_photo_wall_s": [r["wall_clock_s"] for r in out],
                "per_photo_findings": [len(r["findings"]) for r in out],
            }, ensure_ascii=False) + "\n")

        if not args.legacy_severity:
            # 可引用的稳定汇总：只由**非 legacy** 运行写入，避免演示模式污染对外数字
            metrics = {
                "source": "skills/safety-hazard-detection/scripts/local_tier_pipeline.py",
                "photos": [Path(p).name for p in photos],
                "tier_calls_total": tot,
                "per_photo": [
                    {
                        "file": Path(p).name,
                        "tier_calls": r["tier_calls"],
                        "wall_clock_s": r["wall_clock_s"],
                        "n_findings": len(r["findings"]),
                        "next_tier": r["timings"].get("next_tier"),
                        "short_circuit": r["timings"].get("short_circuit"),
                    }
                    for p, r in zip(photos, out)
                ],
                "wall_clock_total_s": total_s,
                "tier2_used": any(r["tier2_used"] for r in out),
                "note": "Tier 2 未授权（cloud_authorized=False），route.enforce_safety_boundary 会将其压回本地；实测 tier2 调用为 0。"
                        "墙钟时间为**单次点测**，波动范围见 docs/local_tier_variance.jsonl。",
            }
            (REPO / "docs" / "local_tier_metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        print("TOTAL tier_calls:", tot, "| 端到端合计 %.2fs" % total_s)

    print("落盘: models/runs/%s-run*.json  +  docs/local_tier_variance.jsonl（只追加）" % tag)


if __name__ == "__main__":
    main()
