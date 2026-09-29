# Invda Project

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛

## Agent skills

### Issue tracker

Issues and specs are tracked as GitHub issues in the [majiantong58-collab/dgx-spark-agent-skills](https://github.com/majiantong58-collab/dgx-spark-agent-skills) repo.

### Triage labels

Five canonical triage roles map to label strings on GitHub issues.

### Domain docs

Single-context layout: `CONTEXT.md` at the repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.

### 事实性断言的单一来源

**事实性断言只在单一来源定义，别处一律引用、不复述。**
数字、能力状态（已实现/不支持）、修复状态（已修复/未修复）、外部状态（仓库/节点/授权）都算。
复述不可避免时（如 `README.md`），**必须带可 grep 的指向**。
详见 `docs/agents/fact-single-source.md`（含两个已知盲区与四个实例）。

### 验证纪律：绿 ≠ 看起来的意思

**绿灯的效力必须被单独证明，不能从「是绿的」推出来。**
五类失效：假绿 / 绿而不完整 / 覆盖表声称有覆盖 / 工具替未证结论背书 / 断言已撤回的主张。
四条纪律：证据须能证伪结论 · 先证明被执行了 · **让结论与环境无关而非控制环境** · 不许 SKIP 计入通过。
详见 `docs/agents/verification-lessons.md`（含当日七类问题的实例与堵法）。
