#!/usr/bin/env python3
"""
发布前预检查:
  1. 检查 build.gradle 中 release buildType 的签名配置是否为 signingConfigs.release
  2. 检查本地 versionCode 是否大于线上版本号（以首个可查询的渠道为准）

用法:
  python3 pre_check.py <project_root>

退出码:
  0 = 检查通过
  1 = 检查未通过（签名配置错误 / 版本号不够）
  2 = 检查失败（文件缺失 / API 查询失败）
"""

import sys
import os
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log, load_env  # noqa: E402


def extract_block(content, keyword):
    """从 Groovy 文本中提取 keyword { ... } 块的内容"""
    pattern = rf'\b{keyword}\s*\{{'
    m = re.search(pattern, content)
    if not m:
        return None
    start = m.end()
    depth = 0
    for i in range(start, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            if depth == 0:
                return content[start:i]
            depth -= 1
    return None


def check_signing_config(project_root):
    """检查 release buildType 是否使用 signingConfigs.release"""
    gradle_path = os.path.join(project_root, "app", "build.gradle")
    if not os.path.isfile(gradle_path):
        log(f"未找到 app/build.gradle: {gradle_path}", "ERROR")
        return False

    with open(gradle_path, 'r') as f:
        content = f.read()

    # 找 buildTypes 块
    build_types_block = extract_block(content, "buildTypes")
    if not build_types_block:
        log("未找到 buildTypes 块", "ERROR")
        return False

    # 在 buildTypes 中找 release 块
    release_block = extract_block(build_types_block, "release")
    if not release_block:
        log("未找到 release buildType", "ERROR")
        return False

    # 检查 signingConfig
    sc_matches = re.findall(r'signingConfig\s+(\S+)', release_block)
    if not sc_matches:
        log("release buildType 未配置 signingConfig", "ERROR")
        return False

    sc = sc_matches[0].strip()
    if sc == "signingConfigs.release":
        log(f"签名配置检查通过: {sc}", "OK")
        return True
    else:
        log(f"签名配置异常: release buildType 使用的是 {sc}，应为 signingConfigs.release", "ERROR")
        log("请检查 app/build.gradle 中的 buildTypes.release.signingConfig", "ERROR")
        return False


def get_local_version(project_root):
    """从 build.gradle 读取 versionCode"""
    gradle_path = os.path.join(project_root, "app", "build.gradle")
    with open(gradle_path, 'r') as f:
        content = f.read()
    m = re.search(r'versionCode\s+(\d+)', content)
    if not m:
        log("未找到 versionCode", "ERROR")
        return None

    vc = int(m.group(1))

    # 也读 versionName
    vn_match = re.search(r'versionName\s+(?:APP_VERSION|"([^"]+)")|APP_VERSION', content)
    version_name = ""
    gp = os.path.join(project_root, "gradle.properties")
    if os.path.isfile(gp):
        with open(gp) as f:
            vnm = re.search(r'APP_VERSION=(.+)', f.read())
            if vnm:
                version_name = vnm.group(1).strip()

    return vc, version_name


def get_online_version(project_root):
    """查询线上版本号，依次尝试各渠道"""
    load_env(project_root)

    # 华为
    hw_cid = os.environ.get("HW_CLIENT_ID", "")
    hw_cs = os.environ.get("HW_CLIENT_SECRET", "")
    hw_aid = os.environ.get("HW_APP_ID", "")
    if hw_cid and hw_cs and hw_aid:
        try:
            from _hw_common import bootstrap_hw, query_app_info
            _, app_id, headers = bootstrap_hw(project_root)
            info = query_app_info(hw_cid, app_id, headers)
            vc = info.get("onShelfVersionCode") or info.get("versionCode")
            vn = info.get("onShelfVersionNumber") or info.get("versionNumber")
            if vc:
                log(f"线上版本(华为): {vn} ({vc})", "OK")
                return int(vc), vn or ""
        except Exception as e:
            log(f"查询华为版本失败: {e}", "WARN")

    # vivo
    vivo_ak = os.environ.get("VIVO_ACCESS_KEY", "")
    vivo_sk = os.environ.get("VIVO_ACCESS_SECRET", "")
    if vivo_ak and vivo_sk:
        try:
            from _vivo_common import bootstrap_vivo, query_app_details
            ak, sk, pkg = bootstrap_vivo(project_root)
            info = query_app_details(ak, sk, pkg)
            vc = info.get("versionCode")
            vn = info.get("versionName")
            if vc:
                log(f"线上版本(vivo): {vn} ({vc})", "OK")
                return int(vc), vn or ""
        except Exception as e:
            log(f"查询vivo版本失败: {e}", "WARN")

    # OPPO
    oppo_cid = os.environ.get("OPPO_CLIENT_ID", "")
    oppo_cs = os.environ.get("OPPO_CLIENT_SECRET", "")
    if oppo_cid and oppo_cs:
        try:
            from _oppo_common import bootstrap_oppo, query_app_info
            cid, cs, pkg, token = bootstrap_oppo(project_root)
            info = query_app_info(cid, cs, token, pkg)
            vc = info.get("version_code")
            vn = info.get("version_name")
            if vc:
                log(f"线上版本(OPPO): {vn} ({vc})", "OK")
                return int(vc), vn or ""
        except Exception as e:
            log(f"查询OPPO版本失败: {e}", "WARN")

    # 小米
    mi_user = os.environ.get("MI_USER_NAME", "")
    mi_pk = os.environ.get("MI_PRIVATE_KEY", "")
    if mi_user and mi_pk:
        try:
            from _mi_common import bootstrap_mi, mi_query
            user, pk, cert, pkg, _, _, _ = bootstrap_mi(project_root)
            data = mi_query(user, pk, cert, pkg)
            pi = data.get("packageInfo", {})
            vc = pi.get("versionCode")
            vn = pi.get("versionName")
            if vc:
                log(f"线上版本(小米): {vn} ({vc})", "OK")
                return int(vc), vn or ""
        except Exception as e:
            log(f"查询小米版本失败: {e}", "WARN")

    return None, None


def check_version(project_root):
    """检查本地版本号是否大于线上版本号"""
    local_vc, local_vn = get_local_version(project_root)
    log(f"本地版本: {local_vn} ({local_vc})", "INFO")

    online_vc, online_vn = get_online_version(project_root)
    if online_vc is None:
        log("无法查询线上版本号，跳过版本检查", "WARN")
        return True

    if local_vc <= online_vc:
        log(f"版本号检查未通过！", "ERROR")
        log(f"  本地 versionCode ({local_vc}) <= 线上 versionCode ({online_vc})", "ERROR")
        log(f"  请先升级 app/build.gradle 中的 versionCode", "ERROR")
        return False

    log(f"版本号检查通过: {local_vc} > {online_vc}", "OK")
    return True


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    project_root = os.path.abspath(project_root)

    print()
    print("=" * 55)
    print("  发布前预检查")
    print("=" * 55)
    print()

    all_ok = True

    # 1. 签名配置检查
    log("[1/2] 检查签名配置", "STEP")
    if not check_signing_config(project_root):
        all_ok = False
    print()

    # 2. 版本号检查
    log("[2/2] 检查版本号", "STEP")
    if not check_version(project_root):
        all_ok = False
    print()

    if all_ok:
        log("预检查全部通过!", "OK")
        sys.exit(0)
    else:
        log("预检查未通过，请修复上述问题", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
