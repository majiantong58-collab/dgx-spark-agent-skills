"""PPE 着装的颜色/几何启发式探针（Tier 0 低成本层）。

⚠️ 这不是语义理解，是**颜色 + 几何启发式**。

本模块只回答「画面里有没有一块符合 PPE 颜色与位置先验的区域」，**不理解物体是什么**。
因此它的固有缺陷是：**一个黄色纸箱会被判成安全帽，一件橙色雨衣会被判成反光衣**。
这是方法的边界，不是实现缺陷。凡是本模块给出的 hit，都只是**候选**，
是否成立必须交由 Tier 1（本地 VLM）或人工复核。

设计意图：COCO 检测器只认 person，认不出任何 PPE。本模块用近乎零成本的方式，
在已有人形框的基础上做一次粗筛，把「绝对没有 PPE 颜色」的帧快速排除，
让昂贵的模型只处理疑难帧。这是真实的边缘分层做法，不是模型的替代品。

默认阈值的光照前提：**室内均匀荧光灯 / 白光，无强逆光、无明显过曝**
（实测样本为电子厂车间：绿色环氧地坪、日光灯顶光）。
户外强光、逆光、夜间需重新标定，直接套用默认值会大量误检。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# OpenCV HSV 取值范围：H 0-179，S 0-255，V 0-255
HsvRange = tuple[tuple[int, int, int], tuple[int, int, int]]

# 安全帽色：黄 / 白 / 橙（工地场景）
HELMET_RANGES: tuple[HsvRange, ...] = (
    ((20, 100, 100), (35, 255, 255)),  # 黄
    ((8, 110, 110), (20, 255, 255)),  # 橙
    ((0, 0, 200), (179, 45, 255)),  # 白（低饱和 + 高亮度）
)
# 反光衣色：高饱和黄 / 橙
VEST_RANGES: tuple[HsvRange, ...] = (
    ((20, 120, 120), (35, 255, 255)),
    ((8, 130, 120), (20, 255, 255)),
)
# 电子厂无尘车间实测场景：蓝色防尘帽 + 蓝色防静电服
# （用户实拍样本中工人戴蓝色圆帽、穿蓝色大褂，与此前的工地假设完全不同）
BLUE_COVERALL_RANGES: tuple[HsvRange, ...] = (((95, 80, 60), (130, 255, 255)),)


@dataclass(frozen=True)
class PpeParams:
    """可调阈值。默认值见上方「光照前提」说明。"""

    helmet_ranges: tuple[HsvRange, ...] = HELMET_RANGES
    vest_ranges: tuple[HsvRange, ...] = VEST_RANGES
    # 饱和度/亮度下限：用于剔除黄褐色木箱、泥土、肤色等低饱和干扰
    sat_floor: int = 60
    val_floor: int = 70
    # 色块最小面积（像素），低于此值视为噪点
    min_blob_area: int = 400
    # 位置约束：安全帽必须落在人形框顶部这一段（比例，0=框顶，1=框底）
    helmet_zone: tuple[float, float] = (0.0, 0.33)
    # 位置约束：反光衣必须落在躯干这一段
    vest_zone: tuple[float, float] = (0.25, 0.75)
    # 命中判定：色块需覆盖该区域的比例
    min_zone_coverage: float = 0.06


DEFAULT_PARAMS = PpeParams()


@dataclass(frozen=True)
class PpeHit:
    """一条候选。kind 取 'helmet' / 'vest'。"""

    kind: str
    box: tuple[int, int, int, int]
    area: int
    zone_coverage: float
    person_index: int | None = None


@dataclass(frozen=True)
class PpeResult:
    """探针输出。masks/overlay 供演示直接上屏。"""

    hits: tuple[PpeHit, ...] = ()
    helmet_mask: np.ndarray | None = None
    vest_mask: np.ndarray | None = None
    overlay: np.ndarray | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def helmet_count(self) -> int:
        return sum(1 for h in self.hits if h.kind == "helmet")

    @property
    def vest_count(self) -> int:
        return sum(1 for h in self.hits if h.kind == "vest")


def _range_mask(hsv: np.ndarray, ranges: tuple[HsvRange, ...], p: PpeParams) -> np.ndarray:
    """把多个 HSV 区间并成一张掩膜，并施加饱和度/亮度下限。"""
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lo, hi in ranges:
        mask |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    # 饱和度下限只对彩色区间生效；白色区间本身饱和度为 0，不能被它误杀
    colored = hsv[:, :, 1] >= p.sat_floor
    bright = hsv[:, :, 2] >= p.val_floor
    return cv2.bitwise_and(mask, mask, mask=(colored & bright).astype(np.uint8) * 255)


def _clean(mask: np.ndarray, min_area: int) -> np.ndarray:
    """开运算去噪 + 剔除小连通块。"""
    k = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 255
    return out


def _hits_in_zone(
    mask: np.ndarray, kind: str, zone: tuple[float, float], x1: int, y1: int, x2: int, y2: int,
    idx: int, params: PpeParams,
) -> list[PpeHit]:
    """在人形框的指定纵向区段内找色块，返回命中。

    位置约束是关键——没有它，地面黄线、蓝色周转箱都会变成 PPE。
    """
    h = y2 - y1
    zy1 = int(y1 + zone[0] * h)
    zy2 = int(y1 + zone[1] * h)
    if zy2 <= zy1:
        return []
    roi = mask[zy1:zy2, x1:x2]
    if roi.size == 0:
        return []
    zone_area = roi.shape[0] * roi.shape[1]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(roi, connectivity=8)
    hits: list[PpeHit] = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < params.min_blob_area:
            continue
        bx = int(stats[i, cv2.CC_STAT_LEFT]) + x1
        by = int(stats[i, cv2.CC_STAT_TOP]) + zy1
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        cov = area / zone_area
        if cov < params.min_zone_coverage:
            continue
        hits.append(PpeHit(kind, (bx, by, bx + bw, by + bh), area, round(cov, 4), idx))
    return hits


def detect_ppe(
    image_bgr: np.ndarray,
    person_boxes: list[tuple[int, int, int, int]] | None = None,
    params: PpeParams = DEFAULT_PARAMS,
) -> PpeResult:
    """在图中找疑似安全帽 / 反光衣区域。

    Args:
        image_bgr: BGR 图像。
        person_boxes: 人形框 [(x1,y1,x2,y2), ...]。**强烈建议传入**——
            没有它就无法施加位置约束，地面黄线、蓝色周转箱等会被大量误报。
            通常来自 YOLO（COCO 只认 person，正好够用）。
        params: 阈值，见 PpeParams。

    Returns:
        PpeResult。hits 均为**候选**，不代表结论成立。
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    helmet_mask = _clean(_range_mask(hsv, params.helmet_ranges, params), params.min_blob_area)
    vest_mask = _clean(_range_mask(hsv, params.vest_ranges, params), params.min_blob_area)

    hits: list[PpeHit] = []
    notes: list[str] = []
    if not person_boxes:
        notes.append(
            "未提供 person_boxes：无法施加位置约束，全图色块直接作为候选，误报率显著升高"
        )
        for kind, mask in (("helmet", helmet_mask), ("vest", vest_mask)):
            n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
            for i in range(1, n):
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area < params.min_blob_area:
                    continue
                bx, by = int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP])
                hits.append(PpeHit(kind, (bx, by, bx + stats[i, cv2.CC_STAT_WIDTH],
                                          by + stats[i, cv2.CC_STAT_HEIGHT]), area, 0.0, None))
    else:
        for idx, (x1, y1, x2, y2) in enumerate(person_boxes):
            hits += _hits_in_zone(helmet_mask, "helmet", params.helmet_zone, x1, y1, x2, y2, idx, params)
            hits += _hits_in_zone(vest_mask, "vest", params.vest_zone, x1, y1, x2, y2, idx, params)

    return PpeResult(tuple(hits), helmet_mask, vest_mask, None, tuple(notes))


