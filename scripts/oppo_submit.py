#!/usr/bin/env python3
"""
OPPO 应用市场 APK 上传 + 提审

流程:
  1. 获取 Token
  2. 查询现有应用详情（复用现有字段，不覆盖不需要改的）
  3. 从 APK 提取 versionCode
  4. 上传 APK 文件 -> 获取 URL + MD5
  5. 调用发布版本接口 (POST /resource/v1/app/upd)

安全锁（必须同时满足）:
  1. 命令行带 --i-know-this-submits-to-production
  2. 环境变量 OPPO_CONFIRM_SUBMIT=YES

用法:
  OPPO_CONFIRM_SUBMIT=YES python3 oppo_submit.py \
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
import time
import argparse
import subprocess
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _oppo_common import (  # noqa: E402
    log, bootstrap_oppo, query_app_info, upload_apk, publish_version,
    get_upload_config, upload_file,
)

SAFETY_FLAG = "--i-know-this-submits-to-production"
SAFETY_ENV = "OPPO_CONFIRM_SUBMIT"
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
    log(f"  示例: {SAFETY_ENV}={SAFETY_ENV_VALUE} python3 oppo_submit.py --apk <apk> --update-desc '...' {SAFETY_FLAG}", "ERROR")
    log("═══════════════════════════════════════════════════════", "ERROR")
    return False


def get_apk_version_code(apk_path, project_root=None):
    """从 APK 提取 versionCode，优先用 aapt2/aapt，兜底读 build.gradle"""
    # 搜索 aapt2/aapt (PATH + Android SDK)
    aapt_paths = ["aapt2", "aapt"]
    sdk_dir = os.environ.get("ANDROID_HOME", os.path.expanduser("~/Library/Android/sdk"))
    if os.path.isdir(sdk_dir):
        bt_dir = os.path.join(sdk_dir, "build-tools")
        if os.path.isdir(bt_dir):
            for bt in sorted(os.listdir(bt_dir), reverse=True):
                for tool in ["aapt2", "aapt"]:
                    p = os.path.join(bt_dir, bt, tool)
                    if os.path.isfile(p):
                        aapt_paths.append(p)

    for tool in aapt_paths:
        try:
            result = subprocess.run(
                [tool, "dump", "badging", apk_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                m = re.search(r"versionCode='(\d+)'", result.stdout)
                if m:
                    log(f"从 APK 提取 versionCode={m.group(1)} (via {tool})", "OK")
                    return m.group(1)
        except (FileNotFoundError, OSError):
            continue

    # 兜底: 读 build.gradle
    # APK 路径: {project_root}/app/build/outputs/apk/release/xxx.apk
    gradle = os.path.normpath(os.path.join(os.path.dirname(apk_path), "..", "..", "..", "..", "app", "build.gradle"))
    if not os.path.isfile(gradle) and project_root:
        gradle = os.path.join(project_root, "app", "build.gradle")

    if os.path.isfile(gradle):
        with open(gradle) as f:
            m = re.search(r"versionCode\s+(\d+)", f.read())
            if m:
                log(f"从 build.gradle 提取 versionCode={m.group(1)}", "WARN")
                return m.group(1)

    log("无法提取 versionCode，请用 --version-code 指定", "ERROR")
    sys.exit(2)


def build_publish_params(existing_info, apk_url, apk_md5, version_code, update_desc, icon_url_override=None, summary_override=None):
    """从现有应用信息构建发布参数，只替换 APK 和更新说明"""
    p = {
        "pkg_name": existing_info.get("pkg_name", ""),
        "version_code": str(version_code),
        "apk_url": json.dumps([{"url": apk_url, "md5": apk_md5, "cpu_code": 0}]),
        "app_name": existing_info.get("app_name", ""),
        "second_category_id": str(existing_info.get("second_category_id", "")),
        "third_category_id": str(existing_info.get("third_category_id", "")),
        "summary": (summary_override if summary_override is not None else (existing_info.get("summary", "") or ""))[:13],
        "detail_desc": existing_info.get("detail_desc", ""),
        "update_desc": update_desc,
        "privacy_source_url": existing_info.get("privacy_source_url", ""),
        "icon_url": icon_url_override or existing_info.get("icon_url", ""),
        "pic_url": existing_info.get("pic_url", ""),
        "online_type": "1",
        "test_desc": existing_info.get("test_desc", ""),
        "business_username": existing_info.get("business_username", ""),
        "business_email": existing_info.get("business_email", ""),
        "business_mobile": existing_info.get("business_mobile", ""),
        "age_level": str(existing_info.get("age_level", "3")),
        "adaptive_equipment": str(existing_info.get("adaptive_equipment", "4")),
        "adaptive_type": str(existing_info.get("adaptive_type", "1")),
        "copyright_url": existing_info.get("copyright_url", ""),
    }

    # 可选字段: 有就传
    if existing_info.get("landscape_pic_url"):
        p["landscape_pic_url"] = existing_info["landscape_pic_url"]
    if existing_info.get("electronic_cert_url"):
        p["electronic_cert_url"] = existing_info["electronic_cert_url"]
    if existing_info.get("icp_url"):
        p["icp_url"] = existing_info["icp_url"]

    return p


def main():
    parser = argparse.ArgumentParser(description="OPPO 应用市场 APK 上传 + 提审", add_help=False)
    parser.add_argument(SAFETY_FLAG, dest="confirm", action="store_true")
    parser.add_argument("--apk", dest="apk_path", required=True, help="APK 文件路径")
    parser.add_argument("--update-desc", dest="update_desc", required=True, help="更新说明（不少于 5 个字）")
    parser.add_argument("--version-code", dest="version_code", default=None, help="版本号（默认从 APK 提取）")
    parser.add_argument("--project-root", dest="project_root_opt", default=None, help="项目根目录")
    parser.add_argument("--icon", dest="icon_path", default=None, help="图标文件路径（上传后覆盖线上 icon_url）")
    parser.add_argument("--summary", dest="summary_override", default=None, help="Summary 覆盖值（最多13字符）")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("project_root", nargs="?", default=None)
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    if not os.path.isfile(args.apk_path):
        log(f"APK 文件不存在: {args.apk_path}", "ERROR")
        sys.exit(2)

    if len(args.update_desc) < 5:
        log("更新说明不少于 5 个字", "ERROR")
        sys.exit(2)

    project_root = args.project_root_opt or args.project_root

    print()
    print("=" * 55)
    print("  OPPO 应用市场 - APK 上传 + 提审")
    print("=" * 55)

    if not check_safety_lock(args):
        sys.exit(2)

    log("安全锁已通过", "WARN")

    # Step 1: 加载凭据 + 获取 Token
    client_id, client_secret, pkg_name, access_token = bootstrap_oppo(project_root)
    log(f"pkg_name={pkg_name}", "INFO")
    print()

    # Step 2: 查询现有应用详情
    log("[1/4] 查询现有应用详情", "STEP")
    existing = query_app_info(client_id, client_secret, access_token, pkg_name)
    log(f"  应用名: {existing.get('app_name')}", "INFO")
    log(f"  当前版本: {existing.get('version_name')} ({existing.get('version_code')})", "INFO")
    print()

    # Step 3: 提取 versionCode
    log("[2/4] 提取版本号", "STEP")
    version_code = args.version_code or get_apk_version_code(args.apk_path, project_root)
    log(f"  新版本 versionCode={version_code}", "INFO")
    print()

    # Step 4: 上传 APK
    log("[3/4] 上传 APK", "STEP")
    apk_url, apk_md5 = upload_apk(client_id, client_secret, access_token, args.apk_path)
    print()

    # Step 4.5: 上传图标覆盖（可选）
    icon_url_override = None
    if args.icon_path:
        if not os.path.isfile(args.icon_path):
            log(f"图标文件不存在: {args.icon_path}", "ERROR")
            sys.exit(2)
        log("正在上传图标到 OPPO...", "STEP")
        icon_upload_url, icon_sign = get_upload_config(client_id, client_secret, access_token)
        icon_result = upload_file(icon_upload_url, icon_sign, args.icon_path, "icon")
        icon_url_override = icon_result.get("url", "")
        if icon_url_override:
            log(f"图标上传成功: {icon_url_override[:80]}", "OK")
        else:
            log("图标上传失败", "ERROR")
            sys.exit(1)
        print()

    # Step 5: 发布版本
    log("[4/4] 发布版本", "STEP")
    params = build_publish_params(existing, apk_url, apk_md5, version_code, args.update_desc, icon_url_override, args.summary_override)
    log(f"  发布参数: {len(params)} 个字段", "INFO")

    data = publish_version(client_id, client_secret, access_token, params)
    success = data.get("data", {}).get("success", False)
    if success:
        print()
        log("提审完成! 可调用 oppo_query.py 查询审核状态", "OK")
        sys.exit(0)
    else:
        log("提审可能失败，请查看上方日志", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
