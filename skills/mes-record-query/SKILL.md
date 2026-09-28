---
name: mes-record-query
description: >-
  查MES 里**已有**的东西（只读，不发号、不落单）：① 工单（按工单号 → 状态 / 数量 / 产线）
  ② 设备台账（按设备编号 → 名称型号 / 工位 / 车间产线 / 接口 / 状态）
  ③ 品质异常单（按单号 → 详情；按部门 / 状态 → 列表）
  ④ 单号查重（给一个候选号 → 「可用 / 已占用」并指出命中在哪一处）。
  数据来源两处都查：原型 index.html 静态种子行 ＋ mes-data/*.json 我们的产出入。
  不适用于：要落新单 / 写 inbox.json / 生成单号（**用 mes-inspection-intake**）、
  判定单号与部门规则的口径本身（用 mes-business-rules）、把数据画进原型页面 / 注入 DOM（属原型侧 loader）、
  改MES 原型或 mes-data 任何文件（本技能只读）、图像识别本身（用 safety-hazard-detection / gauge-reading）、
  结论成文与导出（用 inspection-report）。
  Use when 查工单 / 查设备台账 / 查异常单 / 判断一个单号是否已被占用。
---

# MES 记录查询（mes-record-query）

**只查不写。** 本技能回答「MES 里现在有什么」，是 `mes-inspection-intake`（**写**）的对偶：
落单前先用本技能查重，落单后用本技能回查。**要落新单，请用 `mes-inspection-intake`。**

契约：`docs/agents/mes-bridge-contract.md`（§A.1 行属性与枚举 / §C.1 单号规则 / §C:133 mes-data 位置）。
单号与部门的口径真源在 `skills/mes-business-rules/`，**本技能只读它、不另立规则**。

> 🔴 **`[团队自定]` 声明**：本技能查到的是**原型种子数据**（演示库），不是真实产线数据。
> 对外表述不得暗示这是现场实时数据。

## 前置问题（信息不全时必须先问，禁止猜测）

1. **原型在哪？** 必须由调用方给 `--proto`（index.html 或所在目录）。
   🔴 **本技能不假定MES 工作区路径，也没有默认值**——路径不明就停下来问，
   报错话术即「请告知 MES 原型 index.html 的位置（本技能不猜默认路径）」。
2. **mes-data 在哪？** 默认取 `<原型目录>/mes-data`（**契约 §C:133 明文规定的相对位置**，非猜测）；
   调用方可用 `--data-dir` 覆盖。**查重时若 mes-data 缺失，必须当失败处理**——只查一处会漏号。
3. **要查哪一类？** `--wo` / `--dev` / `--exc` / `--check` 四选一，不给就报错问。
4. **是查还是写？** 要落单 → 转 `mes-inspection-intake`；本技能**不生成任何号**。

## 主流程

1. **校验号格式**（本地先判，不匹配即退出码 1）——见下表。
2. **读两处**：原型 `index.html` 全文 + `mes-data/*.json`（递归取全部字符串值，**schema 无关**）。
3. **按选择器查询**并印人话。
4. **查重**：原型命中 **或** mes-data 命中 → **已占用**，并逐条指出 `行号 / 文件名 + 字段名`。
5. **只读自证**：被读文件在读取时与结束前各算一次 sha256，不一致 → 退出码 1 并报错。

| 选择器 | 格式 | 判据锚点 |
|---|---|---|
| `--wo` | `MO-YYYYMMDD-NNN` / `MO-YYYY-MM-NNNN` | `WORKORDERS` `:11354` |
| `--dev` | `AA-99`（如 `FT-01`） | `dcm-equipment-ledger` 行 `:5520` |
| `--exc` | `QA-YYYYMMDD-NNN` | 契约 §C.1；行属性 `:2255` |
| `--check` | 上面三者任一 | 契约 §C.1 / §C.2 |

**查重口径（重要）**：宁可误报「已占用」，不可误报「可用」——号撞了只是麻烦，
**漏报会让 intake 发出重复单**。故原型侧按**全文出现**判定（排除 `placeholder="如 …"` 示例文本），
命中处按字段名排序：带 `data-no` / `rel` / `no` / `wo` 的行属性优先，其余列为「非行属性上下文」。

## 用法与退出码

```bash
python skills/mes-record-query/scripts/query.py \
    --proto <原型 index.html 或其目录> [--data-dir <mes-data>] \
    (--wo MO-20260812-006 | --dev FT-01 | --exc [QA-…] | --check QA-20260928-101)
```

`--exc` 不给号即按 `--dept <供应商|生产部|设备部|采购部>` / `--status <found|handling|recheck|closed>` 列表。

**退出码**：`0` 成功 / `1` 失败（号格式非法、路径不存在、缺 `--proto`、未指定查询、mes-data 坏 JSON、
只读自证失败）。错误信息**已抹掉本机绝对路径**（手法沿用 `ui/server.py:248`）。

**只读**：本技能不写任何文件。已显式关闭字节码落盘（`sys.dont_write_bytecode`），
否则 `import` 会顺手在 `scripts/__pycache__/` 留下 `.pyc`，「只读」即为假。

## 输出契约

stdout **只印人话**（每行前缀 `[query]`），不印 JSON 给机器消费（`mes-team.md` §10 基线）。
每次运行固定收尾一行只读自证：`只读自证通过：N 个被读文件 sha256 前后一致（未写任何文件）`。

## 负向边界（何时本技能不该被调用）

- **要落新单 / 写 `inbox.json` / 取新单号** → `mes-inspection-intake`。本技能只判定占用，**不发号**。
- **问规则本身**（部门怎么映射、序号为什么从 100 起、`iso` 什么语义） → `mes-business-rules`。
- **要把数据画进原型页面** → 属原型侧 loader（契约 §B），本技能**不得**改 `index.html`。
- **只有图 / 视频帧、还没有结论** → 先走 `safety-hazard-detection` / `gauge-reading`。
- **要出报告 / 导出文档** → `inspection-report`。
- 查真实产线实时数据 → 本技能查的是**原型种子数据**，不是生产库。
