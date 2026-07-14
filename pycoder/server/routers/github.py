"""
GitHub 直连服务 — 认证 / Clone / 发布 / Repo / PR / Issues

对标 VS Code GitHub 集成，提供完整的工作流:
  1. 认证 (Token 输入)
  2. Clone 仓库到本地
  3. 一键发布到 GitHub (创建仓库 + push)
  4. 浏览仓库列表
  5. PR 创建/查看/合并
  6. Issues 创建/查看
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github")

# ── 配置存储 ──

GITHUB_CONFIG = Path.home() / ".pycoder" / "github_config.json"
WORKSPACE_ROOT: Path = Path(
    os.environ.get(
        "PYCODER_WORKSPACE",
        str(Path(__file__).resolve().parents[3]),
    )
).resolve()


def _load_token() -> str:
    """从配置文件读取 GitHub Token"""
    if GITHUB_CONFIG.exists():
        try:
            data = json.loads(GITHUB_CONFIG.read_text(encoding="utf-8"))
            return data.get("token", "")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.debug("load_token_failed error=%s", e)
            return ""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _save_token(token: str, user: dict):
    """保存 GitHub Token + 用户信息"""
    GITHUB_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    GITHUB_CONFIG.write_text(
        json.dumps(
            {"token": token, "user": user, "updated_at": time.time()}, indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )


def _clear_token():
    """清除 GitHub Token"""
    if GITHUB_CONFIG.exists():
        GITHUB_CONFIG.unlink()


def _gh_headers(token: str = "") -> dict:
    t = token or _load_token()
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "PyCoder/0.5.0"}
    if t:
        h["Authorization"] = f"Bearer {t}"
    return h


# ══════════════════════════════════════════════════════════
# P0: 认证
# ══════════════════════════════════════════════════════════


@router.post("/auth")
async def github_auth(req: dict):
    """验证 GitHub Token: {token: "ghp_xxx"} 返回用户信息"""
    token = req.get("token", "")
    if not token:
        raise HTTPException(400, "token is required")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers=_gh_headers(token),
                timeout=10,
            )
            if resp.status_code == 200:
                user = resp.json()
                _save_token(
                    token,
                    {
                        "login": user.get("login", ""),
                        "name": user.get("name", ""),
                        "avatar_url": user.get("avatar_url", ""),
                    },
                )
                login = user.get("login", "")
                return {"success": True, "user": login}
            elif resp.status_code == 401:
                return {"success": False, "error": "Invalid token"}
            else:
                return {"success": False, "error": f"GitHub API error: {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/auth/status")
async def github_auth_status():
    """检查 GitHub 认证状态"""
    token = _load_token()
    if not token:
        return {"authenticated": False}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers=_gh_headers(token),
                timeout=10,
            )
            if resp.status_code == 200:
                return {"authenticated": True, "user": resp.json()}
            return {"authenticated": False}
    except (httpx.HTTPError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning("github_auth_status_failed error=%s", e)
        return {"authenticated": False, "error": "network_error"}


@router.delete("/auth")
async def github_auth_clear():
    """清除 GitHub Token"""
    _clear_token()
    return {"success": True}


# ══════════════════════════════════════════════════════════
# P0: Clone — 克隆仓库
# ══════════════════════════════════════════════════════════


@router.post("/clone")
async def github_clone(req: dict):
    """克隆 GitHub 仓库到本地: {url, target_dir?}"""
    url = req.get("url", "")
    if not url:
        raise HTTPException(400, "url is required")

    # 展开 GitHub 短链接
    if "/" not in url.replace("https://", "").replace("http://", ""):
        url = f"https://github.com/{url}.git"
    elif not url.startswith("http") and not url.startswith("git@"):
        url = f"https://github.com/{url}.git"

    # 从 URL 提取仓库名
    repo_name = url.rstrip("/").rstrip(".git").split("/")[-1]
    target = req.get("target_dir", str(WORKSPACE_ROOT / repo_name))

    try:
        result = subprocess.run(
            ["git", "clone", url, target],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {"success": True, "path": target, "repo_name": repo_name}
        else:
            return {"success": False, "error": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Clone timeout (120s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# P0: Create Repo — 创建 GitHub 仓库
# ══════════════════════════════════════════════════════════


@router.post("/create-repo")
async def github_create_repo(req: dict):
    """在 GitHub 创建仓库: {name, description?, private?}"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated. Please set GitHub token.")

    name = req.get("name", "")
    if not name:
        raise HTTPException(400, "name is required")

    body = {
        "name": name,
        "description": req.get("description", ""),
        "private": req.get("private", True),
        "auto_init": False,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.github.com/user/repos",
                json=body,
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 201:
                data = resp.json()
                return {
                    "success": True,
                    "url": data.get("html_url", ""),
                    "clone_url": data.get("clone_url", ""),
                    "name": data.get("name", name),
                    "full_name": data.get("full_name", ""),
                }
            elif resp.status_code == 422:
                return {"success": False, "error": f"Repository '{name}' may already exist"}
            else:
                return {
                    "success": False,
                    "error": f"GitHub API: {resp.status_code} {resp.text[:200]}",
                }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# P0: Publish — 一键发布 (create-repo + remote add + push)
# ══════════════════════════════════════════════════════════


@router.post("/publish")
async def github_publish(req: dict):
    """一键发布到 GitHub: {repo_name, description?, private?, org?}"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated.")

    repo_name = req.get("repo_name", "")
    description = req.get("description", "")
    private = req.get("private", True)
    org = req.get("org", "")

    if not repo_name:
        repo_name = WORKSPACE_ROOT.name

    # 1. 在 GitHub 创建仓库
    body = {"name": repo_name, "description": description, "private": private, "auto_init": False}
    api_url = (
        f"https://api.github.com/orgs/{org}/repos" if org else "https://api.github.com/user/repos"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(api_url, json=body, headers=_gh_headers(token), timeout=15)
            if resp.status_code not in (201, 200):
                if resp.status_code == 422:
                    return {
                        "success": False,
                        "error": f"Repo '{repo_name}' exists. Set a different name or use Push.",
                    }
                return {"success": False, "error": f"API: {resp.status_code}"}
            repo_data = resp.json()
            clone_url = repo_data.get(
                "clone_url", f"https://github.com/{repo_data.get('full_name', repo_name)}.git"
            )
            html_url = repo_data.get(
                "html_url", f"https://github.com/{repo_data.get('full_name', repo_name)}"
            )
    except Exception as e:
        return {"success": False, "error": f"GitHub API error: {e}"}

    # 2. 检查是否是 git 仓库
    git_dir = WORKSPACE_ROOT / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(WORKSPACE_ROOT), capture_output=True, timeout=10)

    # 3. 检查并设置 remote
    try:
        existing = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if existing.returncode == 0:
            subprocess.run(
                ["git", "remote", "set-url", "origin", clone_url],
                cwd=str(WORKSPACE_ROOT),
                capture_output=True,
                timeout=10,
            )
        else:
            subprocess.run(
                ["git", "remote", "add", "origin", clone_url],
                cwd=str(WORKSPACE_ROOT),
                capture_output=True,
                timeout=10,
            )
    except Exception as e:
        return {"success": False, "error": f"Remote setup error: {e}"}

    # 4. 设置默认分支为 main 并推送
    try:
        subprocess.run(
            ["git", "checkout", "-B", "main"],
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            timeout=10,
        )
        push_result = subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if push_result.returncode == 0:
            return {"success": True, "repo_url": html_url, "repo_name": repo_name}
        else:
            return {
                "success": True,
                "repo_url": html_url,
                "warning": f"Repo created but push: {push_result.stderr.strip()}",
            }
    except Exception as e:
        return {
            "success": True,
            "repo_url": html_url,
            "warning": f"Repo created but push failed: {e}",
        }


# ══════════════════════════════════════════════════════════
# P1: 仓库列表 + 详情
# ══════════════════════════════════════════════════════════


@router.get("/repos")
async def github_list_repos(
    type: str = "owner",
    sort: str = "updated",
    per_page: int = 30,
    page: int = 1,
):
    """列出用户仓库"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user/repos",
                params={"type": type, "sort": sort, "per_page": per_page, "page": page},
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 200:
                repos = []
                for r in resp.json():
                    repos.append(
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "full_name": r["full_name"],
                            "description": r.get("description", ""),
                            "private": r["private"],
                            "html_url": r["html_url"],
                            "clone_url": r["clone_url"],
                            "language": r.get("language", ""),
                            "stargazers_count": r["stargazers_count"],
                            "forks_count": r["forks_count"],
                            "open_issues_count": r["open_issues_count"],
                            "updated_at": r.get("updated_at", ""),
                            "default_branch": r.get("default_branch", "main"),
                        }
                    )
                return {"repos": repos}
            return {"repos": [], "error": f"API: {resp.status_code}"}
    except Exception as e:
        return {"repos": [], "error": str(e)}