def visualize(image_bgr: np.ndarray, result: PpeResult, person_boxes=None) -> np.ndarray:
    """产出演示用叠加图：掩膜着色 + 候选框 + 人形框。"""
    vis = image_bgr.copy()
    # 掩膜半透明着色，便于录屏时肉眼看到"算法看到了什么"
    vis[result.helmet_mask > 0] = (0.5 * vis[result.helmet_mask > 0] + 0.5 * np.array([0, 215, 255])).astype(np.uint8)
    vis[result.vest_mask > 0] = (0.5 * vis[result.vest_mask > 0] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)
    for x1, y1, x2, y2 in (person_boxes or []):
        cv2.rectangle(vis, (x1, y1), (x2, y2), (200, 200, 200), 2)
    for h in result.hits:
        color = (0, 255, 255) if h.kind == "helmet" else (255, 0, 255)
        cv2.rectangle(vis, (h.box[0], h.box[1]), (h.box[2], h.box[3]), color, 2)
        cv2.putText(vis, f"{h.kind} {h.zone_coverage:.0%}", (h.box[0], max(18, h.box[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return vis


def _yolo_person_boxes(image_path: str) -> list[tuple[int, int, int, int]]:
    """用本地 yolo11n 取 person 框。失败则返回空表并提示。"""
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[warn] 未安装 ultralytics，跳过人形框，误报率会升高")
        return []
    model_path = Path(__file__).resolve().parents[3] / "models" / "yolo11n.pt"
    if not model_path.is_file():
        print(f"[warn] 找不到 {model_path}，跳过人形框")
        return []
    r = YOLO(str(model_path))(image_path, verbose=False)[0]
    return [
        tuple(int(v) for v in box)
        for box, cls in zip(r.boxes.xyxy, r.boxes.cls)
        if r.names[int(cls)] == "person"
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="PPE 颜色/几何启发式探针（候选，非结论）")
    ap.add_argument("image")
    ap.add_argument("--out", default=None, help="叠加图输出路径")
    ap.add_argument("--no-person", action="store_true", help="不使用 YOLO 人形框（误报率升高）")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"读不到图像：{args.image}")
    boxes = [] if args.no_person else _yolo_person_boxes(args.image)
    res = detect_ppe(img, boxes)
    print(f"person 框：{len(boxes)}")
    print(f"疑似安全帽：{res.helmet_count}    疑似反光衣：{res.vest_count}")
    for h in res.hits:
        print(f"  - {h.kind} box={h.box} area={h.area} 区域占比={h.zone_coverage:.1%} person#{h.person_index}")
    for n in res.notes:
        print(f"  [note] {n}")
    out = args.out or str(Path(args.image).with_name(Path(args.image).stem + "_ppe.jpg"))
    cv2.imwrite(out, visualize(img, res, boxes))
    print(f"叠加图：{out}")


if __name__ == "__main__":
    main()
