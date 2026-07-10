#!/usr/bin/env python3
"""
Android 应用打包 + 多渠道上传提审一条龙

支持渠道:
  - yyb    腾讯应用宝
  - xiaomi 小米应用商店
  - huawei 华为应用市场
  - oppo   OPPO 应用市场
  - vivo   vivo 应用市场
  - all    所有已配置凭据的渠道（默认）

流程:
  0. 预检查: 签名配置 + 版本号 (调用 pre_check.py)
  1. ./gradlew clean assembleRelease  (打正式包)
  1.5. 上传符号表到 Bugly (非阻塞)
  2. 定位 app/build/outputs/apk/release/app-arm64-v8a-release.apk
  3. 按指定渠道依次上传 + 提审
  4. 全部成功后 Git 打 tag (合并到 master + 创建版本 tag)

安全锁（必须同时满足）:
  1. 命令行带 --i-know-this-submits-to-production
  2. 环境变量 PUBLISH_CONFIRM_SUBMIT=YES（或对应渠道的 YYB_CONFIRM_SUBMIT / MI_CONFIRM_SUBMIT）
  build_and_submit.py 会在 --confirm 时自动为各渠道子进程设置对应环境变量，
  所以只需设 PUBLISH_CONFIRM_SUBMIT=YES 即可。

用法:
  # 打包 + 全渠道提审
  PUBLISH_CONFIRM_SUBMIT=YES python3 build_and_submit.py \
      --i-know-this-submits-to-production \
      --update-desc "修复已知问题" \
      /Users/Ang/workspace/mobile-android

  # 仅应用宝
  PUBLISH_CONFIRM_SUBMIT=YES python3 build_and_submit.py \
      --store yyb --i-know-this-submits-to-production \
      /Users/Ang/workspace/mobile-android

  # 仅打包 + 上传，不提审
  python3 build_and_submit.py --dry-run /Users/Ang/workspace/mobile-android

  # 跳过打包，直接用已有 APK
  PUBLISH_CONFIRM_SUBMIT=YES python3 build_and_submit.py \
      --skip-build --store xiaomi --i-know-this-submits-to-production \
      /Users/Ang/workspace/mobile-android

退出码:
  0 = 全部成功
  1 = 至少一个渠道失败
  2 = 参数错误
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log, load_env  # noqa: E402

# 64 位 APK 固定文件名和相对路径
APK_NAME = "app-arm64-v8a-release.apk"
APK_OUTPUT_DIR = "app/build/outputs/apk/release"

BUILD_TIMEOUT = 1800  # 30 分钟

ALL_STORES = ["yyb", "xiaomi", "huawei", "oppo", "vivo"]


def run_build(project_root):
    """运行 ./gradlew clean assembleRelease"""
    gradlew = os.path.join(project_root, "gradlew")
    if not os.path.isfile(gradlew):
        log(f"未找到 gradlew: {gradlew}", "ERROR")
        sys.exit(1)

    log("开始打包: ./gradlew clean assembleRelease", "STEP")
    log(f"项目目录: {project_root}", "INFO")
    start = time.time()

    result = subprocess.run(
        [gradlew, "clean", "assembleRelease"],
        cwd=project_root,
        timeout=BUILD_TIMEOUT,
    )

    elapsed = time.time() - start
    if result.returncode != 0:
        log(f"打包失败 (exit code {result.returncode})，耗时 {elapsed:.0f}s", "ERROR")
        sys.exit(1)

    log(f"打包成功，耗时 {elapsed:.0f}s", "OK")


def upload_bugly_symbol(project_root):
    """打包后上传符号表到 Bugly（非阻塞，失败不影响后续提审）"""
    cmd = [sys.executable, str(SCRIPT_DIR / "upload_bugly_symbol.py"), project_root]
    log("调用 upload_bugly_symbol.py...", "STEP")
    result = subprocess.run(cmd, cwd=project_root)
    if result.returncode != 0:
        log("Bugly 符号表上传失败，继续后续流程（非阻塞）", "WARN")
    return result.returncode


def find_apk(project_root):
    """定位 app-arm64-v8a-release.apk"""
    apk_path = os.path.join(project_root, APK_OUTPUT_DIR, APK_NAME)
    if not os.path.isfile(apk_path):
        log(f"未找到 APK: {apk_path}", "ERROR")
        out_dir = os.path.join(project_root, APK_OUTPUT_DIR)
        if os.path.isdir(out_dir):
            apks = [f for f in os.listdir(out_dir) if f.endswith(".apk")]
            if apks:
                log(f"目录下找到的 APK: {', '.join(apks)}", "INFO")
        sys.exit(1)

    size_mb = os.path.getsize(apk_path) / 1024 / 1024
    log(f"找到 APK: {apk_path} ({size_mb:.1f} MB)", "OK")
    return apk_path


def check_store_configured(store, project_root):
    """检查某渠道的凭据是否已配置"""
    load_env(project_root)
    if store == "yyb":
        return bool(os.environ.get("YYB_USER_ID") and os.environ.get("YYB_ACCESS_SECRET"))
    elif store == "xiaomi":
        return bool(os.environ.get("MI_USER_NAME") and os.environ.get("MI_PRIVATE_KEY"))
    elif store == "huawei":
        return bool(os.environ.get("HW_CLIENT_ID") and os.environ.get("HW_CLIENT_SECRET"))
    elif store == "oppo":
        return bool(os.environ.get("OPPO_CLIENT_ID") and os.environ.get("OPPO_CLIENT_SECRET"))
    elif store == "vivo":
        return bool(os.environ.get("VIVO_ACCESS_KEY") and os.environ.get("VIVO_ACCESS_SECRET"))
    return False


def make_child_env(confirm):
    """构建子进程环境变量，设置安全锁"""
    env = dict(os.environ)
    if confirm:
        env["YYB_CONFIRM_SUBMIT"] = "YES"
        env["MI_CONFIRM_SUBMIT"] = "YES"
        env["HW_CONFIRM_SUBMIT"] = "YES"
        env["OPPO_CONFIRM_SUBMIT"] = "YES"
        env["VIVO_CONFIRM_SUBMIT"] = "YES"
    return env


def submit_yyb(apk_path, project_root, args, env):
    """委托 submit_apk.py 上传提审到应用宝"""
    cmd = [sys.executable, str(SCRIPT_DIR / "submit_apk.py"), "--apk64", apk_path]
    if args.confirm:
        cmd.append("--i-know-this-submits-to-production")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.update_desc:
        cmd.extend(["--feature", args.update_desc])
    cmd.extend(["--project-root", project_root])

    log("调用 submit_apk.py (应用宝)...", "STEP")
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def submit_xiaomi(apk_path, project_root, args, env):
    """委托 mi_submit.py 上传提审到小米"""
    cmd = [sys.executable, str(SCRIPT_DIR / "mi_submit.py"),
           "--apk", apk_path, "--update-desc", args.update_desc]
    if args.confirm:
        cmd.append("--i-know-this-submits-to-production")
    if args.icon_path:
        cmd.extend(["--icon", args.icon_path])
    if args.privacy_url:
        cmd.extend(["--privacy-url", args.privacy_url])
    cmd.extend(["--project-root", project_root])

    log("调用 mi_submit.py (小米)...", "STEP")
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def submit_huawei(apk_path, project_root, args, env):
    """委托 hw_submit.py 上传提审到华为"""
    cmd = [sys.executable, str(SCRIPT_DIR / "hw_submit.py"),
           "--apk", apk_path]
    if args.confirm:
        cmd.append("--i-know-this-submits-to-production")
    if args.update_desc:
        cmd.extend(["--update-desc", args.update_desc])
    if args.remark:
        cmd.extend(["--remark", args.remark])
    cmd.extend(["--project-root", project_root])

    log("调用 hw_submit.py (华为)...", "STEP")
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def submit_oppo(apk_path, project_root, args, env):
    """委托 oppo_submit.py 上传提审到 OPPO"""
    cmd = [sys.executable, str(SCRIPT_DIR / "oppo_submit.py"),
           "--apk", apk_path,
           "--update-desc", args.update_desc]
    if args.confirm:
        cmd.append("--i-know-this-submits-to-production")
    cmd.extend(["--project-root", project_root])

    log("调用 oppo_submit.py (OPPO)...", "STEP")
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def submit_vivo(apk_path, project_root, args, env):
    """委托 vivo_submit.py 上传提审到 vivo"""
    cmd = [sys.executable, str(SCRIPT_DIR / "vivo_submit.py"),
           "--apk", apk_path,
           "--update-desc", args.update_desc]
    if args.confirm:
        cmd.append("--i-know-this-submits-to-production")
    cmd.extend(["--project-root", project_root])

    log("调用 vivo_submit.py (vivo)...", "STEP")
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Android 应用打包 + 多渠道上传提审一条龙",
        add_help=False,
    )
    parser.add_argument("--store", dest="store", default="all",
                        choices=["yyb", "xiaomi", "huawei", "oppo", "vivo", "all"],
                        help="目标渠道: yyb=应用宝, xiaomi=小米, all=全部(默认)")
    parser.add_argument("--i-know-this-submits-to-production",
                        dest="confirm", action="store_true",
                        help="确认提审（安全锁）")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="仅打包 + 上传，不提审")
    parser.add_argument("--update-desc", dest="update_desc",
                        default="修复已知问题，优化用户体验",
                        help="更新文案（默认: 修复已知问题，优化用户体验）")
    parser.add_argument("--remark", dest="remark", default="",
                        help="华为提审备注（10-300 字符）")
    parser.add_argument("--icon", dest="icon_path", default=None,
                        help="图标路径（仅小米需要时传）")
    parser.add_argument("--privacy-url", dest="privacy_url", default=None,
                        help="隐私政策 URL（仅小米需要时传）")
    parser.add_argument("--skip-build", dest="skip_build", action="store_true",
                        help="跳过打包，直接上传已有 APK")
    parser.add_argument("--skip-check", dest="skip_check", action="store_true",
                        help="跳过预检查（签名配置 + 版本号）")
    parser.add_argument("--skip-bugly", dest="skip_bugly", action="store_true",
                        help="跳过 Bugly 符号表上传")
    parser.add_argument("--skip-git", dest="skip_git", action="store_true",
                        help="跳过 Git 打 tag")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("project_root", nargs="?", default=".",
                        help="Android 项目根目录（默认当前目录）")
    args = parser.parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    project_root = os.path.abspath(args.project_root)

    # Step 0: 预检查（签名配置 + 版本号）
    if not args.skip_check:
        print()
        log("[0/4] 预检查", "STEP")
        check_result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "pre_check.py"), project_root],
            cwd=project_root,
        )
        if check_result.returncode != 0:
            log("预检查未通过，停止发布流程", "ERROR")
            sys.exit(1)
    else:
        log("跳过预检查 (--skip-check)", "WARN")

    # 确定目标渠道
    if args.store == "all":
        stores = [s for s in ALL_STORES if check_store_configured(s, project_root)]
        if not stores:
            log("未找到任何已配置凭据的渠道，请检查 .publish_env", "ERROR")
            sys.exit(2)
    else:
        stores = [args.store]

    print()
    print("=" * 55)
    print(f"  Android 应用上架 - 打包 + 提审")
    print(f"  目标渠道: {', '.join(stores)}")
    print("=" * 55)

    # Step 1: 打包
    if args.skip_build:
        log("跳过打包步骤 (--skip-build)", "WARN")
    else:
        print()
        log("[1/4] 打包 Release APK", "STEP")
        run_build(project_root)

    # Step 1.5: 上传符号表到 Bugly（非阻塞）
    if not args.skip_build and not args.skip_bugly:
        print()
        log("[1.5/4] 上传符号表到 Bugly", "STEP")
        upload_bugly_symbol(project_root)

    # Step 2: 定位 APK
    print()
    log("[2/4] 定位 64 位 APK", "STEP")
    apk_path = find_apk(project_root)

    # Step 3: 逐渠道上传 + 提审
    env = make_child_env(args.confirm)
    results = {}

    for i, store in enumerate(stores, 1):
        # 小米和华为的提审脚本不单独支持 dry-run，跳过
        if store in ("xiaomi", "huawei", "oppo", "vivo") and args.dry_run:
            log(f"{store}: dry-run 模式下跳过（该渠道不支持仅上传不提审）", "WARN")
            continue

        print()
        prefix = f"[3/4] 渠道 {i}/{len(stores)}"
        if store == "yyb":
            log(f"{prefix} 应用宝", "STEP")
            results["应用宝"] = submit_yyb(apk_path, project_root, args, env)
        elif store == "xiaomi":
            log(f"{prefix} 小米应用商店", "STEP")
            results["小米"] = submit_xiaomi(apk_path, project_root, args, env)
        elif store == "huawei":
            log(f"{prefix} 华为应用市场", "STEP")
            results["华为"] = submit_huawei(apk_path, project_root, args, env)
        elif store == "oppo":
            log(f"{prefix} OPPO 应用市场", "STEP")
            results["OPPO"] = submit_oppo(apk_path, project_root, args, env)
        elif store == "vivo":
            log(f"{prefix} vivo 应用市场", "STEP")
            results["vivo"] = submit_vivo(apk_path, project_root, args, env)

    # 汇总
    print()
    print("=" * 55)
    log("提审结果汇总:", "STEP")
    all_ok = True
    for name, rc in results.items():
        if rc == 0:
            log(f"  {name}: 成功", "OK")
        else:
            log(f"  {name}: 失败 (exit {rc})", "ERROR")
            all_ok = False

    if all_ok:
        log("全部渠道提审成功!", "OK")

        # Step 4: Git 打 tag（仅在全部成功且非 dry-run 时执行）
        if not args.dry_run and not args.skip_git:
            print()
            log("[4/4] Git 打 tag", "STEP")
            tag_cmd = [sys.executable, str(SCRIPT_DIR / "git_tag.py"),
                       project_root, "--update-desc", args.update_desc]
            tag_result = subprocess.run(tag_cmd, cwd=project_root)
            if tag_result.returncode != 0:
                log("Git 打 tag 失败（不影响已提交的提审）", "WARN")
        elif args.skip_git:
            log("跳过 Git 打 tag (--skip-git)", "WARN")
    else:
        log("部分渠道失败，跳过 Git 打 tag", "WARN")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
