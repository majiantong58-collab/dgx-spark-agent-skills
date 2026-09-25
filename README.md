# DGX Spark Agent Skills

> 第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛

## 项目简介

基于 NVIDIA DGX Spark 本地算力，开发 Agent Skills 扩展 Agent 专业能力。

## 核心目标

- [ ] 设计并实现 Agent Skills
- [ ] 集成 NVIDIA 技术栈（DGX Spark、NeMo、MCP）
- [ ] 实现多智能体协同
- [ ] 完成完整演示视频和文档

## 评分重点

1. **技术创新性**（25%）- Agent Skills 设计和多智能体协同
2. **技术深度**（25%）- 模型优化和 NVIDIA 技术栈使用
3. **项目完整性**（30%）- 功能完整、文档详实、能顺利演示
4. **平台适配**（15%）- DGX Spark 和 NVIDIA SDK 的深度使用

## 技术栈

- NVIDIA DGX Spark / GX10
- NVIDIA NeMo 3.5 Lightning
- NVIDIA Skills（300+ verified skills）
- StepFun Step 多模态模型
- MCP (Model Context Protocol)
- ROS Mini 机器人

## 竞赛信息

- **截止日期**: 2026年9月29日 23:59
- **总决赛**: 2026年10月15日（苏州金鸡湖）
- **奖品**: 冠军获得华硕 Essent GX10 + StepPlan Max（价值6666元）

## 项目结构

```
.
├── CONTEXT.md              # 项目上下文和背景
├── CLAUDE.md               # Claude Code 配置
├── docs/
│   ├── agents/             # Agent 技能配置
│   │   ├── issue-tracker.md
│   │   ├── triage-labels.md
│   │   └── domain.md
│   └── adr/                # Architecture Decision Records
├── .scratch/               # 本地 issue tracking（预留）
└── src/                    # 源代码（待开发）
```

## 开发工作流

1. 在 GitHub Issues 中创建任务
2. 使用 Claude Code 和工程技能开发
3. 提交代码到 GitHub
4. 定期更新文档和演示视频

## 相关链接

- **GitHub 仓库**: https://github.com/majiantong58-collab/dgx-spark-agent-skills
- **NVIDIA 开发者社区**: https://developer.nvidia.com
- **NVIDIA 中国开发者日**: 10月15日（苏州金鸡湖会展中心）
