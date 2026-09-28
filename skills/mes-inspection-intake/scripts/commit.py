#!/usr/bin/env python
"""mes-inspection-intake 可执行入口。

用法：
    python skills/mes-inspection-intake/scripts/commit.py --finding <发现.json> --out <inbox.json>

机器可读结果写文件（inbox.json / xj-records.json），stdout 只印人话进度。
退出码：0=成功，1=失败。错误信息抹掉本机绝对路径（契约 §D，手法沿用 ui/server.py:248）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intake_core as core  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


def redact(text):
    """抹掉本机绝对路径：仓库根、用户主目录、盘符（契约 §D；手法沿用 ui/server.py:248）。"""
    out = str(text)
    for root, tag in ((REPO, "<repo>"), (Path.home(), "<home>")):
        for form in (str(root), root.as_posix()):
            out = out.replace(form, tag)
    return re.sub(r"(?<![\w<])[A-Za-z]:[\\/]", "<drive>/", out)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mes-inspection-intake",
        description="把巡检发现落成 MES 品质异常单，产出 inbox.json 与同目录的 XJ 巡检记录",
    )
    parser.add_argument("--finding", required=True, help="巡检发现 JSON（findings 数组或单条 finding）")
    parser.add_argument("--out", required=True, help="inbox.json 写出路径（同目录并写 xj-records.json）")
    parser.add_argument(
        "--date",
        default=None,
        help="覆盖单号日期段 YYYY-MM-DD（默认取 finding.captured_at，无则系统当天）",
    )
    parser.add_argument(
        "--dept",
        default=None,
        help=f"显式指定责任部门（须属枚举：{'/'.join(core.DEPT_ENUM)}）",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = core.commit_findings(args.finding, args.out, args.date, args.dept)
    except core.IntakeError as exc:
        print(f"[intake] !! {redact(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 不吞：终端留类型与消息，且先抹掉本机路径
        print(f"[intake] !! 未预期失败 {type(exc).__name__}: {redact(exc)}", file=sys.stderr)
        return 1

    for line in result["progress"]:
        print(f"[intake] {redact(line)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
