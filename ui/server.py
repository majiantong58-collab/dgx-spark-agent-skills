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
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# 关掉 ultralytics 的「缺包就自动 pip install」。
# 它会在**当前线程里同步跑 pip**（subprocess.check_output，无超时）：单线程服务因此
# 卡死到安装结束为止，期间连 /photos 都不响应。实测 2026-09-27：一次解码失败的图触发了
# `pip install pi-heif`，跑了约 8 分钟，而且**真的把 pi-heif 装进了 .venv** ——
# 正踩本项目第一条约束（不装任何包，以免覆盖 CUDA 版 torch）。
# 必须在 ultralytics 被 import 之前设：AUTOINSTALL 是它 import 时读一次的模块级常量
#（ultralytics/utils/__init__.py: AUTOINSTALL = env_bool("YOLO_AUTOINSTALL", True)；
#  env_bool 的语义是「非真值字符串一律 False」）。本文件里 ultralytics 只在
#  _yolo_person_boxes 里按需 import，所以在这里设就足够早。
# 用 setdefault：运维想临时打开，自己设 YOLO_AUTOINSTALL=true 就能盖过。
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "safety-hazard-detection" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import local_tier_pipeline as ltp  # noqa: E402
# route 是编排层的模块，ltp 已经把它加载进来了（它自己会插 sys.path）。
# 这里只取它的最小短边阈值：阈值只有一处定义，界面的文案不会跟编排层漂移。
import route  # noqa: E402

UI_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = REPO / "models" / "ui_uploads"
ANNOTATED_DIR = UPLOAD_DIR / "annotated"
# 内置样片用**打过码**的那一份：`assets/samples/` 会随仓库提交，评委克隆后点开就能跑。
# 未打码的原图仍在 `assets/real_photos/`（被 .gitignore 挡住，只在本机做实验用），
# 两者的文件名相同，改这一行即可整组切换。
PHOTO_DIR = REPO / "assets" / "samples"
INDEX = UI_DIR / "index.html"

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 实测时长的口径说明，直接随响应回给前端，避免前端自己编
WALL_CLOCK_SOURCE = "ui: perf_counter() 包住 run_frame()，与 main() 的 wall_clock_s 同口径"

# 错误文案。**只回人话**：不出现 Python 异常名、不出现本机完整路径。
# 技术细节一律进服务端终端（录屏时终端本身就是证据，页面不是调试窗口）。
MSG_BAD_UPLOAD = "这次检测没能开始：上传的数据没读出来。请重新选一次这张图片。"
MSG_UNREADABLE = "这张图读不出来：它可能不是真正的图片文件，或者文件已损坏。换一张试试。"
MSG_TOO_SMALL = ("这张图太小了：它只有 {size} 像素，短边需要至少 {edge} 像素"
                 "（这是识别环节能判读的最小尺寸）。换一张大一点的试试。")
MSG_RUN_FAILED = ("这次检测没能跑完：本机处理时出错，没有产生结果。换一张试试；"
                  "若换一张仍然失败，请看服务端终端里的错误详情。")

# 界面自己的台账。**刻意不写** docs/local_tier_variance.jsonl、models/runs/、
# skills/evals/results/——那些是实验证据，界面作为技能的外部消费者不得触碰。
# 但界面实测出来的数字同样需要出处，否则数字只活在对话里，查不到。故另立一本账。
LEDGER = UI_DIR / "ui_runs.jsonl"

# 预热实况：ledger 要如实记下本帧跑之前模型是不是已经加载好了
PREWARM_INFO: dict[str, Any] = {"done": False,
                                "tier0_s": None,
                                "vlm_load_s": None,
                                "vlm_loaded": False}


def _safe_name(name: str) -> str:
    """只取纯文件名，挡掉路径穿越。"""
    return Path(str(name)).name


