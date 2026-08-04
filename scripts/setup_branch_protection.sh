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
#    3. token 需包含 scope: repo + workflow (缺失时自动尝试 gh auth refresh)
#    4. 对仓库有 admin 权限
#
#  用法:
#    bash scripts/setup_branch_protection.sh                          # 交互式
#    REPO="PyCoder-ai/pycoder" bash scripts/setup_branch_protection.sh  # 指定仓库
#    bash scripts/setup_branch_protection.sh --dry-run                # 预览不执行
#    bash scripts/setup_branch_protection.sh --no-confirm --verbose   # CI/CD 模式
#    bash scripts/setup_branch_protection.sh --log-file /tmp/bp.log   # 输出日志到文件
#
#  选项:
#    --dry-run         预览配置内容, 不实际执行 API 调用
#    --no-confirm      跳过确认提示 (适合 CI/CD 自动化)
#    --verbose         显示 DEBUG 级别日志
#    --log-file PATH   同时将日志写入指定文件
#    --max-retries N   API 调用最大重试次数 (默认 3)
#    --no-auto-trigger 缺失检查时不自动触发 workflow (仅警告)
#    --repo REPO       指定仓库 (等同于 REPO 环境变量)
#    --branch BRANCH   指定分支 (默认 master)
#    -h, --help        显示帮助
#
#  退出码:
#    0  成功
#    1  通用错误 (参数错误、前置检查失败)
#    2  认证错误 (gh CLI 未安装或未认证)
#    3  网络错误 (重试耗尽)
#    4  API 错误 (GitHub 返回非 2xx)
#
#  安全说明:
#    - 此脚本仅修改分支保护规则, 不触碰代码
#    - enforce_admins=true: 管理员也受保护规则约束 (防止绕过门禁)
#    - allow_force_pushes=false: 禁止 force push 到 master
#    - allow_deletions=false: 禁止删除 master
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── 默认配置 ──────────────────────────────────────────────
DRY_RUN=false
NO_CONFIRM=false
VERBOSE=false
LOG_FILE=""
MAX_RETRIES=3
NO_AUTO_TRIGGER=false
TRIGGER_TIMEOUT=600  # 等待 workflow 完成的超时秒数 (默认 10 分钟)
REPO="${REPO:-}"
BRANCH="${BRANCH:-master}"

# ── 临时文件 ──────────────────────────────────────────────
TMP_DIR=$(mktemp -d -t branch_protection_XXXXXX)
trap 'cleanup' EXIT INT TERM

cleanup() {
  local exit_code=$?
  if [[ -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
  exit "$exit_code"
}

# ── 颜色输出 ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
NC='\033[0m'

# ── 日志系统 ──────────────────────────────────────────────
# 日志级别: DEBUG < INFO < WARN < ERROR
# VERBOSE=true 时显示 DEBUG, 否则从 INFO 开始
_log() {
  local level="$1"
  shift
  local color="$BLUE"
  local prefix="INFO"

  case "$level" in
    DEBUG) color="$GRAY"; prefix="DEBUG"; [[ "$VERBOSE" == "false" ]] && return ;;
    INFO)  color="$BLUE"; prefix="INFO " ;;
    WARN)  color="$YELLOW"; prefix="WARN " ;;
    ERROR) color="$RED"; prefix="ERROR"; ;;
    OK)    color="$GREEN"; prefix="OK   " ;;
  esac

  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')

  # 控制台输出 (带颜色)
  echo -e "${GRAY}${timestamp}${NC} ${color}[${prefix}]${NC} $*"

  # 日志文件输出 (无颜色, 纯文本)
  if [[ -n "$LOG_FILE" ]]; then
    echo "${timestamp} [${prefix}] $*" >> "$LOG_FILE"
  fi
}

debug()   { _log DEBUG "$*"; }
info()    { _log INFO "$*"; }
success() { _log OK "$*"; }
warn()    { _log WARN "$*"; }
error()   { _log ERROR "$*" >&2; }

# ── 错误 trap (打印调用栈) ────────────────────────────────
on_error() {
  local exit_code=$?
  local line_no=$1
  error "脚本在第 ${line_no} 行失败, 退出码: ${exit_code}"
  error "调用栈:"
  local i=0
  while caller $i 2>/dev/null | read -r ln fn file; do
    error "  ${i}: ${file}:${ln} ${fn}"
    ((i++))
  done
  exit "$exit_code"
}
trap 'on_error ${LINENO}' ERR

# ── 参数解析 ──────────────────────────────────────────────
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)       DRY_RUN=true; shift ;;
      --no-confirm)    NO_CONFIRM=true; shift ;;
      --verbose)       VERBOSE=true; shift ;;
      --log-file)      LOG_FILE="$2"; shift 2 ;;
      --max-retries)   MAX_RETRIES="$2"; shift 2 ;;
      --no-auto-trigger) NO_AUTO_TRIGGER=true; shift ;;
      --repo)          REPO="$2"; shift 2 ;;
      --branch)        BRANCH="$2"; shift 2 ;;
      -h|--help)
        sed -n '2,/^# ══/{ /^# ══/!p; }' "$0" | sed 's/^# \?//'
        exit 0
        ;;
      *)
        error "未知参数: $1 (使用 --help 查看帮助)"
        exit 1
        ;;
    esac
  done
}

