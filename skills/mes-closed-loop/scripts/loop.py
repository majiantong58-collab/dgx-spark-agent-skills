#!/usr/bin/env python
"""mes-closed-loop 可执行入口（闭环编排）。

用法：
    python skills/mes-closed-loop/scripts/loop.py route --utterance "这张巡检图帮我落成异常单"
    python skills/mes-closed-loop/scripts/loop.py run \
        --finding <识别产物.json> --out-dir <mes-data> --proto <原型 index.html 或目录> [--candidate QA-…]

`route` 判是否进 MES 侧并给出子技能序列（路由日志）；`run` 真跑闭环并逐条打印消费证明。
结果以人话印到 stdout；退出码 0=成功，1=失败。错误信息抹掉本机绝对路径。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 🔴 「只读自证」的教训（M2）：import 会顺手写 __pycache__/*.pyc，先关掉
sys.dont_write_bytecode = True

import loop_core as core  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

# 控制台默认编码可能是 GBK，会把人话印成乱码；显式转 UTF-8（失败则退回原样）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def redact(text):
    """抹掉本机绝对路径：仓库根、用户主目录、盘符（手法沿用 ui/server.py:248）。"""
    out = str(text)
    for root, tag in ((REPO, "<repo>"), (Path.home(), "<home>")):
        for form in (str(root), root.as_posix()):
            out = out.replace(form, tag)
    return re.sub(r"(?<![\w<])[A-Za-z]:[\\/]", "<drive>/", out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mes-closed-loop",
        description="MES 巡检闭环编排：路由到子技能序列（识别→规则→落单→回执→成文），编排层不自己识别、不自己写单",
    )
    sub = parser.add_subparsers(dest="cmd")

    r = sub.add_parser("route", help="只判路由：这句话进不进 MES 侧？进则走哪几个子技能")
    r.add_argument("--utterance", required=True, help="用户原话")
    r.add_argument("--site", default="未指定", help="巡检点位（缺省「未指定」，不编造）")
    r.add_argument("--frame", action="append", default=None,
                   help="可选：真实帧路径（可重复）。给了才把识别路由委托给 orchestrator；本层不伪造帧")

    x = sub.add_parser("run", help="跑闭环：识别产物 → 规则 → 落单 → 回执 → 成文")
    x.add_argument("--finding", required=True, help="识别层产物 JSON（orchestrator 信封，含 findings[]）")
    x.add_argument("--out-dir", required=True, help="mes-data 目录（intake 在此落 inbox.json / xj-records.json）")
    x.add_argument("--proto", default=None,
                   help="MES 宿主页 index.html 或所在目录。缺省序：--proto > MES_PROTO 环境变量 > "
                        "仓库内 docs/mes-demo/index.html；三者皆无则报错要求显式传入（不猜路径）")
    x.add_argument("--candidate", default=None, help="可选：落单前先查重的候选号；已占用则不落单")
    return parser


def host_page():
    """仓库内最小宿主页（已知回退，**不是猜测**）。装到别处则解析不到 → None。"""
    cand = REPO / "docs" / "mes-demo" / "index.html"
    return cand if cand.is_file() else None


def resolve_proto(raw):
    """缺省序：`--proto` > `MES_PROTO` 环境变量 > 仓库内宿主页 `docs/mes-demo/index.html`。

    🔴 **三者皆无即报错问，不猜路径**——默认值是**已知的**回退，不是「随便找个像的」。
    """
    source = "--proto"
    if not raw:
        raw = os.environ.get("MES_PROTO")
        source = "MES_PROTO 环境变量"
    if not raw:
        cand = host_page()
        if cand is None:
            raise core.LoopError(
                "缺少 --proto：本技能未随仓库内宿主页安装（docs/mes-demo/index.html 不存在），"
                "请显式告知 MES 宿主页 index.html 的位置（本技能不猜默认路径）"
            )
        raw, source = str(cand), "仓库内默认宿主页"
    path = Path(raw)
    if path.is_dir():
        path = path / "index.html"
    if not path.is_file():
        raise core.LoopError(f"{source} 指向的原型文件不存在：{path.name}")
    print(f"[loop] 宿主页：{path.name}（来源：{source}）")
    return path


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "route":
            g = core.gate(args.utterance)
            print(f"[loop] 触发判定：{'进入 MES 侧' if g['trigger'] else '不进入 MES 侧'} —— {g['why']}")
            steps = core.plan(args.utterance)
            if not steps:
                print("[loop] 路由日志：本技能**不触发**（未检出 MES 语境）")
                print("[loop] 改交：有图/帧且未指明识别类型 → inspection-orchestrator；"
                      "已指明识别类型 → 对应识别子技能（safety-hazard-detection / gauge-reading）")
                return 0
            print("[loop] 路由日志：")
            for i, (name, skill, why) in enumerate(steps, 1):
                print(f"[loop]   {i}. {name} → {skill}（{why}）")
            if any("inspection-orchestrator" in s for _n, s, _w in steps):
                for line in core.recognition_route(args.utterance, args.frame, args.site):
                    print(f"[loop]   · {line}")
            return 0

        if args.cmd == "run":
            proto = resolve_proto(args.proto)
            res = core.run_chain(Path(args.finding), Path(args.out_dir), proto, args.candidate)
            for line in res["log"]:
                print(f"[loop] {line}")
            print("[loop] 消费证明（空转防护）：")
            for c in res["checks"]:
                print(f"[loop]   ✓ {c}")
            print(f"[loop] 闭环完成：{res['record']['no']} 已落单并回执确认")
            return 0

        print("[loop] !! 未指定子命令：请用 route 或 run", file=sys.stderr)
        return 1
    except core.LoopError as exc:
        print(f"[loop] !! {redact(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 不吞：留下类型与消息，且先抹掉本机路径
        print(f"[loop] !! 未预期失败 {type(exc).__name__}: {redact(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
