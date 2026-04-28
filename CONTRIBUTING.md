# 项目协作规范

本仓库的默认协作策略只固定三件事：

1. **提交说明默认使用中文**
2. **提交说明必须使用仓库模板，先写为什么要改，再写背景、取舍、风险和验证**
3. **主线合并统一采用 Squash Merge**

这些约定的目标是让主线历史保持“一个需求 / 一个修复 / 一个意图对应一个清晰提交”，同时保证回溯时能快速看懂提交原因和验证范围。

## 1. 本地 Git 初始化

首次克隆后，先执行：

```bash
uv run python scripts/setup_git_conventions.py
```

这会为当前仓库设置：

- `commit.template = .gitmessage-zh-CN.txt`
- `core.hooksPath = .githooks`
- `i18n.commitEncoding = utf-8`
- `i18n.logOutputEncoding = utf-8`

如果不执行这一步，本地 `git commit` 不会自动带出模板，`commit-msg` 校验也不会生效。

## 2. 提交说明规范（默认中文）

所有常规提交默认使用中文，且遵循以下结构：

```text
<一句话说明本次提交的意图>

<补充说明：问题背景、修改思路、影响范围、为什么这样做。>

约束: <这次修改受什么外部条件限制>
备选方案: <考虑过但没采用的方案> | <放弃原因>
信心: <低|中|高>
风险范围: <小|中|大>
提醒: <给以后维护者的注意事项>
已验证: <做了哪些测试或检查>
未验证: <还有哪些没覆盖到>
```

提交说明要求：

- 第一行写“**为什么要改**”，不要只写“改代码”“修复 bug”“更新”。
- 正文写背景、取舍、影响范围，不要只是重复 diff。
- `约束 / 备选方案 / 信心 / 风险范围 / 提醒 / 已验证 / 未验证` 为默认必填项。
- 如果团队需要 Conventional Commits，可以写成 `fix(模块): 为什么要改`，但核心规则不变。

仓库会通过 `.githooks/commit-msg` 调用 `scripts/validate_commit_message.py` 做提交校验。

## 3. 分支与合并策略（统一采用 Squash Merge）

默认流程：

```bash
git checkout master
git pull --ff-only origin master

git checkout -b feature/xxx
# 开发并提交
git push -u origin feature/xxx
```

然后：

- 通过 GitHub Pull Request 发起审查
- 合入 `master` 时统一使用 **Squash Merge**
- 不使用 merge commit
- 不使用 rebase merge

当前远端仓库已配置为：

- `allow_squash_merge = true`
- `allow_merge_commit = false`
- `allow_rebase_merge = false`

### 为什么统一用 Squash Merge

- 主线历史更干净，阅读成本更低
- 一个 PR 最终对应一个主线提交，回滚更直接
- 开发过程中的中间提交可以保留工作节奏，但不会把噪声直接带入主线

### 使用 Squash Merge 时的额外要求

- 一个分支只做一件事，不要在同一 PR 中混入多个不相关目标
- PR 标题要能直接表达“为什么要改”，因为 Squash 后通常会复用或参考 PR 标题
- Squash 后生成的主线提交仍需符合中文 commit 模板规范

## 4. Pull Request 填写要求

仓库提供了 `.github/pull_request_template.md`，提交 PR 时按模板补齐：

- 变更意图
- 背景与方案
- 风险与验证
- 是否符合 Squash Merge 预期

如果一个 PR 无法被自然地压成一个清晰主线提交，说明它的范围通常已经过大，需要拆分。
