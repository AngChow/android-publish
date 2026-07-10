#!/usr/bin/env python3
"""
查询应用宝应用更新审核状态 (POST /query_app_update_status)

用法:
  python3 query_status.py [<project_root>]

退出码: 0 = 成功, 1 = 失败
"""

import sys
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _yyb_common import log, bootstrap, api_call, check_ret, QUERY_APP_UPDATE_STATUS


AUDIT_STATUS_MAP = {
    1: "审核中",
    2: "审核驳回",
    3: "审核通过",
    8: "开发者主动撤销",
}


def main():
    project_root = sys.argv[1] if len(sys.argv) > 1 else None

    print(file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("  应用宝 - 查询审核状态", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    user_id, access_secret, app_id, pkg_name = bootstrap(project_root)
    log(f"app_id={app_id}, pkg_name={pkg_name}", "INFO")
    print(file=sys.stderr)

    data = api_call(
        QUERY_APP_UPDATE_STATUS, access_secret, user_id,
        {"pkg_name": pkg_name, "app_id": app_id},
        timeout=30,
    )
    check_ret(data, "查询审核状态")

    audit_status = data.get("audit_status", 0)
    audit_reason = data.get("audit_reason", "")
    status_text = AUDIT_STATUS_MAP.get(audit_status, f"未知({audit_status})")

    log(f"审核状态: {status_text} (audit_status={audit_status})", "OK")
    if audit_reason:
        log(f"审核原因: {audit_reason}", "INFO")

    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
