#!/usr/bin/env python3
"""
Git 打 Tag：在所有渠道提审成功后执行

流程:
  1. 读取 APP_VERSION 作为 tag 名
  2. 检查当前分支是否已合并到 master
  3. 未合并则: checkout master -> pull -> merge 当前分支 -> push
  4. 基于 master 创建 annotated tag（更新说明 + AI 标记）
  5. push tag
  6. 切回原分支

用法:
  python3 git_tag.py <project_root> [--update-desc "更新说明"]

退出码:
  0 = 成功
  1 = 失败
"""

import sys
import os
import re
import argparse
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log  # noqa: E402


def run_git(project_root, *args, check=True, capture=False):
    """执行 git 命令"""
    cmd = ["git", "-C", project_root] + list(args)
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            log(f"git {' '.join(args)} 失败: {result.stderr.strip()}", "ERROR")
            sys.exit(1)
        return result
    else:
        result = subprocess.run(cmd, timeout=120)
        if check and result.returncode != 0:
            log(f"git {' '.join(args)} 失败 (exit {result.returncode})", "ERROR")
            sys.exit(1)
        return result


def get_version_name(project_root):
    """从 gradle.properties 读取 APP_VERSION"""
    gp = os.path.join(project_root, "gradle.properties")
    with open(gp) as f:
        m = re.search(r'APP_VERSION=(.+)', f.read())
        if m:
            return m.group(1).strip()
    log("未找到 APP_VERSION in gradle.properties", "ERROR")
    sys.exit(1)


def get_model_name():
    """从 ~/.codex/config.toml 读取当前模型名"""
    config_path = os.path.expanduser("~/.codex/config.toml")
    if os.path.isfile(config_path):
        with open(config_path) as f:
            m = re.search(r'^model\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
            if m:
                return m.group(1)
    return "unknown"


def get_prev_tag(project_root, current_version):
    """获取当前版本之前的最近一个 tag"""
    result = run_git(project_root, "tag", "--sort=-creatordate", capture=True)
    for line in result.stdout.strip().split("\n"):
        tag = line.strip()
        if tag and tag != current_version:
            return tag
    return None


def get_commits_between(project_root, from_ref, to_ref):
    """获取两个 ref 之间的 commit subjects，过滤版本号升级和 merge commit"""
    result = run_git(project_root, "log", "--format=%s", f"{from_ref}..{to_ref}", capture=True)
    commits = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 过滤版本号升级 commit
        if re.match(r"chore:\s*版本号升级", line):
            continue
        # 过滤 merge commit
        if line.startswith("Merge branch") or line.startswith("Merge "):
            continue
        commits.append(line)
    return commits


def is_merged_to_master(project_root, branch):
    """检查分支是否已合并到 master"""
    result = run_git(project_root, "merge-base", "--is-ancestor", branch, "origin/master",
                     check=False, capture=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Git 打 Tag", add_help=False)
    parser.add_argument("--update-desc", dest="update_desc", default="修复已知问题，优化用户体验",
                        help="更新说明（应用市场用，不作为 tag message）")
    parser.add_argument("--tag-message", dest="tag_message", default=None,
                        help="自定义 tag message（默认自动从 git log 生成）")
    parser.add_argument("--project-root", dest="project_root_opt", default=None)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("project_root", nargs="?", default=".")
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    project_root = os.path.abspath(args.project_root_opt or args.project_root)

    print()
    print("=" * 55)
    print("  Git 打 Tag")
    print("=" * 55)

    # 读取版本号
    version = get_version_name(project_root)
    log(f"版本号: {version}", "INFO")

    # 检查 tag 是否已存在
    tag_check = run_git(project_root, "tag", "-l", version, check=False, capture=True)
    if tag_check.stdout.strip():
        log(f"Tag {version} 已存在，跳过", "WARN")
        sys.exit(0)

    # 获取当前分支
    branch_result = run_git(project_root, "branch", "--show-current", capture=True)
    current_branch = branch_result.stdout.strip()
    log(f"当前分支: {current_branch}", "INFO")

    # 检查是否已合并到 master
    if is_merged_to_master(project_root, current_branch):
        log(f"分支 {current_branch} 已合并到 master", "OK")
    else:
        log(f"分支 {current_branch} 未合并到 master，开始合并...", "STEP")

        # checkout master
        log("  切换到 master...", "INFO")
        run_git(project_root, "checkout", "master")

        # pull latest
        log("  拉取最新 master...", "INFO")
        run_git(project_root, "pull", "origin", "master")

        # merge
        log(f"  合并 {current_branch} 到 master...", "INFO")
        merge_result = run_git(project_root, "merge", "--no-ff", current_branch,
                               "-m", f"Merge branch '{current_branch}' into master",
                               check=False, capture=True)
        if merge_result.returncode != 0:
            log(f"合并失败: {merge_result.stderr.strip()}", "ERROR")
            log("请手动解决冲突后重试", "ERROR")
            # 切回原分支
            run_git(project_root, "checkout", current_branch, check=False)
            sys.exit(1)

        # push master
        log("  推送 master...", "INFO")
        run_git(project_root, "push", "origin", "master")

        log(f"合并完成", "OK")

    # 创建 tag
    model = get_model_name()

    # 自动从 git log 生成改动总结
    prev_tag = get_prev_tag(project_root, version)
    commit_summary = ""
    if prev_tag:
        commits = get_commits_between(project_root, prev_tag, "HEAD")
        if commits:
            commit_summary = "\n".join(f"- {c}" for c in commits)
            log(f"从 {prev_tag} 到 HEAD 共 {len(commits)} 条改动", "INFO")
        else:
            log(f"{prev_tag} 到 HEAD 无新增改动", "INFO")
    else:
        log("未找到上一个 tag，使用更新文案作为 tag message", "INFO")

    if commit_summary:
        tag_message = f"{args.update_desc}\n\n{commit_summary}\n\nAI-Assisted-By: CodeX ({model})"
    else:
        tag_message = f"{args.update_desc}\n\nAI-Assisted-By: CodeX ({model})"

    log(f"创建 tag: {version}", "STEP")
    log(f"  AI 标记: AI-Assisted-By: CodeX ({model})", "INFO")

    run_git(project_root, "tag", "-a", version, "-m", tag_message)

    # push tag
    log(f"推送 tag: {version}", "STEP")
    run_git(project_root, "push", "origin", version)

    log(f"Tag {version} 创建并推送成功!", "OK")

    # 切回原分支
    if current_branch != "master":
        log(f"切回分支: {current_branch}", "INFO")
        run_git(project_root, "checkout", current_branch, check=False)

    sys.exit(0)


if __name__ == "__main__":
    main()