parse_args "$@"

# ── 日志文件初始化 ────────────────────────────────────────
if [[ -n "$LOG_FILE" ]]; then
  : > "$LOG_FILE"
  info "日志文件: ${LOG_FILE}"
fi

debug "配置参数: DRY_RUN=${DRY_RUN}, NO_CONFIRM=${NO_CONFIRM}, VERBOSE=${VERBOSE}, MAX_RETRIES=${MAX_RETRIES}"

# ── 仓库推断 ──────────────────────────────────────────────
if [[ -z "$REPO" ]]; then
  REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
  if [[ "$REMOTE_URL" =~ github\.com[:/]([^/]+)/([^/]+?)(\.git)?$ ]]; then
    REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    info "从 git remote 推断仓库: ${REPO}"
  else
    if [[ "$NO_CONFIRM" == "true" ]]; then
      error "无法推断仓库且 --no-confirm 模式下无法交互输入, 请用 --repo 指定"
      exit 1
    fi
    read -rp "请输入仓库 (owner/repo, 如 PyCoder-ai/pycoder): " REPO
  fi
fi

info "目标仓库: ${REPO}"
info "目标分支: ${BRANCH}"
debug "临时目录: ${TMP_DIR}"

# ── 前置检查 ──────────────────────────────────────────────
info "检查前置条件..."

# 检查 gh CLI
if ! command -v gh &>/dev/null; then
  error "未找到 gh CLI, 请先安装: https://cli.github.com/"
  exit 2
fi
debug "gh CLI 路径: $(command -v gh)"

# 检查 jq
if ! command -v jq &>/dev/null; then
  error "未找到 jq, 请先安装: https://stedolan.github.io/jq/download/"
  exit 1
fi
debug "jq 路径: $(command -v jq)"

# ── 检查 gh CLI 认证状态和 token 权限 (带重试) ────────────
# 本脚本需要以下 token scope:
#   repo      — 仓库访问、分支保护 API、读取 workflow 运行状态
#   workflow  — 触发 workflow (gh workflow run, 需 workflow_dispatch)
#
# 权限不足时自动尝试 gh auth refresh 补充 scope (最多 2 次)
# --no-confirm 模式下跳过交互式 refresh, 仅报告缺失

# 脚本所需的 GitHub token scope 列表
REQUIRED_SCOPES=("repo" "workflow")

