#!/usr/bin/env python3
"""
上传 Android 符号表 (mapping.txt) 到 Bugly

打完正式包后运行，将 ProGuard/R8 混淆映射文件上传到 Bugly，
确保线上崩溃堆栈能正确还原。

用法:
  python3 upload_bugly_symbol.py <project_root>

退出码:
  0 = 上传成功（或跳过）
  1 = 上传失败
"""

import sys
import os
import re
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log, load_env  # noqa: E402

# mapping.txt 固定路径（相对于项目根目录）
MAPPING_REL_PATH = "app/build/outputs/mapping/release/mapping.txt"
# 默认使用 skill 内的 jar
DEFAULT_JAR_PATH = str(Path(__file__).resolve().parent.parent / "tools" / "buglyqq-upload-symbol.jar")


def get_version_name(project_root):
    """从 gradle.properties 读取 APP_VERSION"""
    gp = os.path.join(project_root, "gradle.properties")
    if not os.path.isfile(gp):
        log(f"未找到 gradle.properties: {gp}", "ERROR")
        return None
    with open(gp) as f:
        m = re.search(r'APP_VERSION=(.+)', f.read())
        if m:
            return m.group(1).strip()
    log("未找到 APP_VERSION in gradle.properties", "ERROR")
    return None


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    project_root = os.path.abspath(project_root)

    print()
    print("=" * 50)
    print("  Bugly 符号表上传")
    print("=" * 50)

    # 加载凭据
    load_env(project_root)
    app_id = os.environ.get("BUGLY_APP_ID", "")
    app_key = os.environ.get("BUGLY_APP_KEY", "")
    jar_path = os.environ.get("BUGLY_JAR_PATH", "") or DEFAULT_JAR_PATH
    bundle_id = os.environ.get("YYB_PKG_NAME", "") or os.environ.get("BUGLY_BUNDLE_ID", "")

    missing = [k for k, v in {
        "BUGLY_APP_ID": app_id,
        "BUGLY_APP_KEY": app_key,
        "BUGLY_JAR_PATH": jar_path,
    }.items() if not v]
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "WARN")
        log("跳过 Bugly 符号表上传（未配置凭据）", "WARN")
        sys.exit(0)
    if not bundle_id:
        log("缺少 YYB_PKG_NAME (用作 bundleid)", "WARN")
        sys.exit(0)

    # 检查 jar 是否存在
    if not os.path.isfile(jar_path):
        log(f"buglyqq-upload-symbol.jar 不存在: {jar_path}", "ERROR")
        sys.exit(1)

    # 检查 mapping.txt
    mapping_path = os.path.join(project_root, MAPPING_REL_PATH)
    if not os.path.isfile(mapping_path):
        log(f"mapping.txt 不存在: {mapping_path}", "ERROR")
        log("请先执行 ./gradlew assembleRelease 打包", "ERROR")
        sys.exit(1)

    mapping_size = os.path.getsize(mapping_path)
    log(f"mapping.txt: {mapping_path} ({mapping_size / 1024:.0f} KB)", "INFO")

    # 获取版本号
    version = get_version_name(project_root)
    if not version:
        sys.exit(1)
    log(f"版本号: {version}", "INFO")
    log(f"appid: {app_id}, bundleid: {bundle_id}", "INFO")
    print()

    # 执行上传
    cmd = [
        "java", "-jar", jar_path,
        "-appid", app_id,
        "-appkey", app_key,
        "-bundleid", bundle_id,
        "-version", version,
        "-platform", "Android",
        "-inputMapping", mapping_path,
    ]
    log("正在上传符号表到 Bugly...", "STEP")
    log(f"命令: {' '.join(cmd[:6])} ... -inputMapping {mapping_path}", "INFO")

    result = subprocess.run(cmd, timeout=120)

    if result.returncode == 0:
        log("Bugly 符号表上传成功!", "OK")
        sys.exit(0)
    else:
        log(f"Bugly 符号表上传失败 (exit code {result.returncode})", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
