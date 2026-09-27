"""对照评测执行器。

用法（见 comparison-design.md §5）：
    py -3.12 skills/evals/run_comparison.py --arm B \
        --cases skills/*/evals/cases.jsonl --out skills/evals/results/B.json
    py -3.12 skills/evals/run_comparison.py --report skills/evals/results/*.json

**实现范围**：`--arm {A,B,C,D}` 四臂均可端到端跑通（加载 skill 文本 → 逐用例判定 → 落 JSON，
含真实 token 用量）；四臂并发执行。评分与多臂汇总（`score` / `compare` /
`render_markdown_table`）仍待 A5。

产物防覆盖：`--out` 指向的文件已存在时**默认报错退出**，需显式 `--force` 才覆盖。
选「拒绝」而非「自动加时间戳」：对照产物要按臂按批做差（Δ1/Δ2），文件名被静默改写会
让后续 `--report` 指向错的批次——A4 出过产物被覆盖的事故，宁可让人显式确认。
指标定义见 metrics.json；执行规格见 comparison-design.md。
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

Arm = Literal["A", "B", "C", "D"]

SKILLS_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAMES = ("safety-hazard-detection", "gauge-reading", "inspection-report")
DEFAULT_SKILL = "safety-hazard-detection"
NOT_FOR_PREFIX = "不适用于："

DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 16
ACCOUNT_CONCURRENCY_LIMIT = 5  # 外部事实：本账户实测并发上限（超出返回 429）
MAX_ATTEMPTS = 3  # 首次 + 2 次重试
NETWORK_BACKOFF_S = 2.0
# 429（并发超限）不能用短退避：退避期间其它请求仍占着槽位，2s/4s 必然重试失败
RATE_LIMIT_BACKOFF_S = 10.0
RETRY_JITTER_S = 1.0

DEFAULT_CASES_GLOB = "skills/*/evals/cases.jsonl"

# comparison-design.md §3 的 13 项指标（(序号, key, 名称, direction)），顺序即表序
METRIC_TABLE: tuple[tuple[int, str, str, str], ...] = (
    (1, "false_trigger_rate", "负向误触发率 FTR", "lower_is_better"),
    (2, "negative_reject_rate", "负向正确拒绝率", "higher_is_better"),
    (3, "trigger_accuracy", "触发准确率", "higher_is_better"),
    (4, "route_sequence_accuracy", "路由序列精确匹配率", "higher_is_better"),
    (5, "conclusion_accuracy", "结论正确率", "higher_is_better"),
    (6, "reading_mae_fs", "读数 MAE（满量程归一）", "lower_is_better"),
    (7, "fabricated_range_count", "编造量程数", "lower_is_better"),
    (8, "hallucinated_items", "幻觉项数", "lower_is_better"),
    (9, "boundary_compliance_rate", "边界合规率", "higher_is_better"),
    (10, "local_fallback_rate", "本地兜底率", "higher_is_better"),
    (11, "tier2_calls_per_task", "Tier 2 调用次数/任务", "lower_is_better"),
    (12, "p95_latency_ms", "P95 端到端延迟", "lower_is_better"),
    (13, "trigger_stability", "触发稳定性", "higher_is_better"),
)
METRIC_KEYS = {metric_id: key for metric_id, key, _name, _direction in METRIC_TABLE}
# 硬门禁：非 0（指标 9 为非 1.0）即失败，不参与加权平均
HARD_GATES = {7: 0.0, 8: 0.0, 9: 1.0}
HARD_GATE_KEYS = tuple(METRIC_KEYS[mid] for mid in sorted(HARD_GATES))

# 本次实验**不测量**的指标（口径决定，非「测不了」）：本实验是纯文本消融，只覆盖触发/路由层。
# 这三项属读数层，需要图像输入与更宽的输出契约，超出 A5 范围。
OUT_OF_SCOPE_METRICS: dict[int, str] = {
    6: "需期望读数与满量程才能算，属读数层",
    9: "需免责声明 / requires_human_review / uncertain 字段，属读数层",
    10: "需 Tier 0/1 链路，本执行器只用云端单次调用",
}
OUT_OF_SCOPE_KEYS = tuple(METRIC_KEYS[mid] for mid in sorted(OUT_OF_SCOPE_METRICS))
SENSITIVITY_RULES = ("majority", "any", "all")

# 本项目实际存在的 4 个 skill 目录名（冻结于 SKILL.md md5 基线）。调用此外的名字 = 幽灵技能。
KNOWN_SKILLS = ("gauge-reading", "inspection-orchestrator", "inspection-report", "safety-hazard-detection")
# 指标 4 的定义是「**编排层**用例的路由序列精确匹配率」，故只统计编排技能的用例
ORCHESTRATION_SKILL = "inspection-orchestrator"
FAILURE_MODE_KEYS = (
    "false_trigger",
    "missed_trigger",
    "wrong_conclusion",
    "boundary_breach",
    "silent_degradation",
    "hallucination",
)

SKILLS_DIR = SKILLS_ROOT / "safety-hazard-detection" / "scripts"
if str(SKILLS_DIR) not in sys.path:  # 复用 StepFun 凭据/JSON 解析适配层，避免第二份实现
    sys.path.insert(0, str(SKILLS_DIR))
from detect_hazards import DEFAULT_MAX_TOKENS, _extract_json, load_credentials  # noqa: E402

USER_TEMPLATE = (
    "任务：{task}\n"
    "素材说明：{assets}\n\n"
    "判断上述任务是否应当调用 Skill。应当调用则给出需要的 Skill 名（按执行顺序）"
    "与可下的结论；不应当调用则明确拒绝。\n"
    '只输出一行 JSON：{{"call_skill":true,"skills":["<skill-name>"],'
    '"findings":[{{"code":"","confidence":0,"evidence":""}}]}}\n'
    '不调用输出：{{"call_skill":false,"skills":[],"findings":[]}}\n'
    "禁止解释过程。"
)


@dataclass(frozen=True)
class CaseResult:
    """单条用例的单次运行结果。"""

    case_id: str
    arm: Arm
    run_index: int
    triggered: bool
    route: list[str]
    output: dict[str, Any]
    latency_ms: int
    tier2_calls: int
    raw_response: str = ""
    error: str = ""  # 非空 = 重试耗尽仍失败；该条**保留**在结果里，不静默丢弃
    attempts: int = 0  # 实际尝试次数（1 = 一次成功；>1 = 重试救回；失败条 = MAX_ATTEMPTS）


def load_cases(paths: Sequence[str]) -> list[dict[str, Any]]:
    """读取并校验 cases.jsonl。

    Raises:
        ValueError: 缺 `id` / `type` / `expect_trigger` 字段，或 id 重复。
    """
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in paths:
        # glob.glob 而非 Path.glob：绝对模式（run_e2e.py 传的就是绝对路径）后者不支持
        matched = sorted(glob.glob(raw_path)) or sorted(glob.glob(str(SKILLS_ROOT.parent / raw_path)))
        for pattern in (Path(p) for p in matched) if matched else [Path(raw_path)]:
            for lineno, line in enumerate(pattern.read_text(encoding="utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                missing = [k for k in ("id", "type", "expect_trigger") if k not in case]
                if missing:
                    raise ValueError(f"{pattern}:{lineno} 缺字段 {missing}")
                if case["id"] in seen:
                    raise ValueError(f"用例 id 重复：{case['id']}")
                seen.add(case["id"])
                cases.append(case)
    return cases


def _split_frontmatter(text: str) -> tuple[str, str]:
    """切出 YAML frontmatter 与正文；无 frontmatter 时描述为空串。"""
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    return (parts[1] if len(parts) >= 3 else ""), (parts[2] if len(parts) >= 3 else text)


def skill_description(skill: str, *, with_not_for: bool = True) -> str:
    """取出 description 段（折叠标量），可选剥掉 `不适用于：…` 那一句（C 臂消融）。"""
    front = _split_frontmatter((SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8"))[0]
    lines, collecting = [], False
    for line in front.splitlines():
        if line.startswith("description:"):
            collecting = True
            continue
        if collecting:
            if not line.startswith((" ", "\t")):
                break
            lines.append(line.strip())
    description = " ".join(lines).strip()
    if not with_not_for:
        idx = description.find(NOT_FOR_PREFIX)
        if idx != -1:
            description = description[:idx].strip()
    return description


def skill_payload(skill: str, arm: Arm) -> str:
    """按实验臂构造 **system 侧** skill 载荷——四臂之间**只有这里不同**。

    A: 不加载任何 SKILL.md（空串）
    B: 完整 skill（description 含 Not-for 段 + 正文 + references）
    C: 完整 skill，但 **仅** description 中删除 Not-for 段；正文与 references 与 B 逐字相同
    D: 只加载 description（含 `[skill: x]` 头），不含正文与 references

    C 臂刻意**不动正文**：Δ2 = FTR(C) − FTR(B) 要测的是 description 里 Not-for 段的净收益，
    正文一并删掉就变成「description + 正文」的合并贡献，不是目标量。

    Returns:
        该臂的 system 提示词；A 臂为空串。
    """
    if arm == "A":
        return ""
    skill_dir = SKILLS_ROOT / skill
    parts = [f"[skill: {skill}]", f"description: {skill_description(skill, with_not_for=arm != 'C')}"]
    if arm == "D":
        # D 与 B 的唯一差异必须是「只有 description」：头与 B/C 逐字一致
        return "\n\n".join(parts)
    body = _split_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))[1]
    parts.append(body.strip())
    references = skill_dir / "references"
    if references.is_dir():
        parts += [
            f"\n[reference: {p.name}]\n{p.read_text(encoding='utf-8').strip()}"
            for p in sorted(references.glob("*.md"))
        ]
    return "\n\n".join(parts)


def build_prompt(case: dict[str, Any], arm: Arm) -> str:
    """按实验臂构造提示词。**除 skill 加载部分外，四臂模板必须逐字一致。**

    A: 不加载任何 SKILL.md
    B: 完整 skill（description 含 Not for 段 + 正文 + references）
    C: 完整 skill，但从 description 中**删除 Not for 段**
    D: 只加载 description，不含正文与 references
    """
    return skill_payload(str(case.get("skill") or DEFAULT_SKILL), arm)


def _chat(system: str, user: str, *, max_tokens: int) -> tuple[str, dict[str, Any], int]:
    """一次 OpenAI 兼容调用。返回 (文本, usage, 延迟ms)。凭据只在内存里过一趟。"""
    from openai import OpenAI

    key, base_url, model = load_credentials()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": user}
    ]
    started = time.monotonic()
    resp = OpenAI(api_key=key, base_url=base_url).chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0, messages=messages
    )
    latency = int((time.monotonic() - started) * 1000)
    usage = getattr(resp, "usage", None)
    message = resp.choices[0].message
    text = (getattr(message, "content", "") or "").strip() or (
        getattr(message, "reasoning_content", "") or ""
    ).strip()
    return (
        text,
        {
            "model": model,
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "finish_reason": str(getattr(resp.choices[0], "finish_reason", "") or ""),
        },
        latency,
    )


def _empty_usage() -> dict[str, Any]:
    """失败占位 usage：保持字段形状，让 token 汇总不必对 error 结果特判。"""
    return {
        "model": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "finish_reason": "",
    }


class RetriesExhausted(RuntimeError):
    """重试耗尽；携带实际尝试次数供落盘（「试了几次」不该是未知项）。"""

    def __init__(self, attempts: int, last: Exception) -> None:
        super().__init__(f"{type(last).__name__}: {last}")
        self.attempts = attempts


def _is_rate_limit(exc: Exception) -> bool:
    """429 判定：并发超限要长退避，与普通网络错误区别对待。"""
    return (
        getattr(exc, "status_code", None) == 429
        or "429" in str(exc)
        or type(exc).__name__ == "RateLimitError"
    )


def _chat_with_retry(system: str, user: str, *, max_tokens: int) -> tuple[str, dict[str, Any], int, int]:
    """`_chat` 的退避重试包装。

    429 用 10s/20s 基准退避，普通错误用 2s/4s；都加 0–1s 抖动打散同批重试
    （抖动只影响重试**时刻**，不影响 temperature=0 下的响应内容与产物顺序）。

    Returns:
        (文本, usage, 延迟ms, 实际尝试次数)

    Raises:
        RetriesExhausted: 尝试 `MAX_ATTEMPTS` 次仍失败，异常携带 `attempts`。
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text, usage, latency = _chat(system, user, max_tokens=max_tokens)
            return text, usage, latency, attempt
        except Exception as exc:  # 网络抖动 / 限流 / 5xx 都可能抛，统一重试
            last_exc = exc
            if attempt < MAX_ATTEMPTS:
                base = RATE_LIMIT_BACKOFF_S if _is_rate_limit(exc) else NETWORK_BACKOFF_S
                time.sleep(base * (2 ** (attempt - 1)) + random.uniform(0, RETRY_JITTER_S))
    assert last_exc is not None  # MAX_ATTEMPTS >= 1
    raise RetriesExhausted(MAX_ATTEMPTS, last_exc)