# 检查 gh CLI 认证状态和 token scope
# 返回值: 0=全部具备, 1=缺失部分 scope, 2=未认证
check_gh_permissions() {
  local missing_scopes=()

  # 1. 检查是否已认证
  debug "检查 gh CLI 认证状态..."
  AUTH_STATUS=$(gh auth status 2>&1) || true
  if ! echo "$AUTH_STATUS" | grep -q "Logged in"; then
    error "gh CLI 未认证, 请运行: gh auth login"
    debug "auth status 输出: ${AUTH_STATUS}"
    return 2
  fi
  debug "认证状态: $(echo "$AUTH_STATUS" | head -1)"

  # 2. 解析 token scope
  # gh auth status 输出格式: "Token scopes: 'repo', 'read:org', 'workflow'"
  local token_scopes
  token_scopes=$(echo "$AUTH_STATUS" | grep -i "Token scopes" | sed "s/.*Token scopes: //" | tr -d "'" | tr ',' '\n' | sed 's/^ *//' || echo "")
  debug "当前 token scope: $(echo "$token_scopes" | tr '\n' ' ')"

  # 3. 逐项检查必需 scope
  for scope in "${REQUIRED_SCOPES[@]}"; do
    if echo "$token_scopes" | grep -qw "$scope"; then
      debug "scope '${scope}': ✓"
    else
      debug "scope '${scope}': ✗ (缺失)"
      missing_scopes+=("$scope")
    fi
  done

  # 4. 检查 token 有效性 (API 调用测试)
  debug "验证 token 有效性..."
  local token_test
  token_test=$(gh api user --jq '.login' 2>&1) || true
  if [[ -z "$token_test" ]] || echo "$token_test" | grep -q "Bad credentials\|401"; then
    error "token 无效或已过期, 请重新认证: gh auth login"
    debug "API 测试响应: ${token_test}"
    return 2
  fi
  debug "token 有效, 用户: ${token_test}"

  # 5. 报告结果
  if [[ ${#missing_scopes[@]} -gt 0 ]]; then
    warn "缺失 token scope: ${missing_scopes[*]}"
    warn "当前 scope: $(echo "$token_scopes" | tr '\n' ' ')"
    # 将缺失 scope 写入全局变量供 refresh 使用
    MISSING_SCOPES_STR="${missing_scopes[*]}"
    return 1
  fi

  success "gh CLI 权限检查通过 (scope: $(echo "$token_scopes" | tr '\n' ' '))"
  return 0
}

# 尝试通过 gh auth refresh 补充缺失的 token scope
# 返回值: 0=刷新成功, 1=刷新失败/用户拒绝
refresh_gh_permissions() {
  local missing=("$@")

  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi

  echo ""
  warn "检测到缺失 scope: ${missing[*]}"
  echo "  这些权限是脚本运行的必需条件:"
  echo "    repo      — 访问仓库、配置分支保护、读取 workflow 状态"
  echo "    workflow  — 触发 workflow (gh workflow run)"
  echo ""

  if [[ "$NO_CONFIRM" == "true" ]]; then
    error "--no-confirm 模式下无法交互式刷新权限"
    warn "请手动执行: gh auth refresh -s ${missing[*]}"
    return 1
  fi

  # 交互式确认
  info "即将执行: gh auth refresh -s ${missing[*]}"
  echo "  这会打开浏览器请求你重新授权 GitHub CLI, 补充缺失的 scope。"
  read -rp "确认刷新权限? (y/N): " confirm_refresh
  if [[ "${confirm_refresh,,}" != "y" ]]; then
    warn "用户取消权限刷新"
    warn "请手动执行: gh auth refresh -s ${missing[*]}"
    return 1
  fi

  # 执行刷新
  info "正在刷新 token scope (添加: ${missing[*]})..."
  local refresh_output
  refresh_output=$(gh auth refresh -s "${missing[@]}" 2>&1) || true

  # gh auth refresh 可能返回非 0 即使成功 (因为交互式流程)
  # 通过重新检查 scope 来验证
  debug "refresh 输出: ${refresh_output:0:300}"

  # 重新检查权限
  local recheck_auth
  recheck_auth=$(gh auth status 2>&1) || true
  local recheck_scopes
  recheck_scopes=$(echo "$recheck_auth" | grep -i "Token scopes" | sed "s/.*Token scopes: //" | tr -d "'" | tr ',' '\n' | sed 's/^ *//' || echo "")

  local all_present=true
  for scope in "${missing[@]}"; do
    if ! echo "$recheck_scopes" | grep -qw "$scope"; then
      all_present=false
    fi
  done

  if [[ "$all_present" == "true" ]]; then
    success "权限刷新成功, 已补充 scope: ${missing[*]}"
    debug "刷新后 scope: $(echo "$recheck_scopes" | tr '\n' ' ')"
    return 0
  else
    error "权限刷新后仍缺失部分 scope"
    warn "当前 scope: $(echo "$recheck_scopes" | tr '\n' ' ')"
    warn "请手动执行: gh auth refresh -s ${missing[*]}"
    return 1
  fi
}

# ── 权限检查主逻辑 (带重试) ────────────────────────────────
PERMISSION_RETRY_MAX=2
permission_attempt=0
permission_ok=false
MISSING_SCOPES_STR=""

while [[ $permission_attempt -le $PERMISSION_RETRY_MAX ]]; do
  ((permission_attempt++))
  debug "权限检查 [尝试 ${permission_attempt}/${PERMISSION_RETRY_MAX}]..."

  check_gh_permissions
  local_check_result=$?

  case $local_check_result in
    0)
      permission_ok=true
      break
      ;;
    1)
      # 缺失部分 scope, 尝试刷新
      if [[ $permission_attempt -le $PERMISSION_RETRY_MAX ]]; then
        # 将 MISSING_SCOPES_STR 转为数组
        read -ra missing_array <<< "$MISSING_SCOPES_STR"
        if refresh_gh_permissions "${missing_array[@]}"; then
          # 刷新成功, 循环回去重新检查
          continue
        else
          # 刷新失败
          if [[ $permission_attempt -lt $PERMISSION_RETRY_MAX ]]; then
            warn "权限刷新失败 (${permission_attempt}/${PERMISSION_RETRY_MAX}), 准备重试..."
            sleep 2
          fi
        fi
      fi
      ;;
    2)
      # 未认证, 无法通过 refresh 解决
      error "gh CLI 未认证或 token 无效, 需要重新登录"
      warn "请执行: gh auth login -s ${REQUIRED_SCOPES[*]}"
      exit 2
      ;;
  esac
done

if [[ "$permission_ok" != "true" ]]; then
  error "权限检查失败, 已达最大重试次数 (${PERMISSION_RETRY_MAX})"
  warn "请手动执行: gh auth refresh -s ${REQUIRED_SCOPES[*]}"
  warn "或重新登录: gh auth login -s ${REQUIRED_SCOPES[*]}"
  exit 2
fi

# 检查 API 速率限制
debug "检查 GitHub API 速率限制..."
RATE_LIMIT=$(gh api rate_limit 2>/dev/null || echo "")
if [[ -n "$RATE_LIMIT" ]]; then
  REMAINING=$(echo "$RATE_LIMIT" | jq -r '.rate.remaining // "unknown"')
  RESET_AT=$(echo "$RATE_LIMIT" | jq -r '.rate.reset // "unknown"')
  if [[ "$REMAINING" != "unknown" ]] && [[ "$REMAINING" -lt 10 ]]; then
    warn "API 速率限制剩余 ${REMAINING} 次, 可能不足 (重置时间: $(date -d "@${RESET_AT}" '+%H:%M:%S' 2>/dev/null || echo "${RESET_AT}"))"
  else
    debug "API 速率限制剩余: ${REMAINING} 次"
  fi
fi

