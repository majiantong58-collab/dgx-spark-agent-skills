# 加强负例集（Decoy Set）—— 预注册说明

## 0. 预注册声明

**本用例集在 A5 全量实验结果产出之前定义并落盘。**

- **预注册时刻**：2026-09-27 02:50 北京时间（2026-09-26 18:50 UTC）
- **当时状态**：全量实验正在运行，**尚未看到任何 Δ2 结果**；已知信息仅为 4 条负例试跑未触发（天花板现象）
- **意义**：本集的定义不依赖任何结果数据，因此属于**预注册**的补充实验，而非看到结果后追加的后验操作

> **本文件一经写下，假设即冻结。** 事后不得修改第 3 节的假设措辞，不得因结果不合预期而更换口径。

---

## 1. 它解决什么问题

对既有 40 条用例（含 16 条真负例）的区分度分析发现：

| 区分度 | 条数 |
|---|---|
| 高（含领域词 + 近似误触发 + 指向同族技能） | 7 |
| 中 | 4 |
| 低（无领域词，任何模型都不会误触发） | 5 |

**低区分度用例集中在 `inspection-orchestrator`（4 条负例中 3 条为天花板）**：`orch-neg-002`（Python 代码）、`orch-neg-003`（安全帽国标）、`orch-neg-004`（风景照）——这些用例上 B 臂与 C 臂都不会触发，Δ2 必然为 0，无法测出 Not-for 段的任何价值。

### 更关键的结构性缺口：负例的 `expect_route` 全部为空

核对 40 条用例的 `expect_route` 字段使用情况：

| 用例类型 | `expect_route` 状态 |
|---|---|
| inspection-orchestrator 的 6 条正向用例 | **有值**（如 `["safety-hazard-detection","gauge-reading"]`） |
| **全部 16 条负例** | **无一有值**：10 条为 `[]`，6 条字段缺失 |

即：**字段本身存在且被正向用例正常使用，但没有任何一条负例声明「应当路由到哪个同族技能」**。多条负例（`gauge-neg-001`、`report-neg-001`、`report-neg-002`、`hazard-neg-002`、`hazard-neg-003`）在 `expect` 散文里写了「交 safety-hazard-detection / 交 gauge-reading / 交 inspection-report」，但该意图**没有编码进可判定字段**。

后果：NVIDIA 方法论强调的 **decoy / 选择压力（routing under selection pressure）** 维度，在负例侧**无法被机器判定**——判定器只能看到「不该触发」，看不到「该去哪儿」。

**本集的核心改进就是补齐这一字段。**

---

## 2. 与既有 16 条负例的区别

| 维度 | 既有 16 条负例 | 本集 9 条 |
|---|---|---|
| 区分度构成 | 高 7 / 中 4 / 低 5 | **高 9 / 中 0 / 低 0** |
| `expect_route` 字段存在率 | 10/16 | **9/9** |
| `expect_route` 声明同族目标 | **0/16** | **4/9**（其余 5 条正确行为是「不路由」故为 `[]`） |
| 编排层负例数 | 4（其中 3 条天花板） | **4（全部同族干扰）** |
| 每条 rationale 是否说明「为何会误触发」 | 部分 | **全部** |

**判定标准**：本集每条均为「同族干扰」——即一个**不读 Not-for 段**的模型，有明确理由误以为这是目标技能的活。该理由逐条写在 `rationale` 字段中。

---

## 3. 待检验的假设（已冻结）

> **H-decoy（预注册，不得事后修改）**
>
> **若 Not-for 段具有净收益，则本集上的 Δ2 应显著大于既有集上的 Δ2。**
>
> **若本集上的 Δ2 同样为 0，则负向条件（Not-for 段）的运行时收益在我们的场景下不成立。**

推论与判定边界：

- 本集全部为高区分度同族干扰，理论上给 Not-for 段留出了最大的发挥空间；既有集因含 5 条天花板用例而**稀释**了 Δ2。
- 因此预期：**Δ2(本集) > Δ2(既有集) ≥ 0**。
- **Δ2(本集) = 0 是强否定结果**：它意味着即便在专门构造的、最有利于负向条件生效的用例上，删掉 Not-for 段也不改变误触发率。

---

## 4. 定位声明

- 本集是**补充实验**，**不替代主结果**。
- **主结果仍以既有 40 条用例（`skills/*/evals/cases.jsonl`）为准。**
- 本集仅用于回答第 3 节的假设，**不得用于替换或重算主结论**。
- 若本集与主结果不一致，**两者都须报告**，不得只报有利的一方。

---

## 5. 文件与字段

- 文件：`skills/evals/cases-decoy.jsonl`（JSONL，UTF-8，每行一个对象）
- Schema 严格对齐既有 `cases.jsonl`：`id` / `skill` / `type` / `expect_trigger` / `input` / `assets` / `expect` / `rationale` / `expect_route`
- 全部 9 条：`type = "negative"`，`expect_trigger = false`
- **未新增任何自创字段**
- **既有 `cases.jsonl` 与 `SKILL.md` 均未被改动**（md5 见下）

### 用例清单

| id | skill | expect_route |
|---|---|---|
| gauge-decoy-001 | gauge-reading | `["safety-hazard-detection"]` |
| gauge-decoy-002 | gauge-reading | `[]` |
| hazard-decoy-001 | safety-hazard-detection | `["gauge-reading"]` |
| hazard-decoy-002 | safety-hazard-detection | `[]` |
| report-decoy-001 | inspection-report | `[]` |
| orch-decoy-001 | inspection-orchestrator | `["gauge-reading","safety-hazard-detection"]` |
| orch-decoy-002 | inspection-orchestrator | `[]` |
| orch-decoy-003 | inspection-orchestrator | `["inspection-report"]` |
| orch-decoy-004 | inspection-orchestrator | `[]` |

---

## 6. 未改动证明

预注册时刻（2026-09-27 02:50）记录的基线 md5：

```
c8f9f87715cf5055911c1dab8ddb6e44 *skills/gauge-reading/evals/cases.jsonl
565ac04a88ec7f1c266adc754fd340c9 *skills/inspection-orchestrator/evals/cases.jsonl
bca457fd5f1cf06aaf7039a06bdcc806 *skills/inspection-report/evals/cases.jsonl
d04a2905b22f976401d23a66e3ffd806 *skills/safety-hazard-detection/evals/cases.jsonl
95aaa0cdbf0e9fb77595883780f7438f *skills/gauge-reading/SKILL.md
03971927d03798f26c4d326b88e0b526 *skills/inspection-orchestrator/SKILL.md
cf8fb46daf349f58877e1a7cddf67e5b *skills/inspection-report/SKILL.md
fe712cf3210d19490b94020c403df34a *skills/safety-hazard-detection/SKILL.md
```

复核命令：

```bash
cd "C:/Users/26270/Desktop/invda"
md5sum skills/*/evals/cases.jsonl skills/*/SKILL.md
```

本集为**新增文件**，不影响上述任何哈希。
