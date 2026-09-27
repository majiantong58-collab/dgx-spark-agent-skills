# Tier 1 静态评测结果（NVIDIA SkillEvaluator v0.3.0）

**运行日期**：2026-09-27 · **不消耗任何 API 费用**（未配置 LLM provider，未跑 Tier 3）

## 完整调用命令

```bash
# 安装（一次性）
uv tool install --python 3.13 "skillevaluator[all] @ git+https://github.com/NVIDIA/SkillEvaluator.git"
# -> C:\Users\26270\.local\bin\skillevaluator.exe  (v0.3.0)

# 质量评分（本文主数据）
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  skillevaluator tier1 quality-check "skills/$d" -r json -o "skills/evals/results/tier1-raw/$d"
done

# PII 扫描
skillevaluator tier1 pii-scan "skills/$d" -r json -o "skills/evals/results/tier1-raw/scans/$d"

# 安全扫描（需要外部扫描器，见下）
skillevaluator tier1 security-scan "skills/$d" -r json -o "skills/evals/results/tier1-raw/scans/$d"

# T3 体检（只报告，不执行）
skillevaluator doctor --env-mode docker
```

---

## 工具使用须知（Tooling notes）

### 1. 必须显式传 `-o`（Windows）

`tier1 quality-check` 在**不传 `-o`** 时，评分阶段正常完成并打印分数，随后在写报告的 `emit_reports` 阶段抛异常并以 traceback 退出。**评分结果可用，但无 JSON 产物、退出码非零**，不适合放进脚本或 CI。

**最小复现**：

```bash
# 复现：评分打印后崩在 emit_reports
skillevaluator tier1 quality-check skills/gauge-reading

# 规避：显式指定输出目录
skillevaluator tier1 quality-check skills/gauge-reading -r json -o skills/evals/results/tier1-raw
```

traceback 末端（v0.3.0）：

```
File "...\skillevaluator\cli.py", line 2052, in quality_check
    if not emit_reports(
File "...\skillevaluator\cli.py", line 2052, in <genexpr>
```

**建议**：本目录所有命令一律带 `-o`。副作用是 JSON 报告会落在指定目录，命名固定为 `skillevaluator-quality.json`；**批量跑多个 skill 时须为每个 skill 指定独立子目录**，否则后一次会覆盖前一次。

---

## 官方原始分数

| skill | Overall | Grade | Correctness (35%) | **Discoverability (25%)** | Reliability (25%) | Efficiency (15%) |
|---|---|---|---|---|---|---|
| inspection-orchestrator | **76.0** | C | 60 | **85** | 75 | 100 |
| safety-hazard-detection | **77.8** | C | 65 | **85** | 75 | 100 |
| gauge-reading | **77.8** | C | 65 | **85** | 75 | 100 |
| inspection-report | **76.0** | C | 60 | **85** | 75 | 100 |

全部 `QUALITY: PASS`（`--min-score` 默认 70，四个 skill 均过线）。

**四个 skill 的 Discoverability 完全同分（85）、扣分项完全一致**，说明该维度对内容差异不敏感——只做模板级字符串匹配。

---

## 命门一：description 长度判定

**判定：4 个 skill 全部未被扣分。**

官方代码（`validators/quality_score.py::_check_discoverability`）实际阈值：

| 条件 | 扣分 |
|---|---|
| `len(desc) < 20` | −20 warning |
| `len(desc) > 200` | −5 info |
| 其他（含 150–200） | **不扣分** |

实测字符数：orchestrator 166、report 156、gauge 138、hazard 135。

**结论：论文里写的「50–150 preferred」只是提示文案，真正触发扣分的是 `>200`。** 166 / 156 落在 150–200 的容忍带内，**未被 flag**。不必为此改描述。若要靠近官方偏好带，只有 orchestrator(166) 和 report(156) 需要压到 150 以下，但**没有分数收益**。

---

## 命门二：explicit negative/boundary phrasing 判定

**判定：我们的负向条件写法，官方评测器「看不见」——既不给分，也不扣分。**

官方实现只有一条**负向**检查（代号 M1），是**惩罚性**的，**没有任何正向加分**：

