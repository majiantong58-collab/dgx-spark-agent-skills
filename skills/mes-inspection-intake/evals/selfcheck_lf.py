#!/usr/bin/env python
"""产物 LF 断言的**双向故障注入**自证。

判据（契约 §C.6）：来源的唯一有效证明是「同 fixture 重跑 ⇒ 除 `produced_at` 外**逐字节相同**」。
⇒ 产物换行**不得随平台变**。Python 文本模式默认按 `os.linesep` 翻译，
Windows 上会把 `\\n` 写成 `\\r\\n` —— **这条契约主张跨平台即假**。

   D0 基线：真实产物目录内不得有 CR（否则现状即违约）
   D1 变异**数据**：造一份含 CRLF 的产物 ⇒ `assert_lf` 必须报
   D2 放松**断言**：让断言恒不检查 ⇒ 同一份带 CR 的文件必须**变哑**
       （若 D2 仍报，说明信号不是这条断言发的，D1 什么也证明不了）

用法：
    python skills/mes-inspection-intake/evals/selfcheck_lf.py [--data-dir <mes-data>]
退出码：0=两向均符合预期；1=有不符合。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.dont_write_bytecode = True

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

import intake_core as core  # noqa: E402

SAMPLE = '{\n  "schema_version": "1",\n  "records": []\n}\n'


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selfcheck-lf", description="产物 LF 断言双向故障注入自证")
    ap.add_argument("--data-dir", default=str(HERE.parents[2] / "docs" / "mes-demo" / "mes-data"),
                    help="要检查的产物目录（默认仓库内 docs/mes-demo/mes-data）")
    args = ap.parse_args(argv)

    bad = 0
    tmp = Path(tempfile.mkdtemp(prefix="lfsc_"))
    try:
        # ── D0 基线：真实产物必须已是 LF
        d = Path(args.data_dir)
        files = sorted(d.glob("*.json")) if d.is_dir() else []
        if not files:
            print(f"[lf] !! 目录里没有 json 产物：{d.name}")
            return 1
        offenders = [f.name for f in files if b"\r" in f.read_bytes()]
        if offenders:
            print(f"[lf] ✗ D0 基线：产物已含 CR —— {offenders}")
            bad += 1
        else:
            print(f"[lf] ✓ D0 基线：{len(files)} 个产物全部无 CR（{', '.join(f.name for f in files)}）")

        # ── D1 变异数据：造一份 CRLF 产物 → 断言必须报
        crlf = tmp / "crlf.json"
        crlf.write_bytes(SAMPLE.replace("\n", "\r\n").encode("utf-8"))
        try:
            core.assert_lf(crlf)
            print("[lf] ✗ D1 含 CRLF 的产物 → **未被拦下**")
            bad += 1
        except core.IntakeError as exc:
            print(f"[lf] ✓ D1 含 CRLF 的产物 → 已拦下：{exc}")

        # ── D1b 反向：纯 LF 产物不得被误报
        lf = tmp / "lf.json"
        lf.write_bytes(SAMPLE.encode("utf-8"))
        try:
            core.assert_lf(lf)
            print("[lf] ✓ D1b 纯 LF 产物 → 不误报")
        except core.IntakeError as exc:
            print(f"[lf] ✗ D1b 纯 LF 产物被误报：{exc}")
            bad += 1

        # ── D2 放松断言：同一份带 CR 的文件必须变哑
        orig = core.assert_lf
        core.assert_lf = lambda p: None          # 放松：恒不检查
        try:
            core.assert_lf(crlf)
            silenced = True
        except core.IntakeError:
            silenced = False
        finally:
            core.assert_lf = orig
        if silenced:
            print("[lf] ✓ D2 放松断言后同一份带 CR 文件变哑 → D1 的信号确由这条断言产生")
        else:
            print("[lf] ✗ D2 放松断言后仍报 → D1 的信号不来自这条断言")
            bad += 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[lf] 结果：{'两向均符合预期' if bad == 0 else f'{bad} 项不符合'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
