"""
android-publish skill - 华为应用市场 (Android) 公共模块
集中处理: 凭据加载、Token 获取、上传地址、文件上传、文件信息更新、提交发布

华为 AGC Publishing API (Android v2):
  https://developer.huawei.com/consumer/cn/doc/AppGallery-connect-References/agcapi-app-submit-0000001158245061

API 基地址: https://connect-api.cloud.huawei.com
认证方式: API Client (client_id + client_secret -> access_token)
"""

import os
import sys
import json
import hashlib
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _yyb_common import log, load_env  # noqa: E402

# ============================================================
# 常量
# ============================================================
HW_API_BASE = "https://connect-api.cloud.huawei.com"

HW_TOKEN_URL = f"{HW_API_BASE}/api/oauth2/v1/token"
HW_APP_INFO_URL = f"{HW_API_BASE}/api/publish/v2/app-info"
HW_UPLOAD_URL = f"{HW_API_BASE}/api/publish/v2/upload-url/for-obs"
HW_FILE_INFO_URL = f"{HW_API_BASE}/api/publish/v2/app-file-info"
HW_SUBMIT_URL = f"{HW_API_BASE}/api/publish/v2/app-submit"


# ============================================================
# 凭据
# ============================================================
def get_hw_credentials():
    """返回 (client_id, client_secret, app_id)"""
    client_id = os.environ.get("HW_CLIENT_ID", "")
    client_secret = os.environ.get("HW_CLIENT_SECRET", "")
    app_id = os.environ.get("HW_APP_ID", "")
    missing = [k for k, v in {
        "HW_CLIENT_ID": client_id,
        "HW_CLIENT_SECRET": client_secret,
        "HW_APP_ID": app_id,
    }.items() if not v]
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "ERROR")
        log("请在 .publish_env 中配置华为应用市场凭据", "ERROR")
        sys.exit(1)
    return client_id, client_secret, app_id


