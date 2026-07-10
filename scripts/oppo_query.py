#!/usr/bin/env python3
"""
查询 OPPO 应用市场应用详情 (GET /resource/v1/app/info)

用法:
  python3 oppo_query.py [<project_root>]

退出码: 0 = 成功, 1 = 失败
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _oppo_common import log, bootstrap_oppo, query_app_info


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  OPPO 应用市场 - 查询应用详情", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    client_id, client_secret, pkg_name, access_token = bootstrap_oppo(project_root)
    log(f"pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    info = query_app_info(client_id, client_secret, access_token, pkg_name)
    log("查询成功", "OK")
    log(f"  应用名: {info.get('app_name')}", "INFO")
    log(f"  版本: {info.get('version_name')} ({info.get('version_code')})", "INFO")
    log(f"  审核状态: {info.get('audit_status_name', info.get('audit_status'))}", "INFO")
    log(f"  上架状态: {info.get('state')}", "INFO")
    log(f"  分类: {info.get('second_category_id')}/{info.get('third_category_id')}", "INFO")
    log(f"  一句话简介: {info.get('summary')}", "INFO")

    print(json.dumps(info, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