@router.get("/repo/{owner}/{repo}")
async def github_repo_detail(owner: str, repo: str):
    """获取仓库详情"""
    token = _load_token()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 200:
                r = resp.json()
                return {
                    "success": True,
                    "repo": {
                        "full_name": r["full_name"],
                        "description": r.get("description", ""),
                        "private": r["private"],
                        "html_url": r["html_url"],
                        "language": r.get("language", ""),
                        "stars": r["stargazers_count"],
                        "forks": r["forks_count"],
                        "open_issues": r["open_issues_count"],
                        "default_branch": r.get("default_branch", "main"),
                        "updated_at": r.get("updated_at", ""),
                    },
                }
            return {"success": False, "error": f"API: {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# P1: Pull Requests
# ══════════════════════════════════════════════════════════


@router.get("/pulls/{owner}/{repo}")
async def github_list_prs(owner: str, repo: str, state: str = "open"):
    """列出 PR"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                params={"state": state, "per_page": 30},
                headers=_gh_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                prs = []
                for pr in resp.json():
                    prs.append(
                        {
                            "number": pr["number"],
                            "title": pr["title"],
                            "state": pr["state"],
                            "user": pr["user"]["login"],
                            "created_at": pr.get("created_at", ""),
                            "html_url": pr["html_url"],
                            "head": pr["head"]["ref"],
                            "base": pr["base"]["ref"],
                            "mergeable": pr.get("mergeable"),
                            "draft": pr.get("draft", False),
                        }
                    )
                return {"pulls": prs}
            return {"pulls": [], "error": f"API: {resp.status_code}"}
    except Exception as e:
        return {"pulls": [], "error": str(e)}


@router.get("/pulls/{owner}/{repo}/{number}")
async def github_pr_detail(owner: str, repo: str, number: int):
    """PR 详情"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
                headers=_gh_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                pr = resp.json()
                return {
                    "success": True,
                    "pull": {
                        "number": pr["number"],
                        "title": pr["title"],
                        "body": pr.get("body", ""),
                        "state": pr["state"],
                        "user": pr["user"]["login"],
                        "created_at": pr.get("created_at", ""),
                        "html_url": pr["html_url"],
                        "head": {
                            "ref": pr["head"]["ref"],
                            "repo": pr["head"]["repo"]["full_name"] if pr["head"]["repo"] else None,
                        },
                        "base": {
                            "ref": pr["base"]["ref"],
                            "repo": pr["base"]["repo"]["full_name"] if pr["base"]["repo"] else None,
                        },
                        "mergeable": pr.get("mergeable"),
                        "merged": pr.get("merged", False),
                        "commits": pr.get("commits", 0),
                        "changed_files": pr.get("changed_files", 0),
                        "additions": pr.get("additions", 0),
                        "deletions": pr.get("deletions", 0),
                    },
                }
            return {"success": False, "error": f"API: {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/pulls/{owner}/{repo}")
async def github_create_pr(owner: str, repo: str, req: dict):
    """创建 PR: {title, head, base, body?}"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated")

    body = {
        "title": req.get("title", ""),
        "head": req.get("head", ""),
        "base": req.get("base", "main"),
        "body": req.get("body", ""),
    }
    if not body["title"] or not body["head"]:
        raise HTTPException(400, "title and head are required")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                json=body,
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 201:
                pr = resp.json()
                return {"success": True, "number": pr["number"], "url": pr["html_url"]}
            return {"success": False, "error": f"API: {resp.status_code} {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/pulls/{owner}/{repo}/{number}/merge")
async def github_merge_pr(owner: str, repo: str, number: int, req: dict):
    """合并 PR: {merge_method?: 'merge'|'squash'|'rebase'}"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge",
                json={"merge_method": req.get("merge_method", "merge")},
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 200:
                return {"success": True, "merged": resp.json().get("merged", False)}
            return {"success": False, "error": f"API: {resp.status_code} {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
# P2: Issues
# ══════════════════════════════════════════════════════════


@router.get("/issues/{owner}/{repo}")
async def github_list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    labels: str = "",
    per_page: int = 30,
):
    """列出 Issues"""
    params: dict = {"state": state, "per_page": per_page}
    if labels:
        params["labels"] = labels

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                params=params,
                headers=_gh_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                issues = []
                for iss in resp.json():
                    if "pull_request" in iss:
                        continue  # 过滤 PR
                    issues.append(
                        {
                            "number": iss["number"],
                            "title": iss["title"],
                            "state": iss["state"],
                            "user": iss["user"]["login"],
                            "labels": [
                                {"name": line["name"], "color": line["color"]}
                                for line in iss.get("labels", [])
                            ],
                            "created_at": iss.get("created_at", ""),
                            "html_url": iss["html_url"],
                            "comments": iss.get("comments", 0),
                        }
                    )
                return {"issues": issues}
            return {"issues": [], "error": f"API: {resp.status_code}"}
    except Exception as e:
        return {"issues": [], "error": str(e)}


@router.post("/issues/{owner}/{repo}")
async def github_create_issue(owner: str, repo: str, req: dict):
    """创建 Issue: {title, body?, labels?}"""
    token = _load_token()
    if not token:
        raise HTTPException(401, "Not authenticated")

    body = {"title": req.get("title", ""), "body": req.get("body", "")}
    if req.get("labels"):
        body["labels"] = req["labels"]
    if not body["title"]:
        raise HTTPException(400, "title is required")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/issues",
                json=body,
                headers=_gh_headers(token),
                timeout=15,
            )
            if resp.status_code == 201:
                iss = resp.json()
                return {"success": True, "number": iss["number"], "url": iss["html_url"]}
            return {"success": False, "error": f"API: {resp.status_code} {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