def bootstrap_hw(project_root=None):
    """一站式入口：加载 .publish_env -> 校验凭据 -> 获取 Token -> 返回 headers"""
    load_env(project_root)
    client_id, client_secret, app_id = get_hw_credentials()

    log("正在获取 AGC Access Token...", "STEP")
    resp = requests.post(
        HW_TOKEN_URL,
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"获取 Token 失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        log(f"Token 响应缺少 access_token: {data}", "ERROR")
        sys.exit(1)
    log("Token 获取成功", "OK")

    headers = {
        "client_id": client_id,
        "Authorization": f"Bearer {token}",
    }
    return client_id, app_id, headers


# ============================================================
# 查询应用信息
# ============================================================
def query_app_info(client_id, app_id, headers, lang="zh-CN"):
    """查询应用信息 (GET /api/publish/v2/app-info)"""
    resp = requests.get(
        HW_APP_INFO_URL,
        params={"appId": app_id, "lang": lang},
        headers=headers,
        timeout=30,
    )
    return resp.json()


# ============================================================
# 文件上传
# ============================================================
def get_file_sha256(file_path):
    """计算文件 SHA256 (小写 hex)"""
    log(f"正在计算 SHA256: {os.path.basename(file_path)}", "STEP")
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(8 * 1024 * 1024)
            if not data:
                break
            sha256.update(data)
    result = sha256.hexdigest()
    log(f"SHA256: {result}", "OK")
    return result


def get_upload_url(app_id, headers, file_path, sha256, file_size):
    """获取 OBS 上传地址 (GET /api/publish/v2/upload-url/for-obs)"""
    log("正在获取上传地址...", "STEP")
    params = {
        "appId": app_id,
        "fileName": os.path.basename(file_path),
        "sha256": sha256,
        "contentLength": str(file_size),
    }
    resp = requests.get(HW_UPLOAD_URL, params=params, headers=headers, timeout=30)
    if resp.status_code != 200:
        log(f"获取上传地址失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    data = resp.json()
    ret = data.get("ret", {})
    if ret.get("code") != 0:
        log(f"获取上传地址失败: {ret}", "ERROR")
        sys.exit(1)
    log("上传地址获取成功", "OK")
    return data


def upload_to_obs(upload_info, file_path, file_size):
    """上传文件到 OBS"""
    log(f"正在上传到 OBS ({file_size / 1024 / 1024:.1f} MB)...", "STEP")
    url_info = upload_info.get("urlInfo", upload_info)
    obs_url = url_info.get("url", "")
    method = (url_info.get("method") or "PUT").upper()
    obs_headers = dict(url_info.get("headers") or {})
    object_id = url_info.get("objectId", "")

    if not obs_url:
        log(f"上传地址为空: {json.dumps(upload_info, ensure_ascii=False)[:500]}", "ERROR")
        sys.exit(1)

    if not any(k.lower() == "content-type" for k in obs_headers):
        obs_headers["Content-Type"] = "application/octet-stream"
    obs_headers["Content-Length"] = str(file_size)

    with open(file_path, "rb") as f:
        resp = requests.request(method, obs_url, data=f, headers=obs_headers, timeout=900)

    if resp.status_code not in (200, 201, 204):
        log(f"OBS 上传失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    log(f"OBS 上传成功 (objectId: {object_id})", "OK")
    return object_id


def update_file_info(app_id, headers, file_name, object_id):
    """更新应用文件信息 (PUT /api/publish/v2/app-file-info, fileType=5 软件包)"""
    log("正在更新应用文件信息...", "STEP")
    body = {
        "fileType": 5,  # 5 = 软件包 (APK/RPK/AAB)
        "files": {
            "fileName": file_name,
            "fileDestUrl": object_id,
        },
    }
    resp = requests.put(
        HW_FILE_INFO_URL,
        params={"appId": app_id},
        json=body,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"更新文件信息失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        sys.exit(1)
    data = resp.json()
    ret = data.get("ret", {})
    if ret.get("code") != 0:
        log(f"更新文件信息失败: {ret}", "ERROR")
        sys.exit(1)
    pkg_version = data.get("pkgVersion", [])
    log(f"文件信息更新成功 (pkgVersion: {pkg_version})", "OK")
    return data


# ============================================================
# 更新语言信息 (设置用户可见的新版本简介)
# ============================================================
HW_LANG_INFO_URL = f"{HW_API_BASE}/api/publish/v2/app-language-info"


def update_language_info(app_id, headers, lang, new_features):
    """更新应用语言信息 (PUT /api/publish/v2/app-language-info)
    设置用户可见的新版本简介 (newFeatures)。
    """
    log(f"正在更新语言信息 ({lang}) newFeatures...", "STEP")
    body = {"lang": lang, "newFeatures": new_features}
    resp = requests.put(
        HW_LANG_INFO_URL,
        params={"appId": app_id},
        json=body,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"更新语言信息失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        return False
    data = resp.json()
    ret = data.get("ret", {})
    if ret.get("code") == 0:
        log(f"语言信息更新成功 (newFeatures: {new_features[:30]}...)", "OK")
        return True
    else:
        log(f"更新语言信息失败: {ret}", "ERROR")
        return False


# ============================================================
# 提交发布
# ============================================================
def submit_app(app_id, headers, remark=""):
    """提交发布 (POST /api/publish/v2/app-submit)"""
    log("正在提交发布...", "STEP")
    params = {"appId": app_id}
    if remark:
        params["remark"] = remark

    resp = requests.post(
        HW_SUBMIT_URL,
        params=params,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"提交发布失败: HTTP {resp.status_code}", "ERROR")
        log(f"响应: {resp.text[:500]}", "ERROR")
        return False

    data = resp.json()
    ret = data.get("ret", {})
    if ret.get("code") == 0:
        log("提交发布成功!", "OK")
        return True
    else:
        log(f"提交发布失败: {ret}", "ERROR")
        return False
