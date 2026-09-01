---
name: git-commit
description: 规范化 git commit 流程：检查状态、分类变更、生成符合 Conventional Commits 规范的提交信息
---

# Git Commit 技能

## 使用时机

用户要求提交代码，或完成一批文件修改后需要 commit 时。

## 流程

1. 运行 `git status` 查看所有变更文件
2. 运行 `git diff` 理解具体改动内容
3. 按照下方规范生成 commit message
4. 运行 `git add -A`（或指定文件）
5. 运行 `git commit -m "<message>"`

## Commit Message 规范（Conventional Commits）

格式：`<type>(<scope>): <subject>`

| type | 含义 |
|------|------|
| feat | 新功能 |
| fix | bug 修复 |
| refactor | 重构（不改变行为） |
| docs | 文档变更 |
| test | 测试相关 |
| chore | 构建/工具/依赖 |

- subject 用中文或英文均可，不超过 72 字符
- scope 可选，填模块名，如 `feat(auth): ...`
- 多个独立变更可以分多次 commit

## 示例

```
feat(tools): 新增 todo_write 工具支持任务状态追踪
fix(permission): 修复 Windows 路径判断在 UNC 路径下失败
docs: 更新 README 安装说明
```
