# Agent Skills 官方规范核对

> 侦察日期：2026-09-27 · 所有结论均来自官方站点，标注了出处 URL 与可访问状态

## 1. 权威规范出处

| URL | 状态 | 内容 |
|---|---|---|
| `https://agentskills.io/specification.md` | HTTP 200 ✅ | **权威格式规范**（frontmatter 字段、目录结构、命名、渐进式披露、校验） |
| `https://agentskills.io/llms.txt` | HTTP 200 ✅ | 官方文档索引（llms.txt 协议） |
| `https://agentskills.io/llms-full.txt` | HTTP 200 ✅ 93KB | 全站文档合并版，本报告主要取样来源 |
| `https://agentskills.io/home.md` | HTTP 200 ✅ | 概览：什么是 skill、渐进式披露三阶段、开放治理 |
| `https://agentskills.io/skill-creation/best-practices.md` | HTTP 200 ✅ | 最佳实践（非规范，是建议） |
| `https://agentskills.io/skill-creation/optimizing-descriptions.md` | HTTP 200 ✅ | description 触发优化（非规范，是方法论） |
| `https://github.com/agentskills/agentskills` | 可访问 ✅ | 官方仓库，含 `skills-ref` 校验库（Apache 2.0） |
| `https://raw.githubusercontent.com/.../skills-ref/README.md` | HTTP 200 ✅ | 校验库用法 |

**治理**：由 Anthropic 最初开发，作为**开放标准**发布，现由生态共同维护（home.md 原文：`originally developed by Anthropic, released as an open standard`）。GitHub 仓库 + Discord 为贡献入口。

---

## 2. SKILL.md frontmatter 权威字段表

来源：`specification.md` 的 Frontmatter 表。**只有 2 个必填字段。**

| 字段 | 必填 | 类型 | 约束 | 官方说明（短引） |
|---|---|---|---|---|
| `name` | **是** | string | Max 64 chars；仅小写字母/数字/连字符；不得以 `-` 开头或结尾；不得含连续 `--`；**必须与父目录同名** | "Lowercase letters, numbers, and hyphens only." |
| `description` | **是** | string | Max **1024 字符**；非空 | "Describes what the skill does and when to use it." |
| `license` | 否 | string | 建议简短，可指向随附 license 文件 | "License name or reference to a bundled license file." |
| `compatibility` | 否 | string | Max **500 字符**；仅在确有环境依赖时写 | "Indicates environment requirements (intended product, system packages, network access, etc.)." |
| `metadata` | 否 | map<string,string> | 任意键值对；建议键名足够独特以免冲突 | "Arbitrary key-value mapping for additional metadata." |
| `allowed-tools` | 否 | string | **空格分隔**的预授权工具列表；**标记为 Experimental** | "Space-separated string of pre-approved tools the skill may use. (Experimental)" |

`name` 字段单独列出的完整规则（specification.md `name` field 小节）：
- Must be 1-64 characters
- May only contain unicode lowercase alphanumeric characters (`a-z`, `0-9`) and hyphens (`-`)
- Must not start or end with a hyphen (`-`)
- Must not contain consecutive hyphens (`--`)
- **Must match the parent directory name**

官方给的非法示例：`PDF-Processing`（大写）、`-pdf`（前导连字符）、`pdf--processing`（连续连字符）。

### 最小可用示例（官方原文）

