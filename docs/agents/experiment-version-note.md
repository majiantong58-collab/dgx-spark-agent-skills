# 实验版本关系说明（v1 → v2）

> 本文说明 `skills/evals/results/` 下各实验产物**对应哪一版技能描述**。
> 结论一句话：**那批结果是 v1 描述下跑的；v2 改的是场景对齐，因此结果的适用范围要标注为「v1」。**

## 1. 版本定义

| 版本 | 含义 | 四个 `SKILL.md` 的 md5 |
|---|---|---|
| **v1** | 原始描述：场景假设为**工地 / 生产车间**，PPE 项为「安全帽 / 反光衣」 | `gauge-reading` `95aaa0cdbf0e9fb77595883780f7438f`<br>`inspection-orchestrator` `03971927d03798f26c4d326b88e0b526`<br>`inspection-report` `cf8fb46daf349f58877e1a7cddf67e5b`<br>`safety-hazard-detection` `fe712cf3210d19490b94020c403df34a` |
| **v2** | 场景对齐：真实场景为**电子厂洁净车间**，PPE 项改为「防尘帽 / 防静电服」；旧项保留为 v1 遗留 | `gauge-reading` `95aaa0cdbf0e9fb77595883780f7438f`（未变）<br>`inspection-orchestrator` `03971927d03798f26c4d326b88e0b526`（未变）<br>`inspection-report` `cf8fb46daf349f58877e1a7cddf67e5b`（未变）<br>**`safety-hazard-detection` `9dd0b9febc38952b10bfe5752cbc5154`（已变）** |

**v2 只改动了一个 `SKILL.md`**（`safety-hazard-detection`），另三个 md5 与 v1 完全一致。

## 2. 哪些实验结果属于 v1

`skills/evals/results/` 下的**全部产物**均标注为「**v1 描述下的结果**」：

`A.json` · `B.json` · `C.json` · `D.json` · `decoy-A/B/C/D.json` · `a4-baseline.json` ·
`a4-sample-report.md` · `report.md` · `decoy-report.md` · `diagnostics.json` ·
`variance-log.md` · `tier1-static.json` · `tier1-static.md` · `tier1-before-after.md`

**这些文件不得修改**——它们是实验证据，包含模型当时的原始响应文本。
改了就等于篡改证据，且会让其中引用的 `hazard_code` 失去可查证性。

## 2b. Tier 1 静态分三阶段对照（**归因必须按这条时间线读**）

静态分经历**两轮受控实验**，**本轮场景对齐是第三轮**。取基准时若只看「最初」那一列，
会把前两轮我们自己量到的效应误读成「工具漂移」——那是错的。

| 阶段 | orchestrator | hazard | gauge | report | 本阶段效应 |
|---|---|---|---|---|---|
| 最初基线 | 76.0 | 77.8 | 77.8 | 76.0 | — |
| + 英文触发词 | 78.5 | 80.2 | 80.2 | 78.5 | **+2.5** |
| + Purpose 段 | **79.8** | **81.5** | **81.5** | **79.8** | **+1.25** |
| **本轮：场景对齐（v2）** | **79.8** | **81.5** | **81.5** | **79.8** | **±0** |

**+3.8（= 2.5 + 1.25）是前两轮受控实验的累计效应，不是工具侧漂移。**
两轮相加与实测位移逐位吻合。

**本轮真正的结论是：场景对齐使静态分「零变化」。**
改了 `hazard_code`、改了场景、改了 4 个文件的措辞，**分数一分未动**。
这是**预期内**的——本轮只换名词、未动结构，静态检查器本就不该有反应。

> **为什么必须较这个真**：同一组数有两种说法。「工具漂移」会让读者连带怀疑我们此前所有
> Tier 1 数字；「我们自己量过的两轮效应」则让那批数字更可信。**写法不同，可信度天差地别。**
>
> 另需注意：`gauge-reading` 在本轮**一个字节都没改**，分数同样停在 81.5——
> 它是天然的阴性对照，**正是它证明了本轮 Δ=0 而不是又一次位移。**

**口径提醒**：上表分数由 `skillevaluator quality-check` 产出（不是 `tier1` 子命令，
后者的 JSON 只有 passed / issue_count，没有百分制）。详见 `skills/evals/check-compliance.md`。

## 3. 一条有力的旁证：v1 描述确实把模型引向了工地语义

