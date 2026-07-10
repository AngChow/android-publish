# android-publish

> 一个 [Codex](https://github.com/openai/codex) Skill，Android 应用发布全流程自动化：预检查(签名+版本号) -> 打包 -> Bugly 符号表上传 -> 多渠道上传提审 -> Git 打 tag。支持应用宝/小米/华为/OPPO/vivo 五大应用市场。

## 安装

对 CodeX 说：

**帮我安装 [AngChow/android-publish](https://github.com/AngChow/android-publish) 这个 skill 及相关库**

CodeX 会自动通过 Skill Installer 拉取仓库、安装 Python 依赖。Bugly 符号表工具已内置在 `tools/buglyqq-upload-symbol.jar`，无需额外下载。

## 快速开始

配置好 `.publish_env`（见 [配置](#配置)）后，对 CodeX 说：

**[$android-publish](https://github.com/AngChow/android-publish/blob/main/SKILL.md) 打包提审当前项目**

CodeX 会自动完成：预检查 -> 打包 -> Bugly 符号表上传 -> 多渠道上传提审 -> Git 打 tag。

## 支持渠道

| 渠道 | 标识 | API 文档 | 签名方式 |
|------|------|---------|---------|
| 腾讯应用宝 | `yyb` | [文档](https://wikinew.open.qq.com/index.html#/iwiki/4015262492) | HmacSHA256 |
| 小米应用商店 | `xiaomi` | [文档](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1134) | RSA (X.509 证书加密) |
| 华为应用市场 | `huawei` | [文档](https://developer.huawei.com/consumer/cn/doc/AppGallery-connect-References/agcapi-app-submit-0000001158245061) | OAuth2 (API Client) |
| OPPO 应用市场 | `oppo` | [文档](https://open.oppomobile.com/documentation/page/info?id=10998) | HmacSHA256 |
| vivo 应用市场 | `vivo` | [文档](https://dev.vivo.com.cn/documentCenter/doc/327) | HmacSHA256 |

## 功能概览

| 脚本 | 能力 | 风险 |
|------|------|:---:|
| `pre_check.py` | 预检查: 签名配置 + 版本号 | 只读 |
| `build_and_submit.py` | 打包 + 多渠道上传提审一条龙 | 写线上 |
| `submit_apk.py` | 应用宝 APK 上传 + 提审 | 写线上 |
| `mi_submit.py` | 小米 APK 上传 + 提审 | 写线上 |
| `hw_submit.py` | 华为 APK 上传 + 提审 | 写线上 |
| `oppo_submit.py` | OPPO APK 上传 + 提审 | 写线上 |
| `vivo_submit.py` | vivo APK 上传 + 提审 | 写线上 |
| `query_app_detail.py` | 应用宝查询应用详情 | 只读 |
| `query_status.py` | 应用宝查询审核状态 | 只读 |
| `mi_query.py` | 小米查询应用信息 | 只读 |
| `hw_query.py` | 华为查询应用信息 | 只读 |
| `oppo_query.py` | OPPO 查询应用详情 | 只读 |
| `vivo_query.py` | vivo 查询应用详情 | 只读 |

## 配置

### 1. 创建 `.publish_env`

在 Android 项目根目录创建 `.publish_env`（**务必加入 `.gitignore`**），按需填写各渠道凭据：

```bash
# ===== 腾讯应用宝 =====
YYB_USER_ID="开发者UserID"
YYB_ACCESS_SECRET="access_secret"
YYB_APP_ID="应用ID"
YYB_PKG_NAME="应用包名"

# ===== 小米应用商店 =====
MI_USER_NAME="开发者登录邮箱"
MI_PRIVATE_KEY="私钥"
MI_CERT_PATH="/path/to/dev.api.public.cer"
MI_PKG_NAME="应用包名"           # 可省略，默认用 YYB_PKG_NAME
MI_APP_NAME="应用名称"
MI_PRIVACY_URL=""               # 更新时可不填
MI_ICON_PATH=""                 # 更新时可不填

# ===== 华为应用市场 =====
HW_CLIENT_ID="API Client ID"
HW_CLIENT_SECRET="API Client Secret"
HW_APP_ID="应用ID"              # AppGallery Connect 中的应用 ID

# ===== OPPO 应用市场 =====
OPPO_CLIENT_ID="OPPO 开放平台 Client ID"
OPPO_CLIENT_SECRET="OPPO 开放平台 Client Secret"
OPPO_PKG_NAME="应用包名"        # 可省略，默认用 YYB_PKG_NAME

# ===== vivo 应用市场 =====
VIVO_ACCESS_KEY="vivo 开放平台 Access Key"
VIVO_ACCESS_SECRET="vivo 开放平台 Access Secret"
VIVO_PKG_NAME="应用包名"        # 可省略，默认用 YYB_PKG_NAME

# ===== Bugly 符号表（可选） =====
BUGLY_APP_ID="Bugly 应用 ID"
BUGLY_APP_KEY="Bugly 应用 Key"
```

只需配置你要发布的渠道对应的凭据即可，`build_and_submit.py --store all` 会自动检测已配置的渠道。

### 2. 小米公钥证书

小米渠道需要将公钥证书文件（`dev.api.public.cer`）放在项目根目录，并加入 `.gitignore`：
（或让 CodeX 帮你加入 `.gitignore`）

### 3. 运行环境

| 依赖 | 说明 |
|------|------|
| Python 3.8+ | 脚本运行环境 |
| requests | HTTP 库 |
| pycryptodome | 小米 RSA 加密 |
| cryptography | 小米 X.509 证书解析 |
| Java / Android SDK | 打包流程依赖 |
| gradlew | 项目根目录的 Gradle Wrapper |

## 使用方法

### 打包提审

对 CodeX 说：

- **全渠道提审**：帮我打包提审当前项目
- **指定渠道**：帮我提审到小米（可替换为华为 / OPPO / vivo / 应用宝）
- **跳过打包**：帮我提审当前项目，跳过打包直接用已有 APK
- **仅上传不提审**（仅应用宝）：帮我上传 APK 到应用宝，先不提审
- **自定义文案**：帮我打包提审，更新文案写"新增 XX 功能"

CodeX 会自动执行预检查、打包、Bugly 符号表上传、多渠道提审、Git 打 tag 全流程。

### 单渠道操作

对 CodeX 说：

| 渠道 | 提审 | 查询 |
|------|------|------|
| 应用宝 | 帮我把 APK 提审到应用宝 | 帮我查应用宝审核状态 / 应用详情 |
| 小米 | 帮我把 APK 提审到小米 | 帮我查小米应用信息 |
| 华为 | 帮我把 APK 提审到华为 | 帮我查华为应用信息 |
| OPPO | 帮我把 APK 提审到 OPPO | 帮我查 OPPO 应用详情 |
| vivo | 帮我把 APK 提审到 vivo | 帮我查 vivo 应用详情 |

### 安全锁

提审是写线上操作，CodeX 会在执行前要求你明确确认。底层通过命令行 `--i-know-this-submits-to-production` + 环境变量双重校验，你只需在对话中确认即可。

## 各渠道特点

### 应用宝
- 上传和提审分离，支持 dry-run（仅上传不提审）
- 更新时可只传 64 位包，保留线上 32 位包
- API 限制：上传 100 次/天，更新 50 次/天
- 审核状态：1=审核中, 2=驳回, 3=通过, 8=撤销

### vivo
- 流程：计算 MD5 -> 上传 APK -> 应用更新（提审）
- 签名方式和应用宝相同（HmacSHA256），timestamp 为毫秒级
- 更新接口必填字段少，自动查询复用 compatibleDevice
- 正式环境限制：50 次/天/接口

### OPPO
- 流程：Token -> 查询现有信息 -> 上传 APK -> 发布版本（复用现有字段）
- 签名方式和应用宝相同（HmacSHA256）
- 发布接口字段多，但自动从查询结果复用，用户只需 APK + 更新说明
- 无 dry-run 模式

### 华为
- 流程：Token -> 上传 OBS -> 更新文件信息 -> 等 2 分钟 -> 提交
- 使用 v2 API（Android），团队级凭据可跨应用通用
- 文档要求传包后等 2 分钟再提交
- 无 API 调用次数限制

### 小米
- 上传即提审，无 dry-run 模式
- 更新只需 APK + updateDesc + appName + packageName
- 不传 icon / privacyUrl 不会覆盖线上已有值
- 无 API 调用次数限制
- push 成功后如需撤回，在小米开放平台手动操作

## 文件结构

```
~/.codex/skills/android-publish/
├── SKILL.md                 # Skill 描述和执行流程
├── README.md                # 本文档
├── .gitignore
├── requirements.txt         # Python 依赖
├── tools/
│   └── buglyqq-upload-symbol.jar  # Bugly 符号表上传工具
└── scripts/
    ├── _yyb_common.py       # 应用宝公共模块（签名、API 封装）
    ├── _mi_common.py        # 小米公共模块（RSA 加密、SIG 生成）
    ├── _hw_common.py        # 华为公共模块
    ├── _oppo_common.py      # OPPO 公共模块
    ├── _vivo_common.py      # vivo 公共模块
    ├── build_and_submit.py  # 多渠道打包提审一条龙
    ├── pre_check.py         # 预检查（签名配置 + 版本号）
    ├── upload_bugly_symbol.py  # Bugly 符号表上传
    ├── git_tag.py           # Git 打 tag
    ├── submit_apk.py        # 应用宝上传提审
    ├── mi_submit.py         # 小米上传提审
    ├── hw_submit.py         # 华为上传提审
    ├── oppo_submit.py       # OPPO 上传提审
    ├── vivo_submit.py       # vivo 上传提审
    ├── query_app_detail.py  # 应用宝查询详情
    ├── query_status.py      # 应用宝查询审核状态
    ├── mi_query.py          # 小米查询应用信息
    ├── hw_query.py          # 华为查询应用信息
    ├── oppo_query.py        # OPPO 查询应用详情
    └── vivo_query.py        # vivo 查询应用详情
```

## License

MIT