```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

---

## 3. 命名 / 目录结构 / 长度的硬性限制

### 目录结构（specification.md）

```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...               # Any additional files or directories
```

只有 `SKILL.md` 是必需的。`scripts/` `references/` `assets/` 三个目录名是**约定俗成的 recommend**（原文用词 "The conventions below are recommendations"），不是强制。

### 硬性 vs 建议——必须区分

| 项 | 数值 | 性质 |
|---|---|---|
| `name` 长度 | ≤ 64 字符 | **硬性**（Must） |
| `description` 长度 | ≤ 1024 字符 | **硬性**（Must），"the specification enforces a hard limit of 1024 characters" |
| `compatibility` 长度 | ≤ 500 字符 | **硬性**（Must，若提供） |
| `name` 与父目录同名 | — | **硬性**（Must） |
| SKILL.md 主文件长度 | **< 500 行** | **建议**（推荐值，非 schema 强制） |
| SKILL.md 主文件 token | **< 5000 tokens** | **建议**（"recommended"） |
| 引用文件嵌套深度 | 距 SKILL.md 一层 | **建议**（"Keep file references one level deep... Avoid deeply nested reference chains."） |

⚠️ **官方从未出现 "100 行" 的说法。** 全站 grep `100 lines` 无命中；两处长度表述（llms-full.txt 第 496 行、第 1816 行）均为 **500 lines**。

### Body content

"no format restrictions. Write whatever helps agents perform the task effectively." 推荐包含：分步指令、输入输出示例、常见边界情况。

---

## 4. `description` 字段的官方建议

### 4.1 规范层（specification.md，强制口径）

- Must be 1-1024 characters
- Should describe **both** what the skill does **and** when to use it
- Should include specific keywords that help agents identify relevant tasks

官方正例：
```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
```
官方反例：`description: Helps with PDFs.`

### 4.2 优化层（optimizing-descriptions.md，方法论口径）

四条写法原则：
1. **Use imperative phrasing** — "Use this skill when..." 而非 "This skill does..."（因为 agent 在决定是否行动）
2. **Focus on user intent, not implementation** — 描述用户想达成什么，不是 skill 的内部机制
3. **Err on the side of being pushy** — 显式列出适用语境，包括用户没直说领域名的情况（"even if they don't explicitly mention 'CSV' or 'analysis.'"）
4. **Keep it concise** — "A few sentences to a short paragraph is usually right"，硬上限 1024 字符

> **观察点回答（触发/不触发条件）**：官方**确实**要求写"不触发条件"，但只出现在**优化指南**而非规范正文。原文："If should-not-trigger queries are false-triggering, the description may be too broad. **Add specificity about what the skill does *not* do, or clarify the boundary between this skill and adjacent capabilities.**"

### 4.3 官方推荐的触发评测方法（可直接照搬）

- 约 **20 条** eval queries：8-10 条 should_trigger + 8-10 条 should_not_trigger
- **最有价值的负例是 near-miss**（共享关键词但实际需要别的东西），而非明显无关的查询
- 每条跑 **3 次**算 **trigger rate**，阈值 **0.5**
- **train/validation 切分**：train ~60% 用于指导修改、validation ~40% 只用于验收，防止过拟合
- **优化循环**：Evaluate → Identify failures(train only) → Revise → Repeat，**5 轮通常足够**
- 官方 tip：`skill-creator` skill（`github.com/anthropics/skills/tree/main/skills/skill-creator`）可自动化该循环

---

## 5. 校验工具 / lint / schema

**有官方校验工具，但没有公开的 JSON Schema 文件。**

- 工具：`skills-ref`，官方参考库，位于 `github.com/agentskills/agentskills/tree/main/skills-ref`，Apache 2.0
- ⚠️ 官方 README 明确标注：**"This library is intended for demonstration purposes only. It is not meant to be used in production."**
- 安装：`pip install -e .` 或 `uv sync`（Windows 有 PowerShell / cmd 两套步骤）
- CLI 三个子命令：
  - `skills-ref validate path/to/skill` — 校验 frontmatter 合法性与命名约定
  - `skills-ref read-properties path/to/skill` — 输出 JSON 属性
  - `skills-ref to-prompt path/...` — 生成 `<available_skills>` XML 注入 agent 系统提示
- Python API：`from skills_ref import validate, read_properties, to_prompt`
- **JSON Schema**：探测了 5 个常见路径（`skills-ref/schema.json`、`skills-ref/src/skills_ref/schema.json`、`schema/skills.schema.json` 等）**全部 404**。规范正文也未提及 JSON Schema。校验以 Python 库形式实现，无独立 schema 产物。

---

## 6. 逐项判定：赛事 PPT 的 6 条说法

| # | PPT 说法 | 判定 | 依据 |
|---|---|---|---|
| 1 | 渐进式披露 progressive disclosure | ✅ **[官方原文认可]** | specification.md 有专章 `## Progressive disclosure`；home.md 展开为三阶段 |
| 2 | 窄触发强路由 | ⚠️ **[半官方：概念官方，术语是讲师演绎]** | "窄触发"对应官方对 over-broad description 的警告；**但"强路由"官方无此概念**——官方无 routing 机制，只有 description 匹配 |
| 3 | 前置问题要规定好 | ⚠️ **[取决于所指，需向讲师确认]** | 若指"前置条件"→ 官方有：*"State prerequisites in your SKILL.md (e.g., 'Requires Node.js 18+')"* + `compatibility` 字段；若指"让 skill 先反问澄清"→ **官方全站无此说法** |
| 4 | 安全边界内嵌 | ❌ **[讲师演绎，官方归责于客户端]** | 官方有 `allowed-tools`（Experimental）与"Trust considerations"章节，但官方把信任/权限执行**放在 client/harness 侧**（"gate project-level skill loading on a trust check"），**并未要求把安全边界嵌入 skill 内容** |
| 5 | description 约 100 token | ❌ **[表述失真]** | 1024 **字符**才是 description 的硬限。官方 "~100 tokens" 指的是 **metadata = `name` + `description` 合计**在启动时加载的开销，不是 description 单字段 |
| 6 | 主流程 <100 行 | ❌ **[官方无此说法]** | 官方两处均为 **500 lines**；<5000 tokens 为建议值。"100 行"全站零命中 |
| 7 | kebab-case 命名 | ✅ **[基本认可，术语非官方]** | 官方未用 "kebab-case" 一词，但规则实质即 kebab-case，且**更严**：禁连续连字符 + 必须与父目录同名 |

