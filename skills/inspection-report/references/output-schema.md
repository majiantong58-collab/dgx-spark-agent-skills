# 巡检报告输出 Schema

> 本文件定义 `inspection-report` 技能的**输出契约**，不增字段、不省略字段。

## 1. JSON

```json
{
  "report_id": "uuid",
  "site": "未指定",
  "inspector": null,
  "captured_at": null,
  "generated_at": "ISO8601",
  "standard_version": "hazard-taxonomy v0.2",
  "summary": {
    "total": 0,
    "critical": 0, "high": 0, "medium": 0, "low": 0,
    "uncertain_count": 0,
    "tier2_calls": 0
  },
  "items": [
    {
      "index": 1,
      "kind": "hazard",
      "code": "PPE-NO-CAP",
      "label": "未戴防尘帽",
      "severity": "high",
      "confidence": 0.91,
      "evidence_ref": "frame_0007#bbox[12,40,88,190]",
      "uncertain": false,
      "source": "safety-hazard-detection",
      "recommendation": "<仅取自 severity-levels.md 映射表>"
    }
  ],
  "partial": false,
  "disclaimers": ["<§4 逐字>"]
}
```

## 2. Markdown 结构（固定小节顺序）

```
# 安全巡检报告
> 点位 / 巡检人 / 巡检时间 / 生成时间 / 判定标准版本
## 1. 关键问题（critical）
## 2. 重要问题（high）
## 3. 一般问题（medium）
## 4. 附录：低风险与待复核项
## 5. 免责声明
```

## 3. 校验规则（违反即中止输出）

| # | 规则 |
|---|---|
| 1 | 每条 `items` 必含 `code` + `confidence` + `evidence_ref` |
| 2 | `items` 中每条的 `code` 必须能在输入里找到对应项（回读校验） |
| 3 | `recommendation` 必须逐字来自 `severity-levels.md` 映射表 |
| 4 | `summary` 各计数必须与 `items` 实际分布一致 |
| 5 | `disclaimers` 非空，且**逐字等于 §4** 定义的字符串 |
| 6 | 字段不得增删；缺值用 `null` / `未指定`，不得省略键 |

## 4. 免责声明（**单一措辞来源**）

以下字符串是 `disclaimers` 的**唯一定义处**，与 `render_markdown.DISCLAIMER` 逐字一致。
`severity-levels.md` §3、`inspection-orchestrator/references/routing-table.md` §3
以及任何产出该字段的脚本都**只引用本节、不得复述或缩写**——两处措辞只要差一个字符，
`render_markdown.render_footer` 的等值判重就会失效，页脚会打印两行近义声明。

```text
本报告由 AI 辅助生成，结论基于图像证据自动判定，需经人工复核确认。本报告不作为处罚、停机或联锁动作的唯一依据。
```