在 A 臂（无技能约束）的原始响应里，模型**自创了技能名**
`helmet_detection` 与 `reflective_clothing_detection`（见 `results/A.json`，
其中 `"skills":["helmet_detection","instrument_detection"]`）。

也就是说：**模型在完全自由发挥时，把任务理解成了「检测安全帽 / 反光衣」**——
这正是 v1 描述写明的工地 PPE 项。这条旁证说明 v1 描述对模型的语义引导是**真实存在且可观测的**，
不是推测。

v2 把描述改为「防尘帽 / 防静电服、洁净室」之后，同一引导方向也会随之改变；
**因此 v1 的实验结论不能直接套用到 v2。**

## 4. v2 改了什么（本次场景对齐）

**契约层（6 个文件）**
- `skills/safety-hazard-detection/SKILL.md` — description / Purpose / 前置问题 / 输出契约示例
- `references/hazard-taxonomy.md` — 版本号 v0.1→**v0.2**；新增 `PPE-NO-CAP` / `PPE-NO-SUIT`；旧码标注 v1 遗留
- `references/ppe-rules.md` — 场景表新增「电子厂洁净车间」并置顶；附实测能力边界
- `inspection-report/references/severity-levels.md` — 新增两条整改建议；旧两条标注 v1 遗留
- `inspection-report/references/output-schema.md` — 示例 code/label 与 `standard_version` 改为 v0.2
- `inspection-orchestrator/references/routing-table.md` — 契约示例 code 并集

**路由（1 个文件，只增不删）**
- `inspection-orchestrator/scripts/route.py` — `HAZARD_KEYWORDS` 新增
  `防尘帽 / 防静电服 / 静电服 / 洁净服 / 无尘服 / 工服 / 洁净车间`（24 → 31 词）；
  **旧词「安全帽 / 反光衣」保留**，否则本节第 3 条的旁证将无从追溯。

**用例（改动 2 条，均在 `skills/safety-hazard-detection/evals/cases.jsonl`）**

| 用例 id | 改动 |
|---|---|
| `hazard-pos-001` | `PPE-NO-HELMET` → **`PPE-NO-CAP`**；assets/input 改为「洁净车间 / 未戴防尘帽」 |
| `hazard-pos-005` | `PPE-NO-VEST` → **`PPE-NO-SUIT`**；assets 改为「洁净区人员未穿防静电服」 |

**未改动的用例（有意保留 v1 语义）**：`hazard-pos-002`（工地安全带）、`hazard-pos-003`、
`hazard-pos-004`、`hazard-neg-001~004`、`hazard-empty-001`。
`hazard-neg-004`（「安全帽的报废年限是多久？」）**是负例**，检的是「无图不触发」，
与场景无关，保留可继续测出 v1 的负向边界。

**文档层**：`skills/README.md` §5 description 示例已同步为 v2。
**尚未同步**：`docs/PRD.md:187`、`docs/demo-script.md:42`、`docs/agents/decision-log.md:254,282,283`
（decision-log 属历史记录，建议原样保留并加版本标注，不重写）。

## 5. 尚未纳入 v2 的遗留项

- `skills/evals/run_e2e.py` 合成的 E2E 素材**画的是黄色安全帽**（v1 语义）；
  改用例后该素材与新场景不一致，**需重新生成素材**才能反映洁净车间场景。
- A5 / decoy 实验**未在 v2 上重跑**。若需 v2 结论，必须重跑，不能沿用 v1 数字。

## 6. 复核命令

```bash
# 合规门禁（v2 已实测 4/4 通过）
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  ./.venv/Scripts/agentskills.exe validate "skills/$d"
done

# 证据未被篡改
md5sum skills/evals/results/*
```

---

## 7. 路径脱敏（2026-09-28）——**含 §2 冻结条款的边界澄清**

> **本节是 §2「这些文件不得修改」的一次受控例外，留痕在此。**
> 不是删改 §2，而是**补它没写清的一处边界**：§2 的枚举清单列了 14 个文件，
> **未包含 `tier1-raw*/**/skillevaluator-quality.json` 这 12 个**。
> 概括语「`results/` 下的全部产物」与枚举清单之间有歧义，本节把两者的处理一并记下。

### 7.1 改了什么

**只做一件事：把本机绝对路径前缀替换为占位符。** 三项字面量替换：

