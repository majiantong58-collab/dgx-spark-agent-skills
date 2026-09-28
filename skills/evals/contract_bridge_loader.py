"""T11-loader —— 桥契约测试的**集成半场**（原型侧）。

上半场（contract_bridge.py）验 skill 产出的 JSON 是否符合契约；
本半场验**同一份产出真在原型 DOM 里渲染出来**，且 §B.1/§B.4/§D/§E.1/§F 在真实浏览器里成立。

被测对象：原型 index.html 尾部的 loader 块（`MES 桥 · 原型侧 loader`），
          经由 `MESHOST.exc.addExcRow` 直调宿主原生注入路径（§B.1）。
期望值来源：契约文档现解析（§B.4 的 97 / 切回次数由调用方传入），本文件不存副本。

⚠️ 环境事实（实测，非假设）：
  · loader 用 `fetch('mes-data/inbox.json')` ⇒ **必须走 HTTP**，file:// 下 fetch 被拦、loader 静默跳过。
  · 路由：`location.hash = '#view=qm-quality-exception'` 与侧栏锚点 href 同路径（index.html:1956），
    经 hashchange → routeViews.go() → 派发 `viewready`（index.html:8156），loader 挂在该事件上。
  · `data-total` 不在 section 上，而在 `[data-count]`（index.html:2240 的「共 N 条」）；
    分页数字在 `.pagination span b`。§B.1 要求两处同刷。
  · 缺文件时 Chromium 会打一条 404 网络日志 —— 那是浏览器行为，**不是失败**，本模块只看 DOM 与 pageerror。
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
VIEW = "qm-quality-exception"        # 契约 §C.7 会覆盖它（值带 qm- 前缀，由契约给出）
ISO_CELL = ".cell-iso"
# 整组条目的 id：与逐条 T11a…T11i 区分开，但一眼看出是同一族（原先整组也印 `T11`，易被当成单条）
GROUP = "T11*"
GROUP_TITLE = "产出 → 原型 DOM 真渲染（整组 T11a–T11i）"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):        # 静音：404 网络日志是浏览器行为，不进断言
        pass


def prerequisites(proto_root):
    """返回 (ok, reason)。前置不满足时由调用方记 SKIP 并写明原因，绝不静默。"""
    proto_root = Path(proto_root)
    if not (proto_root / "index.html").is_file():
        return False, f"找不到原型 {proto_root / 'index.html'}"
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False, "未安装 playwright（pip install playwright && playwright install chromium）"
    return True, ""


def _serve(root):
    handler = functools.partial(_Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _build_site(proto_root, site):
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    shutil.copy2(Path(proto_root) / "index.html", site / "index.html")
    assets = Path(proto_root) / "assets"
    if assets.is_dir():
        shutil.copytree(assets, site / "assets")


def _produce(skill_root, fixture, out_path, extra=()):
    """用真 skill 产出 inbox.json —— T11 要验的是「skill 产出的号真被渲染」，不是手写 JSON。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(Path(skill_root) / "scripts" / "commit.py"),
         "--finding", str(fixture), "--out", str(out_path), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


SNAP_JS = """(v) => {
  const sec = document.querySelector('.mview[data-view="'+v+'"]');
  if (!sec) return null;
  const tb = sec.querySelector('tbody[data-body]');
  const cnt = sec.querySelector('[data-count]');
  const pgb = sec.querySelector('.pagination span b');
  const ban = document.getElementById('mesBridgeBanner');
  const rows = tb ? Array.from(tb.rows).map(r => r.getAttribute('data-no')) : [];
  return {
    rowNos: rows, rowCount: rows.length, firstNo: rows[0] || null,
    created: tb ? tb.getAttribute('data-created') : null,
    total: cnt ? cnt.getAttribute('data-total') : null,
    cntText: cnt ? cnt.textContent.trim() : null,
    pagerB: pgb ? pgb.textContent.trim() : null,
    banner: ban ? ban.innerText.trim() : null,
    bannerErr: ban ? /rgb\\(179, 38, 30\\)/.test(getComputedStyle(ban).backgroundColor) : false
  };
}"""