def _input_problem(path: Path) -> tuple[str | None, str]:
    """进 run_frame 之前先判输入能不能用，返回（问题码, 尺寸文案）。

    问题码：`"unreadable"` 读不出来 / `"too_small"` 分辨率不够 / `None` 没问题。
    判据与 `ppe_color_probe.main()` 和 `route.normalize_input` 一致：
    cv2 读不出来就是读不出来，短边小于编排层的下限就是太小。

    **刻意不用 PIL.Image.open**：ultralytics 在 import 时把 `PIL.Image.open`
    换成了自己的版本（`ultralytics/utils/patches.py`），解码一失败就调
    `check_requirements("pi-heif")` —— 它会在**当前线程里同步跑
    `pip install pi-heif`**。实测（2026-09-27 本机）：这一跑阻塞十几分钟不返回，
    单线程的 HTTPServer 整个卡死，页面上「处理中」永远不停 —— 正是本次要修的
    那个症状，只不过以前查不到根因。而且它会往 .venv 里装包，触碰本项目
    第一条约束（不装任何包，以免覆盖 CUDA 版 torch）。
    cv2 没有被 patch，这条路径不碰 pip。
    """
    try:
        import cv2
        img = cv2.imread(str(path))
    except Exception:  # noqa: BLE001 - 这里「读不出来」本身就是答案，不是错误
        return "unreadable", ""
    if img is None:
        return "unreadable", ""
    h, w = img.shape[:2]
    if min(h, w) < route.MIN_FRAME_EDGE:
        return "too_small", f"{w}×{h}"
    return None, ""


