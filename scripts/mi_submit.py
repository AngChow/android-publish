#!/usr/bin/env python3
"""
小米应用商店 APK 上传 + 提审 (POST /dev/push, synchroType=1)

最小参数: 只传 APK + 更新说明 + appName + packageName
不传 icon / privacyUrl / screenshots，不覆盖线上已有值。
如果 API 报错缺字段，根据报错补充。

安全锁（必须同时满足）:
  1. 命令行带 --i-know-this-submits-to-production
  2. 环境变量 MI_CONFIRM_SUBMIT=YES
  两者缺一不可，否则不上传。

用法:
  MI_CONFIRM_SUBMIT=YES python3 mi_submit.py \
      --apk /path/to/app.apk \
      --update-desc "修复已知问题" \
      --i-know-this-submits-to-production \
      [<project_root>]

  # 显式传 icon / privacyUrl（仅当 API 要求时）
  MI_CONFIRM_SUBMIT=YES python3 mi_submit.py \
      --apk /path/to/app.apk \
      --update-desc "修复已知问题" \
      --icon /path/to/icon.png \
      --privacy-url "https://www.example.com/privacy" \
      --i-know-this-submits-to-production

退出码:
  0 = 成功
  1 = 失败
  2 = 安全锁未满足 / 参数错误
"""

import sys
import os
import json
import argparse
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _mi_common import log, bootstrap_mi, mi_push


SAFETY_FLAG = "--i-know-this-submits-to-production"
SAFETY_ENV = "MI_CONFIRM_SUBMIT"
SAFETY_ENV_VALUE = "YES"


def check_safety_lock(args):
    has_flag = args.confirm
    env_val = os.environ.get(SAFETY_ENV, "")
    has_env = env_val == SAFETY_ENV_VALUE

    if has_flag and has_env:
        return True

    log("═══════════════════════════════════════════════════════", "ERROR")
    log("安全锁未通过，不会上传。提审是写线上操作:", "ERROR")
    log(f"  1) 命令行加 {SAFETY_FLAG}  {'OK' if has_flag else 'MISSING'}", "ERROR")
    log(f"  2) 环境变量 {SAFETY_ENV}={SAFETY_ENV_VALUE}  {'OK' if has_env else 'MISSING'}", "ERROR")
    log("", "ERROR")
    log("  示例:", "ERROR")
    log(f"  {SAFETY_ENV}={SAFETY_ENV_VALUE} python3 mi_submit.py --apk <apk> --update-desc '...' {SAFETY_FLAG}", "ERROR")
    log("═══════════════════════════════════════════════════════", "ERROR")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="小米应用商店 APK 上传 + 提审",
        add_help=False,
    )
    parser.add_argument(SAFETY_FLAG, dest="confirm", action="store_true")
    parser.add_argument("--apk", dest="apk_path", required=True,
                        help="APK 文件路径")
    parser.add_argument("--update-desc", dest="update_desc", required=True,
                        help="更新说明（必填）")
    parser.add_argument("--icon", dest="icon_path", default=None,
                        help="图标文件路径（仅 API 要求时传）")
    parser.add_argument("--privacy-url", dest="privacy_url", default=None,
                        help="隐私政策 URL（仅 API 要求时传）")
    parser.add_argument("--project-root", dest="project_root_opt", default=None,
                        help="项目根目录（查找 .publish_env）")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("project_root", nargs="?", default=None)
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    # 校验 APK
    if not os.path.isfile(args.apk_path):
        log(f"APK 文件不存在: {args.apk_path}", "ERROR")
        sys.exit(2)

    project_root = args.project_root_opt or args.project_root

    print()
    print("=" * 55)
    print("  小米应用商店 - APK 上传 + 提审")
    print("=" * 55)

    # 安全锁
    if not check_safety_lock(args):
        sys.exit(2)

    log("安全锁已通过，3 秒后开始上传...", "WARN")
    time.sleep(3)

    # 加载凭据
    user_name, private_key, cert_path, pkg_name, app_name, _, _ = bootstrap_mi(project_root)

    if not app_name:
        log("MI_APP_NAME 未配置，无法提审", "ERROR")
        sys.exit(2)

    log(f"userName={user_name}", "INFO")
    log(f"pkg_name={pkg_name}, app_name={app_name}", "INFO")
    log(f"APK: {args.apk_path} ({os.path.getsize(args.apk_path) / 1024 / 1024:.1f} MB)", "INFO")
    if args.icon_path:
        log(f"icon: {args.icon_path}", "INFO")
    if args.privacy_url:
        log(f"privacyUrl: {args.privacy_url}", "INFO")
    print()

    # 调用 push
    data = mi_push(
        user_name=user_name,
        private_key=private_key,
        cert_path=cert_path,
        pkg_name=pkg_name,
        app_name=app_name,
        apk_path=args.apk_path,
        update_desc=args.update_desc,
        privacy_url=args.privacy_url,
        icon_path=args.icon_path,
    )

    result = data.get("result", -1)
    message = data.get("message", "")

    if result == 0:
        log(f"提审成功! {message}", "OK")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0)
    else:
        log(f"提审失败: result={result}, message={message}", "ERROR")
        log(f"完整响应: {json.dumps(data, ensure_ascii=False)[:500]}", "ERROR")
        # 如果是缺字段错误，提示用户
        if any(kw in str(message) for kw in ["icon", "privacy", "截图", "图标", "隐私"]):
            log("API 可能要求额外字段，请用 --icon / --privacy-url 补充", "WARN")
        sys.exit(1)


if __name__ == "__main__":
    main()
