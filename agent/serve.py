#!/usr/bin/env python
"""MES Agent 的 HTTP 外壳：把循环挂到 MES 页面旁边。

它做的事很小：收到问题 → 跑 `mes_agent.run()` → 把答案和**走过的工具调用**一起返回。
真正干活的是 `mes_agent.py`；本文件只管进出。

刻意不做的两件事
----------------
1. **不改 MES 原型**。原型被 iframe 进来显示，它自己一行代码都不用动，
   §8.5「MES 侧没有任何服务」对**原型本身**依然成立 —— 助手是外挂在旁边的。
2. **不装任何包**。标准库 `http.server`。且**必须用 ThreadingHTTPServer**：
   单线程 + keep-alive 会让一条空闲连接把服务整个卡死（2026-09-28 在 ui/server.py
   实测过，判据见 .scratch/repro_8770_hang.py）。一次推理要十几秒，
   单线程的话页面在等的时候连静态资源都取不到。

用法
----
    py -3 agent/serve.py                       # 默认 8791
    py -3 agent/serve.py --mes-url http://127.0.0.1:8790/index.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True

import mes_agent  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# 🔴 为什么要有反代：助手的主题要跟 MES 同步，就得能读到 iframe 的 data-theme。
# 而跨源读不到 —— 8790 与 8791 是**不同 origin**（localStorage 也按 origin 隔离）。
# 把 MES 反代到本服务下，iframe 与助手就同源，父页面可以直接观察它的 <html data-theme>。
MES_ORIGIN = "http://127.0.0.1:8790"          # 反代目标；由 main() 覆盖
MES_URL = "/mes/index.html"                   # iframe src（同源路径）；由 main() 覆盖
# 与 mes_agent.py 同一个缺省序：请求里指定 > ANTHROPIC_MODEL > 兜底名
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001"


def redact(text) -> str:
    out = str(text)
    for root, tag in ((REPO, "<repo>"), (Path.home(), "<home>")):
        for form in (str(root), root.as_posix()):
            out = out.replace(form, tag)
    return re.sub(r"(?<![\w<])[A-Za-z]:[\\/]", "<drive>/", out)


# 页面是真 .html 文件，不写成 Python 字符串 ——
# 曾经踩过：Python 三引号里的转义换行被解释成真换行，把内嵌 JS 的字符串字面量写断，
# 页面看着正常、点按钮却没反应（浏览器只报 Invalid or unexpected token）。
# 放进独立文件后这类转义事故从根上不存在。
PAGE_PATH = Path(__file__).resolve().parent / "agent_page.html"





class Handler(BaseHTTPRequestHandler):
    server_version = "mes-agent"
    protocol_version = "HTTP/1.1"

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        # 同 ui/server.py：不关连接会把单线程/半开连接拖住，这里一律关
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def log_message(self, fmt, *args):
        sys.stderr.write("[agent-serve] %s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):  # noqa: N802
        self._send(b"", "text/plain", 204)

    def _proxy_mes(self, sub: str) -> None:
        """把 `/mes/...` 转发到 MES 服务，去掉 `/mes` 前缀。

        前缀一去掉，iframe 里的相对路径就自动对上了：
        页面 `/mes/docs/mes-demo/index.html` 里的 `mes-data/inbox.json`
        浏览器会解析成 `/mes/docs/mes-demo/mes-data/inbox.json`
        → 本函数剥掉 `/mes` → 转发到 8790 的同一路径。**不需要改页面里任何相对路径。**
        """
        url = MES_ORIGIN.rstrip("/") + (sub or "/")
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read()
                ctype = r.headers.get("content-type") or "application/octet-stream"
        except urllib.error.HTTPError as e:
            self._send(b"", "text/plain", e.code)          # 透传状态码，页面自己会报 404
            return
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"反代 MES 失败：{redact(exc)}"}, 502)
            return
        self._send(body, ctype)

    def do_GET(self):  # noqa: N802
        # 反代要在最前面：它需要带 query 的原始 path
        if self.path == "/mes" or self.path.startswith("/mes/"):
            self._proxy_mes(self.path[4:])
            return
        route = self.path.split("?", 1)[0]
        if route in ("/", "/index.html"):
            # 每次现读：改页面不用重启服务（演示时能实时改字）
            try:
                html = PAGE_PATH.read_text(encoding="utf-8")
            except OSError as exc:
                self._json({"error": f"读不到页面 {PAGE_PATH.name}：{exc}"}, 500)
                return
            self._send(html.replace("__MES_URL__", MES_URL).encode("utf-8"),
                       "text/html; charset=utf-8")
            return
        if route == "/health":
            # 自报用的是哪个模型与端点 —— 「模型自己说它是什么」不可信（它答的是系统提示），
            # 配置才是真源。模型名不含凭据，可以外露；token 一律不外露。
            self._json({
                "ok": True,
                "mes_url": MES_URL,
                "mes_origin": MES_ORIGIN,
                "model": DEFAULT_MODEL,
                "endpoint_host": (os.environ.get("ANTHROPIC_BASE_URL") or "").split("//")[-1].split("/")[0] or None,
                "model_is_local": False,
            })
            return
        self._json({"error": "没有这个路径"}, 404)

    def do_POST(self):  # noqa: N802
        if self.path.split("?", 1)[0] != "/ask":
            self._json({"error": "没有这个路径"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (ValueError, UnicodeDecodeError) as exc:
            self._json({"error": f"请求体不是合法 JSON：{exc}"}, 400)
            return

        question = (payload.get("question") or "").strip()
        if not question:
            self._json({"error": "question 为空"}, 400)
            return

        model = payload.get("model") or os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001"
        try:
            out = mes_agent.run(question, model)
            self._json(out)
        except mes_agent.AgentError as exc:
            self._json({"error": redact(exc)}, 502)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": f"{type(exc).__name__}: {redact(exc)}"}, 500)


def main(argv=None) -> int:
    global MES_URL, MES_ORIGIN
    ap = argparse.ArgumentParser(prog="mes-agent-serve", description="MES 助手的 HTTP 外壳")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mes-origin", default=MES_ORIGIN,
                    help="反代目标：真正的 MES 服务地址")
    ap.add_argument("--mes-url", default="/mes/index.html#view=qm-quality-exception",
                    help="左栏 iframe 的 src。缺省走本服务的 /mes 反代 ⇒ 与助手同源 ⇒ 主题可同步")
    ap.add_argument("--proto", default=None, help="agent 读哪个宿主页（转成 MES_PROTO 环境变量）")
    args = ap.parse_args(argv)

    MES_ORIGIN = args.mes_origin
    MES_URL = args.mes_url
    if args.proto:
        os.environ["MES_PROTO"] = args.proto

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[agent-serve] MES 助手就绪 http://{args.host}:{args.port}")
    print(f"[agent-serve] 左栏 MES：{MES_URL}（反代自 {MES_ORIGIN}，同源 ⇒ 主题同步）")
    print(f"[agent-serve] agent 读的宿主页：{os.environ.get('MES_PROTO') or '(仓库内默认 docs/mes-demo/index.html)'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[agent-serve] 已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
