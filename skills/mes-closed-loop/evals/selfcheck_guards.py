#!/usr/bin/env python
"""空转防护的自证：**故障注入**，证明每条消费证明真的会拦下断链。

判据 5 只跑通正向链路是**证明不了**空转防护的——「调了但没用」的实现也能一路绿灯。
故本脚本逐条**故意打断**链路，断言对应护栏报错。哪条护栏不报错，哪条就是死代码。

用法：
    python skills/mes-closed-loop/evals/selfcheck_guards.py --proto <原型 index.html 或目录>
退出码：0=四条护栏全部拦下断链；1=有护栏是死的。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.dont_write_bytecode = True

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

import loop_core as core  # noqa: E402

# 跨技能模块（loop_core 内是惰性 import，故障注入需要提前拿到同一份模块对象）
core.sys_path_add(core.SKILLS / "mes-inspection-intake" / "scripts")
core.sys_path_add(core.SKILLS / "mes-record-query" / "scripts")

FINDING = HERE / "fixtures" / "finding-person.json"
WORK = HERE / "fixtures" / "_guard-tmp"


def _fresh():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    return WORK


def _run(proto):
    return core.run_chain(FINDING, WORK, proto, None)


def g1_intake_writes_nothing(proto):
    """断链①：intake 假装跑完却不产出 → 落单步空转。"""
    import intake_core

    orig = intake_core.commit_findings
    intake_core.commit_findings = lambda *a, **k: {"progress": ["(注入：什么都没写)"]}
    try:
        _fresh()
        _run(proto)
    finally:
        intake_core.commit_findings = orig
    return False, "未拦截"


def g2_rules_ignored_by_intake(proto):
    """断链②：规则判据说「生产部」，而 intake 若落别的部门 → 规则被绕过。"""
    orig = core.rules_expect
    core.rules_expect = lambda f: {"dept": "设备部", "iso": True, "rule": "(注入：错判据)"}
    try:
        _fresh()
        _run(proto)
    finally:
        core.rules_expect = orig
    return False, "未拦截"


def g3_xj_record_missing(proto):
    """断链③：§C.2 要求 rel 指向的 XJ 记录一并产出；若 intake 未履行 → rel 指向空气。

    注意不能只删文件再重跑：intake 追加语义会**重新生成**它，那样测的是重跑不是护栏。
    """
    import intake_core

    orig = intake_core.commit_findings

    def fake(*a, **k):
        r = orig(*a, **k)
        (WORK / "xj-records.json").unlink(missing_ok=True)  # 模拟 §C.2 未履行
        return r

    intake_core.commit_findings = fake
    try:
        _fresh()
        _run(proto)
    finally:
        intake_core.commit_findings = orig
    return False, "未拦截"


def g4_type_not_allowed(proto):
    """断链④：§C.3/v1.7 起演示只可用「人员违规」。喂仪表读数 → 规则必须拒。"""
    doc = json.loads(FINDING.read_text(encoding="utf-8"))
    doc["findings"][0]["label"] = "压力表读数 0.8MPa 超出量程"
    doc["findings"][0]["code"] = "GAUGE-OVER"
    alt = WORK / "finding-gauge.json"
    _fresh()
    alt.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    core.run_chain(alt, WORK, proto, None)
    alt.unlink()
    return False, "未拦截"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selfcheck-guards",
                                 description="空转防护故障注入自证：逐条打断链路，断言护栏报错")
    ap.add_argument("--proto", required=True, help="MES 原型 index.html 或所在目录")
    args = ap.parse_args(argv)
    proto = Path(args.proto)
    if proto.is_dir():
        proto = proto / "index.html"
    if not proto.is_file():
        print(f"[guard] !! 原型文件不存在：{proto.name}", file=sys.stderr)
        return 1

    checks = [
        ("G1 intake 不产出", g1_intake_writes_nothing),
        ("G2 规则被绕过", g2_rules_ignored_by_intake),
        ("G3 XJ 记录缺失", g3_xj_record_missing),
        ("G4 发现类型越界", g4_type_not_allowed),
    ]
    bad = 0
    for name, fn in checks:
        try:
            fn(proto)
        except core.LoopError as exc:
            print(f"[guard] ✓ {name} → 已拦下：{exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[guard] ✗ {name} → 抛了非 LoopError：{type(exc).__name__}: {exc}")
            bad += 1
        else:
            print(f"[guard] ✗ {name} → 护栏是死的（断链未被拦下）")
            bad += 1

    shutil.rmtree(WORK, ignore_errors=True)
    print(f"[guard] 结果：{len(checks) - bad}/{len(checks)} 条护栏有效")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