ROW_JS = """([v, no]) => {
  const sec = document.querySelector('.mview[data-view="'+v+'"]');
  const tb = sec && sec.querySelector('tbody[data-body]');
  const r = tb && tb.querySelector('tr[data-no="'+no+'"]');
  if (!r) return null;
  const iso = r.querySelector('.cell-iso');
  const bdg = iso && iso.querySelector('.badge');
  return { rel: r.getAttribute('data-rel'), dept: r.getAttribute('data-dept'),
           status: r.getAttribute('data-status'), date: r.getAttribute('data-date'),
           isoText: iso ? iso.innerText.trim() : null,
           isoClass: bdg ? bdg.className : null };
}"""


class _Session:
    """一个独立的浏览器上下文 + 控制台记录。每个场景一个，避免场景间互相污染。"""

    def __init__(self, pw, port):
        self.browser = pw.chromium.launch()
        self.page = self.browser.new_page()
        self.logs, self.pageerrors = [], []
        self.page.on("console", lambda m: self.logs.append(f"{m.type}: {m.text}"))
        self.page.on("pageerror", lambda e: self.pageerrors.append(str(e)))
        self.port = port

    def load(self, hash_=""):
        self.page.goto(f"http://127.0.0.1:{self.port}/index.html{hash_}", wait_until="load")
        return self

    def go(self, view=VIEW, settle=1800):
        self.page.evaluate(f"location.hash='#view={view}'")
        self.page.wait_for_timeout(settle)
        return self

    def snap(self, view=VIEW):
        return self.page.evaluate(SNAP_JS, view)

    def row(self, no, view=VIEW):
        return self.page.evaluate(ROW_JS, [view, no])

    def close(self):
        try:
            self.browser.close()
        except Exception:                     # noqa: BLE001 - 关闭失败不该污染测试结论
            pass


def _write_inbox(site, payload):
    d = Path(site) / "mes-data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "inbox.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _reset_mes_data(site):
    """契约 §C.6 重跑须知：commit.py 是**追加**语义，重跑前必须清空 mes-data，
    否则记录累积（§C.6 明确警告 data-total 会变 98）。"""
    shutil.rmtree(Path(site) / "mes-data", ignore_errors=True)


# ---------------------------------------------------------------- loader 侧变异自检
# 每条 T11 断言都必须能被「拆掉它要守的那行 loader 代码」抓红 —— 抓不到即证明该断言空转。
# 每个缺陷给**多组候选锚点**：不同实现（原型 / 宿主页）写法不同，同一缺陷落在不同行上。
# 取第一组「唯一命中」的；全都不中 → 报 AnchorStale（测试台问题），绝不猜。
_DEDUP_PROTO = ("if (injectedNos[no]) { dup++; return; }", ";")
_DEDUP_HOST = ("if (injectedNos[o.no]) { dup++; return; }", ";")
LOADER_MUTATIONS = [
    dict(cid="T11a", why="注入的号与产出不符", cands=[
        ("no: no, rel: strip(r.rel)", "no: no + '-X', rel: strip(r.rel)"),
        ("no:     stripQuotes(r.no),", "no:     stripQuotes(r.no) + '-X',"),
    ]),
    dict(cid="T11b", why="分页数字不再同步（§B.1 双处同刷断一处）", cands=[
        ("if (pg) { pg.textContent = String(n); }", "if (false) { void 0; }"),
        ("if (pgb) { pgb.textContent = String(total); }", "if (false) { void 0; }"),
    ]),
    dict(cid="T11c", why="拆掉 §B.4 幂等闸（切回重复注入）",
         cands=[_DEDUP_PROTO, _DEDUP_HOST]),
    dict(cid="T11d", why="去掉 iso 负映射 —— 即 v1.5 那个静默 bug 原形", cands=[
        ("iso: r.iso === false ? '未隔离' : '已隔离',", "iso: r.iso,"),
        ("iso:    r.iso === true ? ISO_QUARANTINED : ISO_CLEAR,", "iso:    r.iso,"),
    ]),
    dict(cid="T11e", why="跳过/未知 kind 不再出横幅（§F）", cands=[
        ("if (skip.length || unknown) { banner('warn', lines); }",
         "if (false) { banner('warn', lines); }"),
        ("if (lines.length) { banner('warn', lines); }",
         "if (false) { banner('warn', lines); }"),
    ]),
    dict(cid="T11f", why="注入不再让开「查询」回写窗口（§E.1）", cands=[
        ("if (Date.now() < queryBusyUntil) { return; }", ""),
        ("if (Date.now() < queryBusyUntil) {", "if (false) {"),
    ]),
    dict(cid="T11g", why="多条 records 时只看第一条（覆盖不全）", cands=[
        ("var recs = (data && data.records) || [];",
         "var recs = ((data && data.records) || []).slice(0, 1);"),
        ("var recs = Array.isArray(data.records) ? data.records : [];",
         "var recs = (Array.isArray(data.records) ? data.records : []).slice(0, 1);"),
    ]),
    dict(cid="T11h", why="拆掉按 no 的去重 ⇒ 部分失败后切回把已成功的重注一遍",
         cands=[_DEDUP_PROTO, _DEDUP_HOST]),
    dict(cid="T11i", why="把 DOM 的 data-view 值也当成合法 kind（§C.7 混用，静默放行）", cands=[
        ("if (!r || r.kind !== 'quality-exception') { unknown++; return; }",
         "if (!r || (r.kind !== 'quality-exception' && r.kind !== VIEW)) { unknown++; return; }"),
        ("if (r.kind !== KIND) { unknownKind++; return; }",
         "if (r.kind !== KIND && r.kind !== VIEW) { unknownKind++; return; }"),
    ]),
]