# 检查仓库存在性和权限
debug "检查仓库 ${REPO} 的访问权限..."
REPO_INFO=$(gh api "repos/${REPO}" 2>&1) || {
  error "无法访问仓库 ${REPO}, 请检查名称和权限"
  debug "API 响应: ${REPO_INFO}"
  exit 4
}
CAN_PUSH=$(echo "$REPO_INFO" | jq -r '.permissions.admin // false')
if [[ "$CAN_PUSH" != "true" ]]; then
  error "对仓库 ${REPO} 无 admin 权限, 无法配置分支保护规则"
  exit 2
fi
debug "仓库权限: admin=true"

# 检查分支是否存在
debug "检查分支 ${BRANCH} 是否存在..."
BRANCH_CHECK=$(gh api "repos/${REPO}/branches/${BRANCH}" 2>&1) || {
  error "分支 ${BRANCH} 不存在于仓库 ${REPO}"
  debug "API 响应: ${BRANCH_CHECK}"
  exit 4
}
debug "分支 ${BRANCH} 存在"

success "前置条件检查通过"

# ── 必需状态检查列表 ──────────────────────────────────────
REQUIRED_CHECKS=(
  # ── ci.yml (主 CI) ──
  "ubuntu-latest / py3.14"
  "windows-latest / py3.14"
  "慢测试 / 集成测试"
  "构建验证 (wheel)"
  # ── stress-test.yml (独立 workflow) ──
  "高并发 fixture 压测"
  # ── security-scan.yml ──
  "security"
)

info "必需状态检查 (${#REQUIRED_CHECKS[@]} 项):"
for check in "${REQUIRED_CHECKS[@]}"; do
  echo "  • ${check}"
done

# ── 检查名 → workflow 文件映射 ────────────────────────────
# 用于缺失检查时自动触发对应 workflow
declare -A CHECK_TO_WORKFLOW=(
  ["ubuntu-latest / py3.14"]="ci.yml"
  ["windows-latest / py3.14"]="ci.yml"
  ["慢测试 / 集成测试"]="ci.yml"
  ["构建验证 (wheel)"]="ci.yml"
  ["高并发 fixture 压测"]="stress-test.yml"
  ["security"]="security-scan.yml"
)

# ── 构建 JSON payload ────────────────────────────────────
debug "构建 JSON payload..."
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

debug "JSON payload:"
debug "$(echo "$PAYLOAD" | jq '.' 2>/dev/null || echo "$PAYLOAD")"

# ── Dry-run 模式 ──────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  warn "DRY-RUN 模式: 以下是将要配置的内容 (不实际执行)"
  echo ""
  echo "API: PUT repos/${REPO}/branches/${BRANCH}/protection"
  echo "$PAYLOAD" | jq '.'
  echo ""
  info "使用 --dry-run=false 或去掉 --dry-run 参数执行实际配置"
  exit 0
fi

# ── 确认操作 ──────────────────────────────────────────────
if [[ "$NO_CONFIRM" == "false" ]]; then
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
fi

# ── 带 API 重试的调用函数 ─────────────────────────────────
# 重试策略: 指数退避 (2s, 4s, 8s), 最多 MAX_RETRIES 次
# 可重试条件: 网络超时、HTTP 429 (限流)、HTTP 5xx (服务器错误)
gh_api_with_retry() {
  local method="$1"
  local path="$2"
  local input_data="${3:-}"
  local attempt=1
  local result_file="${TMP_DIR}/api_result.txt"
  local stderr_file="${TMP_DIR}/api_stderr.txt"

  while [[ $attempt -le $MAX_RETRIES ]]; do
    debug "API 调用 [尝试 ${attempt}/${MAX_RETRIES}]: ${method} ${path}"

    if [[ -n "$input_data" ]]; then
      if echo "$input_data" | gh api -X "$method" "$path" --input - >"$result_file" 2>"$stderr_file"; then
        debug "API 调用成功 (尝试 ${attempt})"
        cat "$result_file"
        return 0
      fi
    else
      if gh api -X "$method" "$path" >"$result_file" 2>"$stderr_file"; then
        debug "API 调用成功 (尝试 ${attempt})"
        cat "$result_file"
        return 0
      fi
    fi

    # 调用失败, 分析错误类型
    local stderr_content
    stderr_content=$(cat "$stderr_file")
    local http_status=""

    # 从 gh CLI 输出中提取 HTTP 状态码
    if echo "$stderr_content" | grep -q "HTTP 4"; then
      http_status=$(echo "$stderr_content" | grep -oP 'HTTP \d+' | head -1 | awk '{print $2}')
    elif echo "$stderr_content" | grep -q "HTTP 5"; then
      http_status=$(echo "$stderr_content" | grep -oP 'HTTP \d+' | head -1 | awk '{print $2}')
    fi

    debug "错误详情: HTTP ${http_status:-unknown}, stderr: ${stderr_content:0:200}"

    # 判断是否可重试
    local should_retry=false
    local retry_reason=""

    if [[ -z "$http_status" ]]; then
      # 网络错误 (无 HTTP 状态码)
      should_retry=true
      retry_reason="网络错误"
    elif [[ "$http_status" == "429" ]]; then
      should_retry=true
      retry_reason="API 限流 (429)"
    elif [[ "$http_status" =~ ^5[0-9][0-9]$ ]]; then
      should_retry=true
      retry_reason="服务器错误 (${http_status})"
    elif [[ "$http_status" == "403" ]] && echo "$stderr_content" | grep -qi "rate limit"; then
      should_retry=true
      retry_reason="速率限制 (403)"
    else
      should_retry=false
      retry_reason="不可重试错误 (${http_status})"
    fi

    if [[ $attempt -eq $MAX_RETRIES ]]; then
      error "API 调用失败, 已达最大重试次数 (${MAX_RETRIES})"
      error "最后错误: ${stderr_content:0:500}"
      if [[ "$http_status" =~ ^4 ]] && [[ "$http_status" != "429" ]]; then
        error "这是客户端错误 (HTTP ${http_status}), 请检查参数和权限"
        exit 4
      elif [[ -z "$http_status" ]]; then
        error "网络错误, 请检查网络连接后重试"
        exit 3
      fi
      exit 4
    fi

    if [[ "$should_retry" == "true" ]]; then
      local backoff=$(( 2 ** attempt ))
      warn "${retry_reason}, ${backoff}秒后重试 (${attempt}/${MAX_RETRIES})..."
      sleep "$backoff"
      ((attempt++))
    else
      error "${retry_reason}, 不重试"
      error "错误详情: ${stderr_content:0:500}"
      exit 4
    fi
  done

  return 1
}

