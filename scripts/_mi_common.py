"""
android-publish skill - 小米应用商店公共模块
集中处理: 凭据加载、RSA 加密签名、SIG 生成、HTTP 请求封装

小米应用商店 API 文档:
  https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1134

API 基地址: https://api.developer.xiaomi.com/devupload
签名方式: RSA 加密 (PKCS1_v1_5) 使用 X.509 证书公钥
"""

import os
import sys
import json
import hashlib
from pathlib import Path

import requests
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives._serialization import Encoding, PublicFormat

# 复用应用宝公共模块的 env 加载和日志
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _yyb_common import log, load_env  # noqa: E402

# ============================================================
# 常量
# ============================================================
MI_API_BASE = "https://api.developer.xiaomi.com/devupload"

MI_QUERY = "/dev/query"
MI_CATEGORY = "/dev/category"
MI_PUSH = "/dev/push"

# RSA 加密参数 (X.509 证书, 1024 bit key)
GROUP_SIZE = 128
ENCRYPT_GROUP_SIZE = GROUP_SIZE - 11  # PKCS1 padding 占 11 字节


# ============================================================
# 凭据
# ============================================================
def get_mi_credentials():
    """返回 (user_name, private_key, cert_path, pkg_name, app_name, privacy_url, icon_path)"""
    user_name = os.environ.get("MI_USER_NAME", "")
    private_key = os.environ.get("MI_PRIVATE_KEY", "")
    cert_path = os.environ.get("MI_CERT_PATH", "")
    pkg_name = os.environ.get("MI_PKG_NAME", "") or os.environ.get("YYB_PKG_NAME", "")
    app_name = os.environ.get("MI_APP_NAME", "")
    privacy_url = os.environ.get("MI_PRIVACY_URL", "")
    icon_path = os.environ.get("MI_ICON_PATH", "")

    missing = []
    if not user_name:
        missing.append("MI_USER_NAME")
    if not private_key:
        missing.append("MI_PRIVATE_KEY")
    if not cert_path:
        missing.append("MI_CERT_PATH")
    if not pkg_name:
        missing.append("MI_PKG_NAME")
    if missing:
        log(f"缺少环境变量: {', '.join(missing)}", "ERROR")
        log("请在 .publish_env 中配置小米应用商店凭据", "ERROR")
        sys.exit(1)
    return user_name, private_key, cert_path, pkg_name, app_name, privacy_url, icon_path


def bootstrap_mi(project_root=None):
    """一站式入口：加载 .publish_env -> 校验小米凭据"""
    load_env(project_root)
    return get_mi_credentials()


# ============================================================
# RSA 加密
# ============================================================
def encrypt_by_public_key(param, cert_path):
    """
    使用 X.509 证书中的公钥对字符串进行 RSA 加密 (PKCS1_v1_5)。
    分段加密，返回 hex 字符串。
    """
    with open(cert_path, "rb") as f:
        buff = f.read()
    cert_obj = load_pem_x509_certificate(buff, default_backend())
    public_key = cert_obj.public_key()
    pk = public_key.public_bytes(encoding=Encoding.PEM, format=PublicFormat.PKCS1)
    cipher = PKCS1_v1_5.new(RSA.importKey(pk))

    text_bytes = param.encode("UTF-8")
    text_len = len(text_bytes)
    idx = 0
    encrypt_bytes = bytearray()

    while idx < text_len:
        remain = text_len - idx
        segsize = min(remain, ENCRYPT_GROUP_SIZE)
        segment = bytes(text_bytes[idx:idx + segsize])
        encrypt_bytes += cipher.encrypt(segment)
        idx += segsize

    return encrypt_bytes.hex()


# ============================================================
# MD5
# ============================================================
def md5_string(s):
    """计算字符串的 MD5 (32 位小写 hex)"""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def md5_file(file_path):
    """计算文件的 MD5 (32 位小写 hex)，分块读取"""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(8 * 1024 * 1024)
            if not data:
                break
            md5.update(data)
    return md5.hexdigest()


