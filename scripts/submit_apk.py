#!/usr/bin/env python3
"""
应用宝 APK 上传 + 提审 (POST /get_file_upload_info -> PUT COS -> POST /update_app)

⚠️ 危险操作：update_app 会真正提交审核，审核通过后按 deploy_type 发布。
   安全锁（必须同时满足）:
     1. 命令行带 --i-know-this-submits-to-production
     2. 环境变量 YYB_CONFIRM_SUBMIT=YES
   两者缺一不可，否则只上传不提审（或用 --dry-run 只上传不提审）。

用法:
  # 自动检测架构，上传单个 APK 并提审
  YYB_CONFIRM_SUBMIT=YES python3 submit_apk.py /path/to/app.apk \
      --i-know-this-submits-to-production [--feature "本次更新内容"] [<project_root>]

  # 显式指定 32 位/64 位包
  YYB_CONFIRM_SUBMIT=YES python3 submit_apk.py \
      --apk32 /path/to/app-universal.apk \
      --apk64 /path/to/app-arm64.apk \
      --i-know-this-submits-to-production

  # 仅上传不提审
  python3 submit_apk.py /path/to/app.apk --dry-run

  # 定时发布
  YYB_CONFIRM_SUBMIT=YES python3 submit_apk.py /path/to/app.apk \
      --i-know-this-submits-to-production --deploy-type 2 --deploy-time 1720000000

退出码:
  0 = 成功
  1 = 失败
  2 = 安全锁未满足 / 参数错误（未提审）
"""

import sys
import os
import json
import hashlib
import zipfile
import argparse
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import (  # noqa: E402
    log, bootstrap, api_call, check_ret,
    GET_FILE_UPLOAD_INFO, UPDATE_APP,
)


SAFETY_FLAG = "--i-know-this-submits-to-production"
SAFETY_ENV = "YYB_CONFIRM_SUBMIT"
SAFETY_ENV_VALUE = "YES"

# 32 位 ABI 集合
ABI_32 = {"armeabi", "armeabi-v7a", "x86"}
# 64 位 ABI 集合
ABI_64 = {"arm64-v8a", "x86_64"}


# ============================================================
# APK 架构检测
# ============================================================
def detect_apk_arch(apk_path):
    """
    通过检查 APK 内 lib/ 目录判断架构。
    返回:
      'universal' - 含 32 位 ABI（可能同时含 64 位），对应 apk32 槽位（32&64 兼容包）
      '64'        - 仅含 64 位 ABI，对应 apk64 槽位
      'none'      - 无 native 库，默认按 universal 处理
    """
    has_32 = False
    has_64 = False
    try:
        with zipfile.ZipFile(apk_path) as zf:
            for name in zf.namelist():
                if name.startswith("lib/"):
                    parts = name.split("/")
                    if len(parts) >= 2:
                        arch = parts[1]
                        if arch in ABI_32:
                            has_32 = True
                        elif arch in ABI_64:
                            has_64 = True
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        log(f"无法读取 APK（可能不是有效 zip）: {apk_path}", "WARN")
        return "universal"

    if has_32:
        return "universal"
    elif has_64:
        return "64"
    else:
        return "universal"


# ============================================================
# MD5 计算
# ============================================================
def calc_md5(file_path):
    """计算文件 MD5（小写 hex）"""
    log(f"正在计算 MD5: {os.path.basename(file_path)}", "STEP")
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(8 * 1024 * 1024)
            if not data:
                break
            md5.update(data)
    result = md5.hexdigest()
    log(f"MD5: {result}", "OK")
    return result


# ============================================================
# 文件上传
# ============================================================
def get_upload_info(access_secret, user_id, pkg_name, app_id, file_type, file_name):
    """调用 /get_file_upload_info 获取 COS 预签名 URL 和流水号"""
    log(f"正在获取文件上传信息: {file_name} (type={file_type})", "STEP")
    data = api_call(
        GET_FILE_UPLOAD_INFO, access_secret, user_id,
        {
            "pkg_name": pkg_name,
            "app_id": app_id,
            "file_type": file_type,
            "file_name": file_name,
        },
        timeout=30,
    )
    check_ret(data, "获取文件上传信息")
    pre_sign_url = data.get("pre_sign_url", "")
    serial_number = data.get("serial_number", "")
    if not pre_sign_url or not serial_number:
        log(f"返回缺少 pre_sign_url 或 serial_number: {json.dumps(data, ensure_ascii=False)[:500]}", "ERROR")
        sys.exit(1)
    log(f"流水号: {serial_number}", "OK")
    return pre_sign_url, serial_number


