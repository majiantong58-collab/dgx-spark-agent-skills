---
name: mes-inspection-intake
description: >-
  把巡检发现落成MES 品质异常单：读上游结构化 findings，产出 mes-data/inbox.json（供原型侧 loader
  注入 qm-quality-exception 视图），并同时落一条 XJ 巡检记录（契约 §C.2）。落单对象与部门映射均为 [团队自定]，
  不是 MES 原生能力。
  不适用于：图像识别本身（用 safety-hazard-detection / gauge-reading）、结论成文与导出（用 inspection-report）、
  把数据画进原型页面 / 注入 DOM（属原型侧 loader，本技能只写 JSON）、MES 原生巡检业务
  （FR-QM-006 范围不含人员 / PPE / 通道）、改MES 原型任何既有视图。
  Use when 巡检发现要落成 MES 品质异常单。
---

# 巡检发现落单（mes-inspection-intake）

把识别结论变成 MES 里的一张单。**本技能只写 JSON 文件，不碰原型页面**——注入由原型侧 loader 负责。

契约：`docs/agents/mes-bridge-contract.md` v1（§C 数据契约 / §D 安全约束）。
业务规则（部门映射 / 单号口径）在 `skills/mes-business-rules/`，本技能只实现、不另立规则。

> 🔴 **`[团队自定]` 声明**：MES **没有**「现场安全巡检」业务对象（D-030 事实 1：
> `FR-QM-006` 巡检范围明文不含人员 / PPE / 通道）。本技能做的是**把 MES 的边界向外扩一格**，
> 不是 MES 原生能力。对外表述不得省略该定性。

## 前置问题（信息不全时必须先问，禁止猜测）

1. **输入从哪来？** 必须是带 `confidence` 与 `evidence_ref` 的结构化 finding
   （上游契约：`inspection-orchestrator/references/routing-table.md` §3）。缺任一项 → **拒收**，不补默认值。
2. **日期落哪个世界？** 演示要与原型库内 `08-xx` 行可比 → fixture 传原型世界日期（契约 §C.1）。
3. **部门映射命中了吗？** 契约 §C.3 只覆盖 4 类发现。不中 → **报错退出**，由人用 `--dept` 指定，**不猜**。
4. **写到哪？** 由调用方给 `--out`；本技能不自行假定MES 工作区路径。

## 主流程

1. **读 finding** — 接受 `{findings: [...]}` 信封或单条 finding。
2. **必填校验** — `confidence` / `evidence_ref` / `label` 缺任一 → 退出码 1（上游硬规则：无置信度条目必须拒收）。
3. **定日期口径** — `--date` > `finding.captured_at` > 系统当天（后两者为 `[团队自定]` 补充）。
4. **映射部门**（`[团队自定]`，契约 §C.3）— `PPE-` → `生产部`；`kind=gauge` / 仪表位号 → `设备部`；
   其余按关键字；不中即报错。
5. **取号** — 扫 `--out` 所在目录既有 `*.json` 取当日 max+1，**不扫原型 DOM**；序号下限 **100**
   （取 `max(100, 当日既有产出 max+1)`，避免与库内 0xx 种子行撞号）——均为契约 §C.1 v1.1 明文。
6. **引号剔除**（契约 §D）— 产出值中的 `"` `'` 替换为全角，并在 stdout 记一次替换数。
7. **写文件** — `inbox.json` + 同目录 `xj-records.json`（契约 §C.2 要求 rel 指向的记录由本技能一并产出）。
8. **stdout 只印人话进度**；机器可读结果一律进文件。

## 用法与退出码

```bash
python skills/mes-inspection-intake/scripts/commit.py \
    --finding skills/mes-inspection-intake/evals/fixtures/finding-demo.json \
    --out <mes-data>/inbox.json
```

可选：`--date YYYY-MM-DD`（覆盖单号日期段）、`--dept <生产部|设备部|供应商|采购部>`（映射不中时的显式出口）。

**退出码**：`0` 成功 / `1` 失败（找不到文件、坏 JSON、映射不中、枚举越界、既有产出 schema_version 不符）。
错误信息**已抹掉本机绝对路径**（契约 §D，手法沿用 `ui/server.py:248`）。

## 输出契约

`inbox.json` 字段逐项定义见 `references/inbox-schema.md`（与契约 §C 一一对齐）。
写入行为：**追加**到既有 `records[]`（同版本）；遇坏文件或版本不符**拒绝覆盖并报错**。

**`iso` 值口径**：JSON 侧恒为**布尔**，默认 `false`（`[团队自定]`——原型「隔离标识」是**物料扣留**标识，
现场安全类发现不扣留任何物料；置 `true` 等于声称隔离了不存在的东西）。
呈现映射归 loader（契约 §B.2 v1.5：`false → 未隔离`）——**skill 不产出原型专用显示字符串**。

## 负向边界（何时本技能不该被调用）

- 只有图 / 视频帧、还没有结论 → 先走 `safety-hazard-detection` 或 `gauge-reading`。
- 要出报告 / 导出文档 → `inspection-report`；本技能不生成任何文档。
- 要让数据出现在原型页面上 → 属原型侧 loader（契约 §B 注入契约），本技能**不得**改 `index.html`。
- MES 原生巡检业务（在制产品 / 设备参数 / 物料状态）→ 不在本技能范围，也不要拿本技能冒充原生能力。