def _sub_once(text, cands, cid="", where="index.html"):
    """候选锚点里取第一组唯一命中的。全都不中 → 报 AnchorStale（测试台问题，不是被测方违契）。"""
    from contract_bridge import AnchorStale, _near_misses   # 延迟导入，避免与主套件成环
    for find, repl in cands:
        if text.count(find) == 1:
            return text.replace(find, repl)
    hits = "\n".join(f"         命中 {text.count(f)} 次：{f!r}" for f, _ in cands)
    tok, near = _near_misses(text, cands[0][0])
    body = "\n".join(f"           :{ln:<6} {txt[:110]}" for ln, txt in near)
    tail = (f"  → 近似候选（含 {tok!r}）：\n{body}" if near else "  → 找不到近似候选。")
    raise AnchorStale(
        f"[变异 {cid}] 所有候选锚点均未唯一命中（期望恰好 1 次）：\n{hits}\n"
        f"  → 定位：{where}\n"
        f"  → 这是**测试台问题**（锚点过期），不是被测方违契 —— 请更新锚点，不要改期望值。\n"
        f"{tail}")


def selftest_loader(proto_root, skill_root, fixture, idem_total, idem_switches, workdir):
    """对原型副本逐个注入 loader 违规，断言对应 T11 检查变红。返回 True=全部逮到。"""
    print("=== loader 侧变异自检：证明 T11 各断言确有抓错能力 ===")
    from contract_bridge import AnchorStale
    proto_root, tmp = Path(proto_root), Path(workdir)
    tmp.mkdir(parents=True, exist_ok=True)
    html = (proto_root / "index.html").read_text(encoding="utf-8")
    failures, stale = [], []
    for i, mut in enumerate(LOADER_MUTATIONS):
        case = tmp / f"m{i:02d}_{mut['cid']}"
        mutated = case / "proto"
        mutated.mkdir(parents=True, exist_ok=True)
        try:
            (mutated / "index.html").write_text(
                _sub_once(html, mut["cands"], mut["cid"],
                          where=str(proto_root / "index.html")), encoding="utf-8")
        except AnchorStale as exc:              # 逐条降级：一个锚点过期不该让整轮崩掉
            stale.append(str(exc))
            print(f"STALE 变异 {mut['cid']:<5} {mut['why']}\n"
                  f"      → 锚点过期，本变异**未执行**（测试台问题，非被测方问题）")
            shutil.rmtree(case, ignore_errors=True)
            continue
        assets = proto_root / "assets"
        if assets.is_dir():
            shutil.copytree(assets, mutated / "assets")
        results = run_loader_checks(mutated, skill_root, fixture, case / "out",
                                    idem_total, idem_switches)
        got = {r["id"]: r["status"] for r in results}
        red = got.get(mut["cid"]) == FAIL
        if not red:
            failures.append(f"{mut['cid']}（{mut['why']}）未变红：{got.get(mut['cid'])}")
        print(f"{'OK  ' if red else 'BAD '}变异 {mut['cid']:<5} {mut['why']}  → {mut['cid']}={got.get(mut['cid'])}")
        shutil.rmtree(case, ignore_errors=True)
    total = len(LOADER_MUTATIONS)
    ran = total - len(stale)
    print(f"\n--- loader 变异自检：{ran - len(failures)}/{ran} 个变异被逮到 ---")
    print(f"    分母 = 本文件 LOADER_MUTATIONS 条目数：共 {total} 条；"
          f"执行 {ran}，锚点过期未执行 {len(stale)}")
    print("    该表随测试文件一起冻结 ⇒ **分母不应随运行变动**；若变了，"
          "要么表被改（须重冻），要么执行数被 stale 扣掉（上一行已列出）。")
    for f in failures:
        print(f"  BAD {f}")
    if stale:
        print(f"\n!! 测试台问题（{len(stale)} 条，**不是被测方违契**）——请更新下列锚点后重跑：\n")
        for s in stale:
            print(s)
    return not failures and not stale


