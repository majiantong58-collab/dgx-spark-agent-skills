#!/usr/bin/env python
"""mes-record-query 可执行入口（只读）。

用法：
    python skills/mes-record-query/scripts/query.py --proto <原型目录或 index.html> \
        [--data-dir <mes-data>] (--wo MO-… | --dev FT-01 | --exc [QA-…] | --check <候选号>)

查工单 / 查设备 / 查异常单 / 单号查重。**本技能只读**：不写任何文件、不改原型、不碰 mes-data。
结果以人话印到 stdout；退出码 0=成功，1=失败。错误信息抹掉本机绝对路径。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 🔴 本技能声称「只读」：import 会顺手写 __pycache__/*.pyc，必须先关掉字节码落盘
sys.dont_write_bytecode = True

import query_core as core  # noqa: E402

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
        prog="mes-record-query",
        description="查询MES 既有记录（工单 / 设备 / 异常单）与单号查重；只读，不发号、不落单",
    )
    parser.add_argument(
        "--proto",
        default=None,
        help="MES 宿主页位置：index.html 文件或其所在目录。缺省序：--proto > MES_PROTO 环境变量 > "
             "仓库内 docs/mes-demo/index.html；三者皆无则报错要求显式传入（不猜路径）",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="mes-data 目录（默认取 <原型目录>/mes-data，契约 §C:133 规定的相对位置）",
    )
    sel = parser.add_mutually_exclusive_group()
    sel.add_argument("--wo", default=None, metavar="NO", help="查工单：MO-20260812-006 → 状态 / 数量 / 产线")
    sel.add_argument("--dev", default=None, metavar="CODE", help="查设备台账：FT-01")
    sel.add_argument(
        "--exc",
        nargs="?",
        const="",
        default=None,
        metavar="NO",
        help="查异常单：给号查详情；不给号则按 --dept / --status 列表",
    )
    sel.add_argument("--check", default=None, metavar="NO", help="单号查重：判「可用 / 已占用」并指出在哪一处")
    parser.add_argument("--dept", default=None, help="配合 --exc 列表：部门枚举 供应商/生产部/设备部/采购部")
    parser.add_argument("--status", default=None, help="配合 --exc 列表：状态枚举 found/handling/recheck/closed")
    return parser


def host_page():
    """仓库内最小宿主页（已知回退，**不是猜测**）。

    装到别处（如 `~/.claude/skills/`）时解析不到 → 返回 None，退回「问用户」。
    """
    cand = REPO / "docs" / "mes-demo" / "index.html"
    return cand if cand.is_file() else None


def resolve_proto(raw):
    """--proto 可给文件或目录（目录内取 index.html）。

    🔴 缺省序：`--proto` > `MES_PROTO` 环境变量 > 仓库内宿主页 `docs/mes-demo/index.html`。
    **三者皆无即报错问，不猜路径**——有默认值不等于可以猜：默认值是**已知的**回退，
    不是「随便找个像的」。
    """
    source = "--proto"
    if not raw:
        raw = os.environ.get("MES_PROTO")
        source = "MES_PROTO 环境变量"
    if not raw:
        cand = host_page()
        if cand is None:
            raise core.QueryError(
                "缺少 --proto：本技能未随仓库内宿主页安装（docs/mes-demo/index.html 不存在），"
                "请显式告知 MES 宿主页 index.html 的位置（本技能不猜默认路径）"
            )
        raw, source = str(cand), "仓库内默认宿主页"
    path = Path(raw)
    if path.is_dir():
        path = path / "index.html"
    if not path.is_file():
        raise core.QueryError(f"{source} 指向的原型文件不存在：{path.name}")
    print(f"[query] 宿主页：{path.name}（来源：{source}）")
    return path


def main(argv=None):
    args = build_parser().parse_args(argv)
    read_log = {}
    try:
        proto = resolve_proto(args.proto)
        data_dir = Path(args.data_dir) if args.data_dir else proto.parent / "mes-data"

        _raw = core.read_text(proto, read_log)
        text = _raw
        data = core.load_mes_data(data_dir, read_log)

        # 选择器恰好一个
        chosen = [k for k, v in (("wo", args.wo), ("dev", args.dev),
                                 ("exc", args.exc), ("check", args.check)) if v is not None]
        if not chosen:
            raise core.QueryError("未指定查询：请用 --wo / --dev / --exc / --check 之一")
        which = chosen[0]

        if which == "wo":
            core.validate("wo", args.wo)
            lines = core.query_workorder(text, args.wo)
        elif which == "dev":
            core.validate("dev", args.dev)
            lines = core.query_equipment(text, args.dev)
        elif which == "check":
            core.validate("check", args.check)
            lines = core.check_number(core.scan_proto(text), data, args.check)
        else:
            if args.exc:
                core.validate("exc", args.exc)
            lines = core.query_exceptions(text, args.exc or "", args.dept, args.status)
            for _name, rec in data["records"]:
                if args.exc and rec.get("no") == args.exc:
                    lines.append(f"  （mes-data 亦命中：{rec}）")

        drift = core.self_check(read_log)
        print(f"[query] 已读 {len(read_log)} 个文件：{', '.join(sorted(p.name for p in read_log))}")
        for line in lines:
            print(f"[query] {line}")
        # 宿主违约全页审计：**任何一次运行都要看得见**，不只在被问到那条时才暴露
        violations = core.audit_enums(text)
        if violations:
            for line in core.format_violations(violations):
                print(f"[query] {line}")
        if drift:
            for name, before, after in drift:
                print(f"[query] !! 只读自证失败：{name} sha256 {before} → {after}", file=sys.stderr)
            return 1
        print(f"[query] 只读自证通过：{len(read_log)} 个被读文件 sha256 前后一致（未写任何文件）")
    except core.QueryError as exc:
        print(f"[query] !! {redact(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 不吞：留下类型与消息，且先抹掉本机路径
        print(f"[query] !! 未预期失败 {type(exc).__name__}: {redact(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
