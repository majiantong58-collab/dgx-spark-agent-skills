"""对实拍照片中的人脸区域打码（**非破坏性**：只读原图，另存到新目录）。

用途：演示视频要公开发布，而实拍照片含可辨认的真实工人人脸、当事人未同意公开。
本脚本产出一个可直接使用的打码版本，供人工选择是否采用。

打码策略（隐私优先）
--------------------
* 用 YOLO11n 检出 `person`，对每个人形框**上部 1/4（头部区域）**打码。
* **刻意使用极低置信阈值**（默认 0.05，而非检测常用的 0.25）：
  漏打码是**不可逆的隐私伤害**，多打码只是画面损失。两者代价不对称，
  故宁可误打。脚本会同时报出「默认阈值」与「低阈值」两个人数，差额即补打数量。
* 用**马赛克**（缩小再最近邻放大）而非高斯模糊：马赛克不可逆，
  模糊在理论上存在被复原的风险。
* **不添加任何文字标注**——避免把「这是打码图」写死在画面上。

不做的事：不做人脸识别、不导出任何面部特征，只按人形框的几何位置打码。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
YOLO_W = REPO / "models" / "yolo11n.pt"
SRC_DIR = REPO / "assets" / "real_photos"
OUT_DIR = SRC_DIR / "blurred"

HEAD_FRACTION = 0.25   # 头部占人形框上部的比例
MOSAIC_BLOCKS = 6      # 头部区域横向切成几块（越小越糊）


def mosaic(region: np.ndarray, blocks: int = MOSAIC_BLOCKS) -> np.ndarray:
    """马赛克：缩到 blocks 宽再用最近邻放大回去。不可逆。"""
    h, w = region.shape[:2]
    if h < 2 or w < 2:
        return region
    small = cv2.resize(region, (blocks, max(2, int(blocks * h / w))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def detect_persons(img: np.ndarray, conf: float) -> list[tuple[int, int, int, int]]:
    from ultralytics import YOLO

    model = YOLO(str(YOLO_W))
    r = model(img, device=0, conf=conf, verbose=False)[0]
    return [
        tuple(int(v) for v in box)
        for box, cls in zip(r.boxes.xyxy, r.boxes.cls)
        if r.names[int(cls)] == "person"
    ]


def process(src: Path, out_dir: Path, conf: float) -> dict:
    img = cv2.imread(str(src))
    if img is None:
        raise SystemExit(f"读不到图像：{src}")

    boxes_low = detect_persons(img, conf)
    boxes_default = detect_persons(img, 0.25)

    for x1, y1, x2, y2 in boxes_low:
        head_h = max(1, int((y2 - y1) * HEAD_FRACTION))
        hy2 = min(y2, y1 + head_h)
        # 头部区域左右各留一点余量，避免框偏导致边缘露脸
        pad = int((x2 - x1) * 0.05)
        hx1 = max(0, x1 - pad)
        hx2 = min(img.shape[1], x2 + pad)
        if hy2 <= y1 + 1 or hx2 <= hx1 + 1:
            continue
        img[y1:hy2, hx1:hx2] = mosaic(img[y1:hy2, hx1:hx2])

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_blurred{src.suffix}"
    cv2.imwrite(str(out), img)
    return {
        "src": src.name,
        "out": str(out),
        "persons_default_conf": len(boxes_default),
        "persons_low_conf": len(boxes_low),
        "extra_from_low_conf": len(boxes_low) - len(boxes_default),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="*", help="待处理图片；默认处理 SRC_DIR 下全部 jpg")
    ap.add_argument("--conf", type=float, default=0.05, help="打码用的低置信阈值（默认 0.05）")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    srcs = [Path(p) for p in args.images] if args.images else sorted(SRC_DIR.glob("*.jpg"))
    for s in srcs:
        info = process(s, Path(args.out_dir), args.conf)
        print(
            "%-46s person: 默认阈值 %d / 低阈值 %d（补打 %d）"
            % (info["src"][:46], info["persons_default_conf"],
               info["persons_low_conf"], info["extra_from_low_conf"])
        )
        print("   -> %s" % info["out"])


if __name__ == "__main__":
    main()
