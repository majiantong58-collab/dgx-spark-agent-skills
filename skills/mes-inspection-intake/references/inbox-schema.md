# inbox.json 输出契约（对齐 bridge contract v1 §C）

落点：`交付物/mes-prototype/mes-data/inbox.json`（契约 §C），同目录并写 `xj-records.json`。
生成者：`skills/mes-inspection-intake/scripts/commit.py`。

## 1. 信封

| 字段 | 值 | 说明 |
|---|---|---|
| `schema_version` | `"1"` | 🔴 loader 靠它判版本；不认识必须**显式报错**（契约 §F） |
| `produced_by` | `"mes-inspection-intake"` | 固定 |
| `produced_at` | ISO8601 带 `+08:00` | 生成时刻 |
| `records` | 数组 | 追加语义；只有 `kind == "quality-exception"` 的项进 `qm-quality-exception`（契约 §C） |

## 2. `records[]` 单条（逐字段对齐契约 §C）

| 字段 | 类型 | 来源 / 约束 |
|---|---|---|
| `kind` | string | 固定 `quality-exception`（其余 kind 本版忽略，契约 §E.2） |
| `no` | string | `QA-YYYYMMDD-NNN`，**skill 自生成**；不得复用原型 `nextExcNo()`（契约 §C.1） |
| `rel` | string | `XJ<YYYYMMDD><NNN>`，**无连字符**；指向同批产出的 XJ 记录（契约 §C.2） |
| `dept` | string | 必须 ∈ {`供应商`,`生产部`,`设备部`,`采购部`}；映射见 `mes-business-rules/references/department-mapping.md` `[团队自定]` |
| `desc` | string | 异常现象，取 finding 的 `label`（自由文本） |
| `iso` | bool | **隔离标识**。默认 **`false`**（`[团队自定]`）：原型该列 = 物料 / 在制品的**扣留**标识（`:2251` 表头 · `:2203`「禁止流转」· `:9308`「数量 / 区域」），我们的 4 类发现不扣留任何物料 ⇒ 置 `true` 等于声称执行了一次并不存在的物料隔离。置 `true` 仅当发现明确涉及在制产品 / 物料批次**且已执行隔离**（当前无此信号源）。**JSON 侧恒为布尔**，呈现映射归 loader（契约 §B.2 v1.5：`false → 未隔离`） |
| `finder` | string | 固定「巡检 Agent」 |
| `time` / `date` | string | `HH:MM` / `YYYY-MM-DD`，写进 `data-date` |
| `provenance.source_skill` | string | 取 finding 的 `source` |
| `provenance.confidence` | number | 取 finding 的 `confidence`（**缺失即拒收**） |
| `provenance.evidence_ref` | string | 取 finding 的 `evidence_ref`（**缺失即拒收**） |
| `provenance.disclaimer` | string | **逐字**长版「本报告由 AI 辅助生成，结论基于图像证据自动判定，需经人工复核确认。本报告不作为处罚、停机或联锁动作的唯一依据。」= 契约 §C 示例 = `inspection-report/references/output-schema.md` §4（单一来源，不得改写；v1.3 起全链用长版） |

**新单状态**：由原型 `excRowHtml` 写死 `found` / 待处理（契约 §B.2）⇒ 本技能不产出其他状态。

## 3. `xj-records.json`（契约 §C.2 的落盘 / §C.4 的记录字段）

`rel` 指向的记录必须真实存在，且**由本技能一并产出**（D-030 裁决 6）。
结构**与 `inbox.json` 同构**：`{schema_version, produced_by, produced_at, records[]}`。

| 字段 | 值 |
|---|---|
| `no` | 同 `rel`，`XJ<YYYYMMDD><NNN>`（**无连字符**） |
| `date` / `time` | 同该次落单 |
| `obj` | 巡检对象，取 finding 文档的 `site`，缺则「未指定」（**不编造点位**） |
| `finding` | 发现摘要，取该异常的 `desc` |
| `source_skill` / `confidence` | 取值回引对应异常单的 `provenance`（避免两处口径分叉） |
| `related_exception` | 对应的 `QA-...` 单号，供 **XJ → 单据反向追溯** |

**写入口径**（契约 §C.4）：**追加，不去重**——重复提交产生新记录（`no` 由序号机制保证唯一）。
去重需要「同一次发现」的判定口径，该口径未定义，**不发明**。
**消费方**：本版**无自动消费方**（原型不读它）；它是 `rel` 的指涉对象，供人工 / 审计追溯。

## 4. 安全约束（契约 §D，两侧纵深防御）

- 产出值**不得含 `"` 或 `'`**：原型 `esc()`(`:8684`) 只转义 `& < >`，而 `no`/`rel`/`dept`/`date`
  直接拼进 HTML 属性（`:9178`）⇒ 含引号可逃逸出属性。本技能替换为全角引号并在 stdout 记录替换数。
- 错误信息**必须抹掉本机绝对路径**（`<repo>` / `<home>` / `<drive>`）。

## 5. 明确不做（契约未覆盖，不自行发明）

- 不写「严重度」字段：MES 无此字段（D-030 事实 4），改为提交确认的新增字段需求。
- 不发 `recheck` 等其它状态：死态不规避但也不伪造（D-030 裁决 7）。
- 不落 DCM 点检：原型无插入路径，硬做会让 tab 计数失真（契约 §E.2）。
- **不去重**：同一发现重复提交会追加多条（契约 §C.4 明文「追加，不去重」，非本实现自选）。