def run_case(case: dict[str, Any], arm: Arm, run_index: int) -> CaseResult:
    """执行单次用例并采集结果。temperature 固定为 0。

    必须原样记录 raw_response，便于人工复核失败模式。重试耗尽仍失败时返回
    `error` 非空的结果（triggered=False，零值 usage），**不抛出、不丢弃**——
    静默丢条目会污染 FTR 的分母。
    """
    system = build_prompt(case, arm)
    user = USER_TEMPLATE.format(task=case.get("input", ""), assets=case.get("assets", ""))
    try:
        text, usage, latency, attempts = _chat_with_retry(system, user, max_tokens=DEFAULT_MAX_TOKENS)
    except Exception as exc:
        return CaseResult(
            case_id=str(case["id"]),
            arm=arm,
            run_index=run_index,
            triggered=False,
            route=[],
            output={"findings": [], "usage": _empty_usage()},
            latency_ms=0,
            tier2_calls=0,
            raw_response="",
            error=f"{type(exc).__name__}: {exc}",
            attempts=int(getattr(exc, "attempts", 0)),
        )
    try:
        payload = _extract_json(text)
    except Exception:
        payload = {}
    return CaseResult(
        case_id=str(case["id"]),
        arm=arm,
        run_index=run_index,
        triggered=bool(payload.get("call_skill", False)),
        route=[str(s) for s in payload.get("skills", [])],
        output={"findings": payload.get("findings", []), "usage": usage},
        latency_ms=latency,
        tier2_calls=1,
        raw_response=text,
        attempts=attempts,
    )


