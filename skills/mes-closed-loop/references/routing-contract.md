# 闭环路由契约（每步产物 → 下一步消费）

> 只读参考。契约版本 `mes-bridge-contract.md` v1.9。

## 1. 触发闸门：什么算「MES 语境」

🔴 **`[团队自定]`**：MES 无「哪些话算 MES 语境」的明文规则，关键词表由本团队定义。
判据是**能指向系统里的单**，不是「听起来像工业」。

| 类 | 词 | 说明 |
|---|---|---|
| 单号形态 | `MO-######-###` / `MO-####-##-####` / `QA-########-###` | 正则匹配，最硬的信号 |
| 落单动作 | 落单 开单 建单 落成 录入 录进 入系统 报单 提单 | 把发现推向「系统里的单」 |
| 查询动作 | 查一下 查询 查查 什么状态 是否占用 可用吗 被占用 台账里 | 只读路径 |
| MES 业务对象 | MES 异常单 品质异常 巡检单 工单 整改 闭环 台账 追溯 回执 存档 归档 | 业务名词 |

**判定**：命中任一 → 进 MES 侧；否则不进。
**边界判据**：`有图 + 无 MES 语境` → 归 `inspection-orchestrator`（它管识别什么）。

## 2. 路由表

| 意图 | 序列 |
|---|---|
| 落单/录入/整改（含图） | 识别 → mes-business-rules → mes-inspection-intake → mes-record-query → inspection-report |
| 只查记录（含单号） | mes-record-query |
| 只要规则口径 | mes-business-rules |

产出序列的规则见 `scripts/loop_core.py:plan()`。

## 3. 每步的产物与消费关系（空转防护的真源）

| # | 步骤 | 技能 | 产物 | 被谁消费 | 断链检测 |
|---|---|---|---|---|---|
| 1 | 识别 | `inspection-orchestrator`（委托） | `findings[]` | 步 2/3/5 | 无 `findings[]` → 拒（没有发现就没有业务动作） |
| 2 | 判级/部门/隔离 | `mes-business-rules` | `dept` / `iso` 判据 | 步 3 | intake 实际落的 `dept`/`iso` ≠ 判据 → **G2** |
| 3 | 落单 | `mes-inspection-intake` | `inbox.json` + `xj-records.json` | 步 4/5 | 无 inbox → **G1**；`rel` 无实体记录 → **G3** |
| 4 | 回执 | `mes-record-query` | 占用确认 | 步 5 | 刚落的 `no` 在 mes-data 查不到 → 断链 |
| 5 | 成文 | `inspection-report` | 报告输入信封 | 人 | 缺 `hazard_code`/`confidence` → 拒（该技能前置硬要求） |

**为什么必须显式断言**：编排层最容易出的病是「**调了但没用**」——子技能返回成功、编排层照样往下走，
最后产物其实没被任何人消费。故每步都有一条**可失败的断言**，且用故障注入证明它真的会失败
（`evals/selfcheck_guards.py`，当前 4/4）。

## 4. 已知限制与两步命令

### 步 1（识别）不真跑 —— **是设计，不是缺口**

本层**不得自己识别**，故委托是正确形态。`run` 从**识别产物**起跑；委托只在给了 `--frame` 时发生
（orchestrator 的 `normalize_input` 按契约拒收无帧请求，`route.py:91`）。
实测：`--frame …/0df3783c….jpg` → `识别路由（委托 orchestrator）：safety-hazard-detection · tier=0`。

### 步 5（成文）：**不改已验证技能，给两步显式命令**

🔴 **不合并入口**：`inspection-report` 是**已交付并通过 SkillEvaluator 合规校验**的技能，
为合并入口而改它的字节会**作废既有合规结论**。**能力存在、入口不合并** —— 由 agent/调用方自己串：

```bash
# 5-a 组装：识别产物 → report.json（build_report 逐条校验 code/confidence/evidence_ref，缺则拒收）
python -c "import json,sys; sys.dont_write_bytecode=True; sys.path.insert(0,'skills/inspection-report/scripts'); \
from pathlib import Path; import assemble_sections as a; \
doc=json.loads(Path('<识别产物.json>').read_text(encoding='utf-8')); \
built=a.build_report(doc['findings'], meta={'site':doc.get('site'),'captured_at':doc.get('captured_at'), \
'disclaimers':doc.get('disclaimers')}); \
Path('<report.json>').write_text(json.dumps(built,ensure_ascii=False,indent=2),encoding='utf-8')"

# 5-b 渲染：report.json → report.md（render 要求 summary/items/disclaimers 齐备，否则拒出半成品）
python -c "import json,sys; sys.dont_write_bytecode=True; sys.path.insert(0,'skills/inspection-report/scripts'); \
from pathlib import Path; import render_markdown as r; \
md=r.render(json.loads(Path('<report.json>').read_text(encoding='utf-8'))); \
Path('<report.md>').write_text(md,encoding='utf-8')"
```

**实测（2026-09-28）**：两步均 exit=0，产出 `report.json` + `report.md`（900 B），
且 `巡检人：未指定` 未被编造。
**`sys.dont_write_bytecode=True` 必须保留**——否则 `import` 会在**别人的技能目录**里落 `.pyc`，
那是字节级改动，等于污染已验证技能（实测 `find skills/inspection-report -newermt -3min` = **0**）。

### 步 2 的知识层无脚本

`mes-business-rules` 是纯知识技能，故判据在 `loop_core.rules_expect()` 内以 **契约锚点**（§C.3/§C.5）形式引用；
它断言的是「intake 必须落在该判据上」，不是替代 intake 做映射。
