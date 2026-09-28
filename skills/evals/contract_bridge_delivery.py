#!/usr/bin/env python
"""交付区可重放检查 —— 一条命令：**起只读服务（root = 交付区）→ 断言 → 收工**。

为什么要有它（R3 复验时踩到的坑）：
    R2-B 曾声称「活服务 :8899 直指交付区」，但复验时**根本没有 http.server 在监听**，
    唯一活跃的 8770 是 invda 自己的演示页（取 mes-data 返回 404）。
    ⇒ 问题不是内容假，而是**那条结论依赖「某人口中的环境」，第三方无法重放**。
    本脚本把环境**自己建起来**（root 锁定交付区），于是结论只依赖仓库字节，不依赖谁说过什么。

它验的是**交付区**（`交付物/mes-prototype/`），不是临时副本：
    1. 服务真的指向交付区 —— served `inbox.json` 的 sha256 **== 磁盘**（否则可能served 的是别处的旧件）
    2. 首行 `data-no` == 交付区记录里的号
    3. `data-total` 与 `.pagination span b` **双处同刷**（数字取自契约 §B.4）
    4. 隔离列按契约 §B.2 映射渲染；且交付记录的 `iso` 须等于 §C.5 默认值（抓陈旧件）

用法（唯一命令）：
    py -3 skills/evals/contract_bridge_delivery.py
    py -3 skills/evals/contract_bridge_delivery.py --root <交付区目录>

退出码 0=通过 / 1=失败（同 run_e2e.py 约定）。
⚠️ **只读**：SimpleHTTPRequestHandler 仅实现 GET/HEAD，本脚本不向交付区写任何字节。
"""

from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
def _default_root():
    """定位交付区。**此处不写死任何目录名**（公开仓库不得含客户名）。

    默认指向**仓库内** `docs/mes-demo` —— 交付区应是评委能复现的产物；
    本地真原型用 `MES_PROTO` 覆盖。
    """
    env = os.environ.get("MES_PROTO")
    if env:
        return Path(env)
    return REPO / "docs" / "mes-demo"


DEFAULT_ROOT = _default_root()
PASS, FAIL = "PASS", "FAIL"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):        # 静音；404 网络日志是浏览器行为，不入断言
        pass


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    return _sha256(Path(path).read_bytes())