def append_run_ledger(rec: dict[str, Any]) -> None:
    """界面的运行台账：**只追加，从不改写**。

    只写**文件名**，不写本机绝对路径——台账要能直接贴进对外材料。
    写失败不阻断本次响应（响应已经发完了），但必须在控制台喊出来，不静默。
    """
    try:
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ui] !! 台账写入失败（本次结果仍然有效，但没落盘）：{exc}", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "invda-local-ui"
    protocol_version = "HTTP/1.1"

    # ---- 响应助手 ----
    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 必须关连接，否则**单线程服务会被一条空闲的 keep-alive 连接整个卡死**：
        # HTTP/1.1 默认保持连接，handle_one_request 响应完会阻塞在 rfile.readline()
        # 等这条连接的下一个请求。浏览器很容易留着这样一条（预连接、刷新、第二个标签页），
        # 于是服务停在那里，所有新请求全排队。2026-09-28 实测复现（A 通 → B 开空闲连接
        # → C 超时 → D 关掉即恢复），修前表现：页面已加载完仍点不动、curl 也超时。
        # 关连接不影响那三条设计约束（不装包 / 单线程 / 只调 run_frame）。
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

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
        if length <= 0:
            self._json({"ok": False, "error": "没有收到图片数据，这次检测没有开始。请重新选一次。"}, 400)
            return
        if length > MAX_UPLOAD_BYTES:
            self._json({"ok": False, "error":
                        f"这张图太大了（超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB），"
                        "服务没有接收。换一张小一点的试试。"}, 413)
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            name = _safe_name(payload.get("name") or "upload.jpg")
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_EXT:
                raise ValueError(f"不支持的扩展名 {ext!r}，仅接受 {sorted(ALLOWED_EXT)}")
            data = base64.b64decode(payload["data_b64"], validate=True)
        except Exception as exc:  # noqa: BLE001 - 边界层统一转成可读错误回给界面
            print(f"[ui] !! 请求解析失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            self._json({"ok": False, "error": MSG_BAD_UPLOAD}, 400)
            return

        # 上传的图必须先落成**真实文件**：run_frame 会做 is_file + im.verify()，
        # 且 min(w,h) < 64 会直接抛错。落在 models/ui_uploads/，
        # 不污染 assets/real_photos/（那里是实验用的实拍素材）。
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / f"{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
        dest.write_bytes(data)

        # 输入不可用就地返回，**不进 run_frame**：文案能说准（是这张图的问题，
        # 不是本机的问题），而且绕开 ultralytics 那个「解码失败就 pip install」的陷阱
        #（见 _input_problem 的注释）。用户换一张就有结果，不必先白等一轮 YOLO。
        problem, size = _input_problem(dest)
        if problem:
            print(f"[ui] !! 输入不可用（{dest.name}，{problem}），未进入 run_frame", file=sys.stderr)
            self._json({"ok": False, "error":
                        MSG_TOO_SMALL.format(size=size, edge=route.MIN_FRAME_EDGE)
                        if problem == "too_small" else MSG_UNREADABLE}, 400)
            return

        try:
            t0 = time.perf_counter()
            result = ltp.run_frame(str(dest))
            wall_s = round(time.perf_counter() - t0, 2)
        except Exception as exc:  # noqa: BLE001 - 不吞：终端留技术细节，页面只给人话
            # 异常名与消息只进终端，且先抹掉本机完整路径——这一屏会被录进演示视频。
            # （曾把 "IndexError: list index out of range" 原样印在页面上，
            #   还把 route 报错里的绝对路径一起带了出去。）
            print(f"[ui] !! 本帧失败：{type(exc).__name__}: "
                  f"{str(exc).replace(str(REPO), '<repo>')}", file=sys.stderr)
            self._json({"ok": False, "error": MSG_RUN_FAILED}, 500)
            return

        stem = dest.stem
        ann = ANNOTATED_DIR / f"{stem}_tier05.jpg"
        timings = result.get("timings") or {}
        append_run_ledger({
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "input": name,                 # 原始文件名，只有 basename
            "stored_as": dest.name,        # 落盘名，只有 basename
            "kind": "builtin" if (PHOTO_DIR / name).is_file() else "upload",
            "wall_clock_s": wall_s,
            "wall_clock_source": WALL_CLOCK_SOURCE,
            "tier_calls": result.get("tier_calls"),
            # 逐层耗时单独记：timings.total_ms 只累加 *_ms、**不含 tier1_s**，
            # 想复算墙钟时不能拿它求和
            "tier0_ms": timings.get("tier0_ms"),
            "tier0_5_ms": timings.get("tier0_5_ms"),
            "tier1_s": timings.get("tier1_s"),
            "timings_total_ms": timings.get("total_ms"),
            "weakest_conf": timings.get("weakest_conf"),
            "next_tier": timings.get("next_tier"),
            "short_circuit": timings.get("short_circuit"),
            "n_findings": len(result.get("findings") or []),
            "partial": result.get("partial"),
            "tier2_used": result.get("tier2_used"),
            "prewarmed": PREWARM_INFO["done"],
            "vlm_loaded_before_frame": PREWARM_INFO["vlm_loaded"],
        })
        # 标注图**内嵌进本次响应**，页面因此不必再发第二个 HTTP 请求。
        # 本服务是单线程 HTTPServer：浏览器若在一条空闲 keep-alive 连接之外
        # 另开一条去取图，那一条会一直阻塞到前一条关闭（已实测：12s 超时）。
        # 内嵌后该场景在结构上不可能发生。本地演示，响应体大几百 KB 无所谓。
        self._json({
            "ok": True,
            "upload_name": dest.name,
            "wall_clock_s": wall_s,
            "wall_clock_source": WALL_CLOCK_SOURCE,
            "result": result,
            "annotated_url": f"/annotated/{ann.name}" if ann.is_file()
                             else None,
            "annotated_b64": base64.b64encode(ann.read_bytes()).decode("ascii")
                             if ann.is_file() else None,
            "annotated_mime": "image/jpeg",
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
        PREWARM_INFO["tier0_s"] = round(time.perf_counter() - t0, 2)
        print(f"[prewarm] Tier 0 预热完成（{blank[0].name}）：{PREWARM_INFO['tier0_s']}s")

    t0 = time.perf_counter()
    ltp._load_vlm()  # noqa: SLF001 - 预热就是要把权重load进来，这是它的唯一目的
    PREWARM_INFO["vlm_load_s"] = round(time.perf_counter() - t0, 2)
    PREWARM_INFO["vlm_loaded"] = True
    PREWARM_INFO["done"] = True
    print(f"[prewarm] Tier 1 权重加载完成：{PREWARM_INFO['vlm_load_s']}s")


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
    # 终端里留一行：录屏时终端本身就是证据，这行能证明自动装包确实关着
    print(f"[ui] YOLO_AUTOINSTALL={os.environ.get('YOLO_AUTOINSTALL')!r}"
          f"（ultralytics 的自动装包已关：坏图不会再触发 pip，服务不会被它卡住）")

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
