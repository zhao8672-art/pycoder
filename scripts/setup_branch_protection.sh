#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  setup_branch_protection.sh — 配置 GitHub Branch Protection Rules
#
#  功能:
#    使用 gh CLI 自动配置 master 分支的保护规则, 将全部 CI 门禁设为必需检查。
#    配置完成后, PR 合并前必须通过所有必需状态检查。
#
#  前置条件:
#    1. 已安装 GitHub CLI (gh): https://cli.github.com/
#    2. 已认证: gh auth login
#    3. 对仓库有 admin 权限
#
#  用法:
#    bash scripts/setup_branch_protection.sh                    # 交互式输入 owner/repo
#    REPO="PyCoder-ai/pycoder" bash scripts/setup_branch_protection.sh  # 直接指定
#
#  安全说明:
#    - 此脚本仅修改分支保护规则, 不触碰代码
#    - enforce_admins=true: 管理员也受保护规则约束 (防止绕过门禁)
#    - allow_force_pushes=false: 禁止 force push 到 master
#    - allow_deletions=false: 禁止删除 master
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── 颜色输出 ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── 参数解析 ──────────────────────────────────────────────
# REPO 环境变量格式: "owner/repo" (如 "PyCoder-ai/pycoder")
# 未设置时尝试从 git remote 自动推断
if [[ -z "${REPO:-}" ]]; then
  REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
  if [[ "$REMOTE_URL" =~ github\.com[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    info "从 git remote 推断仓库: ${REPO}"
  else
    read -rp "请输入仓库 (owner/repo, 如 PyCoder-ai/pycoder): " REPO
  fi
fi

BRANCH="${BRANCH:-master}"
info "目标分支: ${BRANCH}"
info "目标仓库: ${REPO}"

# ── 前置检查 ──────────────────────────────────────────────
info "检查前置条件..."

if ! command -v gh &>/dev/null; then
  error "未找到 gh CLI, 请先安装: https://cli.github.com/"
  exit 1
fi

if ! gh auth status &>/dev/null; then
  error "gh CLI 未认证, 请运行: gh auth login"
  exit 1
fi

success "前置条件检查通过"

# ── 必需状态检查列表 ──────────────────────────────────────
# 这些名称必须与 workflow 文件中 job 的 name 字段完全一致
# GitHub Branch Protection 使用这些名称匹配状态检查
REQUIRED_CHECKS=(
  # ── ci.yml (主 CI) ──
  "ubuntu-latest / py3.14"        # 跨平台主测试 (Linux)
  "windows-latest / py3.14"       # 跨平台主测试 (Windows)
  "慢测试 / 集成测试"              # 慢测试 + 集成测试
  "构建验证 (wheel)"              # wheel 构建 + import 验证
  # ── stress-test.yml (独立 workflow) ──
  "高并发 fixture 压测"           # 高并发压测 (带 3 次重试)
  # ── security-scan.yml ──
  "security"                      # 安全扫描 (Bandit + Semgrep + Safety)
)

info "必需状态检查 (${#REQUIRED_CHECKS[@]} 项):"
for check in "${REQUIRED_CHECKS[@]}"; do
  echo "  • ${check}"
done

# ── 确认操作 ──────────────────────────────────────────────
echo ""
warn "即将配置 ${BRANCH} 分支保护规则, 这将:"
echo "  - 要求 PR 合并前通过所有必需状态检查"
echo "  - 要求至少 1 人 Code Review 批准"
echo "  - 禁止 force push 和删除分支"
echo "  - 管理员也受规则约束 (enforce_admins)"
echo ""
read -rp "确认继续? (y/N): " confirm
if [[ "${confirm,,}" != "y" ]]; then
  info "已取消"
  exit 0
fi

# ── 配置分支保护 ──────────────────────────────────────────
info "正在配置分支保护规则..."

# 构建 JSON payload
# 使用 jq 安全构建 JSON, 避免转义问题
PAYLOAD=$(jq -n \
  --argjson checks "$(printf '%s\n' "${REQUIRED_CHECKS[@]}" | jq -R . | jq -s .)" \
  '{
    required_status_checks: {
      strict: true,
      contexts: $checks
    },
    enforce_admins: true,
    required_pull_request_reviews: {
      required_approving_review_count: 1,
      dismiss_stale_reviews: true,
      require_code_owner_reviews: false
    },
    restrictions: null,
    allow_force_pushes: false,
    allow_deletions: false,
    required_linear_history: true,
    required_conversation_resolution: true
  }')

# 调用 GitHub API
API_PATH="repos/${REPO}/branches/${BRANCH}/protection"

if echo "$PAYLOAD" | gh api -X PUT "$API_PATH" --input - 2>&1 | tee /tmp/gh_protection_result.txt; then
  success "分支保护规则配置成功!"
else
  error "分支保护规则配置失败"
  cat /tmp/gh_protection_result.txt
  exit 1
fi

# ── 验证配置 ──────────────────────────────────────────────
info "验证配置..."

PROTECTION=$(gh api "repos/${REPO}/branches/${BRANCH}/protection" 2>/dev/null || echo "")

if [[ -n "$PROTECTION" ]]; then
  CONFIGURED_CHECKS=$(echo "$PROTECTION" | jq -r '.required_status_checks.contexts[]?' 2>/dev/null || echo "")

  echo ""
  info "已配置的必需状态检查:"
  if [[ -n "$CONFIGURED_CHECKS" ]]; then
    while IFS= read -r check; do
      echo "  • ${check}"
    done <<< "$CONFIGURED_CHECKS"
  else
    warn "未读取到必需状态检查 (可能权限不足)"
  fi

  echo ""
  info "保护规则概览:"
  echo "  enforce_admins:             $(echo "$PROTECTION" | jq -r '.enforce_admins.enabled')"
  echo "  require_pr_reviews:         $(echo "$PROTECTION" | jq -r '.required_pull_request_reviews.required_approving_review_count // "未设置")')"
  echo "  allow_force_pushes:         $(echo "$PROTECTION" | jq -r '.allow_force_pushes.enabled')"
  echo "  allow_deletions:            $(echo "$PROTECTION" | jq -r '.allow_deletions.enabled')"
  echo "  required_linear_history:    $(echo "$PROTECTION" | jq -r '.required_linear_history.enabled')"
  echo "  strict_status_checks:       $(echo "$PROTECTION" | jq -r '.required_status_checks.strict')"
fi

echo ""
success "═══════════════════════════════════════════════════"
success "  Branch Protection 配置完成!"
success "═══════════════════════════════════════════════════"
echo ""
echo "现在 PR 合并前必须通过以下全部检查:"
for check in "${REQUIRED_CHECKS[@]}"; do
  echo "  ✅ ${check}"
done
echo ""
info "提示: 如需移除保护规则, 运行:"
echo "  gh api -X DELETE repos/${REPO}/branches/${BRANCH}/protection"