def run_arm(
    arm: Arm,
    cases: Sequence[dict[str, Any]],
    runs: int = 3,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[CaseResult]:
    """跑完一个实验臂。每条用例重复 `runs` 次以观测触发稳定性。

    调用是 IO 密集，故用有界线程池并发；但并发**不改变可复现性**：
    任务按 `(用例载入序, run_index)` 提交，`executor.map` 按提交序返回，
    返回前再按该序号显式排序，产物字节与串行执行一致。
    """
    plan = [(idx, run_index, case) for idx, case in enumerate(cases) for run_index in range(runs)]
    if not plan:
        return []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(lambda item: run_case(item[2], arm, item[1]), plan))
    keyed = sorted(zip(plan, results), key=lambda pair: (pair[0][0], pair[0][1]))
    return [result for _, result in keyed]


def _ratio(numerator: int, denominator: int) -> float | None:
    """分母为 0 时返回 None（不可测），不返回 0——0 会伪装成「完美」。"""
    return None if denominator == 0 else numerator / denominator


def _fmt(value: Any) -> str:
    """指标值的表格渲染；None 渲染为 `—`（不可测），不渲染为 0。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _mode(values: Sequence[Any]) -> tuple[Any, int]:
    """众数；平票取最先出现者（输入已按 run_index 升序），保证确定性。"""
    if not values:
        return None, 0
    counts: dict[Any, int] = {}
    first: dict[Any, int] = {}
    for idx, value in enumerate(values):
        counts[value] = counts.get(value, 0) + 1
        first.setdefault(value, idx)
    best = max(counts, key=lambda v: (counts[v], -first[v]))
    return best, counts[best]


def _payload_of(result: CaseResult) -> dict[str, Any] | None:
    """从 raw_response 复原模型输出（落盘 JSON 不保留 findings 本身，只存原文）。

    Returns:
        解析成功返回 dict；响应为空或非 JSON 返回 None。
    """
    raw = result.raw_response.strip()
    if not raw:
        return None
    try:
        payload = _extract_json(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _findings_of(result: CaseResult) -> list[dict[str, Any]]:
    """取该次运行的 findings；优先用已解析结果，JSON 回读时靠 raw_response 复原。"""
    payload = _payload_of(result)
    if payload is not None:
        items = payload.get("findings", [])
        return [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []
    items = result.output.get("findings", [])
    return [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []


def _is_phantom(name: str) -> bool:
    """是否调用了本项目不存在的技能名。下划线/大小写差异先归一，避免误判。"""
    return name.strip().casefold().replace("_", "-") not in KNOWN_SKILLS


def _payload_has(payload: Any, needles: Sequence[str]) -> bool:
    """在 payload 里递归找键名或字符串值包含任一 needle（大小写不敏感）。"""
    if isinstance(payload, dict):
        return any(
            any(n in str(k).casefold() for n in needles) or _payload_has(v, needles)
            for k, v in payload.items()
        )
    if isinstance(payload, list):
        return any(_payload_has(v, needles) for v in payload)
    if isinstance(payload, str):
        return any(n in payload.casefold() for n in needles)
    return False


@dataclass(frozen=True)
class CaseAgg:
    """单条用例跨 `runs` 次运行的聚合结果。"""

    case: dict[str, Any]
    runs_total: int
    runs_valid: int
    runs_triggered: int  # 广义：任一次运行 call_skill=true
    runs_own_skill: int  # 本技能口径：该次运行误调用了本用例 skill 所指技能
    triggered: bool  # 多数票；平票按触发（安全指标保守）
    route: tuple[str, ...]
    codes: tuple[str, ...]
    stability: float
    unparsed: int  # 响应无法解析为 JSON 的有效运行数

    @property
    def case_id(self) -> str:
        return str(self.case["id"])

    @property
    def expect_trigger(self) -> bool:
        return bool(self.case["expect_trigger"])

    @property
    def own_skill_triggered(self) -> bool:
        """本技能口径（多数票）：该用例 `skill` 字段所指技能被误调用。

        `call_skill=true` 但 route 为空（点名不出技能）也计为误调用——保守，
        否则一个「触发但说不出技能名」的响应会被漏计成正确拒绝。
        逐次运行判定后再取多数票，与敏感性三口径同源，避免两处口径打架。
        """
        return bool(self.runs_valid) and self.runs_own_skill * 2 >= self.runs_valid


def _aggregate(results: Sequence[CaseResult], cases: Sequence[dict[str, Any]]) -> list[CaseAgg]:
    """按用例聚合多次运行。顺序与 `cases` 一致（确定性，不依赖 dict 遍历序）。"""
    by_case: dict[str, list[CaseResult]] = {}
    for result in results:
        by_case.setdefault(result.case_id, []).append(result)
    aggs: list[CaseAgg] = []
    for case in cases:
        runs = sorted(by_case.get(str(case["id"]), []), key=lambda r: r.run_index)
        valid = [r for r in runs if not r.error]
        if not valid:
            aggs.append(CaseAgg(case, len(runs), 0, 0, 0, False, (), (), 0.0, 0))
            continue
        flags = [r.triggered for r in valid]
        triggered = sum(flags) * 2 >= len(flags)
        own = str(case.get("skill", ""))
        own_flags = [r.triggered and (own in r.route or not r.route) for r in valid]
        route, hits = _mode([tuple(r.route) for r in valid])
        codes, _ = _mode([tuple(sorted({str(f.get("code", "")) for f in _findings_of(r)})) for r in valid])
        aggs.append(
            CaseAgg(
                case=case,
                runs_total=len(runs),
                runs_valid=len(valid),
                runs_triggered=sum(flags),
                runs_own_skill=sum(own_flags),
                triggered=triggered,
                route=route or (),
                codes=codes or (),
                stability=hits / len(valid),
                unparsed=sum(1 for r in valid if _payload_of(r) is None),
            )
        )
    return aggs


def _case_rows(aggs: Sequence[CaseAgg]) -> list[dict[str, Any]]:
    """逐用例附录（§4.3）+ 失败模式标注。"""
    rows = []
    for agg in aggs:
        case = agg.case
        hit = agg.triggered == agg.expect_trigger
        expect_route = tuple(str(s) for s in case["expect_route"]) if "expect_route" in case else None
        mismatch_route = expect_route is not None and agg.route != expect_route
        if not agg.runs_valid:
            mode = "no_valid_sample"
        elif not hit:
            mode = "missed_trigger" if agg.expect_trigger else "false_trigger"
        elif mismatch_route or ("expect_codes" in case and set(agg.codes) != {str(c) for c in case["expect_codes"]}):
            mode = "wrong_conclusion"
        else:
            mode = ""
        rows.append(
            {
                "case_id": agg.case_id,
                "skill": str(case.get("skill", "")),
                "type": str(case.get("type", "")),
                "expect_trigger": agg.expect_trigger,
                "triggered": agg.triggered,
                "own_skill_triggered": agg.own_skill_triggered,
                "runs_own_skill": agg.runs_own_skill,
                "runs_any_triggered": agg.runs_triggered,
                "trigger_rate": _ratio(agg.runs_triggered, agg.runs_valid),
                "own_skill_rate": _ratio(agg.runs_own_skill, agg.runs_valid),
                "stability": agg.stability,
                "runs_valid": agg.runs_valid,
                "runs_total": agg.runs_total,
                "route": list(agg.route),
                "expect_route": list(expect_route) if expect_route is not None else None,
                "codes": list(agg.codes),
                "hit": hit and not mismatch_route,
                "failure_mode": mode,
            }
        )
    return rows


def score(results: Iterable[CaseResult], cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """按 metrics.json 计算单个实验臂的全部指标。

    硬门禁指标（fabricated_range_count / hallucinated_items / boundary_compliance_rate）
    必须**单列**，不参与任何加权平均。算不出的指标一律置 None 并标注 UNTESTED，
    **不填 0**——0 会被误读成「达标」。

    多次运行的聚合规则：comparison-design.md §2 规定「**取多数票**并记录方差」，
    故 `triggered = 触发次数 * 2 >= 有效运行数`（平票按触发，对安全指标保守；
    `runs` 为奇数时无平票）；route / hazard_code 等非布尔量取众数，平票取 `run_index`
    最小者——`runs` 相同时结果逐字可复现。

    有效运行 = `error` 为空且 `raw_response` 可解析为 JSON 的运行。error 运行**不静默丢弃**：
    单列 `n_errors` / `n_unparsed`，`samples` 给出「有效样本 / 总样本」；负例有效样本缺失、
    有调用失败或有解析失败时 `reliable` 置 False，主指标须标注不可靠。

    Returns:
        {metric_key: value, "hard_gate_failures": [...], "failure_modes": {...},
         "samples": {...}, "cases": [...], "notes": [...]}
    """
    results = list(results)
    aggs = _aggregate(results, cases)
    valid = [a for a in aggs if a.runs_valid > 0]
    negatives = [a for a in valid if not a.expect_trigger]
    positives = [a for a in valid if a.expect_trigger]
    negatives_all = [a for a in aggs if not a.expect_trigger]
    false_triggers = [a for a in negatives if a.own_skill_triggered]
    route_cases = [a for a in valid if a.case.get("skill") == ORCHESTRATION_SKILL and "expect_route" in a.case]
    code_cases = [a for a in valid if "expect_codes" in a.case]

    live = [r for r in results if not r.error]
    n_errors = len(results) - len(live)
    n_unparsed = sum(a.unparsed for a in valid)
    negative_ids = {str(c["id"]) for c in cases if not c["expect_trigger"]}
    hallucinated = sum(
        len(_findings_of(r)) for r in live if r.triggered and r.case_id in negative_ids
    )
    # 诊断：广义触发率（任何技能被误调用）+ 幽灵技能（点了本项目不存在的技能名）
    any_triggered = [a for a in negatives if a.triggered]
    phantom_entries = [name for r in live for name in r.route if _is_phantom(name)]
    phantom_runs = sum(1 for r in live if any(_is_phantom(name) for name in r.route))

    ftr = _ratio(len(false_triggers), len(negatives))
    multi = [a for a in valid if a.runs_valid >= 2]
    metrics: dict[str, Any] = {
        "false_trigger_rate": ftr,
        "negative_any_trigger_rate": _ratio(len(any_triggered), len(negatives)),
        "phantom_skill_count": len(phantom_entries),
        "negative_reject_rate": None if ftr is None else 1 - ftr,
        "trigger_accuracy": _ratio(sum(1 for a in valid if a.triggered == a.expect_trigger), len(valid)),
        "route_sequence_accuracy": _ratio(
            sum(1 for a in route_cases if a.route == tuple(str(s) for s in a.case["expect_route"])),
            len(route_cases),
        ),
        "conclusion_accuracy": _ratio(
            sum(1 for a in code_cases if set(a.codes) == {str(c) for c in a.case["expect_codes"]}),
            len(code_cases),
        ),
        # 6 / 9 / 10 在当前用例字段与输出契约下无法计算，置 None（见 notes），不猜数
        "reading_mae_fs": None,
        "fabricated_range_count": _fabricated_ranges(live, cases),
        "hallucinated_items": hallucinated,
        "boundary_compliance_rate": None,
        "local_fallback_rate": None,
        "tier2_calls_per_task": _ratio(len(live), len(results)),
        "p95_latency_ms": _percentile([int(r.latency_ms) for r in live], 0.95),
        "trigger_stability": (sum(a.stability for a in multi) / len(multi)) if multi else None,
    }

    gate_status = {}
    for metric_id, gate in HARD_GATES.items():
        key = METRIC_KEYS[metric_id]
        if metric_id in OUT_OF_SCOPE_METRICS:
            gate_status[key] = "N/A（本次不适用）"  # 明确不在测量范围，不留 UNTESTED 这种含糊态
            continue
        gate_status[key] = "PASS" if float(metrics[key]) == float(gate) else "FAIL"

    modes = dict.fromkeys(FAILURE_MODE_KEYS, 0)
    for row in _case_rows(aggs):
        if row["failure_mode"] in modes:
            modes[row["failure_mode"]] += 1
    modes["hallucination"] = sum(1 for a in negatives if a.triggered)
    modes["silent_degradation"] = n_unparsed
    out_of_scope_modes = ["boundary_breach"]  # 读数层，本次不测

    # 负例侧计数（主指标可靠性只看这里）；全局计数另存，不混用
    neg_ids = {a.case_id for a in negatives_all}
    neg_errors = sum(1 for r in results if r.error and r.case_id in neg_ids)
    neg_unparsed = sum(a.unparsed for a in negatives)
    reliable, reason = _reliability(len(negatives), len(negatives_all), neg_errors, neg_unparsed)
    notes = [
        "本次只测**触发/路由层**指标（1–5、7、8、11–13）。指标 6、9、10 属读数层，"
        "需要图像输入与更宽的输出契约，**明确不在本次测量范围内**（不是「测不出来」）。",
        "口径差异（务必对照）：指标 1 FTR 用 metrics.json 规定的**本技能口径**"
        "（只算「该用例 skill 所指技能」被误调用），故负例触发但点名了别的技能时 FTR 仍记 0；"
        "`negative_any_trigger_rate` 为**广义口径**（任何技能被调用即算）。两者会显著不同，"
        "附录里的 `false_trigger` 标注对应**广义口径**——FTR 与其并存时以此说明调和。",
        f"指标 4 已按定义收窄为「编排层用例」（`skill == {ORCHESTRATION_SKILL}` 且带 `expect_route`），"
        "本臂纳入分母 0 条时不予放宽、如实标注分母不足。",
        "契约局限（未修）：`USER_TEMPLATE` 规定拒绝时输出 `skills: []`，故无法表达"
        "「拒绝本技能、但点名另一个技能」的意图——2026-09-27 移除了 6 条负例的 `expect_route`"
        "字段（gauge-neg-001 / orch-neg-001 / report-neg-001,002 / hazard-neg-002,003），"
        "`expect` 散文意图原样保留；本次未加 `suggested_skills` 字段，因为改契约即改 prompt，"
        "会让已产出与将产出的数据不可比。",
        "指标 8 为**下界**口径：只统计「应当不触发却仍产出 findings」的条目数；"
        "正向用例的输入回溯需人工或模型复核。",
        "指标 7 的依据：用例带 `expect_value` = 素材给了量程；不带而输出里出现 range/value 即算编造。",
        "聚合规则：§2 规定的多数票（triggered = 触发次数*2 >= 有效运行数）；"
        "方差以逐用例 trigger_rate 与 stability 记录，并在「敏感性」一节并列三种口径。",
    ]
    if n_unparsed:
        notes.append(
            f"**{n_unparsed} 次有效运行的响应无法解析为 JSON**，已按「未触发」计入，"
            "FTR 因此偏乐观 —— 看数前先核对这个计数。"
        )
    if not reliable:
        notes.append(f"主指标可靠性：**不可靠**（{reason}）。")

    return {
        **metrics,
        "arm": results[0].arm if results else "",
        "model": next((str(r.output["usage"].get("model", "")) for r in live if r.output["usage"].get("model")), ""),
        "runs": max((a.runs_total for a in aggs), default=0),
        "hard_gate_failures": sorted(k for k, s in gate_status.items() if s == "FAIL"),
        "hard_gate_out_of_scope": sorted(k for k, s in gate_status.items() if s.startswith("N/A")),
        "hard_gate_status": gate_status,
        "out_of_scope_metrics": {METRIC_KEYS[mid]: why for mid, why in sorted(OUT_OF_SCOPE_METRICS.items())},
        "phantom_skill_names": sorted({name for name in phantom_entries}),
        "phantom_runs": phantom_runs,
        "route_scope_cases": len(route_cases),
        "failure_modes": modes,
        "failure_modes_out_of_scope": out_of_scope_modes,
        "samples": {
            "cases_total": len(aggs),
            "cases_valid": len(valid),
            "negatives_valid": len(negatives),
            "negatives_total": len(negatives_all),
            "positives_valid": len(positives),
            "n_errors": n_errors,
            "n_unparsed": n_unparsed,
            "negatives_errors": neg_errors,
            "negatives_unparsed": neg_unparsed,
            "n_retried": sum(1 for r in results if r.attempts > 1),
        },
        "reliable": reliable,
        "reliability_reason": reason,
        "reliability_checks": {
            "negatives_valid_equals_total": len(negatives) == len(negatives_all),
            "negatives_valid": len(negatives),
            "negatives_total": len(negatives_all),
            "negatives_errors": neg_errors,
            "negatives_unparsed": neg_unparsed,
            "global_errors": n_errors,
            "global_unparsed": n_unparsed,
        },
        "cases": _case_rows(aggs),
        "notes": notes,
    }


def _percentile(values: Sequence[int], q: float) -> float | None:
    """最近秩法分位数；样本为空返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = int(math.ceil(len(ordered) * q))
    return float(ordered[max(0, min(len(ordered) - 1, rank - 1))])


