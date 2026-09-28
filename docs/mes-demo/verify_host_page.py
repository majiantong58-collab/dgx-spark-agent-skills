"""宿主页自检 —— 对 docs/mes-demo/index.html 跑一遍 mes-bridge-contract.md v1.13 的可观测面。

用法（需 playwright；本仓库 .venv 未装，故用系统 python）：
    py -3.14 docs/mes-demo/verify_host_page.py
    # 或 python docs/mes-demo/verify_host_page.py

设计要点：**每条断言都必须能被证伪**。
  · T2/T7 专门用于区分「页面看起来对了」与「真的走了契约的计数公式」——
    种子行直接插 DOM、以及测试中再直插一行，`data-total` 都必须**不动**；
    只有 §B.1 的 addExcRow 能让它 96 → 97。
本脚本会临时清空/改写 docs/mes-demo/mes-data/inbox.json（**随仓库跟踪的交付 fixture**），
结束时（含异常路径，见 `restore_inbox`）逐字节还原为运行前状态。
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import sys
import threading
from pathlib import Path

DEMO = Path(__file__).resolve().parent
REPO = DEMO.parents[1]
INBOX = DEMO / "mes-data" / "inbox.json"
PAGE_PATH = "docs/mes-demo/index.html"
VIEW = "qm-quality-exception"

SNAP = """() => {
  const sec = document.querySelector('.mview[data-view="qm-quality-exception"]');
  const tb  = sec.querySelector('tbody[data-body]');
  const cnt = sec.querySelector('[data-count]');
  const pgb = sec.querySelector('.pagination span b');
  const pgs = sec.querySelector('.pagination .pg-pages b');
  const ban = document.getElementById('mesBridgeBanner');
  return {
    rowNos: Array.from(tb.rows).map(r => r.getAttribute('data-no')),
    created: tb.getAttribute('data-created'),
    total: cnt.getAttribute('data-total'),
    cntText: cnt.textContent.trim(),
    pagerB: pgb.textContent.trim(),
    pagesB: pgs.textContent.trim(),
    banner: ban.hidden ? null : ban.textContent.trim(),
    bannerBg: ban.hidden ? null : getComputedStyle(ban).backgroundColor
  };
}"""


def payload(records, schema="1"):
    return {"schema_version": schema, "produced_by": "mes-demo-verify",
            "produced_at": "2026-01-06T09:30:00+08:00", "records": records}


def rec(no, iso=False, desc="洁净间 2 号工位 1 名人员未穿防静电服（示例数据）",
        dept="生产部", kind="quality-exception"):
    return {"kind": kind, "no": no, "rel": "XJ20260106001", "dept": dept, "desc": desc,
            "iso": iso, "finder": "巡检 Agent", "time": "09:30", "date": "2026-01-06"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Page:
    """一个独立页面会话；记录 console error / pageerror / dialog。"""

    def __init__(self, browser, port):
        self.ctx = browser.new_context()
        self.page = self.ctx.new_page()
        self.cerr, self.perr, self.dialogs = [], [], []
        self.page.on("console", lambda m: self.cerr.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.perr.append(str(e)))
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        self.page.goto(f"http://127.0.0.1:{port}/{PAGE_PATH}", wait_until="load")

    def wait_total(self, want, timeout=5000):
        try:
            self.page.wait_for_function(
                f"() => document.querySelector('[data-count]').getAttribute('data-total') === '{want}'",
                timeout=timeout)
            return True
        except Exception:
            return False

    def go(self, view):
        self.page.evaluate(f"location.hash='#view={view}'")
        self.page.wait_for_timeout(250)

    def snap(self):
        return self.page.evaluate(SNAP)

    def close(self):
        try:
            self.ctx.close()
        except Exception:
            pass


def write_inbox(data):
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    INBOX.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def clear_inbox():
    if INBOX.exists():
        INBOX.unlink()


def snapshot_inbox():
    """记录 inbox.json 的字节与时间戳（不存在则返回 None）。"""
    if not INBOX.exists():
        return None
    st = INBOX.stat()
    return INBOX.read_bytes(), st.st_atime, st.st_mtime


def restore_inbox(snap):
    """把 inbox.json 还原为运行前状态 —— **字节 + mtime 都要还原**。

    ⚠️ 两件事都必须做，理由不同：
      ① `inbox.json` 是**随仓库跟踪**的交付 fixture（不是运行期产物）。本自检有多处会临时
         清空/改写它，**任何一步崩掉都必须还原**，否则会把跟踪文件留在删除状态、污染工作区。
      ② **它的 mtime 本身就是被检验的对象** —— §C.6 的判别式是 `produced_at ↔ mtime` 同秒
         （用来区分「真产出」与「倒填时间的老件」）。而 `write_bytes` 会把 mtime 刷成「现在」，
         于是**每跑一次自检就会把这份证据毁掉一次**。故必须用 `os.utime` 连时间戳一起还原。
    """
    if snap is not None:
        data, atime, mtime = snap
        INBOX.parent.mkdir(parents=True, exist_ok=True)
        INBOX.write_bytes(data)
        os.utime(INBOX, (atime, mtime))
    else:
        clear_inbox()


def main():
    # Windows 控制台默认 GBK，本脚本输出含中文与 ⇒ ⇒ 会 UnicodeEncodeError；这里自带兜底，
    # 使 README 里那条裸命令（不设 PYTHONIOENCODING）也能直接跑。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    keep = snapshot_inbox()
    results = []

    def check(cid, title, ok, detail=""):
        results.append((cid, title, "PASS" if ok else "FAIL", detail))
        print(f"{'PASS' if ok else 'FAIL'}  {cid:<4} {title}" + (f"\n            {detail}" if detail else ""))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP 未安装 playwright（py -3.14 -m pip install playwright && playwright install chromium）")
        return 2

    handler = functools.partial(Quiet, directory=str(REPO))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # ── T11：**按分发的原样**加载（不碰 fixture）—— 期望值全部从产物现推 ──────
            # 必须先跑：它是唯一一条覆盖「评委 clone 下来直接打开」那条路径的断言。
            # 其余各条都自带 fixture，所以分发的 inbox.json 若坏了（dept 越界 / 版本不对），
            # 整轮自检照样全绿 —— 这正是「默认交付就红」最该被逮住的地方。
            shipped = json.loads(INBOX.read_text(encoding="utf-8"))
            srecs = [r for r in shipped.get("records", []) if r.get("kind") == "quality-exception"]
            p = Page(browser, port)
            want_total = str(96 + len(srecs))
            p.wait_total(want_total)
            s11 = p.snap()
            # loader 逐条 afterbegin ⇒ 产物里最后一条在最上
            want_order = [r["no"] for r in reversed(srecs)]
            first = srecs[-1] if srecs else {}
            iso_cell = p.page.evaluate("""() => {
              const b = document.querySelector('.mview[data-view="qm-quality-exception"] '
                        + 'tbody[data-body] tr .cell-iso .badge');
              return b ? b.textContent.trim() : null;
            }""")
            want_iso = "已隔离" if first.get("iso") is True else "未隔离"
            check("T11", "按分发的 inbox.json 原样加载：产物各条落地、计数=96+条数、iso 映射正确、无横幅",
                  bool(srecs) and s11["rowNos"][:len(srecs)] == want_order
                  and s11["total"] == want_total and s11["banner"] is None
                  and iso_cell == want_iso,
                  f"产物 {len(srecs)} 条 期望首行={want_order[:1]} 实际={s11['rowNos'][:1]} "
                  f"total={s11['total']}（期望 {want_total}）iso={iso_cell!r}（期望 {want_iso!r}）banner={s11['banner']!r}")
            p.close()

            # ── T0：临时移走 inbox.json ⇒ §F 静默、96 不变、种子行在场 ─────────────
            clear_inbox()
            p = Page(browser, port)
            p.page.wait_for_timeout(900)
            s = p.snap()
            check("T0", "§F 缺件场景（临时移走 inbox.json）：静默 + data-total=96 + 4 条种子行",
                  s["banner"] is None and s["total"] == "96" and len(s["rowNos"]) == 4
                  and s["pagerB"] == "96" and s["pagesB"] == "12" and not p.perr,
                  f"banner={s['banner']!r} total={s['total']} rows={len(s['rowNos'])} "
                  f"pager={s['pagerB']} pages={s['pagesB']} pageerror={p.perr}")
            p.close()

            # ── T7 先做证伪：直插 DOM 行（不经 addExcRow）⇒ 计数必须不动 ─────────
            p = Page(browser, port)
            p.page.wait_for_timeout(700)
            before = p.snap()["total"]
            p.page.evaluate("""() => {
              const tb = document.querySelector('.mview[data-view="qm-quality-exception"] tbody[data-body]');
              tb.insertAdjacentHTML('afterbegin', '<tr data-no="QA-BYPASS-000"><td>x</td></tr>');
            }""")
            after = p.snap()
            check("T7", "证伪：直插 DOM 行不经 addExcRow ⇒ data-total 不动（证明计数不是数行数）",
                  after["total"] == before and len(after["rowNos"]) == 5 and after["rowNos"][0] == "QA-BYPASS-000",
                  f"直插前 total={before}，直插后 total={after['total']}，行数 {len(after['rowNos'])}（首行 {after['rowNos'][0]}）")
            p.close()

            # ── T1/T2：合规 fixture ⇒ 首行落地 + 96→97 + 分页双处同步 ─────────────
            write_inbox(payload([rec("QA-20260106-101")]))
            p = Page(browser, port)
            arrived = p.wait_total("97")
            s = p.snap()
            check("T1", "合规 inbox.json ⇒ 首行出现该单，data-total 96→97（且无告警横幅）",
                  arrived and s["rowNos"][0] == "QA-20260106-101" and s["created"] == "1"
                  and s["cntText"] == "共 97 条" and s["banner"] is None,
                  f"首行={s['rowNos'][0]} created={s['created']} 计数文案={s['cntText']!r} banner={s['banner']!r}")
            check("T2", "分页双处同刷：条数 96→97、页数 12→13（同源公式的两个投影）",
                  s["pagerB"] == "97" and s["pagesB"] == "13",
                  f"pagerB={s['pagerB']} pagesB={s['pagesB']}")
            check("T1b", "无 console error / 无 pageerror",
                  not p.cerr and not p.perr, f"console={p.cerr} pageerror={p.perr}")

            # ── T3：§B.4 幂等 —— 切走再切回 ≥2 次 ────────────────────────────────
            for _ in range(2):
                p.go("demo-home")
                p.go(VIEW)
            p.page.wait_for_timeout(700)
            s3 = p.snap()
            check("T3", "§B.4 幂等：切走再切回 ×2 ⇒ data-total 保持 97、行不重复",
                  s3["total"] == "97" and s3["created"] == "1"
                  and s3["rowNos"].count("QA-20260106-101") == 1,
                  f"total={s3['total']} created={s3['created']} 该单出现 {s3['rowNos'].count('QA-20260106-101')} 次")
            p.close()

            # ── T4：§C.5 iso 正负映射 ────────────────────────────────────────────
            for iso, want in ((False, "未隔离"), (True, "已隔离")):
                write_inbox(payload([rec("QA-20260106-20%d" % (1 if iso else 2), iso=iso)]))
                p = Page(browser, port)
                p.wait_total("97")
                got = p.page.evaluate("""() => {
                  const r = document.querySelector('.mview[data-view="qm-quality-exception"] tbody[data-body] tr');
                  const b = r.querySelector('.cell-iso .badge');
                  return { text: b.textContent.trim(), cls: b.className };
                }""")
                check(f"T4{'b' if iso else 'a'}", f"§C.5 iso={str(iso).lower()} ⇒ 隔离列「{want}」",
                      got["text"] == want, f"实际 {got['text']!r} class={got['cls']!r}")
                p.close()

            # ── T5：§F 坏 schema_version ⇒ 可见错误横幅 ──────────────────────────
            write_inbox(payload([rec("QA-20260106-301")], schema="99"))
            p = Page(browser, port)
            p.page.wait_for_timeout(900)
            s5 = p.snap()
            check("T5", "§F 坏 schema_version ⇒ 可见错误横幅（含期望/实际版本），不注入",
                  s5["banner"] and "99" in s5["banner"] and s5["total"] == "96",
                  f"banner={s5['banner']!r} bg={s5['bannerBg']} total={s5['total']}")
            p.close()

            # ── T6：§D 注入载荷必须落地为纯文本 ─────────────────────────────────
            evil = 'A" onmouseover="alert(1)" z="'
            write_inbox(payload([rec("QA-20260106-" + evil, desc="异常现象 " + evil, dept="生产部")]))
            p = Page(browser, port)
            p.page.wait_for_timeout(900)
            s6 = p.page.evaluate("""() => {
              const tb = document.querySelector('.mview[data-view="qm-quality-exception"] tbody[data-body]');
              const tr = tb.rows[0];
              return { no: tr.getAttribute('data-no'),
                       attrs: Array.from(tr.attributes).map(a => a.name),
                       injected: tb.querySelectorAll('[onmouseover]').length,
                       desc: tr.cells[3].textContent.trim() };
            }""")
            # 现行必须是被注入的那一行 —— 否则本检查会落在种子行上「空转通过」
            check("T6", "§D 引号载荷不逃逸：被注入行仍只有契约 5 个属性、无 onmouseover、无 dialog",
                  s6["no"].startswith("QA-20260106-")
                  and sorted(s6["attrs"]) == sorted(["data-no", "data-rel", "data-dept", "data-status", "data-date"])
                  and s6["injected"] == 0 and not p.dialogs
                  and "onmouseover" in s6["desc"],
                  f"该行 data-no={s6['no']!r} 属性={s6['attrs']} 全表 [onmouseover] 元素数={s6['injected']} "
                  f"dialog={p.dialogs} 现象列={s6['desc']!r}")
            p.close()

            # ── T8：§F dept 越界 / 未知 kind ⇒ 跳过但**不静默**（横幅列出） ──────
            write_inbox(payload([rec("QA-20260106-401", dept="不存在部"),
                                 rec("QA-20260106-402", kind="dcm-maintenance"),
                                 rec("QA-20260106-403")]))
            p = Page(browser, port)
            p.page.wait_for_timeout(900)
            s8 = p.snap()
            check("T8", "§F dept 越界跳过并列横幅、未知 kind 跳过并计数、合法条照常注入",
                  s8["total"] == "97" and s8["rowNos"][0] == "QA-20260106-403"
                  and s8["banner"] and "不存在部" in s8["banner"] and "未知 kind" in s8["banner"]
                  and s8["bannerBg"] != "rgb(179, 38, 30)",
                  f"total={s8['total']} 首行={s8['rowNos'][0]} banner={s8['banner']!r} bg={s8['bannerBg']}")
            p.close()

            # ── T9：§B.1 全局导出面 —— 经全局入口调用必须真能推动计数 ────────────
            # 上面各条都走 loader 内部直调，**覆盖不到全局导出本身**；
            # 少了本条，「改名把全局打坏」会静默通过整轮自检。
            clear_inbox()
            p = Page(browser, port)
            p.page.wait_for_timeout(700)
            # 全局缺失时必须记 FAIL 而不是抛异常 —— 否则整轮被 traceback 打断，剩余断言全不跑。
            # 「只有一个授权全局」的检查刻意**不写死被禁的旧名**：把该名写进断言，等于
            # 为了断言它不存在而把它留在公开仓库里。改为枚举「所有暴露 exc.addExcRow 的全局」，
            # 既不落字符串，又比检查单个名字更强（任何多余导出都会被抓）。
            g = p.page.evaluate("""() => {
              const hosts = Object.keys(window).filter(k => {
                try { const v = window[k];
                      return !!(v && v.exc && typeof v.exc.addExcRow === 'function'); }
                catch (e) { return false; }
              });
              const out = { hosts: hosts, before: document.querySelector('[data-count]').getAttribute('data-total'),
                            called: false, err: null };
              if (hosts.indexOf('MESHOST') < 0) {
                out.err = 'window.MESHOST.exc.addExcRow 不可达（实际暴露该入口的全局：' + JSON.stringify(hosts) + '）';
                return out;
              }
              try {
                const sec = document.querySelector('.mview[data-view="qm-quality-exception"]');
                window.MESHOST.exc.addExcRow(sec, { no: 'QA-GLOBAL-001', rel: 'XJ20260106009',
                  dept: '生产部', desc: '经全局入口注入（示例数据）', iso: '未隔离',
                  finder: '巡检 Agent', time: '09:00', date: '2026-01-06' });
                out.called = true;
              } catch (e) { out.err = String(e); }
              return out;
            }""")
            s9 = p.snap()
            check("T9", "§B.1 全局导出：MESHOST 是唯一暴露 addExcRow 的全局，且经它调用真能推动计数",
                  g["hosts"] == ["MESHOST"] and g["called"]
                  and s9["total"] == "97" and s9["rowNos"][0] == "QA-GLOBAL-001",
                  f"暴露该入口的全局={g['hosts']} 调用成功={g['called']} err={g['err']} "
                  f"total {g['before']}→{s9['total']} 首行={s9['rowNos'][0]}")
            p.close()

            # ── T10：§E.1 查询入口 `[data-q]` + 回写窗口 —— 窗口内触发的注入必须让开 ──
            # 若 loader 硬插进 600ms 窗口，600ms 后的 innerHTML 回写会把它**整体抹掉**，
            # 于是「行不见了」而计数已 +1 —— 正是 §E.1 要防的那种「界面看着没事、其实丢了」。
            clear_inbox()
            p = Page(browser, port)
            p.page.wait_for_timeout(700)
            probe = p.page.evaluate("""() => {
              const qs = document.querySelectorAll('[data-q]');
              if (qs.length !== 1) { return { n: qs.length, skel: -1 }; }
              qs[0].click();          // 点击与取骨架放在同一 JS turn，避免和 600ms 窗口赛跑
              const tb = document.querySelector('.mview[data-view="qm-quality-exception"] tbody[data-body]');
              return { n: qs.length, skel: tb.querySelectorAll('tr.skeleton').length };
            }""")
            write_inbox(payload([rec("QA-20260106-501")]))
            p.go("demo-home")
            p.go(VIEW)                 # 窗口内触发 viewready ⇒ loader 应让开
            p.page.wait_for_timeout(1500)
            s10 = p.snap()
            check("T10", "§E.1 查询入口 `[data-q]` 唯一；窗口内触发的注入让开回写窗口、未被覆盖抹掉",
                  probe["n"] == 1 and probe["skel"] == 1
                  and s10["total"] == "97" and s10["rowNos"][0] == "QA-20260106-501",
                  f"[data-q]={probe['n']} 骨架行={probe['skel']} total={s10['total']} 首行={s10['rowNos'][0]}")
            p.close()
        finally:
            browser.close()
            srv.shutdown()
            restore_inbox(keep)     # 放在 finally 里：断言抛异常时也要还原跟踪文件

    bad = [r for r in results if r[2] != "PASS"]
    print(f"\n--- {len(results) - len(bad)}/{len(results)} PASS ---")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
