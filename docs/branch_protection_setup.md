# Branch Protection Rules 配置指南

> 配置完成后，PR 合并前必须通过全部 CI 门禁检查，确保代码质量。

## 必需状态检查清单

以下 6 项状态检查需要配置为必需（Required）：

| # | 检查名称 | 所属 Workflow | 说明 |
|---|---------|--------------|------|
| 1 | `ubuntu-latest / py3.14` | PyCoder CI | Linux 主测试 + 覆盖率 ≥80% |
| 2 | `windows-latest / py3.14` | PyCoder CI | Windows 跨平台测试 |
| 3 | `慢测试 / 集成测试` | PyCoder CI | 慢测试 + 集成测试 |
| 4 | `构建验证 (wheel)` | PyCoder CI | wheel 构建 + import 验证 |
| 5 | `高并发 fixture 压测` | 高并发压测 | 4 阶段压测 (3 次重试) |
| 6 | `security` | Security Scan | Bandit + Semgrep + Safety 安全扫描 |

---

## 方式一：自动化脚本（推荐）

使用 `gh` CLI 一键配置，无需手动点击 UI。

### 前置条件

```bash
# 安装 GitHub CLI (macOS)
brew install gh

# 安装 GitHub CLI (Windows)
winget install GitHub.cli

# 认证
gh auth login
```

### 执行

```bash
# 自动从 git remote 推断 owner/repo
bash scripts/setup_branch_protection.sh

# 或直接指定
REPO="PyCoder-ai/pycoder" bash scripts/setup_branch_protection.sh
```

脚本会自动：
- 配置 6 项必需状态检查
- 要求至少 1 人 Code Review 批准
- 启用 `enforce_admins`（管理员也受约束）
- 禁止 force push 和分支删除
- 启用线性历史（禁止 merge commit，要求 squash/rebase）

---

## 方式二：GitHub UI 手动配置

### 步骤 1：进入分支保护设置

1. 打开仓库页面：`https://github.com/<owner>/<repo>`
2. 点击 **Settings** 标签
3. 左侧菜单选择 **Branches**
4. 在 "Branch protection rules" 区域点击 **Add branch protection rule**

### 步骤 2：配置保护规则

#### 2.1 基本信息

- **Branch name pattern**: `master`

#### 2.2 Protect matching branches

勾选以下选项：

```
☑ Require a pull request before merging
    Required approving reviews: 1
    ☑ Dismiss stale pull request approvals when new commits are pushed
    ☐ Require review from Code Owners  (可选, 按需开启)

☑ Require status checks to pass before merging
    ☑ Require branches to be up to date before merging
    在下方搜索框逐个添加以下 6 项检查 (见下方)

☑ Require conversation resolution before merging

☑ Do not allow bypassing the above settings  (enforce_admins)
```

#### 2.3 添加必需状态检查

在 "Require status checks" 区域的搜索框中，逐个搜索并添加：

1. 搜索 `ubuntu-latest` → 选择 **ubuntu-latest / py3.14**
2. 搜索 `windows-latest` → 选择 **windows-latest / py3.14**
3. 搜索 `慢测试` → 选择 **慢测试 / 集成测试**
4. 搜索 `构建验证` → 选择 **构建验证 (wheel)**
5. 搜索 `高并发` → 选择 **高并发 fixture 压测**
6. 搜索 `security` → 选择 **security**

> **注意**: 搜索框只显示**最近运行过**的检查。如果是首次配置，请先触发一次 CI 运行（push 任意 commit），确保所有 workflow 都至少执行过一次。

#### 2.4 以下选项不要勾选

```
☐ Allow force pushes
☐ Allow deletions
☐ Lock branch
```

### 步骤 3：保存

点击页面底部的 **Create** 按钮。

---

## 方式三：GitHub API 直接调用

适合 CI/CD 自动化场景。

### 单条命令配置

```bash
REPO="PyCoder-ai/pycoder"  # 替换为你的仓库
BRANCH="master"

gh api -X PUT "repos/${REPO}/branches/${BRANCH}/protection" --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "ubuntu-latest / py3.14",
      "windows-latest / py3.14",
      "慢测试 / 集成测试",
      "构建验证 (wheel)",
      "高并发 fixture 压测",
      "security"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": true,
  "required_conversation_resolution": true
}
EOF
```

### 验证配置

```bash
gh api "repos/${REPO}/branches/${BRANCH}/protection" | jq '.required_status_checks.contexts'
```

预期输出：
```json
[
  "ubuntu-latest / py3.14",
  "windows-latest / py3.14",
  "慢测试 / 集成测试",
  "构建验证 (wheel)",
  "高并发 fixture 压测",
  "security"
]
```

---

## 配置后的效果

配置完成后，PR 合并时会强制检查：

```
PR 合并条件:
  ✅ 至少 1 人 Code Review 批准
  ✅ ubuntu-latest / py3.14       (主测试 + 覆盖率)
  ✅ windows-latest / py3.14      (跨平台测试)
  ✅ 慢测试 / 集成测试
  ✅ 构建验证 (wheel)
  ✅ 高并发 fixture 压测           (带 3 次重试)
  ✅ security                     (安全扫描)
  ✅ 分支已 up-to-date (无冲突)
  ✅ 所有对话已标记为已解决
```

任一条件不满足 → **Merge 按钮灰色不可点击**。

---

## 移除保护规则

如需临时移除保护（不推荐）：

```bash
# 通过 gh CLI
gh api -X DELETE "repos/${REPO}/branches/${BRANCH}/protection"

# 或在 GitHub UI:
# Settings → Branches → 对应规则右侧 "Delete"
```

---

## 常见问题

### Q: 搜索框找不到某个状态检查？

状态检查只显示**最近运行过**的。先 push 一个 commit 触发所有 workflow，等待运行完成后重试。

### Q: 必需检查名称与 workflow 中的 name 字段不一致？

GitHub 使用 job 的 `name` 属性作为状态检查名称。如修改了 workflow 中的 `name`，需同步更新 Branch Protection 配置。当前对应关系：

| Workflow 文件 | job name 字段 | 状态检查名称 |
|---------------|--------------|-------------|
| ci.yml | `"${{ matrix.os }} / py${{ matrix.python-version }}"` | `ubuntu-latest / py3.14` / `windows-latest / py3.14` |
| ci.yml | `"慢测试 / 集成测试"` | `慢测试 / 集成测试` |
| ci.yml | `"构建验证 (wheel)"` | `构建验证 (wheel)` |
| stress-test.yml | `"高并发 fixture 压测"` | `高并发 fixture 压测` |
| security-scan.yml | (job_id: security) | `security` |

### Q: enforce_admins 开启后管理员也无法绕过？

是的。`enforce_admins=true` 后，包括仓库 owner 在内的所有人都必须遵守保护规则。这是防止"走后门"合并的安全最佳实践。如需紧急修复，可临时关闭保护规则再恢复。