# ── 触发 workflow (手动触发) ──────────────────────────────
# 使用 gh workflow run 触发指定 workflow, 需该 workflow 支持 workflow_dispatch
trigger_workflow() {
  local workflow_file="$1"
  debug "触发 workflow: ${workflow_file}"

  local trigger_result
  trigger_result=$(gh workflow run "$workflow_file" --repo "$REPO" 2>&1) || {
    warn "触发 ${workflow_file} 失败: ${trigger_result}"
    # 检查是否因缺少 workflow_dispatch 触发器
    if echo "$trigger_result" | grep -qi "workflow_dispatch\|does not have"; then
      warn "${workflow_file} 未配置 workflow_dispatch 触发器, 无法手动触发"
      warn "解决: 为该 workflow 添加 'workflow_dispatch:' 到 on: 段, 或 push 一个空 commit 触发"
    fi
    return 1
  }

  debug "触发成功: ${trigger_result}"
  return 0
}

# ── 等待 workflow 最近一次运行完成 ─────────────────────────
# 轮询 gh run list 直到运行完成或超时
# 超时/失败时打印详细诊断信息: job 状态、失败步骤、run URL
wait_for_workflow() {
  local workflow_file="$1"
  local elapsed=0
  local poll_interval=15

  info "等待 ${workflow_file} 运行完成 (超时 ${TRIGGER_TIMEOUT}s)..."

  # 获取最近的运行 ID
  local run_id=""
  while [[ $elapsed -lt $TRIGGER_TIMEOUT ]]; do
    run_id=$(gh run list --workflow "$workflow_file" --repo "$REPO" --limit 1 --json databaseId,status,conclusion --jq '.[0].databaseId // empty' 2>/dev/null || echo "")

    if [[ -n "$run_id" ]]; then
      debug "找到运行 ID: ${run_id}"
      break
    fi

    debug "等待运行开始... (${elapsed}s/${TRIGGER_TIMEOUT}s)"
    sleep "$poll_interval"
    elapsed=$((elapsed + poll_interval))
  done

  if [[ -z "$run_id" ]]; then
    warn "未找到 ${workflow_file} 的运行记录 (可能触发失败)"
    warn "可能原因:"
    warn "  1. workflow_dispatch 触发器未生效 (检查 YAML 语法)"
    warn "  2. gh CLI 权限不足 (需要 repo + workflow scope)"
    warn "  3. workflow 文件不在默认分支 (workflow_dispatch 仅从默认分支读取)"
    warn "手动检查: gh run list --workflow ${workflow_file} --repo ${REPO}"
    return 1
  fi

  # 获取运行 URL (用于超时/失败时引导用户查看)
  local run_url=""
  run_url=$(gh run view "$run_id" --repo "$REPO" --json url --jq '.url' 2>/dev/null || echo "")
  debug "运行 URL: ${run_url:-未知}"

  # 轮询运行状态
  while [[ $elapsed -lt $TRIGGER_TIMEOUT ]]; do
    # 一次性获取完整运行状态 (status + conclusion + jobs)
    local run_json
    run_json=$(gh run view "$run_id" --repo "$REPO" --json status,conclusion,jobs 2>/dev/null || echo "{}")

    local status conclusion
    status=$(echo "$run_json" | jq -r '.status // "unknown"')
    conclusion=$(echo "$run_json" | jq -r '.conclusion // "pending"')

    # 计算进度百分比
    local progress=0
    if [[ $TRIGGER_TIMEOUT -gt 0 ]]; then
      progress=$((elapsed * 100 / TRIGGER_TIMEOUT))
    fi

    # 统计 job 状态
    local total_jobs running_jobs queued_jobs completed_jobs failed_jobs
    total_jobs=$(echo "$run_json" | jq -r '.jobs | length' 2>/dev/null || echo "0")
    running_jobs=$(echo "$run_json" | jq -r '[.jobs[] | select(.status == "in_progress")] | length' 2>/dev/null || echo "0")
    queued_jobs=$(echo "$run_json" | jq -r '[.jobs[] | select(.status == "queued")] | length' 2>/dev/null || echo "0")
    completed_jobs=$(echo "$run_json" | jq -r '[.jobs[] | select(.status == "completed")] | length' 2>/dev/null || echo "0")
    failed_jobs=$(echo "$run_json" | jq -r '[.jobs[] | select(.conclusion != "success" and .conclusion != null)] | length' 2>/dev/null || echo "0")

    debug "[${progress}%] 运行 ${run_id}: status=${status}, jobs=${completed_jobs}/${total_jobs} 完成, ${running_jobs} 运行中, ${queued_jobs} 排队, ${failed_jobs} 失败, elapsed=${elapsed}s"

    if [[ "$status" == "completed" ]]; then
      if [[ "$conclusion" == "success" ]]; then
        success "${workflow_file} 运行完成 (成功, 耗时 ${elapsed}s)"
        return 0
      else
        # 运行失败 — 打印详细诊断
        echo ""
        warn "${workflow_file} 运行完成 (结论: ${conclusion:-unknown})"
        print_run_diagnostics "$run_id" "$run_json" "$run_url" "$workflow_file"
        return 1
      fi
    fi

    sleep "$poll_interval"
    elapsed=$((elapsed + poll_interval))
  done

  # ── 超时处理: 打印当前完整状态 ──
  echo ""
  warn "等待 ${workflow_file} 超时 (${TRIGGER_TIMEOUT}s), 运行仍在进行中"

  # 获取超时时刻的完整状态快照
  local timeout_json
  timeout_json=$(gh run view "$run_id" --repo "$REPO" --json status,conclusion,jobs,url,createdAt,startedAt,updatedAt 2>/dev/null || echo "{}")

  print_run_diagnostics "$run_id" "$timeout_json" "$run_url" "$workflow_file" "timeout"

  return 1
}

