"""
android-publish skill - 公共模块
集中处理: .publish_env 自动加载、凭据校验、HmacSHA256 签名、HTTP 请求封装、错误提示

腾讯应用宝开发者 API 文档:
  https://wikinew.open.qq.com/index.html#/iwiki/4015262492

API 基地址: https://p.open.qq.com/open_file/developer_api
签名算法: HmacSHA256(key=access_secret, params 按 ASCII 升序拼接为 k1=v1&k2=v2)
"""

import os
import sys
import time
import hmac
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import requests

# ============================================================
# 常量
# ============================================================
API_BASE = "https://p.open.qq.com/open_file/developer_api"

# API 路由
QUERY_APP_DETAIL = "/query_app_detail"
GET_FILE_UPLOAD_INFO = "/get_file_upload_info"
UPDATE_APP = "/update_app"
QUERY_APP_UPDATE_STATUS = "/query_app_update_status"


# ============================================================
# 日志
# ============================================================
def log(msg, level="INFO"):
    colors = {
        "INFO": "\033[36m", "OK": "\033[32m", "WARN": "\033[33m",
        "ERROR": "\033[31m", "STEP": "\033[35m",
    }
    reset = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{level}]{reset} {msg}", file=sys.stderr)


# ============================================================
# .publish_env 自动加载
# ============================================================
def load_env(project_root=None):
    """
    从 project_root/.publish_env 加载凭据到 os.environ。
    优先使用已有的环境变量（不覆盖外部 export 的值）。
    如果未提供 project_root，则从 cwd 向上找 .publish_env。
    """
    env_file = None
    if project_root:
        candidate = Path(project_root) / ".publish_env"
        if candidate.exists():
            env_file = candidate
    else:
        cur = Path.cwd()
        for p in [cur, *cur.parents]:
            candidate = p / ".publish_env"
            if candidate.exists():
                env_file = candidate
                break

    if env_file is None:
        return False

    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)
    return True


# ============================================================
# 凭据
# ============================================================
def get_credentials():
    """返回 (user_id, access_secret, app_id, pkg_name)，缺失则退出"""
    user_id = os.environ.get("YYB_USER_ID", "")
    access_secret = os.environ.get("YYB_ACCESS_SECRET", "")
    app_id = os.environ.get("YYB_APP_ID", "")
    pkg_name = os.environ.get("YYB_PKG_NAME", "")
    missing = [k for k, v in {
        "YYB_USER_ID": user_id,
        "YYB_ACCESS_SECRET": access_secret,
        "YYB_APP_ID": app_id,
        "YYB_PKG_NAME": pkg_name,
    }.items() if not v]
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "ERROR")
        log("请确认项目根目录有 .publish_env 文件，且包含:", "ERROR")
        log("  YYB_USER_ID / YYB_ACCESS_SECRET / YYB_APP_ID / YYB_PKG_NAME", "ERROR")
        sys.exit(1)
    return user_id, access_secret, app_id, pkg_name


# ============================================================
# 签名
# ============================================================
def cal_sign(access_secret, params):
    """
    HmacSHA256 签名计算:
    1) 请求参数（除 sign 外）按 ASCII 升序排序
    2) 拼接为 k1=v1&k2=v2（值为 None 的参数不参与）
    3) HmacSHA256(key=access_secret)
    4) 转小写 hex
    """
    # 过滤 None 值
    filtered = {k: v for k, v in params.items() if v is not None}
    # 按 key ASCII 升序排序
    sorted_keys = sorted(filtered.keys())
    # 拼接
    sign_str = "&".join(f"{k}={filtered[k]}" for k in sorted_keys)
    # HmacSHA256
    h = hmac.new(
        key=access_secret.encode("utf-8"),
        msg=sign_str.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return h.hexdigest()


# ============================================================
# HTTP 请求封装
# ============================================================
def api_call(path, access_secret, user_id, business_params, timeout=60):
    """
    调用应用宝开发者 API。

    自动添加公共参数 (user_id, timestamp, sign)，
    以 POST application/x-www-form-urlencoded 方式发送。

    返回: dict (JSON 响应)
    """
    url = API_BASE + path

    # 公共参数 + 业务参数
    all_params = {
        "user_id": user_id,
        "timestamp": str(int(time.time())),
    }
    all_params.update(business_params)

    # 计算签名
    sign = cal_sign(access_secret, all_params)
    all_params["sign"] = sign

    # URL 编码后发送（签名计算时不编码，发送时编码）
    body = urlencode(all_params)

    log(f"POST {path}", "INFO")
    resp = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )

    if resp.status_code != 200:
        log(f"HTTP {resp.status_code}: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    try:
        data = resp.json()
    except json.JSONDecodeError:
        log(f"响应不是有效 JSON: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    return data


def check_ret(data, context=""):
    """检查 API 返回的 ret 是否为 0，非 0 则打印错误并退出"""
    ret = data.get("ret", -1)
    msg = data.get("msg", "")
    if ret != 0:
        log(f"{context}失败: ret={ret}, msg={msg}", "ERROR")
        log(f"完整响应: {json.dumps(data, ensure_ascii=False)[:500]}", "ERROR")
        sys.exit(1)
    return data


# ============================================================
# 便捷调用
# ============================================================
def bootstrap(project_root=None):
    """
    一站式入口：加载 .publish_env -> 校验凭据
    返回 (user_id, access_secret, app_id, pkg_name)
    """
    load_env(project_root)
    user_id, access_secret, app_id, pkg_name = get_credentials()
    return user_id, access_secret, app_id, pkg_name