```python
generic   = ["data", "files", "documents", "project", "manage", "handle", "process"]
negatives = ["not for", "do not use", "instead use", "except when", "not when"]
if len(desc) > 100 and _contains_any_term(desc, generic) and not _contains_any_term(desc, negatives):
    dim.deduct(5, "info", "Broad description without negative triggers may cause over-triggering",
               "Add boundary phrases like 'Do NOT use for...'")
```

三个结论：

1. **纯英文关键词匹配**。我们的「不适用于」不含 `not for` / `do not use` 等任何英文串 → 该检查**永不触发**。
2. **写负向条件没有正向收益**。这条规则是「避免 −5」的惩罚规避机制，不是加分项。**我们写 Not-for 段，官方评分一分都不多给。**
3. **该检查能触发的前提是 description 里含英文字眼**（`data`/`files`/`process` 等）。我们是中文描述 → 检查条件恒为假。

### ⚠️ 附带发现：一个误判（false negative）

同一函数里的 WHEN-to-use 检查：

```python
trigger_words = ["use", "when", "for", "helps", "allows"]
if not _contains_any_term(desc, trigger_words):
    dim.deduct(10, "info", "Description doesn't mention WHEN to use this skill")
```

我们 4 个 description **都写了「当用户给出…时触发」/「当用户提供…时使用」**，语义完全满足要求，但因为匹配的是英文字面量，**4 个 skill 全部被误扣 10 分**。

**这 10 分是纯语言偏见造成的**，不是内容缺陷。若要让官方评测器认可，唯一办法是在 description 里**混入英文触发词**（如以 `Use when` 开头，或插入 `when` / `for` 字样）。这是本次评测最有实操价值的发现。

> 注意：`for` 是极短的子串，中文描述里几乎不可能自然出现，因此不要指望碰巧命中。

---

## 其余 T1 项

| 项 | 结果 |
|---|---|
| **PII / secrets 扫描** | 4 个 skill **全部 PASS**（warnings=0, errors=0）。凭据治理历史在静态口径下**无残留问题** |
| **License 检查** | 未单独报错；quality-check 的 SKILL_SPEC 推荐字段中未含 license 扣分 |
| **Security 扫描** | **INCOMPLETE，非失败**。`incomplete_scans: ["skillspector"]`，`files_scanned: 0, checks_performed: 0`。原因是未安装外部扫描器 |
| schema / hygiene | 未报错（quality-check 内部含 frontmatter 与命名检查，均通过） |

### 补全安全扫描需要（未执行，供决策）

```bash
brew install gitleaks semgrep          # Windows 无 brew，需另找安装方式
uv tool install git+https://github.com/NVIDIA/SkillSpector.git
```

### Correctness / Reliability 的扣分项（非命门，仅备查）

- Correctness 60–65：缺 `## Available Scripts` 表格式脚本文档、正文未提 `run_script`、frontmatter 缺推荐字段 `version` / `metadata.author` / `metadata.tags`
- Reliability 75：4 条 warning（细节见 `tier1-static.json`）

这些是 NVIDIA 的**推荐字段**而非规范必填项（我们的 `skills-ref` 校验已全 PASS），**不构成合规问题**。

---

## T3 体检结果（只报告，未执行）

`skillevaluator doctor --env-mode docker`：

| 检查 | 状态 | 说明 |
|---|---|---|
| CLI package | pass | skillevaluator 0.3.0 |
| Public LLM provider | **fail** | 未配置 provider（需 `SKILL_EVAL_LLM_PROVIDER` + key） |
| Harbor agents | warn | 自动选择需先配置 provider |
| docker prerequisite | **fail** | **harbor CLI not found** |

另：本机 **Docker daemon 未运行**（`npipe:////./pipe/dockerDesktopLinuxEngine` 连接失败）。

**跑 T3 需要补齐三件事**：provider key、Harbor CLI（`[all]` extra 未带进来）、运行中的 Docker。**每跑一次都产生真实 API 费用。**

---

## 产物文件

| 文件 | 内容 |
|---|---|
| `skills/evals/results/tier1-static.json` | 合并后的结构化结果（分数、逐维度扣分项、PII、security） |
| `skills/evals/results/tier1-raw/*/skillevaluator-quality.json` | 官方 quality-check 原生输出 |
| `skills/evals/results/tier1-raw/scans/*/skillevaluator-pii.json` | 官方 pii-scan 原生输出 |
| `skills/evals/results/tier1-raw/scans/*/skillevaluator-security.json` | 官方 security-scan 原生输出（incomplete） |