| # | 原值（字节级字面量的**形态**） | 新值 | 处数 |
|---|---|---|---|
| 1 | `C:\\Users\\<用户名>\\Desktop\\<仓库目录>`（JSON 转义形态，文件里就是双反斜杠） | `<repo>` | 252 |
| 2 | `C:/Users/<用户名>/Desktop/<仓库目录>`（正斜杠形态） | `<repo>` | 2 |
| 3 | `C:\Users\<用户名>`（唯一不在仓库内的路径：校验工具安装位置） | `<用户目录>` | 1 |

**合计 255 处，14 个文件。**

> **为什么这里写 `<用户名>` 而不写原字面量**：本节自身会随仓库公开，
> 把原字面量抄进来等于**在同一处把刚脱敏掉的东西又写回去**，也会让 §7.6 的第 1 条自检失败。
> 需要精确原字面量的话，它在 git 历史 `ccbe393` 里（见 §7.8），**未丢失、可随时取回**。

### 7.2 **不含任何数据变更**（本节最要紧的一句）

替换是**纯字节级、语义空操作**。以下**一律未动**：

- **数字**：所有分数、`issue_count`、`line_number`、行数、md5 —— 一个未动
- **结论与判定**：`severity`、`check_name`、`passed`、三阶段对照的任何取值
- **模型原始响应文本**：`message` / `suggestion` / `raw_response` 等字段的正文
- **`hazard_code`** 及一切可查证标识
- **字段名、JSON 结构、键序、缩进、行尾（CRLF/LF 原样保留）**

被替换的只是「这台机器把仓库放在哪个目录」。**替换后 `<repo>` 后面的相对路径完整保留**，
故「工具当时说的是哪个文件」这一信息**逐位可复核**（例：`<repo>\skills\gauge-reading\SKILL.md`）。

### 7.3 为什么改

本机绝对路径会随公开仓库泄露作者的用户名与目录结构，且与我们自己写在
`README.md`「关于测试素材的声明」里的隐私姿态自相矛盾。依据见
`docs/agents/clone-preflight-findings.md`。

### 7.4 怎么做的（可复现）

在 **bytes** 上做 `replace`，不经过文本解码；**逐文件记录实际命中的规则**，
替换后用同一组规则**逆序还原**，断言还原后与原文**逐字节相同**——
断言在 `write` **之前**，失败则一个字节都不落盘。该断言在首次运行时确实拦下过一次规则歧义
（`<repo>` 同时来自规则 1 与 2，逆向时无法区分），修正为「按命中集合逆向」后才放行。

### 7.5 改了什么文件（md5 前后对照）

| 文件 | 处数 | md5 前 | md5 后 |
|---|---:|---|---|
| `tier1-before-after.md` | 2 | `f141b21b2c929fb0c7ff6ef85b666143` | `f25a5f694ae62256226f34c6de713970` |
| `tier1-static.md` | 1 | `087193d6a638d9800258d93ad1b41360` | `a1ab3283d46417419bb0e2f6a5a98ea3` |
| `tier1-raw/skillevaluator-quality.json` | 22 | `2e6469cd52830a86229d28b2422f0ef3` | `7fc753926b069f51e6eaa77287d11a18` |
| `tier1-raw/safety-hazard-detection/skillevaluator-quality.json` | 22 | `c868b08400af63afc970f00801c8fe21` | `c5c09ebee9260c6fa231043daae0470b` |
| `tier1-raw/inspection-orchestrator/skillevaluator-quality.json` | 24 | `6fbb3ab78880d4c9a440f341bce637af` | `3709d6fcf77b1bdceca36305eeb6fe4e` |
| `tier1-raw/inspection-report/skillevaluator-quality.json` | 24 | `8a7ba7abd2e2d3372437bed039a39e7e` | `8aa633b8a6b5d77ffb4b762b8b5b0e58` |
| `tier1-raw-after/gauge-reading/skillevaluator-quality.json` | 20 | `1cf1d3bda6b914e1effaaa8ccd7644b3` | `aea44772d17744572dbf06963b73d42a` |
| `tier1-raw-after/safety-hazard-detection/skillevaluator-quality.json` | 20 | `e69099b3361a8ad0e4355474e5600d1d` | `0106d057d1e8c7376f69d169f445ab95` |
| `tier1-raw-after/inspection-orchestrator/skillevaluator-quality.json` | 22 | `f665ee742f07c473fb5e66c93114b806` | `8e6a1e359ecf0ec1b81bf9728ede036a` |
| `tier1-raw-after/inspection-report/skillevaluator-quality.json` | 22 | `134ef486dae9b2fd193aaf644daae9cb` | `b79b6b4f107416100ce3d9859f9a2322` |
| `tier1-raw-purpose/gauge-reading/skillevaluator-quality.json` | 18 | `40008010a4c22d694ec6a8de811119a4` | `f9f5bcb796ef748dd6c972d3970a960f` |
| `tier1-raw-purpose/safety-hazard-detection/skillevaluator-quality.json` | 18 | `f7fc083f8b4bb7c2c323e557b639baea` | `76d58cce247e2b7f6bb153d3b2d50e87` |
| `tier1-raw-purpose/inspection-orchestrator/skillevaluator-quality.json` | 20 | `70afb180074bf9d38dffb917985b337b` | `bf17216db4bc5c89b41c1a9e3280a345` |
| `tier1-raw-purpose/inspection-report/skillevaluator-quality.json` | 20 | `b24920e1b2fae7fa332bb196e1b8494b` | `40740f1a709993d1aec93efc3939139d` |
| **合计** | **255** | | |