**结论：6 条里真正是官方原文的只有 1 条（渐进式披露）+ 1 条近似（kebab-case）；2 条是讲师演绎（安全边界内嵌、窄触发强路由的"路由"部分）；1 条是数值失真（100 token）；1 条是数值错误（100 行 → 官方 500 行）。**

---

## 7. 三个观察点的直接回答

### 7.1 官方是否明确提到「触发条件」与「不触发条件」的写法？

**是，但分属两份文档。**
- 规范层（强制口径）：`description` "Should describe both what the skill does and **when to use it**" —— 即"触发条件"是规范要求。
- 优化层（方法口径）："不触发条件"作为**修正手段**出现——"Add specificity about what the skill does *not* do, or clarify the boundary between this skill and adjacent capabilities."
- 官方给的 before/after 范例把两者揉进一句话：
  ```yaml
  description: >
    Analyze CSV and tabular data files — compute summary statistics,
    add derived columns, generate charts, and clean messy data. Use this
    skill when the user has a CSV, TSV, or Excel file and wants to
    explore, transform, or visualize the data, even if they don't
    explicitly mention "CSV" or "analysis."
  ```

### 7.2 「渐进式披露」的官方原始表述

规范原文：*"Agents load skills **progressively**, pulling in more detail only as a task calls for it."*

三级加载预算（specification.md `## Progressive disclosure`）：

| 层级 | 内容 | 官方 token 口径 | 加载时机 |
|---|---|---|---|
| 1. Metadata | `name` + `description` | **~100 tokens** | 启动时，对**所有** skill 加载 |
| 2. Instructions | 完整 `SKILL.md` body | **< 5000 tokens (recommended)** | skill 被激活时 |
| 3. Resources | `scripts/` `references/` `assets/` | as needed | 按需 |

home.md 把同一条机制重述为**三阶段**：**Discovery → Activation → Execution**。

> 此处正是 PPT "description 约 100 token" 说法的来源——讲师把**第 1 级 metadata 的总预算**记成了 description 单字段的预算。

### 7.3 官方是否有 skills 目录的分发/复用机制（插件市场、registry）？

**没有官方 registry，也没有官方插件市场。**

- 官方的复用叙事是**格式可移植性**，不是分发基础设施：home.md 原文 *"Build a skill once and use it across any skills-compatible agent"*，以及 *"portable, version-controlled folders"*。
- `registry` 一词全站仅出现 **1 次**，且是在**给客户端实现者的假设性建议**里（llms-full.txt 第 10 行）：*"A cloud-hosted or sandboxed agent will need an alternative discovery mechanism — **an API, a remote registry, or bundled assets**."* —— 这是让客户端自己去想，不是规范定义的分发机制。
- **实际生态靠 client 各自实现**：`home.md` 的 Client Showcase 列出约 50 个支持产品（Claude Code、Claude、ChatGPT/Codex、GitHub Copilot、VS Code、Cursor、Gemini CLI、OpenCode、Goose、Spring AI、Snowflake、Databricks、Kiro、Tabnine 等），每个 client 有自己的安装路径约定（目录 / 配置文件 / CLI flag）。规范明确说 "how this works varies by client"。
- 官方对 client 的发现机制指导见 `client-implementation/adding-skills-support.md`，列出三种层级：**project-level / user-level / organization-level** skills。

---

## 8. 与本项目直接相关的可执行结论

1. **`name` 必须等于父目录名** —— 若 `skills/<x>/SKILL.md` 里写 `name: <y>`，官方校验直接失败。这是最容易踩的坑。
2. **description 用 1024 字符额度，不要自我压缩到"100 token"** —— 讲师说法会让我们写得过短，反而伤触发率。
3. **主文件上限按 500 行 / 5000 tokens 控制**，不是 100 行。
4. **`allowed-tools` 是 Experimental**，跨 client 支持不一致，不要作为安全边界的唯一依赖。
5. **可交付的客观验证**：`skills-ref validate ./<skill-dir>`，可直接作为赛事作品的自检环节。
6. **description 的"不触发条件"要写**，但依据应引 optimizing-descriptions.md 而非 specification.md（规范正文没写）。
