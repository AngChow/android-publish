"""
android-publish skill - OPPO 应用市场公共模块
集中处理: 凭据加载、Token 获取、HmacSHA256 签名、文件上传、API 封装

OPPO 开放平台 API 文档:
  https://open.oppomobile.com/documentation/page/info?id=10998

API 基地址: https://oop-openapi-cn.heytapmobi.com
认证方式: Access Token (client_id + client_secret 换取，48h 有效)
签名方式: HmacSHA256 (与腾讯应用宝相同)
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

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _yyb_common import log, load_env  # noqa: E402

# ============================================================
# 常量
# ============================================================
OPPO_API_BASE = "https://oop-openapi-cn.heytapmobi.com"

OPPO_TOKEN_URL = "/developer/v1/token"
OPPO_APP_INFO = "/resource/v1/app/info"
OPPO_APP_UPD = "/resource/v1/app/upd"
OPPO_GET_UPLOAD_URL = "/resource/v1/upload/get-upload-url"


# ============================================================
# 凭据
# ============================================================
def get_oppo_credentials():
    """返回 (client_id, client_secret, pkg_name)"""
    client_id = os.environ.get("OPPO_CLIENT_ID", "")
    client_secret = os.environ.get("OPPO_CLIENT_SECRET", "")
    pkg_name = os.environ.get("OPPO_PKG_NAME", "") or os.environ.get("YYB_PKG_NAME", "")
    missing = [k for k, v in {
        "OPPO_CLIENT_ID": client_id,
        "OPPO_CLIENT_SECRET": client_secret,
    }.items() if not v]
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "ERROR")
        log("请在 .publish_env 中配置 OPPO 应用市场凭据", "ERROR")
        sys.exit(1)
    if not pkg_name:
        log("缺少 OPPO_PKG_NAME 或 YYB_PKG_NAME", "ERROR")
        sys.exit(1)
    return client_id, client_secret, pkg_name


def bootstrap_oppo(project_root=None):
    """一站式入口：加载 .publish_env -> 校验凭据 -> 获取 Token
    返回 (client_id, client_secret, pkg_name, access_token)
    """
    load_env(project_root)
    client_id, client_secret, pkg_name = get_oppo_credentials()

    log("正在获取 OPPO Access Token...", "STEP")
    resp = requests.get(
        OPPO_API_BASE + OPPO_TOKEN_URL,
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"获取 Token 失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    data = resp.json()
    if data.get("errno") != 0:
        log(f"获取 Token 失败: {data}", "ERROR")
        sys.exit(1)
    access_token = data.get("data", {}).get("access_token", "")
    if not access_token:
        log(f"Token 响应缺少 access_token: {data}", "ERROR")
        sys.exit(1)
    log("Token 获取成功 (48h 有效)", "OK")
    return client_id, client_secret, pkg_name, access_token


# ============================================================
# 签名 (与腾讯应用宝相同: HmacSHA256)
# ============================================================
def cal_sign(client_secret, params):
    """HmacSHA256 签名: 参数按 ASCII 升序拼接 k1=v1&k2=v2，HmacSHA256(key=client_secret)"""
    filtered = {k: v for k, v in params.items() if v is not None}
    sorted_keys = sorted(filtered.keys())
    sign_str = "&".join(f"{k}={filtered[k]}" for k in sorted_keys)
    h = hmac.new(
        key=client_secret.encode("utf-8"),
        msg=sign_str.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return h.hexdigest()


# ============================================================
# API 调用
# ============================================================
def api_call(path, client_id, client_secret, access_token, business_params, method="POST"):
    """
    调用 OPPO API。自动添加公共参数 (access_token, timestamp, api_sign)。
    POST: application/x-www-form-urlencoded
    GET: query params
    """
    url = OPPO_API_BASE + path

    all_params = {
        "access_token": access_token,
        "timestamp": str(int(time.time())),
    }
    all_params.update(business_params)

    # 计算签名
    sign = cal_sign(client_secret, all_params)
    all_params["api_sign"] = sign

    log(f"{method} {path}", "INFO")

    if method == "GET":
        resp = requests.get(url, params=all_params, timeout=30)
    else:
        body = urlencode(all_params)
        resp = requests.post(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )

    if resp.status_code != 200:
        log(f"HTTP {resp.status_code}: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    return resp.json()


def check_errno(data, context=""):
    """检查 errno 是否为 0"""
    errno = data.get("errno", -1)
    if errno != 0:
        msg = data.get("data", {}).get("message", "") if isinstance(data.get("data"), dict) else ""
        log(f"{context}失败: errno={errno}, message={msg}", "ERROR")
        log(f"完整响应: {json.dumps(data, ensure_ascii=False)[:500]}", "ERROR")
        sys.exit(1)
    return data


# ============================================================
# 查询应用详情
# ============================================================
def query_app_info(client_id, client_secret, access_token, pkg_name):
    """查询普通包应用详情 (GET /resource/v1/app/info)"""
    data = api_call(
        OPPO_APP_INFO, client_id, client_secret, access_token,
        {"pkg_name": pkg_name}, method="GET",
    )
    check_errno(data, "查询应用详情")
    return data.get("data", {})


# ============================================================
# 文件上传
# ============================================================
def get_upload_config(client_id, client_secret, access_token):
    """获取上传配置 (GET /resource/v1/upload/get-upload-url)"""
    data = api_call(
        OPPO_GET_UPLOAD_URL, client_id, client_secret, access_token,
        {}, method="GET",
    )
    check_errno(data, "获取上传配置")
    upload_url = data.get("data", {}).get("upload_url", "")
    sign = data.get("data", {}).get("sign", "")
    if not upload_url or not sign:
        log(f"返回缺少 upload_url 或 sign: {data}", "ERROR")
        sys.exit(1)
    return upload_url, sign


def upload_file(upload_url, sign, file_path, file_type="apk"):
    """上传文件到 OPPO 文件服务器 (POST multipart/form-data)"""
    file_size = os.path.getsize(file_path)
    log(f"正在上传文件 ({file_type}, {file_size / 1024 / 1024:.1f} MB)...", "STEP")

    with open(file_path, "rb") as f:
        resp = requests.post(
            upload_url,
            data={"type": file_type, "sign": sign},
            files={"file": (os.path.basename(file_path), f)},
            timeout=900,
        )

    if resp.status_code != 200:
        log(f"文件上传失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    data = resp.json()
    if data.get("errno") != 0:
        msg = data.get("data", {}).get("message", "")
        log(f"文件上传失败: errno={data.get('errno')}, message={msg}", "ERROR")
        sys.exit(1)

    result = data.get("data", {})
    url = result.get("url", "")
    md5 = result.get("md5", "")
    log(f"文件上传成功: {os.path.basename(file_path)}", "OK")
    log(f"  URL: {url[:60]}...", "INFO")
    log(f"  MD5: {md5}", "INFO")
    return result


def upload_apk(client_id, client_secret, access_token, apk_path):
    """完整上传 APK: 获取配置 -> 上传 -> 返回 (url, md5)"""
    log("正在上传 APK 到 OPPO...", "STEP")
    upload_url, sign = get_upload_config(client_id, client_secret, access_token)
    result = upload_file(upload_url, sign, apk_path, "apk")
    return result.get("url", ""), result.get("md5", "")


# ============================================================
# 发布版本
# ============================================================
def publish_version(client_id, client_secret, access_token, params):
    """发布版本 (POST /resource/v1/app/upd)"""
    data = api_call(
        OPPO_APP_UPD, client_id, client_secret, access_token,
        params, method="POST",
    )
    check_errno(data, "发布版本")
    success = data.get("data", {}).get("success", False)
    if success:
        log("发布版本提交成功!", "OK")
    return data