**其余 `results/` 文件的内容一字未动。**（`git diff` 显示的另外 15 个文件仅行尾差异，
是检出时的 CRLF 转换，与本次脱敏无关——`git diff` 已将其忽略。）

### 7.6 自证（三条，均应通过）

```bash
# 1) 全库不应再有本机路径（按「泄漏形态」匹配，而不是按某一个人的用户名）
git grep -n -E '[A-Za-z]:[\\/]+Users[\\/]+[0-9]+' -- .     # 期望：零输出

# 2) 本次改动只应是前缀替换（255 增 / 255 删，14 个文件）
git diff --stat -- skills/evals/results/

# 3) 12 个 JSON 仍是合法 JSON（用 find，避免 bash globstar 未开时漏掉子目录）
find skills/evals/results -name 'skillevaluator-quality.json' -print0 \
  | while IFS= read -r -d '' f; do python -m json.tool "$f" > /dev/null && echo "OK $f"; done
```

### 7.7 与 §2 冻结的关系

- **§2 枚举的 14 个文件中**，本次动了 2 个：`tier1-before-after.md`、`tier1-static.md`。
- **§2 未枚举的 12 个 `tier1-raw*/**/skillevaluator-quality.json`**，本次动了 252 处。
  按概括语「全部产物」它们本就在冻结范围内，故**一并按受控例外处理**，不利用这处歧义。
- **冻结基线不受影响**：`tier1-before-after.md` §四记录的 md5 **只覆盖 4 个 `SKILL.md`**，
  本次**一个 `SKILL.md` 都没碰**（复核：4 个 md5 与 §1 版本表一致）。
- 全库检索：**这 12 个 JSON 的哈希在任何文档中都未被记录**，故无校验和被破坏。

> **一句话**：这次改的是「机器路径」，不是「数据」。若日后需要还原，
> 按 §7.1 的三条规则逆序替换即可逐字节复原。

### 7.8 ⚠️ 本次脱敏**不覆盖 git 历史**——这一条必须说清

本次只清理了**工作区 / 未来的 HEAD**。原字面量仍存在于**已经推送到公开远端的历史提交**中：

```
$ git branch -r --contains ccbe393
  origin/main                      # ← ccbe393 已在公开远端
$ git show ccbe393:skills/evals/results/tier1-raw/skillevaluator-quality.json \
    | grep -c -E '[A-Za-z]:[\\/]+Users[\\/]+[0-9]+'
# 仍能取到原字面量（实测：命中，非 0）
```

**含义**：

- 本次改动让 **HEAD 可浏览的状态**不再含本机路径（这也是评审真正会看到的东西）。
- 但**任何人 `git log -p` 或 `git show ccbe393` 仍能看到**。**这不是一次完整的清除。**
- 想彻底清除，只能重写历史（`git filter-repo` + 强推），代价是**全部 commit hash 变更**、
  需对公开仓库 force-push，且会与本地其他未提交工作冲突。**提交截止前不建议做**，
  除非明确认定该用户名属于必须清除的敏感信息。
- **未做**，在本节留痕备查。