def _fabricated_ranges(live: Sequence[CaseResult], cases: Sequence[dict[str, Any]]) -> int:
    """量程未知（用例未给 `expect_value`）却仍输出数值/量程的次数，应为 0。

    响应无法解析的运行既不入分子也不入分母（否则解析失败会伪装成合规）。
    """
    known = {str(c["id"]) for c in cases if "expect_value" in c}
    hits = 0
    for result in live:
        if result.case_id in known:
            continue
        payload = _payload_of(result)
        if payload is not None and _payload_has(payload, ("range", "value")):
            hits += 1
    return hits


def _reliability(n_valid: int, n_total: int, n_errors: int, n_unparsed: int) -> tuple[bool, str]:
    """负例侧可靠性（主指标 FTR 的分母只由负例构成，故只按负例判）。

    逐条返回**具体哪条不满足 + 具体数值**，不用「或」把原因糊起来。
    另：非负例的运行失败/解析失败不影响 FTR，但会进 `samples` 的全局计数，不做隐瞒。
    """
    reasons = []
    if n_valid != n_total:
        reasons.append(f"负例有效样本不足：{n_valid}/{n_total}")
    if n_errors:
        reasons.append(f"负例上有 {n_errors} 次调用失败（已从分母剔除）")
    if n_unparsed:
        reasons.append(f"负例上有 {n_unparsed} 次响应无法解析（按未触发计入，FTR 偏乐观）")
    return (not reasons), "；".join(reasons) if reasons else "负例样本完整、无失败、无解析失败"


