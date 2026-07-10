#!/usr/bin/env python3
"""
查询华为应用市场应用信息 (GET /api/publish/v2/app-info)

用法:
  python3 hw_query.py [<project_root>]

退出码: 0 = 成功, 1 = 失败
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _hw_common import log, bootstrap_hw, query_app_info


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  华为应用市场 - 查询应用信息", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    client_id, app_id, headers = bootstrap_hw(project_root)
    log(f"appId={app_id}", "INFO")
    print(file=sys.stderr)

    data = query_app_info(client_id, app_id, headers)
    ret = data.get("ret", {})
    if ret.get("code") != 0:
        log(f"查询失败: {ret}", "ERROR")
        sys.exit(1)

    log("查询成功", "OK")
    app_info = data.get("appInfo", {})
    state_map = {0: "已上架", 1: "审核不通过", 2: "已下架", 3: "待上架",
                 4: "审核中", 5: "升级审核中", 7: "草稿", 8: "升级审核不通过",
                 11: "撤销上架"}
    state = app_info.get("releaseState")
    log(f"  状态: {state_map.get(state, f'未知({state})')}", "INFO")
    log(f"  在架版本: {app_info.get('onShelfVersionNumber')} ({app_info.get('onShelfVersionCode')})", "INFO")
    log(f"  草稿版本: {app_info.get('versionNumber')} ({app_info.get('versionCode')})", "INFO")

    for lang_info in data.get("languages", []):
        if lang_info.get("lang") == "zh-CN":
            log(f"  应用名: {lang_info.get('appName')}", "INFO")
            log(f"  新特性: {(lang_info.get('newFeatures') or '')[:60]}", "INFO")

    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
