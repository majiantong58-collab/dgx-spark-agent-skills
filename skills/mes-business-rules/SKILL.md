---
name: mes-business-rules
description: >-
  MES 落单业务规则库（只读知识，不执行动作、不写文件）。当需要判定「巡检发现 → MES 品质异常单」的
  责任部门、单号与关联单格式、状态口径时查阅；每条规则要么带 file:line 锚点，要么显式标注 [团队自定]。
  不适用于：执行落单与生成 inbox.json（用 mes-inspection-intake）、改原型界面或注入 DOM（属原型侧 loader）、
  MES 通用操作问答与按钮位置、非本 MES 系统的质量体系与工艺问题、图像识别本身（用 safety-hazard-detection）。
  Use when 判定落单口径（部门 / 单号 / 关联单 / 状态）。
---

# MES 业务规则库（mes-business-rules）

**只承载规则，不执行动作。** 落单执行一律走 `mes-inspection-intake`。
规则真源：`docs/agents/mes-bridge-contract.md` v1（§A 落点 / §C 数据契约）+ `docs/agents/decision-log.md` D-030。

> 🔴 **本技能全部「巡检 → MES」规则均为 `[团队自定]`，不是 MES 原生能力。**
> 依据 D-030 事实 1：MES 无「现场安全巡检」业务对象（`srs-v1.27.md:265`，`FR-QM-006` 的巡检范围
> 明文只含「在制产品、设备参数、物料状态」，**不含人员 / PPE / 通道**）。
> **引用处不得省略该标注**——D-018 教训：给自定判断加一个像出处的名目，会让它免于被核查。

## Purpose

把「巡检发现怎么落成 MES 单据」的口径收在一处，让 skill 侧与原型侧引用同一组规则，且每条规则可 grep 复核。

## 前置问题（信息不全时必须先问，禁止猜测）

1. 要判哪一类？**部门映射 / 单号 / 关联单 / 状态口径**——只答被问到的那一类，不顺手扩写。
2. 该情形在契约里有锚点吗？有 → 引 `file:line`；没有 → **标 `[团队自定]` 或直接说「契约未覆盖」**，不得猜。
3. 是不是在问 MES 原生能力？若是，先答清**MES 里没有这个业务对象**，再说我们的扩展（`references/mes-object-facts.md`）。

## 规则索引

| 主题 | 去哪看 |
|---|---|
| 责任部门映射（4 类发现 → 4 个部门枚举） | `references/department-mapping.md` |
| 单号 `QA-YYYYMMDD-NNN` / 关联单 `XJ<YYYYMMDD><NNN>` | `references/numbering.md` |
| MES 有什么、**没有什么**（业务对象 / 字段 / 死态） | `references/mes-object-facts.md` |

## 输出契约

回答形如：`结论 + 依据锚点（file:line 或 [团队自定]）+ 是否被 MES 原生支持`。
**不接受无锚点的断言**：凡涉及「MES 里有 / 没有」，必须给 `srs-v1.27.md` 或 `index.html` 的锚点。

## 负向边界（何时本技能不该被调用）

- 要**执行**落单、写文件、生成 `inbox.json` → 用 `mes-inspection-intake`；本技能只读不写。
- 要改原型、注入 DOM、调 `addExcRow` → 属原型侧 loader（R2-B 领地），本技能不涉及。
- 问「MES 怎么操作 / 按钮在哪」这类软件使用问题 → 不属业务规则。
- 问识别本身（怎么看出 PPE 违规）→ 用 `safety-hazard-detection`。