def _ftr_by_rule(rows: Sequence[dict[str, Any]], rule: str, *, broad: bool) -> float | None:
    """按聚合口径重算负例误触发率。

    `broad=False`（**本技能口径**，与指标 1 同源）：只算「该用例 skill 所指技能」被误调用，
    逐次运行判定后取票；`broad=True`（广义口径）：任何技能被调用即算。
    三种口径共用同一批负例（`runs_valid > 0`），分母一致才可比。
    """
    key = "runs_any_triggered" if broad else "runs_own_skill"
    negatives = [r for r in rows if not r["expect_trigger"] and r["runs_valid"] > 0]
    if not negatives:
        return None
    if rule == "majority":
        hits = sum(1 for r in negatives if (r["triggered"] if broad else r["own_skill_triggered"]))
    elif rule == "any":
        hits = sum(1 for r in negatives if r[key] > 0)
    else:
        hits = sum(1 for r in negatives if r[key] >= r["runs_valid"])
    return hits / len(negatives)


def _sensitivity(arm_scores: dict[Arm, dict[str, Any]]) -> dict[str, Any]:
    """换聚合口径 Δ2 是否改号——审稿人必问，我们自己先答。

    两套口径各自独立给出三行，**每行都带定义与分母**；本技能口径的 majority 行
    与指标 1 逐位相等（同一份逐次运行判定），从根上杜绝「同一报告两个 FTR」。
    """
    by_rule: dict[str, Any] = {}
    broad_by_rule: dict[str, Any] = {}
    for rule in SENSITIVITY_RULES:
        for target, broad in ((by_rule, False), (broad_by_rule, True)):
            ftr_b = _ftr_by_rule(arm_scores.get("B", {}).get("cases", []), rule, broad=broad)
            ftr_c = _ftr_by_rule(arm_scores.get("C", {}).get("cases", []), rule, broad=broad)
            target[rule] = {
                "ftr_b": ftr_b,
                "ftr_c": ftr_c,
                "delta2": None if (ftr_b is None or ftr_c is None) else ftr_c - ftr_b,
            }
    values = [(rule, by_rule[rule]["delta2"]) for rule in SENSITIVITY_RULES]
    values = [(rule, by_rule[rule]["delta2"]) for rule in SENSITIVITY_RULES]
    missing = [rule for rule, v in values if v is None]
    nonzero = [(rule, v) for rule, v in values if v]
    zero = [rule for rule, v in values if v == 0]
    signs = {(v > 0) - (v < 0) for _rule, v in nonzero}
    # state 与 verdict 一一对应；verdict 只说有证据的话——没有效应时不得声称「结论成立」，
    # 也不得把「全零」说成「只在某口径成立」（那是假话）。
    if missing:
        state = "unavailable"
        verdict = f"**{ '、'.join(missing) } 口径算不出 Δ2（负例缺失），三种口径均无法校验**——本次不回答该问题。"
    elif not nonzero:
        state = "all_zero"
        verdict = "三种口径下 Δ2 均为 0，**本次样本未观测到差异**（既不支持也不否定 Not-for 段的作用）。"
    elif len(signs) > 1:
        state = "reversed"
        verdict = "**三种口径下 Δ2 正负相反——结论随聚合口径反转，这是必须如实报告的发现**，不可只报 majority 一种。"
    elif zero:
        state = "zero_mixed"
        verdict = (
            f"Δ2 在 {'、'.join(zero)} 口径下为 0、在 "
            f"{'、'.join(f'{r}={v:+.3f}' for r, v in nonzero)} 口径下非 0——"
            "**效应幅度随口径变化，不是稳健结论**，三种口径须并列报告（主结论口径为 majority）。"
        )
    else:
        state = "robust"
        verdict = "三种口径下 Δ2 同号，主结论对聚合口径稳健。"
    return {
        "primary_rule": "majority",
        "primary_rule_source": "comparison-design.md §2「取多数票」",
        "state": state,
        "by_rule": by_rule,
        "broad_by_rule": broad_by_rule,
        "broad_values": [broad_by_rule[rule]["delta2"] for rule in SENSITIVITY_RULES],
        "sign_consistent": state == "robust",
        "verdict": verdict,
    }