def run_loader_checks(proto_root, skill_root, fixture, workdir, idem_total, idem_switches,
                      base_total=None, kind_value=None, view_value=None, query_attr=None):
    """跑集成半场。返回 results（与主套件同格式的 dict 列表）。异常一律记 FAIL，不外抛。

    base_total / kind_value / view_value 均由**契约现解析**后传入（§B.1 的 base、§C.7 的映射），
    不在此硬编码——宿主页与原型在这些点上的实现细节不同，硬编码会把「契约要求」误写成「原型现状」。
    """
    global VIEW                       # §C.7：data-view 带 qm- 前缀，值由契约给出（本模块只见一次）
    if view_value:
        VIEW = view_value
    base = base_total if base_total is not None else idem_total - 1
    results = []

    def add(cid, title, status, detail=""):
        results.append({"id": cid, "title": title, "status": status, "detail": detail})

    ok, reason = prerequisites(proto_root)
    if not ok:
        add(GROUP, GROUP_TITLE, SKIP, reason)
        return results

    from playwright.sync_api import sync_playwright

    site = Path(workdir) / "loader" / "site"
    _build_site(proto_root, site)
    inbox = site / "mes-data" / "inbox.json"

    produced = _produce(skill_root, fixture, inbox)
    if produced.returncode != 0:
        add(GROUP, GROUP_TITLE, FAIL,
            f"skill 产出失败 rc={produced.returncode}：{(produced.stderr or '').strip()[:160]}")
        return results
    rec = json.loads(inbox.read_text(encoding="utf-8"))["records"][0]
    no, dept = rec["no"], rec["dept"]

    srv, port = _serve(site)
    try:
        with sync_playwright() as pw:
            _scenarios(pw, port, skill_root, site, inbox, no, dept, rec,
                       idem_total, idem_switches, base, view_value or VIEW,
                       query_attr, add)
    except Exception as exc:                  # noqa: BLE001 - 浏览器不可用等，记 FAIL 而非崩掉整套
        add(GROUP, GROUP_TITLE, FAIL,
            f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        srv.shutdown()
        srv.server_close()
    return results


def _scenarios(pw, port, skill_root, site, inbox, no, dept, rec, idem_total, idem_switches,
               batch_base, view, query_attr, add):
    # ---------- T11a 真渲染 + T11b §B.1 计数双处同刷 ----------
    s = _Session(pw, port).load().go()
    try:
        snap = s.snap()
        row = s.row(no)
        problems = []
        if not snap:
            problems.append("视图 section 不存在")
        else:
            if snap["firstNo"] != no:
                problems.append(f"首行 data-no={snap['firstNo']!r}，期望 skill 产出的 {no!r}")
            if not row:
                problems.append(f"DOM 中找不到 data-no={no!r} 的行")
            else:
                if row["dept"] != dept:
                    problems.append(f"data-dept={row['dept']!r}，期望 {dept!r}")
                if row["rel"] != rec["rel"]:
                    problems.append(f"data-rel={row['rel']!r}，期望 {rec['rel']!r}")
                if row["date"] != rec["date"]:
                    problems.append(f"data-date={row['date']!r}，期望 {rec['date']!r}")
                if row["status"] != "found":
                    problems.append(f"data-status={row['status']!r}，期望 'found'（§B.2 写死）")
                # 期望文本**由产出记录现推**：契约 §C.5 的默认值会变，测试不预设 true/false
                want_iso, want_cls = (("未隔离", "badge-neutral") if rec["iso"] is False
                                      else ("已隔离", "badge-quarantine"))
                if row["isoText"] != want_iso:
                    problems.append(f"iso={rec['iso']!r} 时隔离列显示 {row['isoText']!r}，"
                                    f"期望 {want_iso!r}")
                if want_cls not in (row["isoClass"] or ""):
                    problems.append(f"iso={rec['iso']!r} 时徽标类名 {row['isoClass']!r}，"
                                    f"期望含 {want_cls!r}")
            if snap["banner"]:
                problems.append(f"成功注入却出现横幅：{snap['banner'][:80]!r}")
        add("T11a", "产出 → 原型 DOM 真渲染（首行 data-no == skill 产出的号）",
            PASS if not problems else FAIL,
            "；".join(problems) if problems else f"{no} 已渲染，rel={rec['rel']} dept={dept} 隔离列=已隔离")

        # §B.1：data-total 与分页数字必须双处同刷（原型 refreshExcTotals :9209 一次改两处）
        problems = []
        if not snap:
            problems.append("视图 section 不存在")
        else:
            if snap["total"] != str(idem_total):
                problems.append(f"[data-count] data-total={snap['total']!r}，期望 {idem_total}")
            # 契约只要求「页头『共 N 条』显示正确的 N」（§B.1 注），**不要求该元素文本恰为裸数字**：
            # 原型把裸数字放在内层 <b>，宿主页把「共 N 条」整体放在带 data-count 的元素上——两者都合规。
            # 原先此处写成严格相等，等于把「原型现状」误当成「契约要求」。
            if str(idem_total) not in (snap["cntText"] or ""):
                problems.append(f"[data-count] 文本={snap['cntText']!r}，其中应含 {idem_total}")
            if snap["pagerB"] != str(idem_total):
                problems.append(f".pagination span b={snap['pagerB']!r}，期望 {idem_total}")
            if snap["created"] != "1":
                problems.append(f"data-created={snap['created']!r}，1 条产出应使基数 +1")
        add("T11b", f"§B.1 计数双处同刷（均 == {idem_total}）", PASS if not problems else FAIL,
            "；".join(problems) if problems
            else f"[data-count]={snap['total']}／文本={snap['cntText']}／分页={snap['pagerB']}／data-created={snap['created']}")

        # ---------- T11c §B.4 幂等：切走再切回 ×N，data-total 不变 ----------
        before = snap
        for _ in range(idem_switches):
            s.go("qm-inspection-list", settle=800)      # 切走
            s.go(VIEW, settle=1200)                     # 切回（viewready 重触发）
        after = s.snap()
        problems = []
        if not after:
            problems.append("切回后视图 section 不存在")
        else:
            if after["total"] != str(idem_total):
                problems.append(f"data-total 漂移到 {after['total']!r}（期望恒为 {idem_total}）")
            if after["pagerB"] != str(idem_total):
                problems.append(f"分页数字漂移到 {after['pagerB']!r}")
            if after["rowCount"] != before["rowCount"]:
                problems.append(f"行数从 {before['rowCount']} 变成 {after['rowCount']}")
            dups = {n for n in after["rowNos"] if after["rowNos"].count(n) > 1}
            if dups:
                problems.append(f"重复注入的行：{sorted(dups)}")
        add("T11c", f"§B.4 幂等：切走再切回 ×{idem_switches}，data-total 保持 {idem_total}",
            PASS if not problems else FAIL,
            "；".join(problems) if problems
            else f"data-total={after['total']}、行数={after['rowCount']}、无重复 data-no")
    finally:
        s.close()

    # ---------- T11d iso 负映射（§B.2 v1.5：布尔留语义层，呈现映射在 loader） ----------
    payload = json.loads(inbox.read_text(encoding="utf-8"))
    payload["records"][0]["iso"] = False
    _write_inbox(site, payload)
    s = _Session(pw, port).load().go()
    try:
        row = s.row(no)
        problems = []
        if not row:
            problems.append(f"iso:false 的记录未渲染（找不到 {no}）")
        elif row["isoText"] != "未隔离":
            problems.append(f"iso:false 却显示 {row['isoText']!r} —— 正是 v1.5 的要害："
                            f"直传布尔 false 会被静默显示成「已隔离」")
        elif "badge-neutral" not in (row["isoClass"] or ""):
            problems.append(f"文案对了但徽标类名是 {row['isoClass']!r}，期望含 'badge-neutral'"
                            f"（§B.2：未隔离 = neutral，已隔离 = quarantine）")
        add("T11d", "iso:false → 隔离列显示「未隔离」(badge-neutral)（§B.2 v1.5 负映射）",
            PASS if not problems else FAIL,
            "；".join(problems) if problems
            else f"{no} 隔离列=未隔离／{row['isoClass']}")
    finally:
        s.close()

    # ---------- T11e §F 失败可见性四例 ----------
    problems, seen = [], []
    cases = [
        ("坏版本", {"schema_version": "9", "records": []}, True, "schema_version"),
        ("缺文件", None, False, None),
        ("未知 kind", {"schema_version": "1", "records": [{"kind": "unknown-x", "no": "Z-1"}]},
         True, "kind"),
        ("空数组", {"schema_version": "1", "records": []}, False, None),
    ]
    for label, payload, want_banner, needle in cases:
        if payload is None:
            if inbox.exists():
                inbox.unlink()
        else:
            _write_inbox(site, payload)
        s = _Session(pw, port).load().go()
        try:
            snap = s.snap()
            got_banner = bool(snap and snap["banner"])
            if got_banner != want_banner:
                problems.append(f"{label}：横幅{'出现' if got_banner else '缺失'}，期望"
                                f"{'可见' if want_banner else '静默'}（{snap['banner'][:70] if snap and snap['banner'] else ''}）")
            elif want_banner and needle and needle not in (snap["banner"] or ""):
                problems.append(f"{label}：横幅未提到 {needle!r}（{snap['banner'][:70]!r}）")
            else:
                seen.append(f"{label}={'横幅' if got_banner else '静默'}✓")
            # 缺文件场景：404 网络日志是浏览器行为，只认 pageerror
            if s.pageerrors:
                problems.append(f"{label}：pageerror 非空 {s.pageerrors[:1]}")
        finally:
            s.close()
    add("T11e", "§F 失败可见性四例（坏版本/缺文件/未知 kind/空数组）", PASS if not problems else FAIL,
        "；".join(problems) if problems else "；".join(seen))

    # ---------- T11g §B.4 多条 records：首轮全部注入，切回全部跳过 ----------
    d8 = str(rec["date"]).replace("-", "")
    multi_fx = Path(site).parent / "multi-findings.json"   # 放在 site 根之外，避免被服务出去
    multi_fx.write_text(json.dumps({
        "captured_at": f"{rec['date']}T14:32:00+08:00", "site": "洁净间 3 号工位",
        "findings": [
            {"kind": "hazard", "code": "SAFE", "label": f"洁净间 {i} 号工位 1 名人员未穿防静电服",
             "confidence": 0.8, "evidence_ref": f"mes-data/evidence/m{i}.jpg"}
            for i in (1, 2, 3)
        ],
    }, ensure_ascii=False), encoding="utf-8")
    _reset_mes_data(site)
    proc = _produce(skill_root, multi_fx, inbox)
    problems = []
    if proc.returncode != 0:
        problems.append(f"多条 records 夹具产出失败 rc={proc.returncode}："
                        f"{(proc.stderr or '').strip()[:120]}")
    else:
        mnos = [r["no"] for r in json.loads(inbox.read_text(encoding="utf-8"))["records"]]
        want = None
        s = _Session(pw, port).load()
        try:
            # 基数取自**契约 §B.1**（base=96），不再靠「注入前快照」：宿主页可能在加载即路由并注入，
            # 读到的「基数」其实是注入后的值（实测 99），那样期望值会整体偏移。
            want = batch_base + len(mnos)
            s.go(view, settle=2200)
            first = s.snap()
            for _ in range(2):
                s.go("qm-inspection-list", settle=800)
                s.go(view, settle=1200)
            final = s.snap()
            if first["total"] != str(want):
                problems.append(f"首轮 data-total={first['total']!r}，期望 {batch_base}+{len(mnos)}={want}")
            missing = sorted(set(mnos) - set(final["rowNos"]))
            if missing:
                problems.append(f"有记录未渲染：{missing}")
            if final["total"] != str(want):
                problems.append(f"切回后 data-total={final['total']!r}，期望恒为 {want}"
                                f" —— 多条 records 下若按「跑过一轮没有」而非按 no 去重，这里会翻倍")
            if final["pagerB"] != str(want):
                problems.append(f"分页数字={final['pagerB']!r}，期望 {want}")
            dups = sorted({n for n in final["rowNos"] if final["rowNos"].count(n) > 1})
            if dups:
                problems.append(f"重复注入的行：{dups}")
        finally:
            s.close()
    add("T11g", f"§B.4 多条 records：首轮全注入、切回×{idem_switches} 全跳过",
        PASS if not problems else FAIL,
        "；".join(problems) if problems
        else f"基数→{want}，切回后仍 {want}，无重复 data-no")

    # ---------- T11h §B.4 部分注入后切回不重复（去重键必须是 no，不是「跑过一轮没有」）----------
    # 构造输入（**非夹具**，不宣称 skill 能检出这些）：第 2 条 dept 越界 ⇒ 首轮只落地 2 条。
    # 若实现把闸开在「本轮跑过没有」，切回会把**已成功的那 2 条再注入一遍** ⇒ data-total 翻倍。
    payload_b = {"schema_version": "1", "records": [
        {"kind": "quality-exception", "no": f"QA-{d8}-901", "rel": f"XJ{d8}901", "dept": "生产部",
         "desc": "构造输入 A", "iso": False, "finder": "巡检 Agent", "time": "14:32", "date": rec["date"]},
        {"kind": "quality-exception", "no": f"QA-{d8}-902", "rel": f"XJ{d8}902", "dept": "制造部",
         "desc": "构造输入 B（部门越界，应被跳过）", "iso": False, "finder": "巡检 Agent",
         "time": "14:32", "date": rec["date"]},
        {"kind": "quality-exception", "no": f"QA-{d8}-903", "rel": f"XJ{d8}903", "dept": "设备部",
         "desc": "构造输入 C", "iso": False, "finder": "巡检 Agent", "time": "14:33", "date": rec["date"]},
    ]}
    _reset_mes_data(site)
    _write_inbox(site, payload_b)
    want_n, landed, problems = 2, [], []
    s = _Session(pw, port).load()
    try:
        want = batch_base + want_n                  # 基数取自契约 §B.1，理由同 T11g
        s.go(view, settle=2200)
        first = s.snap()
        landed = [n for n in first["rowNos"] if n in {r["no"] for r in payload_b["records"]}]
        for _ in range(2):
            s.go("qm-inspection-list", settle=800)
            s.go(view, settle=1200)
        final = s.snap()
        if first["total"] != str(want):
            problems.append(f"首轮 data-total={first['total']!r}，期望 {batch_base}+{want_n}={want}"
                            f"（3 条里 1 条部门越界）")
        if "枚举" not in (first["banner"] or ""):
            problems.append(f"首轮未就部门越界出可见横幅（§F）：{(first['banner'] or '')[:70]!r}")
        if final["total"] != str(want):
            problems.append(f"切回后 data-total={final['total']!r}，期望仍为 {want}"
                            f" ⇒ **去重键不是 no**：部分失败后把已成功的那几条重注了一遍")
        dups = sorted({n for n in final["rowNos"] if final["rowNos"].count(n) > 1})
        if dups:
            problems.append(f"重复注入的行：{dups}")
    finally:
        s.close()
    add("T11h", "§B.4 部分注入后切回不重复（去重键 = no，且标记点在成功之后）",
        PASS if not problems else FAIL,
        "；".join(problems) if problems
        else f"首轮落地 {len(landed)}/3 条（越界那条被跳过并出横幅），切回×2 后仍 {want}、无重复")

    # ---------- T11i §C.7 kind ↔ data-view 混用：差一个 qm- 前缀，混用**不得静默** ----------
    # 这正是 R2-B 实现宿主页时实踩的坑：把 DOM 的 data-view 值填进了 JSON 的 kind。
    # 契约 §C：非 quality-exception 的 kind 本版忽略；§F：忽略必须计数并出横幅 ⇒ 不得静默。
    mixed_no = f"QA-{d8}-950"
    _reset_mes_data(site)
    _write_inbox(site, {"schema_version": "1", "records": [
        {"kind": VIEW, "no": mixed_no, "rel": f"XJ{d8}950", "dept": "生产部",
         "desc": "构造输入（kind 误用了 DOM 的 data-view 值）", "iso": False,
         "finder": "巡检 Agent", "time": "14:32", "date": rec["date"]},
    ]})
    s = _Session(pw, port).load()
    try:
        s.go(view, settle=2200)
        snap = s.snap()
        banner = snap["banner"] or ""
        problems = []
        if mixed_no in snap["rowNos"]:
            problems.append(f"kind 误用 DOM 值（{VIEW!r}）却被当成合法单据注入了")
        if snap["total"] != str(batch_base):
            problems.append(f"data-total={snap['total']!r}，期望仍为基数 {batch_base}（该条不该落地）")
        if "kind" not in banner:
            problems.append(f"§F：忽略未知 kind 未出可见横幅 ⇒ **静默**（正是 §C.7 警告的形态）："
                            f"{banner[:70]!r}")
        add("T11i", f"§C.7 kind 误用 DOM 值（{VIEW!r}）不得静默：不落地 + 可见横幅",
            PASS if not problems else FAIL,
            "；".join(problems) if problems
            else f"未落地（data-total 仍 {batch_base}），横幅已标注未知 kind")
    finally:
        s.close()

    # ---------- T11f §E.1 竞态窗口：注入不得落在「查询」的 600ms 回写窗口内 ----------
    # ⚠ 必须显式写回一条**有记录**的 payload —— T11e 最后一例是空数组、且「缺文件」一例删过文件，
    #   沿用循环残留变量会让本场景注入空数据、断言全部空转（上一版就是这么假过的）。
    _write_inbox(site, {"schema_version": "1", "records": [rec]})
    # ⚠ 不少宿主页在**加载时就路由到默认视图**（原型不会）⇒ 若直接加载，那条记录在加载那刻就已注入，
    #   等我们点「查询」时已无单可插，断言会**假红**。先落在一个中性 hash 上，确保
    #   「本视图的首次 viewready」由本场景自己触发，这条断言才测的是 §E.1 而不是页面的默认路由。
    s = _Session(pw, port).load(hash_="#view=__probe__")
    try:
        # ⚠ **查询触发方式是契约没规定的**（§E.1 只写了危险与「不得同帧」，没写入口）。
        #   原型靠点 `[data-q]`；宿主页暴露全局 `runQuery()`。两者都合规 ⇒ 本测试两种都试，
        #   都没有时**不判 FAIL 而记「不适用」**：没有查询入口 ⇒ 该危险压根无法发生。
        # §E.1(v1.13)：宿主**须**把「查询」触发元素标记为约定的 `[data-q]`。
        # ⇒ 本仓库宿主只走单路；**缺失即违约**（原先的多路探测 + 记「不适用」已按裁决去掉）。
        # 属性名从契约现解析（不硬编码），契约改则测试跟随。
        qattr = query_attr or "[data-q]"
        trig = s.page.evaluate(f"""() => {{
          var sec = document.querySelector('.mview[data-view="{VIEW}"]');
          var el = (sec || document).querySelector('{qattr}') ||
                   document.querySelector('{qattr}');
          if (el) {{ el.click(); return '{qattr}'; }}
          return '';
        }}""")
        if not trig:
            add("T11f", "§E.1 竞态：注入让开「查询」回写窗口", FAIL,
                f"本页找不到 §E.1(v1.13) 约定的查询入口 `{qattr}` ⇒ 宿主未按约定标记，"
                f"**违约**（契约：宿主须提供可识别的查询入口）。"
                f"此时既测不到让位行为，也不该记「不适用」——不适用会把违约洗成沉默。")
            return
        s.go(VIEW, settle=300)
        early = s.snap()
        s.page.wait_for_timeout(1600)
        late = s.snap()
        problems = []
        if not early or not late:
            problems.append("视图 section 不存在")
        else:
            if early["rowCount"] and no in early["rowNos"]:
                problems.append(f"注入落在查询窗口内（未让位，触发方式={trig}）"
                                f"—— 该行会被稍后的整体回写抹掉")
            if no not in late["rowNos"]:
                problems.append(f"查询窗口过后仍未注入 {no}（应延后补注入且存活）")
            if any(r == no for r in late["rowNos"][1:]):
                problems.append("延后补注入造成重复行")
        add("T11f", "§E.1 竞态：注入让开「查询」回写窗口且延后存活",
            PASS if not problems else FAIL,
            "；".join(problems) if problems
            else f"触发={trig}；窗口内未注入（{early['rowCount']} 行）→ "
                 f"窗口后已注入且存活（{late['rowCount']} 行）")
    finally:
        s.close()
