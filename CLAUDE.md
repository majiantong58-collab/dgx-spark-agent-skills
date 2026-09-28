# Invda Project

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛

## Agent skills

### Issue tracker

Issues and specs are tracked as GitHub issues in the [majiantong58-collab/dgx-spark-agent-skills](https://github.com/majiantong58-collab/dgx-spark-agent-skills) repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles map to label strings in `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` at the repo root and `docs/adr/` for ADRs. See `docs/agents/domain.md`.

### 事实性断言的单一来源

**事实性断言只在单一来源定义，别处一律引用、不复述。**
数字、能力状态（已实现/不支持）、修复状态（已修复/未修复）、外部状态（仓库/节点/授权）都算。
复述不可避免时（如 `README.md`），**必须带可 grep 的指向**。
详见 `docs/agents/fact-single-source.md`（含两个已知盲区与四个实例）。
