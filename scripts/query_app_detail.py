#!/usr/bin/env python3
"""
查询应用宝应用详情 (POST /query_app_detail)

用法:
  python3 query_app_detail.py [<project_root>]

输出 JSON 到 stdout（供其他脚本消费），日志输出到 stderr。
退出码: 0 = 成功, 1 = 失败
"""

import sys
import os
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log, bootstrap, api_call, check_ret, QUERY_APP_DETAIL


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  应用宝 - 查询应用详情", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    user_id, access_secret, app_id, pkg_name = bootstrap(project_root)
    log(f"app_id={app_id}, pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    data = api_call(
        QUERY_APP_DETAIL, access_secret, user_id,
        {"pkg_name": pkg_name, "app_id": app_id},
        timeout=30,
    )
    check_ret(data, "查询应用详情")

    # 输出 JSON 到 stdout
    print(json.dumps(data, ensure_ascii=False, indent=2))
    log("查询成功", "OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
