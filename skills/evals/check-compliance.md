# Skill 合规门禁（交付前自检）

对 `skills/` 下 4 个 skill 跑官方校验器 `skills-ref`，验证 frontmatter 符合 Agent Skills 规范。

## 怎么跑

在项目根（`<repo>` = 本仓库克隆目录）执行：

```bash
for d in inspection-orchestrator safety-hazard-detection gauge-reading inspection-report; do
  ./.venv/Scripts/agentskills.exe validate "skills/$d" || echo "FAILED: $d"
done
```

单跑一个：

```bash
./.venv/Scripts/agentskills.exe validate skills/gauge-reading
```

## 预期结果

4 个全部输出 `Valid skill: skills\<name>`，**退出码 0**。

```
Valid skill: skills\inspection-orchestrator
Valid skill: skills\safety-hazard-detection
Valid skill: skills\gauge-reading
Valid skill: skills\inspection-report
```

失败时长这样（退出码 1），任一行出现即视为门禁不通过：

```
Validation failed for <path>:
  - Directory name 'x' must match skill name 'y'
```

## 环境（已配置，勿重复折腾）

- 解释器：`<repo>\.venv\Scripts\python.exe`（Python 3.12.10）
- 包：`skills-ref==0.1.1`，Apache-2.0，PyPI 作者 `Keith Lazuka <klazuka@anthropic.com>`（Anthropic 官方）
- 依赖：`click 8.5.0`、`strictyaml 1.7.3`、`python-dateutil`、`six`
- 重装：`./.venv/Scripts/python.exe -m pip install "skills-ref==0.1.1"`

> ⚠️ **坑：CLI 可执行文件叫 `agentskills.exe`，不叫 `skills-ref.exe`。**
> PyPI 包名是 `skills-ref`，但安装后生成的命令是 `agentskills`。
> 官方文档里写的 `skills-ref validate ./my-skill` 指的是 GitHub 仓库里 `pip install -e .` 的本地安装路径，与 PyPI 包的命令名不一致。

## 其他可用子命令

```bash
./.venv/Scripts/agentskills.exe read-properties skills/gauge-reading   # 输出 JSON 属性
./.venv/Scripts/agentskills.exe to-prompt skills/gauge-reading         # 生成 <available_skills> XML
```

## Tier 1 静态质检（零 API 成本）

`skills/evals/results/tier1-static.json` 里的 `overall_score` / `grade` / `dimensions`
是由 **NVIDIA SkillEvaluator 的 `quality-check` 子命令**产出的：

```bash
skillevaluator quality-check skills/<skill> -r json -o <输出目录>
```

> ⚠️ **口径坑（实测踩过）**：不要用 `skillevaluator tier1 PATH` 去复现那批数字。
> `tier1` 的 JSON 输出结构完全不同——只有 `overall_passed` / `issue_count` / 各严重度计数，
> **没有百分制 `overall_score`**。要复现 `tier1-static.json` 必须用 `quality-check`。
>
> 另一个坑：`quality-check` **不接受 `--no-llm`**（会报 `No such option`），
> 而 `tier1` 接受。两者选项集不同。

**对比分数时注意基准**：静态分经历过多轮受控实验，取错基准会把
**我们自己量到的效应**误读成工具漂移。正确的时间线与归因见
`docs/agents/experiment-version-note.md` §2b。

## 这个门禁能查什么 / 不能查什么

**能查**（已用负面对照实测确认，非空跑）：
- `name` 与父目录名不一致 → 报 `Directory name '...' must match skill name '...'`
- `name` 含大写 → 报 `Skill name '...' must be lowercase`
- 缺必填字段 → 报 `Missing required field in frontmatter: description`

> 负面对照方法（可复现）：在临时目录建 `bad-dir-name/SKILL.md`，写入 `name: totally-different-name`，`validate` 退出码 1。

**不能查**：
- 文件行数 / token 体积（官方 500 行只是**建议值**，校验器不强制）
- description 的触发质量、是否写了「不适用」边界
- 正文内容质量

## 权威性说明

官方 `skills-ref` README 自述：*"This library is intended for demonstration purposes only. It is not meant to be used in production."*

因此它是**一层保险，不是权威判定**。规范正文（`https://agentskills.io/specification.md`）才是判据；校验器只覆盖 frontmatter 的可机械检查部分。装不上或版本失效时，按规范正文人工核对即可，不阻塞交付。
