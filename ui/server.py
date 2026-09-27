"""本地三层视觉推理流水线的极简演示界面（录屏用）。

零新依赖：只用 Python 自带的 `http.server` + 一个自包含 HTML。

三条设计约束（不要改）
----------------------
1. **不装任何包**。`.venv` 的 torch 是用 CUDA 12.8 专用源两步装出来的，
   装 web 框架有覆盖掉 CUDA 版 torch 的风险。
2. **单线程 `HTTPServer`**（不是 `ThreadingHTTPServer`）。这样「模型只加载一次」
   是结构上保证的，而不是靠约定。
3. **只调 `run_frame`，绝不调 `main()`**。`main()` 会向
   `docs/local_tier_variance.jsonl` 追加方差记录、覆盖 `docs/local_tier_metrics.json`、
   往 `skills/evals/results/` 写 —— 那些是实验证据，界面不得触碰。

墙钟时间从哪来
--------------
`wall_clock_s` 是 `main()` 加的，不在 `run_frame` 的返回里。本服务**自己**在
`run_frame` 调用前后打点，并在响应里标注 `wall_clock_source`，避免与既有记录混淆。
标题上的总耗时一律取这个值；**不要**去求和 `timings`——`timings.total_ms` 只累加
`*_ms` 结尾的键，**不含** `tier1_s`，求和会算出 4 秒这种与对外数字矛盾的结果。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "safety-hazard-detection" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import local_tier_pipeline as ltp  # noqa: E402

UI_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = REPO / "models" / "ui_uploads"
ANNOTATED_DIR = UPLOAD_DIR / "annotated"
PHOTO_DIR = REPO / "assets" / "real_photos"
INDEX = UI_DIR / "index.html"

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 实测时长的口径说明，直接随响应回给前端，避免前端自己编
WALL_CLOCK_SOURCE = "ui: perf_counter() 包住 run_frame()，与 main() 的 wall_clock_s 同口径"


def _safe_name(name: str) -> str:
    """只取纯文件名，挡掉路径穿越。"""
    return Path(str(name)).name


class Handler(BaseHTTPRequestHandler):
    server_version = "invda-local-ui"
    protocol_version = "HTTP/1.1"

    # ---- 响应助手 ----
    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            code,
        )

    def _file(self, path: Path, ctype: str) -> None:
        if not path.is_file():
            self._json({"ok": False, "error": f"文件不存在: {path.name}"}, 404)
            return
        self._send(path.read_bytes(), ctype)

    def log_message(self, fmt: str, *args) -> None:
        # 保留控制台输出：录屏时终端里的请求日志本身就是证据
        sys.stderr.write("[ui] %s - %s\n" % (self.address_string(), fmt % args))

    # ---- GET ----
    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        if route in ("/", "/index.html"):
            self._file(INDEX, "text/html; charset=utf-8")
            return
        if route == "/photos":
            names = sorted(p.name for p in PHOTO_DIR.glob("*.jpg"))
            self._json({
                "ok": True,
                "photos": [{"name": n, "url": f"/photo/{n}"} for n in names],
            })
            return
        if route.startswith("/photo/"):
            self._file(PHOTO_DIR / _safe_name(route[len("/photo/"):]), "image/jpeg")
            return
        if route.startswith("/annotated/"):
            self._file(ANNOTATED_DIR / _safe_name(route[len("/annotated/"):]), "image/jpeg")
            return
        self._json({"ok": False, "error": "not found"}, 404)

    # ---- POST /run ----
    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/run":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._json({"ok": False, "error": f"请求体大小非法: {length} 字节"}, 413)
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            name = _safe_name(payload.get("name") or "upload.jpg")
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_EXT:
                raise ValueError(f"不支持的扩展名 {ext!r}，仅接受 {sorted(ALLOWED_EXT)}")
            data = base64.b64decode(payload["data_b64"], validate=True)
        except Exception as exc:  # noqa: BLE001 - 边界层统一转成可读错误回给界面
            self._json({"ok": False, "error": f"请求解析失败: {exc}"}, 400)
            return

        # 上传的图必须先落成**真实文件**：run_frame 会做 is_file + im.verify()，
        # 且 min(w,h) < 64 会直接抛错。落在 models/ui_uploads/，
        # 不污染 assets/real_photos/（那里是实验用的实拍素材）。
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / f"{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        dest.write_bytes(data)

        try:
            t0 = time.perf_counter()
            result = ltp.run_frame(str(dest))
            wall_s = round(time.perf_counter() - t0, 2)
        except Exception as exc:  # noqa: BLE001 - 把后端异常如实回给界面，不吞
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return

        stem = dest.stem
        ann = ANNOTATED_DIR / f"{stem}_tier05.jpg"
        self._json({
            "ok": True,
            "upload_name": dest.name,
            "wall_clock_s": wall_s,
            "wall_clock_source": WALL_CLOCK_SOURCE,
            "result": result,
            "annotated_url": f"/annotated/{ann.name}" if ann.is_file()
                             else None,
        })
        print(f"[ui] {dest.name}  wall_clock={wall_s}s  tier_calls={result['tier_calls']}")


def prewarm(run_frame_once: bool = True) -> None:
    """预热：Tier 0 首次调用约 4077ms（YOLO 权重加载），暖机后 <150ms。

    必须**在服务进程内**预热才有意义——模型缓存是模块级、进程内的。
    另起一个进程预热不会传递到服务进程，这是本方案的固有限制。
    """
    photos = sorted(PHOTO_DIR.glob("*.jpg"))
    if not photos:
        print("[prewarm] assets/real_photos/ 为空，跳过 Tier 0 预热")
        return

    # 优先拿已知的「无人帧」预热：它会短路，不会触发 Tier 1，
    # 因此预热成本可预期，也不会在预热阶段就吃掉 10 秒的 VLM 推理。
    blank = [p for p in photos if p.name.startswith("5c6ec8b6")] or photos[:1]
    if run_frame_once:
        t0 = time.perf_counter()
        ltp.run_frame(str(blank[0]))
        print(f"[prewarm] Tier 0 预热完成（{blank[0].name}）：{time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    ltp._load_vlm()  # noqa: SLF001 - 预热就是要把权重load进来，这是它的唯一目的
    print(f"[prewarm] Tier 1 权重加载完成：{time.perf_counter() - t0:.2f}s")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="本地三层流水线演示界面。只调 run_frame，不写任何实验产物。"
    )
    ap.add_argument("--host", default="127.0.0.1",
                    help="默认 127.0.0.1，避免 Windows 防火墙弹窗")
    ap.add_argument("--port", type=int, default=8770,
                    help="默认 8770（避开 8000：NVIDIA 自家工具占用）")
    ap.add_argument("--no-prewarm", action="store_true", help="跳过启动预热（不建议）")
    args = ap.parse_args()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)

    if not args.no_prewarm:
        print("[prewarm] 预热中……（Tier 0 冷启动约 4 秒）")
        prewarm()
    else:
        print("[prewarm] 已跳过：首帧 Tier 0 会慢约 4 秒")

    # 单线程 HTTPServer：一次只处理一个请求，模型只加载一次是结构保证。
    httpd = HTTPServer((args.host, args.port), Handler)
    print(f"预热完成 http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[ui] 已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