def compare(arm_scores: dict[Arm, dict[str, Any]]) -> dict[str, Any]:
    """计算派生指标 Δ1 = B − A 与 Δ2 = FTR(C) − FTR(B)。

    Δ2 是本评测的核心结论：负向条件（Not for 段）的净收益。
    FTR **越低越好**，故 **Δ2 为正值 = Not-for 段带来的净收益**（与 Δ1 的符号习惯不同，以本式为准）。
    """
    arms = sorted(arm_scores)
    delta1: dict[str, Any] = {}
    for metric_id, key, name, direction in METRIC_TABLE:
        a, b = (arm_scores.get(arm, {}).get(key) for arm in ("A", "B"))
        if a is None or b is None:
            delta1[key] = {"id": metric_id, "name": name, "direction": direction, "value": None, "verdict": "n/a"}
            continue
        value = b - a
        better = value > 0 if direction == "higher_is_better" else value < 0
        delta1[key] = {
            "id": metric_id,
            "name": name,
            "direction": direction,
            "value": value,
            "verdict": "improved" if better and value != 0 else ("worse" if value != 0 else "same"),
        }

    ftr_b = arm_scores.get("B", {}).get("false_trigger_rate")
    ftr_c = arm_scores.get("C", {}).get("false_trigger_rate")
    usable = [arm for arm in ("B", "C") if arm in arm_scores]
    reliable = bool(
        ftr_b is not None
        and ftr_c is not None
        and all(arm_scores[arm].get("reliable") for arm in usable)
        and arm_scores["B"]["samples"]["negatives_valid"] == arm_scores["C"]["samples"]["negatives_valid"]
    ) if len(usable) == 2 else False
    # 逐条列出不可靠的**具体**原因（不用「或」把原因糊起来）
    reason_bits = []
    for arm in ("B", "C"):
        if arm not in arm_scores:
            reason_bits.append(f"{arm} 臂结果缺失")
        elif not arm_scores[arm].get("reliable"):
            reason_bits.append(f"{arm} 臂：{arm_scores[arm].get('reliability_reason')}")
    if len(usable) == 2 and arm_scores["B"]["samples"]["negatives_valid"] != arm_scores["C"]["samples"]["negatives_valid"]:
        reason_bits.append(
            f"两臂有效负例数不一致：B={arm_scores['B']['samples']['negatives_valid']} "
            f"C={arm_scores['C']['samples']['negatives_valid']}"
        )
    reason_bc = "；".join(reason_bits) if reason_bits else "B/C 两臂负例样本完整、无失败、无解析失败，且有效负例数一致"
    b_samples = arm_scores.get("B", {}).get("samples", {})
    negatives_total = b_samples.get("negatives_total", 0)
    delta2 = {
        "key": "delta_not_for_gain",
        "name": "Δ2 = FTR(C) − FTR(B)",
        "value": None if (ftr_b is None or ftr_c is None) else ftr_c - ftr_b,
        "ftr_b": ftr_b,
        "ftr_c": ftr_c,
        "direction": "positive_is_gain",
        "reliable": reliable,
        "samples": {
            "negatives_valid": b_samples.get("negatives_valid", 0),
            "negatives_total": negatives_total,
        },
        "reason": reason_bc,
    }

    # NVIDIA 语汇的双轨表述（§4 之外的口径换算，见 conversion_note）
    nvidia = {
        "decoy_cases": negatives_total,
        "decoy_definition": "expect_trigger=false 的用例（decoy = 不该被调用的诱饵任务）",
        "routing_change_b_to_c": None if delta2["value"] is None else {
            "from_ftr": ftr_b,
            "to_ftr": ftr_c,
            "delta_pp": delta2["value"] * 100,
        },
        "skill_lift_axis": "with-skill vs without-skill —— 本评测里对应 Δ1 = B − A（A = 不加载 skill）",
        "comparable_to_skill_lift": False,
        "conversion_note": (
            "换算说明：Δ2 与 NVIDIA 语汇的 `Skill Lift` **不是同一轴**。Skill Lift 对照的是"
            "「加载 skill / 不加载 skill」，本评测中对应 Δ1 = B − A；Δ2 是**同一个 skill 内部**的"
            "description 变体对照（B 含 Not-for 段 vs C 删去 Not-for 段），度量的是负向条件对"
            "routing 的影响，即「选择压力下的 routing 变化」。两者不可等同、不可相加，"
            "也不能把 Δ2 当作 Skill Lift 报出去。"
        ),
    }
    return {
        "arms": arms,
        "scores": arm_scores,
        "delta1": delta1,
        "delta2": delta2,
        "sensitivity": _sensitivity(arm_scores),
        "nvidia": nvidia,
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d"),
            "model": _first_model(arm_scores),
            "runs": sorted({s.get("runs") for s in arm_scores.values() if s.get("runs")}),
            "aggregation": "majority（comparison-design.md §2 取多数票）",
        },
        "notes": [note for arm in arms for note in arm_scores[arm].get("notes", [])],
    }


def _first_model(arm_scores: dict[Arm, dict[str, Any]]) -> str:
    for arm in sorted(arm_scores):
        model = arm_scores[arm].get("model")
        if model:
            return str(model)
    return "未记录"


def _conclusion_line(delta2: dict[str, Any]) -> str:
    """§4.5 一句话结论：直接用 Δ2 的数值回答「Not for 条件值多少分」。"""
    if delta2["value"] is None:
        return "一句话结论：Δ2 不可计算（B/C 两臂数据不全），Not-for 段的价值**本次未能量化**。"
    prefix = "" if delta2["reliable"] else "⚠ 不可靠 —— "
    return (
        f"{prefix}一句话结论：从 description 删除 `不适用于：` 段后，负向误触发率从 "
        f"{_fmt(delta2['ftr_b'])} 变为 {_fmt(delta2['ftr_c'])}，Δ2 = {delta2['value']:+.3f}"
        f"（{delta2['value'] * 100:+.1f} 个百分点）——正值即 Not-for 段的净收益。"
    )


