---
name: mes-closed-loop
description: >-
  MES 巡检**闭环编排**：把一次巡检发现串成「识别 → 判级/部门/隔离 → 落单 → 回执 → 成文」五个业务动作，
  并保证每一步的产物被下一步真正消费（空转防护）。编排层**只做路由**——不自己识别、不自己判级、不自己写单，
  一律调子技能（inspection-orchestrator / mes-business-rules / mes-inspection-intake / mes-record-query /
  inspection-report）。
  🔴 触发前提：**必须出现 MES 语境**（单号 MO-/QA-、落单/开单/录入/整改/闭环/台账）——
  **没提 MES 就不进 MES 侧**。
  不适用于：给了巡检图但**未提 MES**（用 inspection-orchestrator 管「识别什么」）、已指明单一识别类型
  （直接调 safety-hazard-detection / gauge-reading）、只问单号与部门规则的口径本身（用 mes-business-rules）、
  只查已有记录不求闭环（用 mes-record-query）、纯图片判读/修图/通用 OCR、把数据注入原型页面（属原型侧 loader）。
  Use when 巡检发现要变成 MES 里的业务动作（落单 / 整改 / 录入 / 闭环）。
---

# MES 巡检闭环编排（mes-closed-loop）

**只编排，不干活。** 本技能决定「这一句话该按什么顺序调哪几个子技能」，并把上一步的产物交给下一步；
识别、判级、写单、查询、成文的**业务逻辑全部在子技能里**，本层一句都不重复实现。

契约：`docs/agents/mes-bridge-contract.md` v1.9（§C.1 取号 / §C.2 rel 与 XJ 记录 / §C.3 部门映射 / §C.5 iso / §C.6 产物可验证性）。

## 🔴 与 invda `inspection-orchestrator` 的触发边界（一刀切）

> 两个编排层打架是本阶段最容易出的触发冲突，故边界必须切在**词**上，不留解释空间。

| | `inspection-orchestrator` | **本技能** |
|---|---|---|
| 管什么 | 「**识别什么**」 | 「**发现如何变成业务动作**」 |
| 触发条件 | 给了图/帧、**未指明识别类型** | **必须出现 MES 语境** |
| 无 MES 语境时 | **触发**（问到识别为止） | **一律不触发** |
| 二者同时成立时 | 被本技能**当子步骤调用** | 外层：先调它定识别路由，再往下走 |

**一句话**：**没提 MES 就不进 MES 侧。** 图决定「看什么」，MES 语境决定「要不要变成系统里的单」。

## 前置问题（信息不全时必须先问，禁止猜测）

1. **有没有 MES 语境？** 没有 → **不触发本技能**，改交 `inspection-orchestrator`（或已指明类型时直接交识别子技能）。
2. **宿主页在哪？** 缺省序：`--proto` > `MES_PROTO` 环境变量 > 仓库内 `docs/mes-demo/index.html`。
   **有默认值不等于可以猜**——装到别处解析不到时**退回「问用户」**，不找一个像的顶上。
3. **mes-data 落在哪？** 由调用方给 `--out-dir`；本技能不自行假定。
4. **发现类型可触发吗？** 🔴 契约 §C.3/v1.7：演示、文案、夹具**一律只用「人员违规」**——
   通道堵塞 / 设备渗漏 / 仪表读数三类**上游当前产不出结论**。喂进来即报错，不猜测、不降级。
5. **帧是真的吗？** 有真帧才把识别路由委托给 `orchestrator`；**本层不伪造帧路径**去骗过它的校验。

## 主流程

```bash
python skills/mes-closed-loop/scripts/loop.py route --utterance "<用户原话>" [--frame <真实帧>]
python skills/mes-closed-loop/scripts/loop.py run \
    --finding <识别产物.json> --out-dir <mes-data> [--proto <宿主页 index.html 或目录>] [--candidate QA-…]
```

`route` 判触发 + 出**路由日志**；`run` 真跑链路并逐条打印**消费证明**。

**链路**（每步产物必须被下一步消费，否则报错停下）：
1. **识别** → `inspection-orchestrator`（**委托**：本层不给识别结论）
2. **判级/部门/隔离** → `mes-business-rules`（§C.3 人员违规 → 生产部；§C.5 `iso=false`）
3. **落单** → `mes-inspection-intake`（§C.1 取号下限 100；§C.2 一并产出 XJ 记录）— **全链唯一的写动作**
4. **回执** → `mes-record-query`（落单**前**查重；落单**后**确认该号已占用）
5. **成文** → `inspection-report`（输入须含 `hazard_code` + `confidence`，缺则拒收）。
   该技能**不提供单入口 CLI 且不得改动**（已过合规校验）——两步显式命令见
   `references/routing-contract.md` §4（`assemble_sections.py` → `render_markdown.py`，已实测）。

## 输出契约

stdout **只印人话**（前缀 `[loop]`），不印 JSON 给机器消费。
`route` 输出触发判定 + 路由日志；`run` 输出每步产物 + 四条消费证明。

**空转防护**（本技能的核心主张）：每步产物都被下一步**真读**——
① 规则判据的 `dept`/`iso` 必须等于 intake 实际落的字段值；
② intake 的 `rel` 必须在 `xj-records.json` 内有实体记录（§C.2）；
③ 刚落的 `no` 必须能被 `mes-record-query` **重新读盘**查到；
④ 报告输入必须引用该单号且 `hazard_code`/`confidence` 齐备。

护栏本身可被证伪：`python skills/mes-closed-loop/evals/selfcheck_guards.py --proto <原型>` 用**故障注入**
逐条打断链路，断言对应护栏报错（当前 4/4 有效）。**只跑通正向链路证明不了空转防护**——
「调了但没用」的实现也能一路绿灯。

**退出码**：`0` 成功 / `1` 失败（无 MES 语境之外的任何失败、断链、类型越界、路径不存在）。
错误信息**已抹掉本机绝对路径**（手法沿用 `ui/server.py:248`）。
**只读自证**：已关字节码落盘（`sys.dont_write_bytecode`），编排层本身不写文件；写动作只发生在 intake 步。

## 负向边界（何时本技能不该被调用）

- **有图但没提 MES** → `inspection-orchestrator`。这是本技能**最常被误触发**的场景。
- **已指明识别类型**（「读这块表」「看看有没有隐患」） → 直接调对应识别子技能，两层编排都不用过。
- **只问规则口径**（部门怎么映射、序号为什么从 100 起） → `mes-business-rules`。
- **只查已有记录、不落单** → `mes-record-query`。
- **要注入原型页面 / 改 DOM** → 属原型侧 loader，本技能不涉及。
- **重跑须知**：intake 是**追加**语义，重跑 `run` 前须清空 `--out-dir`（契约 §C.6），否则序号会一路涨。
