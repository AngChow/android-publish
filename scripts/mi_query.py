#!/usr/bin/env python3
"""
查询小米应用商店应用信息 (POST /dev/query)

用法:
  python3 mi_query.py [<project_root>]

退出码: 0 = 成功, 1 = 失败
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _mi_common import log, bootstrap_mi, mi_query


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  小米应用商店 - 查询应用信息", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    user_name, private_key, cert_path, pkg_name, _, _, _ = bootstrap_mi(project_root)
    log(f"userName={user_name}, pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    data = mi_query(user_name, private_key, cert_path, pkg_name)

    result = data.get("result", -1)
    message = data.get("message", "")
    if result != 0:
        log(f"查询失败: result={result}, message={message}", "ERROR")
        log(f"完整响应: {json.dumps(data, ensure_ascii=False)[:500]}", "ERROR")
        sys.exit(1)

    log("查询成功", "OK")
    pkg_info = data.get("packageInfo", {})
    if pkg_info:
        log(f"  应用名: {pkg_info.get('appName', '')}", "INFO")
        log(f"  包名: {pkg_info.get('packageName', '')}", "INFO")
        log(f"  版本: {pkg_info.get('versionName', '')} ({pkg_info.get('versionCode', '')})", "INFO")
    log(f"  允许新增: {data.get('create', False)}", "INFO")
    log(f"  允许更新版本: {data.get('updateVersion', False)}", "INFO")
    log(f"  允许更新信息: {data.get('updateInfo', False)}", "INFO")

    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
