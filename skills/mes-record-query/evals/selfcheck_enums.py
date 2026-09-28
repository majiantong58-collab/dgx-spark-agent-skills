#!/usr/bin/env python
"""枚举越界护栏的自证：**双向故障注入**。

判据（R2-B 实测报出的真缺陷 / 契约 §A.1·§A.4·§A.5）：
  宿主把 `st` 改成契约枚举外的值，查询**不得照打**，必须出可见信号。

只测「喂坏数据会报错」是不够的——**若护栏其实是别的代码碰巧挡下的**，
这条断言就是装饰。故两个方向都测：
  D1 变异**数据**：`st=running` → `bogus` ⇒ 必须报（EXIT≠0 或 ⚠️）
  D2 变异**实现**：把枚举集合放宽到「什么都合法」再喂同一份坏数据
     ⇒ **必须变哑**。若 D2 仍报，说明信号来自别处，D1 证明不了护栏有效。

用法：
    python skills/mes-record-query/evals/selfcheck_enums.py --proto <宿主页 index.html 或目录>
退出码：0=两向都符合预期；1=有不符合。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERY = HERE.parent / "scripts" / "query.py"
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.dont_write_bytecode = True

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

import query_core as core  # noqa: E402

TARGET_NO = "MO-20260812-006"
TARGET_ST = "running"


def _mutated_host(src: Path, tmp: Path, new_st: str) -> Path:
    """复制宿主页并把 TARGET_NO 的 st 改成 new_st（**不改原文件**）。"""
    text = src.read_text(encoding="utf-8")
    pat = re.compile(rf"(no: '{re.escape(TARGET_NO)}'.*?st: ')[^']*(')", re.S)
    mutated, n = pat.subn(rf"\g<1>{new_st}\g<2>", text, count=1)
    if n != 1:
        raise SystemExit(f"[enum] !! 变异失败：在宿主页里找不到 {TARGET_NO} 的 st（宿主结构可能已变）")
    out = tmp / "index.html"
    out.write_text(mutated, encoding="utf-8")
    return out


def _run_query(host: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(QUERY), "--proto", str(host), "--wo", TARGET_NO],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr)


def _signalled(rc: int, out: str) -> bool:
    """「有可见信号」= 非零退出 **或** 出现 ⚠️。"""
    return rc != 0 or "⚠" in out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selfcheck-enums",
                                 description="枚举越界护栏双向故障注入自证")
    ap.add_argument("--proto", required=True, help="宿主页 index.html 或所在目录")
    args = ap.parse_args(argv)
    src = Path(args.proto)
    if src.is_dir():
        src = src / "index.html"
    if not src.is_file():
        print(f"[enum] !! 宿主页不存在：{src.name}", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="enumsc_"))
    bad = 0
    try:
        # D0 基线：原样应**无**越界信号（否则后面两项都无从判断）
        rc0, out0 = _run_query(src)
        if _signalled(rc0, out0):
            print(f"[enum] ✗ D0 基线：未变异的宿主页就报了越界 —— 存在误报\n{out0.strip()}")
            bad += 1
        else:
            print(f"[enum] ✓ D0 基线：未变异宿主页无越界信号（EXIT={rc0}）")

        host = _mutated_host(src, tmp, "bogus")

        # D1 变异数据 → 必须报
        rc1, out1 = _run_query(host)
        if _signalled(rc1, out1):
            first = next((l for l in out1.splitlines() if "越界" in l), "").strip()
            print(f"[enum] ✓ D1 变异数据 st=bogus → 已报（EXIT={rc1}）：{first}")
        else:
            print(f"[enum] ✗ D1 变异数据 st=bogus → **照打不报**（EXIT={rc1}）")
            bad += 1

        # D2 变异实现：放宽枚举常量 → 同一份坏数据必须**变哑**。
        #    若仍拦，说明信号来自别处，D1 就证明不了这条护栏有效。
        text = host.read_text(encoding="utf-8")
        orig = core.WO_STATES
        try:
            core.WO_STATES = tuple(set(orig) | {"bogus"})
            widened_audit = [b for b in core.audit_enums(text) if b["kind"] == "工单状态 st"]
            try:
                core.query_workorder(text, TARGET_NO)
                widened_raised = False
            except core.QueryError:
                widened_raised = True
        finally:
            core.WO_STATES = orig

        if widened_audit or widened_raised:
            print(f"[enum] ✗ D2 放宽枚举后仍拦（audit={widened_audit} raised={widened_raised}）"
                  f" → D1 的信号不来自本护栏")
            bad += 1
        else:
            print("[enum] ✓ D2 放宽枚举后同一份坏数据变哑（audit 空 + 不抛）"
                  " → D1 的信号确由本护栏产生")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[enum] 结果：{'两向均符合预期' if bad == 0 else f'{bad} 项不符合'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
