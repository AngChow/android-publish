---
name: android-publish
description: "Android 应用打包提审全流程自动化：打 Release 包并提交到应用宝/小米/华为/OPPO/vivo 五大应用市场审核，含预检查(签名+版本号)、Bugly 符号表上传、Git 打 tag。触发词：打包提审、出包、上架、发布应用、多渠道提审、Android 打包发布、build and publish、build and submit。"
---

# Android 应用发布 Skill

打 Release 包并提交到应用宝/小米/华为/OPPO/vivo 五大应用市场审核，端到端自动化。

## 执行指令

当用户要求"打包提审"（或"出包"/"上架"/"发布应用"/"多渠道提审"等）时：

1. **确认更新文案**：如用户未指定，使用默认值"修复已知问题，优化用户体验"，或询问用户
2. **执行一条龙命令**：
   ```bash
   PUBLISH_CONFIRM_SUBMIT=YES python3 ~/.codex/skills/android-publish/scripts/build_and_submit.py \
       --i-know-this-submits-to-production \
       --update-desc "<更新文案>" \
       <项目根目录>
   ```
3. **监控输出**：脚本自动完成全部步骤（预检查 -> 打包 -> Bugly -> 多渠道提审 -> Git tag），无需人工干预
4. **报告结果**：汇总各渠道成功/失败状态给用户
5. **异常处理**：预检查失败（签名/版本号）则停止并告知用户具体原因；某渠道失败不影响其他渠道

### 仅打包不提审（dry-run）

仅应用宝支持 dry-run（上传不提审），小米/华为/OPPO/vivo 上传即提审，dry-run 时自动跳过：

```bash
python3 ~/.codex/skills/android-publish/scripts/build_and_submit.py \
    --dry-run --store yyb \
    <项目根目录>
```

### 指定单渠道

```bash
PUBLISH_CONFIRM_SUBMIT=YES python3 ~/.codex/skills/android-publish/scripts/build_and_submit.py \
    --store yyb|xiaomi|huawei|oppo|vivo \
    --i-know-this-submits-to-production \
    --update-desc "<更新文案>" \
    <项目根目录>
```

### 跳过步骤

- `--skip-build`：跳过打包，直接用已有 APK
- `--skip-bugly`：跳过 Bugly 符号表上传
- `--skip-git`：跳过 Git 打 tag
- `--skip-check`：跳过预检查

## 自动化流程

| 步骤 | 脚本 | 说明 |
|------|------|------|
| Step 0 预检查 | `pre_check.py` | 检查 release 签名配置为 `signingConfigs.release` + 本地 versionCode > 线上版本号 |
| Step 1 打包 | `./gradlew clean assembleRelease` | 定位 `app-arm64-v8a-release.apk`（只上传 64 位包） |
| Step 1.5 Bugly | `upload_bugly_symbol.py` | 上传 mapping.txt（非阻塞，失败不影响提审） |
| Step 2 多渠道提审 | 各渠道 `*_submit.py` | 依次上传到已配置凭据的渠道，独立安全锁 |
| Step 3 Git tag | `git_tag.py` | 全部成功后，合并到 master + 创建版本 tag + 推送 |

## 支持渠道

| 渠道 | 标识 | 签名方式 | dry-run | API 限制 |
|------|------|---------|---------|---------|
| 腾讯应用宝 | `yyb` | HmacSHA256 | 支持 | 上传 100 次/天，更新 50 次/天 |
| 小米应用商店 | `xiaomi` | RSA (X.509 证书) | 不支持（上传即提审） | 无 |
| 华为应用市场 | `huawei` | OAuth2 (API Client) | 不支持 | 无 |
| OPPO 应用市场 | `oppo` | HmacSHA256 | 不支持 | 50 次/天/接口 |
| vivo 应用市场 | `vivo` | HmacSHA256 | 不支持 | 50 次/天/接口 |

所有渠道支持中文更新文案，`--update-desc` 统一传入。华为额外设置用户可见的 `newFeatures` 字段。

## 安全锁

提审是写线上操作，必须同时满足：
- 命令行带 `--i-know-this-submits-to-production`
- 环境变量 `PUBLISH_CONFIRM_SUBMIT=YES`（多渠道）或对应渠道变量

`build_and_submit.py` 在 `--confirm` 时自动为各子进程设置对应环境变量，所以只需设 `PUBLISH_CONFIRM_SUBMIT=YES`。

## 各渠道特点

- **应用宝**：上传和提审分离，支持 dry-run。限制 100 次/天上传、50 次/天更新。
- **小米**：上传即提审，更新只需 APK + updateDesc。无 API 限制。
- **华为**：Token -> 上传 OBS -> 更新文件信息 -> 更新语言信息(更新文案) -> 等 2 分钟 -> 提交。团队级凭据跨应用通用。
- **OPPO**：发布接口字段多，但自动从查询结果复用现有值。限制 50 次/天/接口。
- **vivo**：上传 APK 返回流水号+versionCode，更新接口必填字段少。限制 50 次/天/接口。

## 前置条件

1. 各应用商店已接入应用并成功发布上线
2. 项目根目录有 `.publish_env`（已被 `.gitignore`），包含各渠道凭据
3. 小米公钥证书文件放在项目根目录，已加入 `.gitignore`
4. 本机有 Python 3.8+、`requests`、`pycryptodome`、`cryptography`
5. 项目根目录有 `gradlew`，已配置 Java / Android SDK

## 单渠道操作

各渠道支持独立查询和提审，详见 README.md。

## Bugly 符号表

打包后自动上传 `mapping.txt` 到 Bugly（非阻塞），确保线上崩溃堆栈可还原。jar 工具内置在 skill 的 `tools/` 目录，凭据从 `.publish_env` 读取（`BUGLY_APP_ID` / `BUGLY_APP_KEY`）。