# ── 打印运行诊断信息 ──────────────────────────────────────
# 显示 job 级别状态、失败步骤、时间信息和 run URL
print_run_diagnostics() {
  local run_id="$1"
  local run_json="$2"
  local run_url="$3"
  local workflow_file="$4"
  local context="${5:-failure}"  # "failure" 或 "timeout"

  local status conclusion created started updated
  status=$(echo "$run_json" | jq -r '.status // "unknown"')
  conclusion=$(echo "$run_json" | jq -r '.conclusion // "pending"')
  created=$(echo "$run_json" | jq -r '.createdAt // "unknown"')
  started=$(echo "$run_json" | jq -r '.startedAt // "unknown"')
  updated=$(echo "$run_json" | jq -r '.updatedAt // "unknown"')

  echo ""
  warn "═══════════════════════════════════════════════════"
  if [[ "$context" == "timeout" ]]; then
    warn "  超时诊断 — ${workflow_file}"
  else
    warn "  失败诊断 — ${workflow_file}"
  fi
  warn "═══════════════════════════════════════════════════"

  # 基本信息
  echo ""
  info "运行信息:"
  echo "  Run ID:        ${run_id}"
  echo "  状态:          ${status}"
  echo "  结论:          ${conclusion}"
  echo "  创建时间:      ${created}"
  echo "  开始时间:      ${started}"
  echo "  最后更新:      ${updated}"
  if [[ -n "$run_url" ]]; then
    echo "  Run URL:       ${run_url}"
  fi

  # Job 级别状态
  local total_jobs
  total_jobs=$(echo "$run_json" | jq -r '.jobs | length' 2>/dev/null || echo "0")

  if [[ "$total_jobs" -gt 0 ]] 2>/dev/null; then
    echo ""
    info "Job 状态 (${total_jobs} 个):"
    echo "$run_json" | jq -r '.jobs[] | "  \(.status // "?") | \(.conclusion // "pending") | \(.name)"' 2>/dev/null || echo "  (无法解析 job 信息)"

    # 失败 job 的详细步骤
    local failed_job_count
    failed_job_count=$(echo "$run_json" | jq -r '[.jobs[] | select(.conclusion != "success" and .conclusion != null and .conclusion != "pending")] | length' 2>/dev/null || echo "0")

    if [[ "$failed_job_count" -gt 0 ]] 2>/dev/null; then
      echo ""
      warn "失败 Job 详情 (${failed_job_count} 个):"
      echo "$run_json" | jq -r '
        .jobs[] |
        select(.conclusion != "success" and .conclusion != null and .conclusion != "pending") |
        "  ✗ \(.name) [\(.conclusion)]"
      ' 2>/dev/null || echo "  (无法解析)"

      # 失败步骤
      echo ""
      warn "失败步骤:"
      echo "$run_json" | jq -r '
        .jobs[] |
        select(.conclusion != "success" and .conclusion != null and .conclusion != "pending") |
        . as $job |
        (.steps[]? | select(.conclusion != "success" and .conclusion != null) |
          "  ✗ \($job.name) → \(.name) [\(.conclusion)]"
        )
      ' 2>/dev/null || echo "  (无法解析步骤信息)"
    fi

    # 超时模式下显示仍在运行的 job
    if [[ "$context" == "timeout" ]]; then
      local running_count
      running_count=$(echo "$run_json" | jq -r '[.jobs[] | select(.status == "in_progress" or .status == "queued")] | length' 2>/dev/null || echo "0")

      if [[ "$running_count" -gt 0 ]] 2>/dev/null; then
        echo ""
        warn "仍在运行的 Job (${running_count} 个):"
        echo "$run_json" | jq -r '
          .jobs[] |
          select(.status == "in_progress" or .status == "queued") |
          "  ⏳ \(.status) | \(.name) (已运行 \((.steps | map(.number) | length)) 步)"
        ' 2>/dev/null || echo "  (无法解析)"
      fi
    fi
  fi

  # 建议
  echo ""
  if [[ "$context" == "timeout" ]]; then
    info "超时可能原因:"
    echo "  1. runner 资源不足 (GitHub 免费层并发数有限)"
    echo "  2. workflow 本身执行时间超过 ${TRIGGER_TIMEOUT}s (可用 --max-retries 无法解决, 需增大超时)"
    echo "  3. workflow 卡在排队等待 (queued 状态)"
    echo ""
    info "建议操作:"
    echo "  • 查看 Run URL 实时日志: ${run_url:-未获取到}"
    echo "  • 增大超时: 修改脚本中 TRIGGER_TIMEOUT 值"
    echo "  • 手动检查: gh run view ${run_id} --repo ${REPO} --log"
    echo "  • 取消运行: gh run cancel ${run_id} --repo ${REPO}"
  else
    info "失败可能原因:"
    echo "  1. workflow 配置错误 (YAML 语法、依赖安装失败)"
    echo "  2. 测试失败 (代码 bug 或测试本身问题)"
    echo "  3. 权限不足 (GITHUB_TOKEN 缺少所需 scope)"
    echo ""
    info "建议操作:"
    echo "  • 查看失败日志: gh run view ${run_id} --repo ${REPO} --log-failed"
    echo "  • 查看 Run URL: ${run_url:-未获取到}"
    echo "  • 重新触发: gh run rerun ${run_id} --repo ${REPO} --failed"
    echo "  • 修复后重试: 修改代码后 push, workflow 自动触发"
  fi
  warn "═══════════════════════════════════════════════════"
}

