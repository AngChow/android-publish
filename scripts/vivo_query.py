#!/usr/bin/env python3
"""
查询 vivo 应用市场应用详情 (method=app.query.details)

用法:
  python3 vivo_query.py [<project_root>]

退出码: 0 = 成功, 1 = 失败
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _vivo_common import log, bootstrap_vivo, query_app_details


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  vivo 应用市场 - 查询应用详情", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    access_key, access_secret, pkg_name = bootstrap_vivo(project_root)
    log(f"pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    info = query_app_details(access_key, access_secret, pkg_name)
    log("查询成功", "OK")
    log(f"  应用名: {info.get('appName', info.get('app_name', ''))}", "INFO")
    log(f"  版本: {info.get('versionName', '')} ({info.get('versionCode', '')})", "INFO")
    log(f"  审核状态: {info.get('auditStatus', info.get('audit_status', ''))}", "INFO")

    print(json.dumps(info, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
