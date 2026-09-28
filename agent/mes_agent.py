#!/usr/bin/env python
"""MES Agent —— 一个真循环的智能体，挂在威马 MES 上。

它和「skill」的区别
-------------------
skill 是说明书：翻开、照做、合上。
本文件是**会自己决定下一步**的东西：拿到问题 → 想 → 挑一个工具 → 看结果 →
再想 → 直到能回答。中间走几步、走哪几步，是它自己定的，不是写死的。

循环长什么样
------------
    问 题
     ↓
    ┌─→ 调模型（带上工具清单）
    │      ↓
    │   stop_reason == "tool_use"？ ── 是 ──→ 执行工具 → 把结果塞回对话 ─┐
    │      │ 否                                                          │
    │      ↓                                                             │
    └── 结束，输出答案 ←──────────────────────────────────────────────────┘

零依赖
------
只用标准库 urllib（不用 anthropic SDK），所以：**任何 python 都能跑，不用装包**。
也因此它能跑在 `.venv` 里，够得着 torch（真推理那一侧）。

用法
----
    py -3 agent/mes_agent.py "QA-20260813-100 现在什么状态？"
    py -3 agent/mes_agent.py --verbose "生产部现在有几条待处理？"
    echo "查一下 FT-01" | py -3 agent/mes_agent.py

环境：ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN（本机 Claude Code 已有）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True

from mes_tools import TOOL_SCHEMAS, execute  # noqa: E402  (内含路径解析与重定向)

REPO = Path(__file__).resolve().parents[1]

# 控制台可能是 GBK，会把中文印成乱码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

MAX_ROUNDS = 8  # 预算闸：循环不可能无限转（没有这个闸，一个坏工具就能烧到底）

SYSTEM = """你是威马 MES 的品质助手，接在一条「巡检 Agent → MES 落单」的链路上。

铁律（违反比答不出来更糟）：
1. **只讲查得到的事实**。你手上有工具，查了再说。查不到就说"没查到"，绝不推测数据。
2. **落单前必须先查重**（用 check_number）。重复落单在 MES 里是事故。
3. **落单必须有证据**：confidence 和 evidence_ref 只能来自一次真实检测的结果，
   你自己编一个数字比拒绝落单坏得多。拿不到就明说拿不到。
4. **不越权**。你只能做工具清单里的事。改变更、改工艺、删记录都不在清单里，
   被问到就说做不到并建议找谁。
5. 回答用中文，简短、给数字、给单号。不要复述工具返回的原始格式，要整理成人话。

背景：异常单号形如 QA-YYYYMMDD-NNN，巡检记录形如 XJ<YYYYMMDD><NNN>，工单形如 MO-…。
责任部门只有四个：供应商 / 生产部 / 设备部 / 采购部。
状态只有四个：found(待处理) / handling(处理中) / recheck(复验中) / closed(已关闭)。"""


def redact(text) -> str:
    out = str(text)
    for root, tag in ((REPO, "<repo>"), (Path.home(), "<home>")):
        for form in (str(root), root.as_posix()):
            out = out.replace(form, tag)
    return re.sub(r"(?<![\w<])[A-Za-z]:[\\/]", "<drive>/", out)


class AgentError(Exception):
    pass


def call_model(messages: list, model: str, max_tokens: int) -> dict:
    """打一次 Messages API。用 urllib，不引 SDK。"""
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if not base or not token:
        raise AgentError(
            "缺少 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN —— "
            "本 agent 靠环境里的模型端点工作（Claude Code 的环境里已有这两个）"
        )
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM,
        "tools": TOOL_SCHEMAS,
        "messages": messages,
    }
    req = urllib.request.Request(
        base + "/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": token,
            "authorization": "Bearer " + token,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise AgentError(f"模型端点 HTTP {e.code}：{redact(detail)}") from None
    except urllib.error.URLError as e:
        raise AgentError(f"连不上模型端点：{redact(e.reason)}") from None


def run(question: str, model: str, verbose: bool = False, max_tokens: int = 2048) -> dict:
    """跑一轮完整对话。返回 {answer, rounds, calls, stopped}。

    循环在这里 —— 每一轮都可能要求调工具，调完再问，直到模型不再要工具。
    """
    messages = [{"role": "user", "content": question}]
    calls = []           # 走过的工具调用，供外部审计
    rounds = 0

    while rounds < MAX_ROUNDS:
        rounds += 1
        resp = call_model(messages, model, max_tokens)
        stop = resp.get("stop_reason")
        blocks = resp.get("content") or []

        if verbose:
            print(f"  [轮 {rounds}] stop_reason={stop}", file=sys.stderr)

        # 把模型这一轮的输出原样记进对话（含 thinking / text / tool_use）
        messages.append({"role": "assistant", "content": blocks})

        if stop != "tool_use":
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return {
                "answer": text.strip(),
                "rounds": rounds,
                "calls": calls,
                "stopped": stop,
            }

        # 本轮要求调工具 —— 逐个执行，结果装进一条 user 消息回灌
        results = []
        for b in blocks:
            if b.get("type") != "tool_use":
                continue
            name, args, tid = b.get("name"), b.get("input") or {}, b.get("id")
            if verbose:
                print(f"      → 调 {name}({json.dumps(args, ensure_ascii=False)[:120]})",
                      file=sys.stderr)
            out, ok = execute(name, args)
            calls.append({"tool": name, "args": args, "ok": ok, "out": out[:400]})
            if verbose:
                head = out.splitlines()[0] if out.splitlines() else ""
                print(f"        {'✓' if ok else '✗'} {head[:120]}", file=sys.stderr)
            results.append({
                "type": "tool_result",
                "tool_use_id": tid,
                "content": out,
                "is_error": not ok,
            })
        messages.append({"role": "user", "content": results})

    # 撞到预算闸：**明说**，不要假装答完了
    return {
        "answer": f"（未在 {MAX_ROUNDS} 轮内得出结论，已停止。这是一次未完成，不是答案。）",
        "rounds": rounds,
        "calls": calls,
        "stopped": "max_rounds",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="mes-agent",
        description="MES 智能体：会自己挑工具、走多步、给出结论（命令行版）",
    )
    ap.add_argument("question", nargs="*", help="要问的问题；不填则从 stdin 读")
    ap.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001")
    ap.add_argument("--verbose", "-v", action="store_true", help="把循环每一步打到 stderr（看得到它走了几步）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（含走过的工具调用，供审计）")
    args = ap.parse_args(argv)

    question = " ".join(args.question).strip()
    if not question:
        question = sys.stdin.read().strip()
    if not question:
        print("没给问题。用法：py -3 agent/mes_agent.py \"查一下 QA-20260813-100\"", file=sys.stderr)
        return 2

    try:
        out = run(question, args.model, verbose=args.verbose)
    except AgentError as exc:
        print(f"[agent] !! {redact(exc)}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(out["answer"])
        if args.verbose:
            print(f"\n[agent] 走了 {out['rounds']} 轮，调了 {len(out['calls'])} 次工具，"
                  f"结束原因 {out['stopped']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