# ── 自动触发缺失的 workflow 并重新配置 ─────────────────────
auto_trigger_missing() {
  local -n missing_ref=$1
  local triggered_workflows=()
  local failed_workflows=()

  echo ""
  warn "检测到 ${#missing_ref[@]} 项缺失检查, 尝试自动触发对应 workflow..."

  # 收集需要触发的唯一 workflow 文件
  local workflows_to_trigger=()
  for missing_check in "${missing_ref[@]}"; do
    local wf="${CHECK_TO_WORKFLOW[$missing_check]:-}"
    if [[ -n "$wf" ]]; then
      # 去重
      local already_in=false
      for existing in "${workflows_to_trigger[@]:-}"; do
        if [[ "$existing" == "$wf" ]]; then
          already_in=true
          break
        fi
      done
      if [[ "$already_in" == "false" ]]; then
        workflows_to_trigger+=("$wf")
        info "缺失检查「${missing_check}」→ 触发 ${wf}"
      fi
    else
      warn "缺失检查「${missing_check}」无对应 workflow 映射, 跳过"
    fi
  done

  if [[ ${#workflows_to_trigger[@]} -eq 0 ]]; then
    warn "无可触发的 workflow, 请手动 push 一个空 commit: git commit --allow-empty -m 'ci: trigger workflows'"
    return 1
  fi

  # 逐个触发
  echo ""
  info "触发 ${#workflows_to_trigger[@]} 个 workflow..."
  for wf in "${workflows_to_trigger[@]}"; do
    if trigger_workflow "$wf"; then
      triggered_workflows+=("$wf")
    else
      failed_workflows+=("$wf")
    fi
  done

  # 等待已触发的 workflow 完成
  if [[ ${#triggered_workflows[@]} -gt 0 ]]; then
    echo ""
    info "等待 ${#triggered_workflows[@]} 个 workflow 完成..."
    for wf in "${triggered_workflows[@]}"; do
      wait_for_workflow "$wf" || warn "${wf} 未在超时内完成, 状态检查可能仍未出现"
    done
  fi

  # 重新配置分支保护
  if [[ ${#triggered_workflows[@]} -gt 0 ]]; then
    echo ""
    info "重新配置分支保护规则 (使新出现的状态检查生效)..."
    local reconfigure_result
    reconfigure_result=$(gh_api_with_retry PUT "repos/${REPO}/branches/${BRANCH}/protection" "$PAYLOAD")
    if [[ -n "$reconfigure_result" ]]; then
      success "分支保护规则已重新配置"
    else
      warn "重新配置失败, 请稍后手动重新运行本脚本"
    fi
  fi

  # 报告失败项
  if [[ ${#failed_workflows[@]} -gt 0 ]]; then
    echo ""
    warn "${#failed_workflows[@]} 个 workflow 触发失败:"
    for fw in "${failed_workflows[@]}"; do
      echo "  ✗ ${fw}"
    done
    warn "请手动检查这些 workflow 是否已配置 workflow_dispatch 触发器"
  fi

  return 0
}

# ── 配置分支保护 ──────────────────────────────────────────
info "正在配置分支保护规则..."
API_PATH="repos/${REPO}/branches/${BRANCH}/protection"

RESULT=$(gh_api_with_retry PUT "$API_PATH" "$PAYLOAD")

if [[ -n "$RESULT" ]]; then
  success "分支保护规则配置成功!"
  debug "API 响应 (前 500 字符): ${RESULT:0:500}"
else
  error "分支保护规则配置失败 (无响应)"
  exit 4
fi

# ── 验证配置 ──────────────────────────────────────────────
info "验证配置..."

# 验证也用重试机制
PROTECTION=$(gh_api_with_retry GET "repos/${REPO}/branches/${BRANCH}/protection" "" || echo "")

if [[ -n "$PROTECTION" ]]; then
  CONFIGURED_CHECKS=$(echo "$PROTECTION" | jq -r '.required_status_checks.contexts[]?' 2>/dev/null || echo "")

  echo ""
  info "已配置的必需状态检查:"

  if [[ -n "$CONFIGURED_CHECKS" ]]; then
    # 逐项验证: 预期 vs 实际
    missing_checks=()
    while IFS= read -r actual_check; do
      echo "  • ${actual_check}"
    done <<< "$CONFIGURED_CHECKS"

    # 检查是否有遗漏
    for expected in "${REQUIRED_CHECKS[@]}"; do
      if ! echo "$CONFIGURED_CHECKS" | grep -qF "$expected"; then
        missing_checks+=("$expected")
      fi
    done

    if [[ ${#missing_checks[@]} -gt 0 ]]; then
      echo ""
      warn "以下预期检查未在配置中找到 (${#missing_checks[@]} 项):"
      for missing in "${missing_checks[@]}"; do
        echo "  ✗ ${missing}"
      done

      if [[ "$NO_AUTO_TRIGGER" == "true" ]]; then
        warn "可能原因: 对应 workflow 尚未运行过, GitHub 未生成状态检查记录"
        warn "解决: push 一个 commit 触发所有 workflow, 然后重新运行本脚本"
        warn "(或去掉 --no-auto-trigger 选项让脚本自动触发)"
      else
        # ── 自动触发缺失的 workflow ──
        auto_trigger_missing missing_checks

        # 重新验证
        echo ""
        info "重新验证配置..."
        PROTECTION=$(gh_api_with_retry GET "repos/${REPO}/branches/${BRANCH}/protection" "" || echo "")
        if [[ -n "$PROTECTION" ]]; then
          CONFIGURED_CHECKS=$(echo "$PROTECTION" | jq -r '.required_status_checks.contexts[]?' 2>/dev/null || echo "")
          remaining_missing=()
          for expected in "${REQUIRED_CHECKS[@]}"; do
            if ! echo "$CONFIGURED_CHECKS" | grep -qF "$expected"; then
              remaining_missing+=("$expected")
            fi
          done

          if [[ ${#remaining_missing[@]} -eq 0 ]]; then
            success "全部 ${#REQUIRED_CHECKS[@]} 项检查已配置"
          else
            echo ""
            info "已配置的必需状态检查 (重新验证后):"
            while IFS= read -r actual_check; do
              echo "  • ${actual_check}"
            done <<< "$CONFIGURED_CHECKS"
            echo ""
            warn "仍有 ${#remaining_missing[@]} 项检查缺失:"
            for missing in "${remaining_missing[@]}"; do
              echo "  ✗ ${missing}"
            done
            warn "可能原因: workflow 运行失败或超时, 请在 GitHub Actions 页面确认"
            warn "手动解决: gh workflow run <workflow.yml> --repo ${REPO}, 然后重新运行本脚本"
          fi
        fi
      fi
    fi
  else
    warn "未读取到必需状态检查 (可能权限不足或配置未生效)"
  fi

  echo ""
  info "保护规则概览:"
  echo "  enforce_admins:             $(echo "$PROTECTION" | jq -r '.enforce_admins.enabled')"
  echo "  require_pr_reviews:         $(echo "$PROTECTION" | jq -r '.required_pull_request_reviews.required_approving_review_count // "未设置"')"
  echo "  allow_force_pushes:         $(echo "$PROTECTION" | jq -r '.allow_force_pushes.enabled')"
  echo "  allow_deletions:            $(echo "$PROTECTION" | jq -r '.allow_deletions.enabled')"
  echo "  required_linear_history:    $(echo "$PROTECTION" | jq -r '.required_linear_history.enabled')"
  echo "  strict_status_checks:       $(echo "$PROTECTION" | jq -r '.required_status_checks.strict')"
else
  warn "无法读取验证数据 (可能权限不足), 请在 GitHub UI 手动确认配置"
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
echo ""
if [[ -n "$LOG_FILE" ]]; then
  success "完整日志已保存至: ${LOG_FILE}"
fi
