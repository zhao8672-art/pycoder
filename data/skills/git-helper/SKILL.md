# Git 助手

## 技能描述
帮助进行 Git 操作，包括提交、分支管理、合并冲突解决等。

## 功能
- 生成规范的提交信息
- 解决合并冲突
- 分支管理建议
- 代码回滚操作
- 交互式 rebase
- .gitignore 管理

## 使用方式
```
请帮我 [Git 操作描述]
```

## 支持的 Git 操作
1. **提交**: 生成 Conventional Commits 格式的提交信息
2. **分支**: 创建、切换、合并、删除分支
3. **冲突**: 分析冲突并提供解决方案
4. **回滚**: reset、revert 操作指导
5. **历史**: log、blame、diff 分析
6. **标签**: 创建和管理版本标签

## 提交信息格式
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```
类型: feat, fix, docs, style, refactor, test, chore