# ============================================================
# SIG 生成
# ============================================================
def generate_sig(request_data_json, file_items, private_key, cert_path):
    """
    生成加密签名 SIG。

    参数:
      request_data_json: RequestData 的 JSON 字符串
      file_items: list of (name, file_path) 元组，如 [("apk", "/path/to.apk"), ("icon", "/path/to.png")]
      private_key: 私钥（或账号密码）
      cert_path: X.509 证书路径

    返回: 加密后的 hex 字符串
    """
    sig_list = [{"name": "RequestData", "hash": md5_string(request_data_json)}]

    for name, file_path in file_items:
        if file_path and os.path.isfile(file_path):
            log(f"  计算 MD5: {name} ({os.path.basename(file_path)})", "INFO")
            sig_list.append({"name": name, "hash": md5_file(file_path)})

    sig_json = {"sig": sig_list, "password": private_key}
    sig_str = json.dumps(sig_json)

    log("正在生成 RSA 签名...", "STEP")
    encrypted = encrypt_by_public_key(sig_str, cert_path)
    log("签名生成完成", "OK")
    return encrypted


# ============================================================
# HTTP 请求
# ============================================================
def mi_query(user_name, private_key, cert_path, pkg_name):
    """查询应用信息 (POST /dev/query)"""
    request_data = {"packageName": pkg_name, "userName": user_name}
    request_data_json = json.dumps(request_data)
    sig = generate_sig(request_data_json, [], private_key, cert_path)

    log(f"POST {MI_QUERY}", "INFO")
    resp = requests.post(
        MI_API_BASE + MI_QUERY,
        data={"RequestData": request_data_json, "SIG": sig},
        timeout=30,
    )
    return resp.json()


def mi_push(user_name, private_key, cert_path, pkg_name, app_name,
            apk_path, update_desc, privacy_url=None, icon_path=None,
            test_account=None, online_time=None):
    """
    推送应用到小米应用商店 (POST /dev/push)，synchroType=1 (更新包)。

    最小参数: user_name, private_key, cert_path, pkg_name, app_name, apk_path, update_desc
    可选参数: privacy_url, icon_path, test_account, online_time

    只有显式传入的字段才会发送，未传入的字段不会覆盖线上已有值。
    """
    # 构建 appInfo - 只包含实际提供的字段
    app_info = {
        "appName": app_name,
        "packageName": pkg_name,
        "updateDesc": update_desc,
    }
    if privacy_url:
        app_info["privacyUrl"] = privacy_url
    if test_account:
        app_info["testAccount"] = test_account
    if online_time:
        app_info["onlineTime"] = online_time

    request_data = {
        "userName": user_name,
        "appInfo": json.dumps(app_info),
        "synchroType": 1,
    }
    request_data_json = json.dumps(request_data)

    # 文件列表 (用于 SIG 计算) - 只包含实际存在的文件
    file_items = [("apk", apk_path)]
    if icon_path:
        file_items.append(("icon", icon_path))

    sig = generate_sig(request_data_json, file_items, private_key, cert_path)

    # 构建 multipart 请求
    files = {}
    if apk_path and os.path.isfile(apk_path):
        files["apk"] = (os.path.basename(apk_path), open(apk_path, "rb"))
    if icon_path and os.path.isfile(icon_path):
        files["icon"] = (os.path.basename(icon_path), open(icon_path, "rb"))

    log(f"POST {MI_PUSH}", "INFO")
    log(f"正在上传到小米应用商店...", "STEP")
    resp = requests.post(
        MI_API_BASE + MI_PUSH,
        data={"RequestData": request_data_json, "SIG": sig},
        files=files,
        timeout=900,
    )

    for _, fobj in files.values():
        fobj.close()

    return resp.json()
