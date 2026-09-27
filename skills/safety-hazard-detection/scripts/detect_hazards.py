"""隐患检测器调用封装。

只做「图像 -> 候选框 + 标签 + 置信度」，不做分级、不写报告、不做合规判定。
判定标准见 ../references/hazard-taxonomy.md。

两条通路：

- Tier 0/1 本地检测器（`load_detector` / `preprocess` / `detect`）——B1 实现，本次不动。
- **Tier 2 StepFun 云端视觉（`detect_via_cloud`）——A4 已打通**，是本文件当前可用的通路。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Detection:
    """单个检测结果（未分级、未定 severity）。"""

    hazard_code: str
    confidence: float
    bbox: tuple[int, int, int, int] = field(default=(0, 0, 0, 0))
    uncertain: bool = False


def load_detector(model_path: str, *, device: str = "cuda") -> Any:
    """加载本地检测器会话（ONNX Runtime GPU / TensorRT 可切换）。

    Args:
        model_path: 权重路径。
        device: 推理设备；不可用时由调用方决定是否回落 CPU。

    Returns:
        可复用的推理会话句柄。
    """
    raise NotImplementedError("B1 实现")


def preprocess(frame: Any, *, input_size: int = 640) -> Any:
    """letterbox 缩放与归一化，保持长宽比不变。"""
    raise NotImplementedError("B1 实现")


def detect(session: Any, frame: Any, *, conf_threshold: float | None = None) -> list[Detection]:
    """对单帧做检测，返回**未过滤**的候选。

    阈值语义：低于 `REVIEW_CONFIDENCE` 的候选在此处即被丢弃。

    Args:
        session: `load_detector` 返回的会话句柄。
        frame: 单帧图像（BGR 或 RGB，由 preprocess 统一）。
        conf_threshold: 候选保留下限，对应 taxonomy 的剔除阈值。
            `None` = 由调用方注入单一来源常量
            `inspection_orchestrator/scripts/tier_budget.REVIEW_CONFIDENCE`（0.40）——
            **本模块不得重复写该字面量**，否则两处会各自漂移。

    Returns:
        候选列表，**尚未**升级到 Tier 1、**尚未**套用 severity。
    """
    raise NotImplementedError("B1 实现")


def apply_taxonomy(detections: list[Detection], *, taxonomy_version: str) -> list[dict]:
    """按 taxonomy 补 severity / label / uncertain，并回标标准版本号。

    只允许输出 taxonomy 中已定义的 hazard_code；表里没有的一律降为 uncertain。
    """
    taxonomy = load_taxonomy()
    applied: list[dict] = []
    for det in detections:
        entry = taxonomy.get(det.hazard_code)
        if entry is None:
            # 表外编码：不丢弃、不猜 severity，降为 uncertain 并显式回标原编码。
            applied.append(
                {
                    "code": det.hazard_code,
                    "label": det.hazard_code,
                    "category": "未定义",
                    "severity": _downgrade("low"),
                    "confidence": det.confidence,
                    "bbox": list(det.bbox),
                    "uncertain": True,
                    "uncertain_reason": "hazard_code 不在 taxonomy 中",
                    "standard_version": taxonomy_version,
                }
            )
            continue
        uncertain = det.uncertain
        applied.append(
            {
                "code": det.hazard_code,
                "label": entry["label"],
                "category": entry["category"],
                "severity": _downgrade(entry["severity"]) if uncertain else entry["severity"],
                "confidence": det.confidence,
                "bbox": list(det.bbox),
                "uncertain": uncertain,
                "uncertain_reason": None,
                "standard_version": taxonomy_version,
            }
        )
    return applied


# --------------------------------------------------------------------------
# taxonomy 单一事实来源：直接解析 references/hazard-taxonomy.md，不在代码里重抄编码表
# --------------------------------------------------------------------------

TAXONOMY_FILE = Path(__file__).resolve().parent.parent / "references" / "hazard-taxonomy.md"
TAXONOMY_VERSION = "hazard-taxonomy v0.1"

# §3「uncertain 且 severity 降一档」——降到底后不再降
_SEVERITY_DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}

_TAXONOMY_ROW = re.compile(
    r"^\|\s*`(?P<code>[A-Z][A-Z0-9-]*)`\s*\|(?P<label>[^|]+)\|(?P<category>[^|]+)"
    r"\|(?P<severity>[^|]+)\|(?P<evidence>[^|]+)\|"
)


def _downgrade(severity: str) -> str:
    """severity 降一档（taxonomy §3）。"""
    return _SEVERITY_DOWNGRADE.get(severity, severity)


def load_taxonomy(path: Path | str = TAXONOMY_FILE) -> dict[str, dict[str, str]]:
    """解析 hazard-taxonomy.md §1 的编码表。

    Returns:
        {hazard_code: {label, category, severity, evidence}}；解析不到任何行时抛错，
        避免「静默空表」把全部结论误判成表外编码。
    """
    text = Path(path).read_text(encoding="utf-8")
    table: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = _TAXONOMY_ROW.match(line.strip())
        if m:
            table[m.group("code")] = {
                "label": m.group("label").strip(),
                "category": m.group("category").strip(),
                "severity": m.group("severity").strip(),
                "evidence": m.group("evidence").strip(),
            }
    if not table:
        raise ValueError(f"taxonomy 解析为空：{path}")
    return table


# --------------------------------------------------------------------------
# Tier 2：StepFun 云端视觉适配层（A4）
# --------------------------------------------------------------------------

# 🔴 实测硬约束（D-010）：step-5-preview 是 reasoning 模型，
# max_tokens < 256 时 content 返回空字符串，会被误判成调用失败。
MIN_SAFE_MAX_TOKENS = 256
# ⚠️ A4 实测补充：256 只是「不返回空串」的下限。真正的瓶颈是 **reasoning 与答案共享
# max_tokens**——预算被 CoT 吃光时 finish_reason=length，content 依然是空的。
# 实测：提示词里逐行列举编码会让模型在 CoT 里**先复述一遍题面**再推理，
# 512/2048 均被吃光。对策是提示词尽量短（编码压成一行）+ 给足余量。
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class CloudCall:
    """一次云端调用的可审计记录。**不含任何凭据**。"""

    task_id: str
    model: str
    image_name: str
    image_bytes: int
    image_sha256: str
    image_width: int | None
    image_height: int | None
    base64_chars: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    content_chars: int
    reasoning_chars: int
    answer_field: str
    finish_reason: str
    latency_ms: int
    ok: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def find_repo_root(start: Path | None = None) -> Path:
    """向上查找含 `.env` 或 `.git` 的仓库根；找不到则回退到本文件上三级。"""
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".env").is_file() or (candidate / ".git").is_dir():
            return candidate
    return Path(__file__).resolve().parents[3]


def load_credentials() -> tuple[str, str, str]:
    """从仓库根 `.env` 读 StepFun 凭据。

    🔴 Key 只在此处进入内存，不写日志、不进报告、不做任何回显。

    Returns:
        (api_key, base_url, model)。

    Raises:
        RuntimeError: 任一变量缺失或为空。
    """
    from dotenv import load_dotenv

    load_dotenv(find_repo_root() / ".env", override=False)
    key = os.environ.get("STEPFUN_API_KEY", "").strip()
    base_url = os.environ.get("STEPFUN_BASE_URL", "").strip()
    model = os.environ.get("STEPFUN_MODEL", "").strip()
    missing = [
        name
        for name, value in (
            ("STEPFUN_API_KEY", key),
            ("STEPFUN_BASE_URL", base_url),
            ("STEPFUN_MODEL", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f".env 缺少变量：{', '.join(missing)}")
    return key, base_url, model


def encode_image(image_path: Path | str) -> tuple[str, dict[str, Any]]:
    """读图并编码为 base64，同时采集尺寸与体积（token 外推需要）。"""
    path = Path(image_path)
    raw = path.read_bytes()
    meta: dict[str, Any] = {
        "image_name": path.name,
        "image_bytes": len(raw),
        "image_sha256": hashlib.sha256(raw).hexdigest()[:16],
        "image_width": None,
        "image_height": None,
    }
    try:
        from PIL import Image

        with Image.open(path) as im:
            meta["image_width"], meta["image_height"] = im.size
    except Exception:  # 尺寸只是审计信息，拿不到不应阻断识别
        pass
    return base64.b64encode(raw).decode("ascii"), meta


def build_prompt(allowed_codes: list[str]) -> str:
    """构造视觉隐患识别提示词。

    编码表从 taxonomy 注入，避免提示词与标准漂移。
    **保持短**：编码压成一行、不复述规则——逐行列举会被 reasoning 模型在 CoT 里
    整段复述，直接把 max_tokens 吃光（A4 实测）。
    """
    codes = ",".join(sorted(allowed_codes))
    return (
        "工业现场图像隐患判读。\n"
        f"可用编码：{codes}\n"
        "只报图中可见证据；置信度 0~1；不确定必须标注；禁止复述本题；禁止解释过程。\n"
        '只输出一行 JSON：{"hazards":[{"code":"","confidence":0,'
        '"bbox":[x1,y1,x2,y2],"evidence":""}]}\n'
        '无隐患输出：{"hazards":[]}'
    )


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中抠出第一个 JSON 对象；容忍 ```json 围栏与前后废话。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("响应中找不到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def detect_via_cloud(
    image_path: Path | str,
    *,
    task_id: str = "",
    frame_id: str = "frame_0000",
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_S,
    client: Any | None = None,
) -> tuple[list[dict], CloudCall]:
    """Tier 2：单帧图像送 StepFun 视觉端点，返回已套用 taxonomy 的隐患条目。

    网络异常**不抛出**——转为 `CloudCall.ok=False` 返回，由调用方按降级路径处理
    （预算护栏见 inspection-orchestrator/references/escalation-policy.md）。

    Args:
        image_path: 待识别图像路径。
        task_id: 任务号，仅用于审计串联。
        frame_id: 帧号，用于拼 `evidence_ref`。
        model: 覆盖 .env 中的模型名。
        max_tokens: **必须 ≥ MIN_SAFE_MAX_TOKENS**，否则 reasoning 模型会返回空 content。
        timeout: 单次请求超时（秒）。
        client: 注入已构造的 OpenAI 客户端（便于离线测试）。

    Returns:
        (findings, call_record)。findings 为 routing-table.md §3 契约中的条目。
    """
    if max_tokens < MIN_SAFE_MAX_TOKENS:
        raise ValueError(f"max_tokens 必须 ≥ {MIN_SAFE_MAX_TOKENS}（D-010 实测约束）")

    b64, meta = encode_image(image_path)
    taxonomy = load_taxonomy()
    started = time.monotonic()

    def _record(**kw: Any) -> CloudCall:
        return CloudCall(
            task_id=task_id,
            model=kw.pop("model", model or "unknown"),
            image_name=meta["image_name"],
            image_bytes=meta["image_bytes"],
            image_sha256=meta["image_sha256"],
            image_width=meta["image_width"],
            image_height=meta["image_height"],
            base64_chars=len(b64),
            latency_ms=int((time.monotonic() - started) * 1000),
            **kw,
        )

    if client is None:
        from openai import OpenAI

        key, base_url, env_model = load_credentials()
        model = model or env_model
        client = OpenAI(api_key=key, base_url=base_url)

    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            timeout=timeout,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_prompt(sorted(taxonomy))},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
        )
    except Exception as exc:  # 网络/鉴权/配额一律降级，不炸调用方
        return [], _record(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            content_chars=0,
            reasoning_chars=0,
            answer_field="none",
            finish_reason="error",
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    usage = getattr(resp, "usage", None)
    finish_reason = str(getattr(resp.choices[0], "finish_reason", "") or "")
    message = resp.choices[0].message
    content = (getattr(message, "content", "") or "").strip()
    reasoning = (getattr(message, "reasoning_content", "") or "").strip()
    # reasoning 模型：content 为空时退回 reasoning_content，不要直接判失败
    answer, answer_field = (content, "content") if content else (reasoning, "reasoning_content")

    usage_kw = {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "content_chars": len(content),
        "reasoning_chars": len(reasoning),
        "answer_field": answer_field,
        "finish_reason": finish_reason,
    }

    if not answer:
        return [], _record(
            ok=False,
            error=f"content 与 reasoning_content 均为空（finish_reason={finish_reason}）",
            **usage_kw,
        )

    try:
        payload = _extract_json(answer)
    except Exception as exc:
        # 带上 finish_reason 与响应片段——否则每次解析失败都要再烧一次 API 才能定位
        return [], _record(
            ok=False,
            error=f"响应解析失败: {exc}（finish_reason={finish_reason}）"
            f" 片段={answer[:200]!r}",
            **usage_kw,
        )

    detections = [
        Detection(
            hazard_code=str(item.get("code", "")).strip(),
            confidence=float(item.get("confidence", 0.0)),
            bbox=tuple(int(v) for v in (item.get("bbox") or (0, 0, 0, 0)))[:4],
        )
        for item in payload.get("hazards", [])
        if item.get("code")
    ]
    styled = apply_taxonomy(detections, taxonomy_version=TAXONOMY_VERSION)

    findings = [
        {
            "kind": "hazard",
            "code": item["code"],
            "label": item["label"],
            "severity": item["severity"],
            "confidence": item["confidence"],
            "tier": 2,
            "evidence_ref": f"{frame_id}#bbox{item['bbox']}",
            "uncertain": item["uncertain"],
            "source": "safety-hazard-detection",
            "requires_human_review": item["severity"] == "critical" or item["uncertain"],
            "evidence": next(
                (
                    str(h.get("evidence", ""))
                    for h in payload.get("hazards", [])
                    if str(h.get("code", "")).strip() == item["code"]
                ),
                "",
            ),
        }
        for item in styled
    ]
    return findings, _record(ok=True, **usage_kw)
