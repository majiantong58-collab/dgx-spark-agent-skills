# Scratch Directory

这个目录用于本地 issue tracking（当 GitHub 不可用时）。

## 结构

```
.scratch/
├── <feature-slug>/
│   ├── spec.md                    # 功能规格说明
│   └── issues/
│       ├── 01-<slug>.md           # 实现任务 1
│       ├── 02-<slug>.md           # 实现任务 2
│       └── ...
└── ...
```

## 使用

- **发布到 issue tracker**: 在 `.scratch/<feature-slug>/` 创建文件
- **获取 ticket**: 读取对应的 markdown 文件

当前使用 **GitHub Issues** 作为主要 issue tracker，此目录预留。
