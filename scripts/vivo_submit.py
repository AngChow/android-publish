#!/usr/bin/env python3
"""
vivo 应用市场 APK 上传 + 提审

流程:
  1. 计算 APK MD5
  2. 上传 APK (app.upload.apk.app) -> 获取流水号 + versionCode
  3. 应用更新 (app.sync.update.app) -> 提审

安全锁（必须同时满足）:
  1. 命令行带 --i-know-this-submits-to-production
  2. 环境变量 VIVO_CONFIRM_SUBMIT=YES

用法:
  VIVO_CONFIRM_SUBMIT=YES python3 vivo_submit.py \
      --apk /path/to/app.apk \
      --update-desc "修复已知问题" \
      --i-know-this-submits-to-production \
      [<project_root>]

退出码:
  0 = 成功
  1 = 失败
  2 = 安全锁未满足 / 参数错误
"""

import sys
import os
import json
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _vivo_common import (  # noqa: E402
    log, bootstrap_vivo, calc_md5, upload_apk, update_app,
)

SAFETY_FLAG = "--i-know-this-submits-to-production"
SAFETY_ENV = "VIVO_CONFIRM_SUBMIT"
SAFETY_ENV_VALUE = "YES"


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
    log(f"  示例: {SAFETY_ENV}={SAFETY_ENV_VALUE} python3 vivo_submit.py --apk <apk> --update-desc '...' {SAFETY_FLAG}", "ERROR")
    log("═══════════════════════════════════════════════════════", "ERROR")
    return False


def main():
    parser = argparse.ArgumentParser(description="vivo 应用市场 APK 上传 + 提审", add_help=False)
    parser.add_argument(SAFETY_FLAG, dest="confirm", action="store_true")
    parser.add_argument("--apk", dest="apk_path", required=True, help="APK 文件路径")
    parser.add_argument("--update-desc", dest="update_desc", default="", help="更新说明（5-200 字）")
    parser.add_argument("--compatible-device", dest="compatible_device", type=int, default=1,
                        help="兼容设备: 1=手机(默认), 2=手机和平板, 3=平板")
    parser.add_argument("--online-type", dest="online_type", type=int, default=1,
                        help="上架类型: 1=审核通过后立即发布(默认), 2=定时发布")
    parser.add_argument("--project-root", dest="project_root_opt", default=None)
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
    print("  vivo 应用市场 - APK 上传 + 提审")
    print("=" * 55)

    if not check_safety_lock(args):
        sys.exit(2)

    log("安全锁已通过", "WARN")

    # 加载凭据
    access_key, access_secret, pkg_name = bootstrap_vivo(project_root)
    file_path = os.path.abspath(args.apk_path)
    file_size = os.path.getsize(file_path)
    log(f"pkg_name={pkg_name}", "INFO")
    log(f"APK: {os.path.basename(file_path)} ({file_size / 1024 / 1024:.1f} MB)", "INFO")
    print()

    # 查询现有应用信息，复用 compatibleDevice（必填字段，避免覆盖）
    from _vivo_common import query_app_details
    existing = query_app_details(access_key, access_secret, pkg_name)
    existing_device = existing.get("compatibleDevice", args.compatible_device)
    existing_online = existing.get("onlineType", args.online_type)
    log(f"  当前 compatibleDevice={existing_device}, onlineType={existing_online}", "INFO")
    print()

    # Step 1: 计算 MD5
    log("[1/3] 计算 APK MD5", "STEP")
    file_md5 = calc_md5(file_path)
    log(f"  MD5: {file_md5}", "OK")
    print()

    # Step 2: 上传 APK
    log("[2/3] 上传 APK", "STEP")
    serialnumber, version_code, version_name = upload_apk(
        access_key, access_secret, pkg_name, file_path, file_md5,
    )
    log(f"  流水号: {serialnumber[:20]}...", "OK")
    log(f"  versionCode: {version_code}, versionName: {version_name}", "OK")
    print()

    # Step 3: 应用更新（提审）
    log("[3/3] 应用更新", "STEP")
    update_params = {
        "packageName": pkg_name,
        "versionCode": version_code,
        "apk": serialnumber,
        "fileMd5": file_md5,
        "onlineType": str(existing_online),
        "compatibleDevice": str(existing_device),
    }
    if args.update_desc:
        if len(args.update_desc) < 5:
            log("更新说明不少于 5 个字", "WARN")
        else:
            update_params["updateDesc"] = args.update_desc

    log(f"  更新参数: {len(update_params)} 个字段", "INFO")
    data = update_app(access_key, access_secret, update_params)

    print()
    log("提审成功! 请到 vivo 开放平台查看审核进度", "OK")
    log(f"  响应: {json.dumps(data, ensure_ascii=False)[:200]}", "INFO")
    sys.exit(0)


if __name__ == "__main__":
    main()
