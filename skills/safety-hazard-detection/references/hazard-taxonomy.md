# 隐患分类表（Hazard Taxonomy）

> 版本：v0.2 · 所有识别结果必须回标本版本号，便于复核与追溯。
> v0.2 变更：新增 `PPE-NO-CAP` / `PPE-NO-SUIT`（电子厂洁净车间真实场景）。
> v1 遗留编码一律保留、不删——v1 实验结果（`skills/evals/results/`）中记录的正是旧编码，
> 删掉会让那批证据成为无法查证的孤儿。详见 `docs/agents/experiment-version-note.md`。

## 1. 隐患编码

| hazard_code | 中文标签 | 类别 | 默认 severity | 典型证据 |
|---|---|---|---|---|
| `PPE-NO-CAP` | 未戴防尘帽 | 人员 PPE | high | 头部区域无帽体（**v2 主场景**：电子厂洁净车间） |
| `PPE-NO-SUIT` | 未穿防静电服 | 人员 PPE | medium | 躯干无洁净服 / 防静电服（**v2 主场景**） |
| `PPE-NO-HELMET` | 未戴安全帽 | 人员 PPE | high | 头部区域无帽体（**v1 遗留**，保留以便对照 v1 实验结果） |
| `PPE-NO-VEST` | 未穿反光衣 | 人员 PPE | medium | 躯干无高亮条带（**v1 遗留**，同上） |
| `PPE-NO-HARNESS` | 高处作业未系安全带 | 人员 PPE | critical | 高处人员无系挂点 |
| `ACCESS-INTRUDE` | 违规闯入 | 区域管控 | high | 人员进入警戒 / 围栏区 |
| `ACCESS-BLOCKED` | 通道堵塞 | 通道 | medium | 疏散通道被物料 / 车辆占压 |
| `EQUIP-LEAK` | 设备渗漏 | 设备 | high | 液体 / 气体泄漏痕迹、积液 |
| `FIRE-OPEN-FLAME` | 明火 | 消防 | critical | 非许可区域明火 |
| `FIRE-SMOKE` | 烟雾 | 消防 | critical | 异常烟雾 |
| `ELEC-EXPOSED` | 带电体裸露 | 电气 | critical | 配电箱门敞开、线缆裸露 |
| `HOUSEKEEPING` | 现场凌乱 | 5S | low | 物料散落、无定置 |

## 2. 阈值（与 SKILL.md 主流程第 4 步一致）

| 置信区间 | 处置 | tier |
|---|---|---|
| `conf ≥ 0.75` | 采纳 | 0 |
| `0.40 ≤ conf < 0.75` | 升 Tier 1 本地 VLM 复核 | 1 |
| `conf < 0.40` | 丢弃，不报 | — |

> 阈值是**可配置常量**，不是魔法数字：改阈值必须同步更新本表与本技能的 evals 用例。

## 3. `uncertain` 判定（必须标，不得编造）

命中任一条件 → `uncertain: true`，且 `severity` 降一档：

- 目标区域像素面积 < 图像面积 0.5%
- 目标被遮挡面积 > 40%
- 局部过曝 / 欠曝导致轮廓不可辨
- 单帧孤立证据（跨帧不复现）

## 4. 复核要求

- `severity = critical` 的条目**无论置信度多高**都必须人工复核。
- 人员类隐患进入报告时**不带任何身份信息**，只描述行为与 PPE 状态。