def render_markdown_table(comparison: dict[str, Any], arms: Sequence[Arm]) -> str:
    """渲染 comparison-design.md §3 的主表、§4 的差值表 / 逐用例附录 / 失败模式。"""
    arms = list(arms)
    lines = ["# 对照评测结果", ""]
    meta = comparison["meta"]
    lines += [
        f"- 模型：`{meta['model']}`　日期：{meta['generated_at']}　运行次数：{meta['runs'] or '未记录'}"
        f"　聚合：{meta['aggregation']}",
        "",
        "## 主表（§3）",
        "",
        "| # | 指标 | " + " | ".join(f"{a} 臂" for a in arms) + " |",
        "|---|---|" + "---|" * len(arms),
    ]
    for metric_id, key, name, _direction in METRIC_TABLE:
        cells = " | ".join(_fmt(comparison["scores"].get(a, {}).get(key)) for a in arms)
        shown = f"**{name}**" if key in HARD_GATE_KEYS else name
        lines.append(f"| {metric_id} | {shown} | {cells} |")
    lines += [
        "",
        f"> 表中 `n/a` 的指标（6、9、10）属读数层，**明确不在本次测量范围内**，见文末「本次测量范围」。",
        "",
        "## 诊断指标（不属于 §3 的 13 项，单列；这是「skill 到底有没有用」最直白的证据）",
        "",
        "| 诊断项 | " + " | ".join(f"{a} 臂" for a in arms) + " |",
        "|---|" + "---|" * len(arms),
    ]
    for key, label in (
        ("false_trigger_rate", "指标 1 FTR（**本技能口径**）"),
        ("negative_any_trigger_rate", "广义触发率（**任何技能**被误调用）"),
        ("phantom_skill_count", "幽灵技能调用次数（点了不存在的技能名）"),
    ):
        lines.append(
            f"| {label} | "
            + " | ".join(_fmt(comparison["scores"].get(a, {}).get(key)) for a in arms)
            + " |"
        )
    for arm in arms:
        names = comparison["scores"].get(arm, {}).get("phantom_skill_names") or []
        if names:
            lines.append(f"- {arm} 臂幻觉出的技能名：{'、'.join(f'`{n}`' for n in names)}")
    lines += [
        "",
        "> 为什么两个口径都要看：本技能口径下，**模型点了别的技能（含不存在的技能名）不算误触发**。",
        "> 若只报 FTR，一个「见任务就触发、乱点名」的臂会与「安静拒绝」的臂得到同样的 0.000。",
        "",
        "### 硬门禁指标（单列，不参与加权平均）",
        "",
    ]
    for key in HARD_GATE_KEYS:
        status = {a: comparison["scores"].get(a, {}).get("hard_gate_status", {}).get(key) for a in arms}
        lines.append(f"- **{key}**：" + "；".join(f"{a}={v}" for a, v in status.items()))
    lines += ["", "### 有效样本 / 总样本", ""]
    for arm in arms:
        s = comparison["scores"].get(arm, {}).get("samples", {})
        lines.append(
            f"- {arm} 臂：用例 {s.get('cases_valid')}/{s.get('cases_total')}，"
            f"负例 {s.get('negatives_valid')}/{s.get('negatives_total')}，"
            f"调用失败 {s.get('n_errors')}，响应无法解析 {s.get('n_unparsed')}，"
            f"经重试成功 {s.get('n_retried')}"
        )
    lines += ["", "## 差值表（§4.2）", "", "| # | 指标 | Δ1 = B − A | 方向判读 | Δ2 = FTR(C) − FTR(B) |", "|---|---|---|---|---|"]
    d2 = comparison["delta2"]
    sens = comparison["sensitivity"]
    for metric_id, key, name, _direction in METRIC_TABLE:
        d1 = comparison["delta1"][key]
        d2_cell = f"**{d2['value']:+.3f}**" if key == "false_trigger_rate" and d2["value"] is not None else ""
        lines.append(f"| {metric_id} | {name} | {_fmt(d1['value'])} | {d1['verdict']} | {d2_cell} |")
    lines += [
        "",
        f"- **Δ2 = FTR(C) − FTR(B) = {_fmt(d2['value'])}**（**本技能口径**，与主表指标 1 同源；"
        f"FTR 越低越好，正值 = Not-for 段净收益）",
        f"- Δ2 有效样本：负例 {d2['samples']['negatives_valid']}/{d2['samples']['negatives_total']}"
        f"（{'满足' if d2['samples']['negatives_valid'] == d2['samples']['negatives_total'] else '不足'}）",
        f"- 可靠性判定：**{'可靠' if d2['reliable'] else '不可靠'}** —— {d2['reason']}",
        "",
        "## 敏感性：换聚合口径 Δ2 还成立吗",
        "",
        f"主结论采用 **{sens['primary_rule']}**（{sens['primary_rule_source']}）。"
        "下表每一行都写明**口径、定义与分母**，与主表指标 1 的关系是逐位相等（同一份逐次运行判定）。",
        "",
        f"**表 A — 本技能口径（= 主表指标 1 的口径；分母 = 有效负例 {d2['samples']['negatives_valid']} 条）**",
        "：只算「该用例 `skill` 所指技能」被误调用，逐次运行判定后取票。",
        "",
        "| 聚合口径 | FTR(B) | FTR(C) | Δ2 |",
        "|---|---|---|---|",
    ]
    labels = {"majority": "majority（主结论）", "any": "any（任一次误调用即算）", "all": "all（每次都误调用才算）"}
    for rule in SENSITIVITY_RULES:
        row = sens["by_rule"][rule]
        lines.append(f"| {labels[rule]} | {_fmt(row['ftr_b'])} | {_fmt(row['ftr_c'])} | {_fmt(row['delta2'])} |")
    lines += [
        "",
        f"- {sens['verdict']}",
        "",
        f"**表 B — 广义口径（诊断；分母同为有效负例 {d2['samples']['negatives_valid']} 条）**"
        "：任何技能被调用即算误触发（含点名了本项目不存在的技能）。**与表 A 不可混用、不可相减。**",
        "",
        "| 聚合口径 | FTR(B) | FTR(C) | Δ2 |",
        "|---|---|---|---|",
    ]
    for rule in SENSITIVITY_RULES:
        row = sens["broad_by_rule"][rule]
        lines.append(f"| {labels[rule]} | {_fmt(row['ftr_b'])} | {_fmt(row['ftr_c'])} | {_fmt(row['delta2'])} |")
    lines += [
        "",
        "## NVIDIA 语汇双轨表述",
        "",
        f"- decoy 用例数：{comparison['nvidia']['decoy_cases']}（{comparison['nvidia']['decoy_definition']}）",
        f"- B→C 的选择压力下 routing 变化：{_fmt(d2['value'])}",
        f"- 与本评测 Skill Lift 轴的对应关系：{comparison['nvidia']['skill_lift_axis']}",
        f"- 可否等同：**{'可' if comparison['nvidia']['comparable_to_skill_lift'] else '不可'}**",
        f"- {comparison['nvidia']['conversion_note']}",
        "",
        "## 失败模式归类（§4.4）",
        "",
        "| 模式 | " + " | ".join(f"{a} 臂" for a in arms) + " |",
        "|---|" + "---|" * len(arms),
    ]
    for mode in FAILURE_MODE_KEYS:
        # 逐臂都要给单元格，否则表格列数对不上
        cells = [
            "本次不适用"
            if mode in comparison["scores"].get(a, {}).get("failure_modes_out_of_scope", [])
            else str(comparison["scores"].get(a, {}).get("failure_modes", {}).get(mode, ""))
            for a in arms
        ]
        lines.append(f"| {mode} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 逐用例附录（§4.3）",
        "",
        "`广义触发` 与 `本技能误触发` 两列并存，是为了让读者能把附录的失败模式标注与"
        "主表指标 1（本技能口径）对上——两者口径不同，数值本就可以不同。",
        "",
        "| 用例 | 臂 | 期望触发 | 广义触发 | 本技能误触发 | 稳定性 | 有效/总 | 命中 | 失败模式 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        for row in comparison["scores"].get(arm, {}).get("cases", []):
            lines.append(
                f"| {row['case_id']} | {arm} | {row['expect_trigger']} | {row['triggered']} | "
                f"{row.get('own_skill_triggered')} | "
                f"{_fmt(row['stability'])} | "
                f"{row['runs_valid']}/{row['runs_total']} | {'是' if row['hit'] else '否'} | {row['failure_mode'] or '—'} |"
            )
    lines += ["", "## 结论（§4.5）", "", _conclusion_line(d2), "", "## 本次测量范围", ""]
    oos = {k: v for arm in arms for k, v in comparison["scores"].get(arm, {}).get("out_of_scope_metrics", {}).items()}
    lines += [
        "本实验为**纯文本消融**（A5 不发图），按设计只测**触发/路由层**：",
        "",
        f"- **本次测量**：指标 {'、'.join(str(i) for i, _k, _n, _d in METRIC_TABLE if i not in OUT_OF_SCOPE_METRICS)}",
        "- **明确不在本次测量范围内**：",
    ]
    lines += [f"  - 指标 {mid} {METRIC_TABLE[mid - 1][2]}：{why}" for mid, why in sorted(OUT_OF_SCOPE_METRICS.items()) if oos]
    lines += [
        "- 硬门禁中涉及指标 9 的整条标注「本次不适用」——**不是通过，也不是失败**。",
        "- 未扩 `USER_TEMPLATE` / 输出契约来强行凑这些指标（降级优先，非本次核心）。",
        "",
        "## 口径备注",
        "",
    ]
    lines += [f"- {note}" for note in dict.fromkeys(comparison["notes"])]
    return "\n".join(lines)


def _load_results(path: str, arm: Arm, cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """从落盘 JSON 复原一次单臂运行并评分。

    落盘时只保留 raw_response，不保留 findings —— 评分链路统一从 raw_response
    复解析（与实时路径同一套 `_extract_json`），故回读与在线评分结果一致。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload["arm"] != arm:
        raise ValueError(f"{path} 记录的是 {payload['arm']} 臂，与文件名分组不符")
    results = [
        CaseResult(
            case_id=str(row["case_id"]),
            arm=arm,
            run_index=int(row["run_index"]),
            triggered=bool(row["triggered"]),
            route=[str(s) for s in row.get("route", [])],
            output={"findings": [], "usage": row.get("usage", {})},
            latency_ms=int(row.get("latency_ms", 0)),
            tier2_calls=1,
            raw_response=str(row.get("raw_response", "")),
            error=str(row.get("error", "")),
            attempts=int(row.get("attempts", 0)),
        )
        for row in payload["results"]
    ]
    return score(results, cases)


def _print_markdown(text: str) -> None:
    """打印报告。Windows 控制台默认 GBK，`−`(U+2212) / `⚠` 会让 print 抛 UnicodeEncodeError，
    故保留原编码只把错误策略改成 replace（中文仍正确，个别符号降级为 `?`），不改变控制台编码。"""
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
    print(text)


def _run_report(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """`--report`：读多臂结果 JSON → 逐臂评分 → 出主表 / 差值表 / 附录 / 失败模式。"""
    case_paths = args.cases or [str(SKILLS_ROOT.parent / DEFAULT_CASES_GLOB)]
    cases = load_cases(case_paths)
    arm_scores: dict[Arm, dict[str, Any]] = {}
    for path in sorted(args.report):
        arm = json.loads(Path(path).read_text(encoding="utf-8"))["arm"]
        if arm in arm_scores:
            parser.error(f"{arm} 臂出现多份结果文件：{path}")
        arm_scores[arm] = _load_results(path, arm, cases)
    comparison = compare(arm_scores)
    markdown = render_markdown_table(comparison, sorted(arm_scores))
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"写入 {args.out}")
    else:
        _print_markdown(markdown)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：`--arm` 跑单臂，`--report` 汇总多臂。"""
    parser = argparse.ArgumentParser(description="带 skill vs 不带 skill 对照评测")
    parser.add_argument("--arm", choices=["A", "B", "C", "D"])
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条用例（冒烟用）")
    parser.add_argument("--out")
    parser.add_argument("--report", nargs="*", default=[])
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=(
            f"单臂并发请求数（默认 {DEFAULT_CONCURRENCY}，上限 {MAX_CONCURRENCY}）。"
            f"注意：本账户实测并发上限为 {ACCOUNT_CONCURRENCY_LIMIT}（外部限制，非本脚本设计），"
            f"超过会触发 429——429 会按 10s/20s 退避重试，能救回但明显更慢；"
            f"要一次跑干净建议 --concurrency {ACCOUNT_CONCURRENCY_LIMIT}"
        ),
    )
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的 --out 产物")
    args = parser.parse_args(argv)

    if not args.arm and not args.report:
        parser.error("需要 --arm 或 --report")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"--concurrency 需在 1..{MAX_CONCURRENCY} 之间，收到 {args.concurrency}")
    if args.out and Path(args.out).exists() and not args.force:
        parser.error(f"产物已存在，拒绝覆盖：{args.out}（确认覆盖请加 --force）")

    if args.report:
        return _run_report(args, parser)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    results = run_arm(args.arm, cases, runs=args.runs, concurrency=args.concurrency)

    tokens = sum(r.output["usage"]["total_tokens"] for r in results)
    failed = sum(1 for r in results if r.error)
    report = {
        "arm": args.arm,
        "n_cases": len(cases),
        "runs": args.runs,
        "concurrency": args.concurrency,
        "skill_payload_chars": len(build_prompt(cases[0], args.arm)) if cases else 0,
        "total_tokens": tokens,
        "n_errors": failed,
        "results": [
            {
                "case_id": r.case_id,
                "run_index": r.run_index,
                "triggered": r.triggered,
                "route": r.route,
                "usage": r.output["usage"],
                "latency_ms": r.latency_ms,
                "raw_response": r.raw_response,
                "error": r.error,
                "attempts": r.attempts,
            }
            for r in results
        ],
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        suffix = f"，{failed} 条失败（已保留在结果中，计入 FTR 分母）" if failed else ""
        retried = sum(1 for r in results if r.attempts > 1)
        retry_note = f"，{retried} 条经重试成功" if retried else ""
        print(f"写入 {args.out}（{len(results)} 次运行，{tokens} tokens{suffix}{retry_note}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
