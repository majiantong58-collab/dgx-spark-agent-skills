# 路由表与子技能数据契约

## 1. 路由判据（先看能力信号，再看关键词）

| 输入信号 | 目标技能 | tier |
|---|---|---|
| 人员 / PPE / 通道 / 渗漏 / 明火 / 闯入 | `safety-hazard-detection` | 0→1 |
| 表盘 / 指针 / 读数 / 压力 / 温度 / 液位 / 抄表 | `gauge-reading` | 1 |
| 已有结论 + 要求成文 / 导出 / 汇总 | `inspection-report` | 2（如需云端措辞） |
| 无图像、纯文本提问 | **不路由**，直接回答 | — |
| 非工业场景（街景 / 办公 / 家居） | **不路由**，返回 `out_of_scope` | — |

**冲突消解优先级**：明确指定的单一技能 > 关键词判定 > 默认编排。
用户说"读这个表"，即使图里同时有人，也**只**走 `gauge-reading`。

## 2. 多目标混合时的顺序

```
safety-hazard-detection ──┐
                          ├──▶ inspection-report
gauge-reading ────────────┘
```
串行执行，**不并行**——避免同一帧被 Tier 2 重复计费（预算见 `escalation-policy.md`）。

## 3. 跨技能数据契约（`inspection-report` 依赖此结构）

```json
{
  "task_id": "uuid",
  "site": "未指定 | <点位名>",
  "captured_at": "ISO8601 | null",
  "routes": [{"skill": "...", "reason": "...", "tier": 0}],
  "findings": [
    {
      "kind": "hazard | gauge",
      "code": "PPE-NO-CAP | PPE-NO-SUIT | PPE-NO-HELMET | P-101",
      "label": "...",
      "severity": "critical|high|medium|low",
      "confidence": 0.0,
      "tier": 0,
      "evidence_ref": "frame_0007#bbox[12,40,88,190]",
      "uncertain": false,
      "source": "safety-hazard-detection | gauge-reading | user",
      "requires_human_review": true
    }
  ],
  "partial": false,
  "disclaimers": ["<唯一措辞来源：inspection-report/references/output-schema.md §4，逐字>"]
}
```

**契约硬规则**
- 每条 `finding` 必带 `confidence`；缺置信度的条目 `inspection-report` 必须拒收。
- `evidence_ref` 必填，指向原始帧或 bbox，保证可追溯。
- 上层不得改写子技能返回的 `confidence` 与 `severity`。