def _serve(root):
    handler = functools.partial(_Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _fmt_delta(sec):
    """按量级选单位——`:.0f 天` 会把 16 分钟印成「0 天」（我犯过这个渲染错）。"""
    if sec < 60:
        return f"{sec:.2f} 秒"
    if sec < 3600:
        return f"{sec / 60:.1f} 分钟"
    if sec < 86400:
        return f"{sec / 3600:.1f} 小时"
    return f"{sec / 86400:.0f} 天"


def _provenance_note(inbox):
    """按 §C.6 的**实际作用域**报来源证据，分三档，不作超出它的宣称。

    §C.6：脚本产出 Δ≤1s（写入即落盘）；手写件实例 Δ=46 天；且 Δ≈0 **证明不了**非手写。
    故这里只报「是否满足脚本直写签名」，来源是否成立交由 D6 的复现判定。
    """
    try:
        doc = json.loads(inbox.read_text(encoding="utf-8"))
        stamp = datetime.datetime.fromisoformat(doc["produced_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"produced_at 不可解析（{type(exc).__name__}）"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    mtime = datetime.datetime.fromtimestamp(inbox.stat().st_mtime, tz=datetime.timezone.utc)
    delta = abs((mtime - stamp).total_seconds())
    if delta <= 1:
        return (f"produced_at ↔ mtime Δ={_fmt_delta(delta)} ⇒ **脚本直写签名成立**（§C.6：写入即落盘）；"
                f"但 §C.6 明示这**证明不了**「非手写」—— 来源是否成立由 **D6 的复现**判定")
    if delta < 86400:
        return (f"produced_at ↔ mtime Δ={_fmt_delta(delta)} ⇒ **不满足 §C.6 的脚本直写签名**（Δ≤1s）；"
                f"典型成因是**先产出、后拷贝**（内容保留、mtime 被更新），"
                f"也可能是倒填 —— 本判别式分不开这两者，内容来源由 **D6 的复现**判定")
    return (f"produced_at ↔ mtime Δ={_fmt_delta(delta)} ⇒ **倒填时间的老件**"
            f"（§C.6 判别式明确能查的那一类）")


def _reproduce_payload(inbox):
    """按 §C.6 的方法验来源：由 payload 反推 fixture → 重跑 commit.py → 比对字节。

    这是契约认定的**唯一有效**来源证明（命名与 schema 都证明不了谁写的）。
    ⚠ 局限（如实写出，且经变异证明过）：fixture 系**由产物反推** ⇒
      · **抓得到**：序列化偏差（键序/缩进/换行/尾随换行）＋**不由产物反推的字段**不一致
        （如 `rel`：它由序号机制导出，与 `no` 必须同号 —— 本检查正是靠这条抓到过一版
        `no=…-101 / rel=…001` 的坏 payload）
      · **抓不到**：`desc`/`confidence` 等会被反推进 fixture 的内容（改它们复现照样相同）
    故它证明的是「与 commit.py 在该输入下的输出一致」，**不能证明产生时点**。
    """
    try:
        shipped = json.loads(inbox.read_text(encoding="utf-8"))
        rec = shipped["records"][0]
        fx = {"captured_at": f"{rec['date']}T{rec['time']}:00+08:00", "site": "复现用",
              "findings": [{"kind": "hazard", "code": "PPE-NO-SUIT", "label": rec["desc"],
                            "confidence": rec["provenance"]["confidence"],
                            "evidence_ref": rec["provenance"]["evidence_ref"],
                            "source": rec["provenance"]["source_skill"]}]}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return f"无法由 payload 反推 fixture（{type(exc).__name__}: {exc}）", False
    tmp = Path(tempfile.mkdtemp(prefix="cb_repro_"))
    try:
        fxp, out = tmp / "fixture.json", tmp / "inbox.json"
        fxp.write_text(json.dumps(fx, ensure_ascii=False), encoding="utf-8")
        commit = REPO / "skills" / "mes-inspection-intake" / "scripts" / "commit.py"
        proc = subprocess.run([sys.executable, str(commit), "--finding", str(fxp), "--out", str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if not out.is_file():
            return f"复现产出缺失（rc={proc.returncode}）：{(proc.stderr or '').strip()[:120]}", False
        norm = lambda s: re.sub(r'"produced_at": "[^"]*"', '"produced_at": "<N>"', s)  # noqa: E731
        same = norm(inbox.read_text(encoding="utf-8")) == norm(out.read_text(encoding="utf-8"))
        return (("**来源成立**（§C.6 认可的唯一证明）：由 payload 反推 fixture 重跑 ⇒ "
                 "除 produced_at 外**逐字节相同**"
                 "（局限：fixture 系反推，故只证明「与该输入下流水线输出一致」，不证明产生时点）")
                if same else "复现**不一致**：该 payload 与「同输入下 commit.py 的输出」不符"), same
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _resolve_payload(root):
    """payload 就是交付区里的 `mes-data/inbox.json`。返回 (站点根, 文件名, 说明)。

    v1.13 裁决（总监推翻先前「让测试自己造 fixture」）：**交付区应随附 `inbox.json`**。
    理由：默认门若永久红，会被训练成「看见红也不当回事」——**比没有门更糟**。
    故本函数**不再造 fixture**：缺文件就如实报缺，让缺位本身可见。
    ⚠ 文件名**不构成来源证明**——来源另由 `_provenance_note()` 按 §C.6 判据如实报。
    """
    if (root / "mes-data" / "inbox.json").is_file():
        return root, "inbox.json", ""
    return root, "missing", "缺 `mes-data/inbox.json`（交付区应随附该文件，见 v1.13 裁决）"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="contract_bridge_delivery",
                                 description="交付区可重放检查（只读起服务 → 断言）")
    ap.add_argument("--root", default=os.environ.get("MES_PROTO") or str(DEFAULT_ROOT),
                    help="交付区/宿主页目录（默认仓库内 docs/mes-demo）")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    results = []

    def check(cid, title, ok, detail=""):
        results.append((cid, PASS if ok else FAIL, title, detail))
        return ok

    print("=== 交付区可重放检查 ===")
    print(f"root = {root}")

    site, source, note = _resolve_payload(root)
    return _run(site, source, note, results, check)


def _run(site, source, note, results, check):
    root = site
    if source == "missing":
        check("D0", "交付区前置文件存在（或可由 example 现造 fixture）", False, note)
        return _report(results)

    index, inbox = site / "index.html", site / "mes-data" / "inbox.json"
    missing = [str(p) for p in (index, inbox) if not p.is_file()]
    if missing:
        check("D0", "交付区前置文件存在", False, f"缺失：{missing}")
        return _report(results)
    # ⚠ **不得**因「文件名是 inbox.json」就宣称「产出物」——§C.6 的全部意义就是
    #   「schema 合规 / 文件名都证明不了谁写的」。此处只报**按契约判据可查的事实**。
    # 「文件名」不是来源证明；本条只报 §C.6 判据**能查**的事实，来源判定归 D6。
    check("D0", f"前置文件存在（payload 文件 = {inbox.name}）", True,
          (note + "｜" if note else "")
          + f"命名不构成来源证明；本条只报 §C.6 判据可查的事实 ——— {_provenance_note(inbox)}")

    # 期望值从契约现解析（不在本文件存副本）
    sys.path.insert(0, str(HERE.parent))
    import contract_bridge as cb
    try:
        c = cb.parse_contract(cb.DEFAULT_CONTRACT)
    except (cb.ContractError, OSError, ValueError) as exc:
        check("D0b", "契约可解析", False, f"{type(exc).__name__}: {exc}")
        return _report(results)
    check("D0b", "契约可解析", True,
          f"§B.4 data-total={c['idem_total']}｜§C.5 iso 默认={c['iso_default']}｜"
          f"{c['provenance_proof']}")

    disk_bytes = inbox.read_bytes()
    disk_sha = _sha256(disk_bytes)
    rec = json.loads(disk_bytes.decode("utf-8"))["records"][0]
    no, iso = rec["no"], rec["iso"]

    srv, port = _serve(root)
    try:
        # ---- ① 服务真的指向交付区：served 字节 == 磁盘字节
        url = f"http://127.0.0.1:{port}/mes-data/inbox.json"
        try:
            served = urllib.request.urlopen(url, timeout=15).read()
            served_sha = _sha256(served)
            check("D1", "served inbox.json sha256 == 磁盘（服务确实指向交付区）",
                  served_sha == disk_sha,
                  f"served={served_sha[:16]}… 磁盘={disk_sha[:16]}… 一致｜{len(served)}B")
        except Exception as exc:                          # noqa: BLE001
            check("D1", "served inbox.json sha256 == 磁盘（服务确实指向交付区）", False,
                  f"取不到 served 字节：{type(exc).__name__}: {exc}")
            return _report(results)

        # ---- ②③④ 浏览器断言
        from playwright.sync_api import sync_playwright
        import contract_bridge_loader as cbl
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            pageerrors = []
            page.on("pageerror", lambda e: pageerrors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
            page.evaluate(f"location.hash='#view={cbl.VIEW}'")
            page.wait_for_timeout(2000)
            snap = page.evaluate(cbl.SNAP_JS, cbl.VIEW)
            row = page.evaluate(cbl.ROW_JS, [cbl.VIEW, no])
            browser.close()

        if not snap:
            check("D2", "首行 data-no == 交付区记录的号", False, "视图 section 不存在")
            check("D3", "data-total 与分页双处同刷", False, "视图 section 不存在")
            check("D4", "隔离列按 §B.2 渲染", False, "视图 section 不存在")
            return _report(results)

        check("D2", f"首行 data-no == 交付区记录的号（{no}）", snap["firstNo"] == no and bool(row),
              f"首行={snap['firstNo']!r}｜行内 dept={row['dept'] if row else None!r} rel="
              f"{row['rel'] if row else None!r}" if row else f"首行={snap['firstNo']!r}，未找到该行")

        both = (snap["total"] == str(c["idem_total"]), snap["pagerB"] == str(c["idem_total"]))
        check("D3", f"data-total 与 .pagination span b 双处同刷（{c['idem_total']}）", all(both),
              f"[data-count]={snap['total']!r}／分页={snap['pagerB']!r}")

        # ---- ④ 陈旧件检测：交付记录的 iso 必须等于 §C.5 默认值
        want_iso, want_cls = (("未隔离", "badge-neutral") if iso is False
                              else ("已隔离", "badge-quarantine"))
        stale = iso is not c["iso_default"]
        checks = []
        if stale:
            checks.append(f"交付记录 iso={iso!r} ≠ §C.5 默认 {c['iso_default']}"
                          f" —— 疑似**陈旧件**（schema 合规也查不出，见 §C.6 教训）")
        if not row:
            checks.append("找不到该行，无从核对隔离列")
        elif row["isoText"] != want_iso:
            checks.append(f"隔离列显示 {row['isoText']!r}，按 §B.2 应为 {want_iso!r}")
        elif want_cls not in (row["isoClass"] or ""):
            checks.append(f"隔离列徽标 {row['isoClass']!r}，应为 {want_cls!r}")
        check("D4", f"隔离列 = {want_iso}（{want_cls}）；交付记录 iso 符合 §C.5 默认", not checks,
              "；".join(checks) if checks
              else f"{no} iso={iso!r} → 隔离列={row['isoText']}／{row['isoClass']}")

        # ---- ⑥ §C.6 唯一有效的来源证明：复现（逐字节相同）
        repro_detail, repro_ok = _reproduce_payload(inbox)
        check("D6", "§C.6 来源证明：复现（除 produced_at 外逐字节相同）", repro_ok, repro_detail)
        if pageerrors:
            check("D5", "无 pageerror", False, f"{pageerrors[:1]}")
        else:
            check("D5", "无 pageerror（404 网络日志不计）", True, "pageerror = 0")
    finally:
        srv.shutdown()
        srv.server_close()

    print("\n本次判定所依据的字节（第三方可据此复核）：")
    print(f"  root               {root}")
    print(f"  payload 文件       {source}")
    for label, p in (("index.html", index), ("inbox.json", inbox),
                     ("xj-records.json", root / "mes-data" / "xj-records.json")):
        print(f"  {label:<18} " + (f"sha256={_sha256_file(p)}" if p.is_file() else "（不存在）"))
    print(f"  契约               sha256={_sha256_file(cb.DEFAULT_CONTRACT)}")
    print(f"  本脚本             sha256={_sha256_file(Path(__file__))}")
    return _report(results)


def _report(results):
    print()
    for cid, status, title, detail in results:
        print(f"{status:<4}  {cid:<4} {title}")
        if detail:
            print(f"      └─ {detail}")
    n_fail = sum(1 for _, s, _, _ in results if s == FAIL)
    print(f"\n--- 结果：{len(results) - n_fail} PASS / {n_fail} FAIL ---")
    return 0 if n_fail == 0 else 1


# ---------------------------------------------------------------- 变异自检
# 对交付区**副本**逐个注入违规，再**原样重放本命令**（--root 指向副本）——
# 断言必须变红，否则该断言没有效力。顺带证明「这条命令真的可被第三方重放」。
# 同一缺陷在不同实现里落在不同行上（原型 vs 仓库内宿主页）⇒ 给候选锚点，取第一组唯一命中的。
DELIVERY_MUTATIONS = [
    dict(cid="D2", kind="text", rel="index.html", why="注入的号与交付记录不符", cands=[
        ("no: no, rel: strip(r.rel)", "no: no + '-X', rel: strip(r.rel)"),
        ("no:     stripQuotes(r.no),", "no:     stripQuotes(r.no) + '-X',"),
    ]),
    dict(cid="D3", kind="text", rel="index.html", why="分页数字不再同步（双处同刷断一处）", cands=[
        ("if (pg) { pg.textContent = String(n); }", "if (false) { void 0; }"),
        ("if (pgb) { pgb.textContent = String(total); }", "if (false) { void 0; }"),
    ]),
    dict(cid="D4", kind="json", rel="mes-data/inbox.json", why="交付记录 iso 改 true（陈旧件特征）"),
    dict(cid="D6", kind="json", rel="mes-data/inbox.json", json_mut="rel",
         why="payload 的 rel 与序号机制导出值不符（复现失败）"),
]


def selftest_delivery(root):
    import re as _re
    import shutil
    import subprocess
    import tempfile

    inbox = root / "mes-data" / "inbox.json"
    if not inbox.is_file():
        print("=== 交付区检查的变异自检 ===")
        print(f"无法自检：{root} 下没有 mes-data/inbox.json。")
        print("  → 这是**输入问题**（该目录不是「已产出」的交付区），不是测试台失效。")
        print("  → 用 `--root` 指定含产出物的交付区，或先在该目录产出 inbox.json 再跑。")
        return False

    print("=== 交付区检查的变异自检：证明各断言确有抓错能力 ===")
    tmp = Path(tempfile.mkdtemp(prefix="cb_delivery_st_"))
    failures = []
    for i, mut in enumerate(DELIVERY_MUTATIONS):
        copy = tmp / f"m{i:02d}_{mut['cid']}" / "root"
        shutil.copytree(root, copy)
        target = copy / mut["rel"]
        try:
            if mut["kind"] == "text":
                text = target.read_text(encoding="utf-8")
                picked = next(((f, r) for f, r in mut["cands"] if text.count(f) == 1), None)
                if picked is None:
                    hits = "；".join(f"{f!r} 命中 {text.count(f)} 次" for f, _ in mut["cands"])
                    failures.append(f"{mut['cid']} 所有候选锚点均未唯一命中 —— **测试台问题**，"
                                    f"不是被测方问题（{hits}）")
                    print(f"STALE 变异 {mut['cid']} 锚点过期：{hits}")
                    shutil.rmtree(copy.parent, ignore_errors=True)
                    continue
                target.write_text(text.replace(*picked), encoding="utf-8")
            else:
                doc = json.loads(target.read_text(encoding="utf-8"))
                if mut.get("json_mut") == "rel":
                    # 必须改**不由产物反推**的字段：desc/confidence 会被反推进 fixture，
                    # 改它们复现照样相同（变异证明过这一点）。rel 由序号机制导出，改它才露馅。
                    doc["records"][0]["rel"] = doc["records"][0]["rel"] + "9"
                else:
                    doc["records"][0]["iso"] = True
                target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        except (OSError, ValueError, KeyError, IndexError) as exc:
            failures.append(f"{mut['cid']} 变异无法施加（{type(exc).__name__}: {exc}）"
                            f" —— **输入问题**，不是被测方问题")
            print(f"BAD  变异 {mut['cid']} 无法施加：{type(exc).__name__}")
            shutil.rmtree(copy.parent, ignore_errors=True)
            continue
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "--root", str(copy)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        red = _re.search(rf"^FAIL\s+{mut['cid']}\b", proc.stdout, _re.M) is not None
        if not red:
            failures.append(f"{mut['cid']}（{mut['why']}）未变红（rc={proc.returncode}）")
        print(f"{'OK  ' if red else 'BAD '}变异 {mut['cid']:<4} {mut['why']}  → "
              f"{mut['cid']}={'FAIL' if red else '未变红'}")
        shutil.rmtree(copy.parent, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n--- 交付区变异自检：{len(DELIVERY_MUTATIONS) - len(failures)}/"
          f"{len(DELIVERY_MUTATIONS)} 个变异被逮到 ---")
    for f in failures:
        print(f"  BAD {f}")
    return not failures


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.argv.remove("--selftest")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        root = Path(os.environ.get("MES_PROTO") or str(DEFAULT_ROOT)).resolve()
        raise SystemExit(0 if selftest_delivery(root) else 1)
    raise SystemExit(main())
