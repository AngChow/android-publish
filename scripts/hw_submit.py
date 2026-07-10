#!/usr/bin/env python3
"""
华为应用市场 APK 上传 + 提审 (Android v2 Publishing API)

流程:
  1. 获取 Token
  2. 计算 SHA256 -> 获取 OBS 上传地址 -> 上传 APK
  3. 更新应用文件信息 (fileType=5 软件包)
  4. 更新语言信息 (设置用户可见的更新文案)
  5. 等待 2 分钟 (软件包异步解析) -> 提交发布

安全锁（必须同时满足）:
  1. 命令行带 --i-know-this-submits-to-production
  2. 环境变量 HW_CONFIRM_SUBMIT=YES

用法:
  HW_CONFIRM_SUBMIT=YES python3 hw_submit.py \
      --apk /path/to/app.apk \
      --i-know-this-submits-to-production \
      [--remark "备注信息"] \
      [<project_root>]

退出码:
  0 = 成功
  1 = 失败
  2 = 安全锁未满足 / 参数错误
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _hw_common import (  # noqa: E402
    log, bootstrap_hw, get_file_sha256, get_upload_url,
    upload_to_obs, update_file_info, update_language_info, submit_app,
)

SAFETY_FLAG = "--i-know-this-submits-to-production"
SAFETY_ENV = "HW_CONFIRM_SUBMIT"
SAFETY_ENV_VALUE = "YES"

# 文档要求: 传包后等候 2 分钟再调用提交发布接口
WAIT_SECONDS = 120


def check_safety_lock(args):
    has_flag = args.confirm
    env_val = os.environ.get(SAFETY_ENV, "")
    has_env = env_val == SAFETY_ENV_VALUE

    if has_flag and has_env:
        return True

    log("═══════════════════════════════════════════════════════", "ERROR")
    log("安全锁未通过，不会提审。提审是写线上操作:", "ERROR")
    log(f"  1) 命令行加 {SAFETY_FLAG}  {'OK' if has_flag else 'MISSING'}", "ERROR")
    log(f"  2) 环境变量 {SAFETY_ENV}={SAFETY_ENV_VALUE}  {'OK' if has_env else 'MISSING'}", "ERROR")
    log("", "ERROR")
    log("  示例:", "ERROR")
    log(f"  {SAFETY_ENV}={SAFETY_ENV_VALUE} python3 hw_submit.py --apk <apk> {SAFETY_FLAG}", "ERROR")
    log("═══════════════════════════════════════════════════════", "ERROR")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="华为应用市场 APK 上传 + 提审",
        add_help=False,
    )
    parser.add_argument(SAFETY_FLAG, dest="confirm", action="store_true")
    parser.add_argument("--apk", dest="apk_path", required=True,
                        help="APK 文件路径")
    parser.add_argument("--remark", dest="remark", default="",
                        help="提审备注（10-300 字符，给审核员看）")
    parser.add_argument("--update-desc", dest="update_desc", default="",
                        help="更新文案（用户可见的新版本简介）")
    parser.add_argument("--project-root", dest="project_root_opt", default=None,
                        help="项目根目录（查找 .publish_env）")
    parser.add_argument("--no-wait", dest="no_wait", action="store_true",
                        help="跳过 2 分钟等待（不推荐，可能导致提交失败）")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("project_root", nargs="?", default=None)
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    if not os.path.isfile(args.apk_path):
        log(f"APK 文件不存在: {args.apk_path}", "ERROR")
        sys.exit(2)

    project_root = args.project_root_opt or args.project_root

    print()
    print("=" * 55)
    print("  华为应用市场 - APK 上传 + 提审 (Android)")
    print("=" * 55)

    if not check_safety_lock(args):
        sys.exit(2)

    log("安全锁已通过", "WARN")

    # 加载凭据 + 获取 Token
    client_id, app_id, headers = bootstrap_hw(project_root)

    file_path = os.path.abspath(args.apk_path)
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    log(f"appId={app_id}", "INFO")
    log(f"APK: {file_name} ({file_size / 1024 / 1024:.1f} MB)", "INFO")
    print()

    # Step 1: 计算 SHA256
    log("[1/5] 计算文件哈希", "STEP")
    sha256 = get_file_sha256(file_path)
    print()

    # Step 2: 获取上传地址 + 上传
    log("[2/5] 上传 APK 到 OBS", "STEP")
    upload_info = get_upload_url(app_id, headers, file_path, sha256, file_size)
    object_id = upload_to_obs(upload_info, file_path, file_size)
    print()

    # Step 3: 更新文件信息
    log("[3/5] 更新应用文件信息", "STEP")
    update_file_info(app_id, headers, file_name, object_id)
    print()

    # Step 4: 更新语言信息（用户可见的更新文案）
    if args.update_desc:
        log("[4/5] 更新用户可见的更新文案", "STEP")
        update_language_info(app_id, headers, "zh-CN", args.update_desc)
        print()

    # Step 5: 等待 + 提交
    log("[5/5] 提交发布", "STEP")
    if not args.no_wait:
        log(f"等待 {WAIT_SECONDS}s（软件包异步解析）...", "WARN")
        time.sleep(WAIT_SECONDS)

    ok = submit_app(app_id, headers, args.remark)
    if ok:
        print()
        log("提审完成! 请到 AGC 控制台查看审核进度", "OK")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
