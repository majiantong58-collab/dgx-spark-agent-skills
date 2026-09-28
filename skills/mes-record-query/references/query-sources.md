# 查询数据来源与字段锚点

> 只读参考。行号为 `交付物/mes-prototype/index.html` 实测（2026-09-28）。
> 契约版本：`mes-bridge-contract.md` v1.7 + v1.8 §E.2 裁决。

## 两处来源（缺一不可）

| 来源 | 内容 | 由谁给 |
|---|---|---|
| 宿主页 `index.html` | 工单 / 设备台账 / 异常单的种子数据 | 缺省序 `--proto` > `MES_PROTO` > 仓库内 `docs/mes-demo/index.html`；皆无则**报错问，不猜** |
| `<mes-data>/*.json` | 我们自己的产出入 `inbox.json` / `xj-records.json` | 默认 `<原型目录>/mes-data`（契约 §C:133） |

🔴 **只查原型会漏**：`inbox.json` 里由 `mes-inspection-intake` 生成的新单**不在**原型 HTML 里，
只有 loader 注入后才可见。查重必须两处都查，否则刚落的单会被判「可用」而撞号。

## 原型侧锚点

| 对象 | 位置 | 形状 |
|---|---|---|
| 工单状态映射 | `:11345-11353` `WO_ST` | `running: ['生产中','badge-info']`（7 态：created/pending/running/paused/done/closed/cancelled） |
| 工单行 | `:11354` `WORKORDERS` | `{no,qty,ps,pe,st,sync,line,prog,reason}`；`line:null` = 未派线 |
| 异常单行 | `:2255` 起 | `<tr data-no data-rel data-dept data-status data-date>`；描述在该行 `title=` 属性 |
| 异常单状态枚举 | 契约 §A.1 `:2231` | `found` / `handling` / `recheck` / `closed` |
| 异常单部门枚举 | 契约 §A.1 `:2230` | 供应商 / 生产部 / 设备部 / 采购部 |
| 设备台账行 | `:5520` 起 | `<tr data-dcm-eq-row data-ws data-line data-st>`；列序 编号/名称型号/工位/车间产线/接口/状态 |
| MachineSN 口径 | `:15197` | 设备编号与 Job 采集 MachineSN **同源映射**（INT-DCM-002） |

## 不算占用的文本

原型里有若干「如 QA-…」的**输入提示**，是示例不是记录，扫描时先抹掉（`RE_PLACEHOLDER`）：

- `:2228` `placeholder="如 QA-20260812"`
- `:10370` `placeholder="如 QA-20260813-001"`（该号同时是真实行，**例子与真号重合**，故必须按上下文排除而非按号排除）
- `:11714` `placeholder="如 MO-20260814-014"`

## mes-data 侧

| 文件 | 结构 | 锚点 |
|---|---|---|
| `inbox.json` | `{schema_version, produced_by, produced_at, records[]}`，`records[].no` 为异常单号 | 契约 §C 示例 `:135-160` |
| `xj-records.json` | 同构；`no` = `XJ<YYYYMMDD><NNN>`，另有 `related_exception` | 契约 §C.4 `:263` |

扫描用**递归取全部字符串值**（不锁 schema）：契约将来加字段不需要改本技能。
值需 `fullmatch` 单号格式才算命中（描述里提到某号 ≠ 该号被占用）。

## 已知边界

- 工单/设备**只有原型一处来源**——`mes-data` 不含工单与设备，本技能不假装它有。
- 原型 `WORKORDERS` 存在**两种工单号形态**：`MO-20260812-006` 与 `MO-2026-07-0100`（`:11369`），两者都接受。
- 行号会随原型改版漂移；格式正则与块级解析（`<tr …>…</tr>`）不依赖行号，仅本文件的锚点表需要同步。
