"""
android-publish skill - vivo 应用市场公共模块
集中处理: 凭据加载、HmacSHA256 签名、文件上传、API 封装

vivo 开放平台 API 文档:
  https://dev.vivo.com.cn/documentCenter/doc/327

API 基地址: https://developer-api.vivo.com.cn/router/rest
所有接口共用同一个 URL，通过 method 参数区分。
认证方式: access_key + access_secret，签名 HmacSHA256（timestamp 为毫秒级）。
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
VIVO_API_BASE = "https://developer-api.vivo.com.cn/router/rest"


# ============================================================
# 凭据
# ============================================================
def get_vivo_credentials():
    """返回 (access_key, access_secret, pkg_name)"""
    access_key = os.environ.get("VIVO_ACCESS_KEY", "")
    access_secret = os.environ.get("VIVO_ACCESS_SECRET", "")
    pkg_name = os.environ.get("VIVO_PKG_NAME", "") or os.environ.get("YYB_PKG_NAME", "")
    missing = [k for k, v in {
        "VIVO_ACCESS_KEY": access_key,
        "VIVO_ACCESS_SECRET": access_secret,
    }.items() if not v]
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "ERROR")
        log("请在 .publish_env 中配置 vivo 应用市场凭据", "ERROR")
        sys.exit(1)
    if not pkg_name:
        log("缺少 VIVO_PKG_NAME 或 YYB_PKG_NAME", "ERROR")
        sys.exit(1)
    return access_key, access_secret, pkg_name


def bootstrap_vivo(project_root=None):
    """加载 .publish_env -> 校验凭据
    返回 (access_key, access_secret, pkg_name)
    """
    load_env(project_root)
    return get_vivo_credentials()


# ============================================================
# 签名 (HmacSHA256，timestamp 为毫秒级)
# ============================================================
def cal_sign(access_secret, params):
    """HmacSHA256 签名: 参数按 ASCII 升序拼接 k1=v1&k2=v2，HmacSHA256(key=access_secret)"""
    filtered = {k: v for k, v in params.items() if v is not None}
    sorted_keys = sorted(filtered.keys())
    sign_str = "&".join(f"{k}={filtered[k]}" for k in sorted_keys)
    h = hmac.new(
        key=access_secret.encode("utf-8"),
        msg=sign_str.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return h.hexdigest()


def build_common_params(access_key, method):
    """构建公共参数"""
    return {
        "method": method,
        "access_key": access_key,
        "timestamp": str(int(time.time() * 1000)),  # 毫秒级
        "format": "json",
        "v": "1.0",
        "sign_method": "hmac",
        "target_app_key": "developer",
    }


# ============================================================
# API 调用
# ============================================================
def api_call(access_key, access_secret, method, business_params, timeout=60):
    """
    调用 vivo API (POST application/x-www-form-urlencoded)。
    所有接口共用同一个 URL，通过 method 参数区分。
    """
    params = build_common_params(access_key, method)
    params.update(business_params)

    sign = cal_sign(access_secret, params)
    params["sign"] = sign

    body = urlencode(params)
    log(f"POST {VIVO_API_BASE} (method={method})", "INFO")
    resp = requests.post(
        VIVO_API_BASE,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )

    if resp.status_code != 200:
        log(f"HTTP {resp.status_code}: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    return resp.json()


def check_code(data, context=""):
    """检查 code 是否为 0，subCode 是否为 0"""
    code = data.get("code", -1)
    sub_code = data.get("subCode", "")
    msg = data.get("msg", "")
    if code != 0:
        log(f"{context}失败: code={code}, msg={msg}", "ERROR")
        sys.exit(1)
    if sub_code and str(sub_code) != "0":
        log(f"{context}业务失败: subCode={sub_code}, msg={msg}", "ERROR")
        sys.exit(1)
    return data


# ============================================================
# 文件上传 (multipart/form-data，file 不参与签名)
# ============================================================
def upload_file(access_key, access_secret, method, pkg_name, file_path, extra_params=None):
    """
    上传文件到 vivo (POST multipart/form-data)。
    file 参数不参与签名，其余参数正常签名。
    """
    file_size = os.path.getsize(file_path)
    log(f"正在上传文件 ({file_size / 1024 / 1024:.1f} MB)...", "STEP")

    # 构建除 file 外的所有参数
    params = build_common_params(access_key, method)
    params["packageName"] = pkg_name
    if extra_params:
        params.update(extra_params)

    # 签名 (不含 file)
    sign = cal_sign(access_secret, params)
    params["sign"] = sign

    # 上传
    with open(file_path, "rb") as f:
        resp = requests.post(
            VIVO_API_BASE,
            data=params,
            files={"file": (os.path.basename(file_path), f)},
            timeout=900,
        )

    if resp.status_code != 200:
        log(f"文件上传失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)

    data = resp.json()
    check_code(data, "文件上传")
    result = data.get("data", {})
    log(f"文件上传成功: serialnumber={result.get('serialnumber', '')[:16]}...", "OK")
    return result


def upload_apk(access_key, access_secret, pkg_name, apk_path, file_md5):
    """上传 APK 文件，返回 (serialnumber, versionCode, versionName)"""
    result = upload_file(
        access_key, access_secret, "app.upload.apk.app",
        pkg_name, apk_path,
        extra_params={"fileMd5": file_md5},
    )
    return (
        result.get("serialnumber", ""),
        result.get("versionCode", ""),
        result.get("versionName", ""),
    )


# ============================================================
# 查询应用详情
# ============================================================
def query_app_details(access_key, access_secret, pkg_name):
    """查询应用详情 (method=app.query.details)"""
    data = api_call(access_key, access_secret, "app.query.details", {"packageName": pkg_name})
    check_code(data, "查询应用详情")
    return data.get("data", {})


# ============================================================
# 应用更新
# ============================================================
def update_app(access_key, access_secret, params):
    """应用同步更新 (method=app.sync.update.app)"""
    data = api_call(access_key, access_secret, "app.sync.update.app", params, timeout=60)
    check_code(data, "应用更新")
    return data


# ============================================================
# MD5
# ============================================================
def calc_md5(file_path):
    """计算文件 MD5 (小写 hex)"""
    import hashlib
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(8 * 1024 * 1024)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()