def upload_to_cos(pre_sign_url, file_path):
    """通过 COS 预签名 URL 上传文件（PUT 原始数据）"""
    file_size = os.path.getsize(file_path)
    log(f"正在上传到 COS ({file_size / 1024 / 1024:.1f} MB)...", "STEP")
    with open(file_path, "rb") as f:
        resp = requests.put(
            pre_sign_url,
            data=f,
            headers={"Content-Type": "application/octet-stream"},
            timeout=900,
        )
    if resp.status_code not in (200, 204):
        log(f"COS 上传失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    log("COS 上传成功", "OK")


def upload_apk(access_secret, user_id, pkg_name, app_id, apk_path):
    """
    完整上传一个 APK 文件:
    1. 获取上传信息（预签名 URL + 流水号）
    2. 上传到 COS
    3. 计算 MD5
    返回: (serial_number, md5)
    """
    file_name = os.path.basename(apk_path)
    pre_sign_url, serial_number = get_upload_info(
        access_secret, user_id, pkg_name, app_id, "apk", file_name
    )
    upload_to_cos(pre_sign_url, apk_path)
    md5 = calc_md5(apk_path)
    return serial_number, md5


# ============================================================
# 安全锁
# ============================================================
def check_safety_lock(args):
    has_flag = args.confirm
    env_val = os.environ.get(SAFETY_ENV, "")
    has_env = env_val == SAFETY_ENV_VALUE

    if has_flag and has_env:
        return True

    if args.dry_run:
        return False

    log("═══════════════════════════════════════════════════════", "ERROR")
    log("安全锁未通过，将不会提审（APK 仍会上传）。提审是写线上操作:", "ERROR")
    log(f"  1) 命令行加 {SAFETY_FLAG}  {'OK' if has_flag else 'MISSING'}", "ERROR")
    log(f"  2) 环境变量 {SAFETY_ENV}={SAFETY_ENV_VALUE}  {'OK' if has_env else 'MISSING'}", "ERROR")
    log("", "ERROR")
    log("  示例:", "ERROR")
    log(f"  YYB_CONFIRM_SUBMIT=YES python3 submit_apk.py <apk> {SAFETY_FLAG}", "ERROR")
    log("═══════════════════════════════════════════════════════", "ERROR")
    return False


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="应用宝 APK 上传 + 提审",
        add_help=False,
    )
    parser.add_argument(SAFETY_FLAG, dest="confirm", action="store_true",
                        help="确认提审（安全锁 1/2）")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="仅上传 APK，不提审")
    parser.add_argument("--apk32", dest="apk32_path", default=None,
                        help="32 位或 32&64 兼容包路径")
    parser.add_argument("--apk64", dest="apk64_path", default=None,
                        help="64 位安装包路径")
    parser.add_argument("--feature", dest="feature", default=None,
                        help="版本特性说明")
    parser.add_argument("--deploy-type", dest="deploy_type", type=int, default=1,
                        help="发布类型: 1=审核通过后立即发布(默认), 2=定时发布")
    parser.add_argument("--deploy-time", dest="deploy_time", type=int, default=None,
                        help="定时发布时间(秒级时间戳, 北京时间, deploy_type=2 时必填)")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("apk", nargs="?", default=None,
                        help="APK 文件路径（自动检测架构）")
    parser.add_argument("--project-root", dest="project_root_opt", default=None,
                        help="项目根目录（查找 .publish_env），优先于位置参数")
    parser.add_argument("project_root", nargs="?", default=None,
                        help="项目根目录（查找 .publish_env）")
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    # 解析 APK 路径
    apk32_path = args.apk32_path
    apk64_path = args.apk64_path

    # 先校验显式指定的文件存在
    for label, path in [("--apk32", apk32_path), ("--apk64", apk64_path)]:
        if path and not os.path.isfile(path):
            log(f"文件不存在: {path}", "ERROR")
            sys.exit(2)

    # 位置参数兜底
    if args.apk and not apk32_path and not apk64_path:
        if not os.path.isfile(args.apk):
            log(f"文件不存在: {args.apk}", "ERROR")
            sys.exit(2)
        arch = detect_apk_arch(args.apk)
        log(f"自动检测架构: {args.apk} -> {arch}", "INFO")
        if arch == "64":
            apk64_path = args.apk
        else:
            apk32_path = args.apk
    elif not apk32_path and not apk64_path:
        log("未指定 APK 文件。请提供 APK 路径，或使用 --apk32/--apk64 指定。", "ERROR")
        sys.exit(2)

    # deploy_type 校验
    if args.deploy_type not in (1, 2):
        log(f"deploy_type 必须为 1 或 2，当前: {args.deploy_type}", "ERROR")
        sys.exit(2)
    if args.deploy_type == 2 and not args.deploy_time:
        log("deploy_type=2 (定时发布) 时必须提供 --deploy-time", "ERROR")
        sys.exit(2)

    print(file=sys.stderr)
    print("=" * 55, file=sys.stderr)
    print("  应用宝 - APK 上传 + 提审", file=sys.stderr)
    print("=" * 55, file=sys.stderr)

    # 安全锁
    should_submit = check_safety_lock(args)

    if args.dry_run:
        log("dry-run 模式: 仅上传，不提审", "WARN")
        should_submit = False

    # 加载凭据（--project-root 优先于位置参数）
    project_root = args.project_root_opt or args.project_root
    user_id, access_secret, app_id, pkg_name = bootstrap(project_root)
    log(f"app_id={app_id}, pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    # ============================================================
    # Step 1: 上传 APK 文件
    # ============================================================
    apk32_info = None  # (serial_number, md5)
    apk64_info = None

    if apk32_path:
        log(f"[1/2] 上传 32 位/兼容包: {apk32_path}", "STEP")
        apk32_info = upload_apk(access_secret, user_id, pkg_name, app_id, apk32_path)
        print(file=sys.stderr)

    if apk64_path:
        log(f"[1/2] 上传 64 位包: {apk64_path}", "STEP")
        apk64_info = upload_apk(access_secret, user_id, pkg_name, app_id, apk64_path)
        print(file=sys.stderr)

    if not should_submit:
        log("APK 上传完成，未提审（安全锁未通过或 dry-run）", "OK")
        if apk32_info:
            log(f"  apk32 serial_number={apk32_info[0]}", "INFO")
        if apk64_info:
            log(f"  apk64 serial_number={apk64_info[0]}", "INFO")
        log("如需提审，请加 --i-know-this-submits-to-production 并设置 YYB_CONFIRM_SUBMIT=YES", "INFO")
        sys.exit(0)

    # ============================================================
    # Step 2: 调用 update_app 提审
    # ============================================================
    log("[2/2] 正在提交审核...", "STEP")
    log("安全锁已通过，3 秒后真实提交...", "WARN")
    time.sleep(3)

    update_params = {
        "pkg_name": pkg_name,
        "app_id": app_id,
        "deploy_type": args.deploy_type,
    }

    # 定时发布
    if args.deploy_type == 2:
        update_params["deploy_time"] = args.deploy_time

    # APK 文件信息（不上传的架构不传该字段，保留上次版本不变）
    if apk32_info:
        update_params["apk32_flag"] = 1
        update_params["apk32_file_serial_number"] = apk32_info[0]
        update_params["apk32_file_md5"] = apk32_info[1]

    if apk64_info:
        update_params["apk64_flag"] = 1
        update_params["apk64_file_serial_number"] = apk64_info[0]
        update_params["apk64_file_md5"] = apk64_info[1]

    # 版本特性说明
    if args.feature:
        update_params["feature"] = args.feature

    log(f"update_app 参数: {json.dumps(update_params, ensure_ascii=False, indent=2)}", "INFO")

    data = api_call(UPDATE_APP, access_secret, user_id, update_params, timeout=120)
    check_ret(data, "提交审核")

    log("提审成功! 请到应用宝开放平台查看审核进度", "OK")
    log(f"响应: {json.dumps(data, ensure_ascii=False)[:500]}", "INFO")
    log("可用 query_status.py 查询审核状态", "INFO")
    sys.exit(0)


if __name__ == "__main__":
    main()
