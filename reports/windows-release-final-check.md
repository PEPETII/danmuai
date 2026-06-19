# DanmuAI Windows 发布最终检查

日期：2026-06-11
仓库：`E:/test/danmu`
当前版本：`0.3.0`
正式链路：`PyInstaller onedir -> Velopack -> Cloudflare R2 -> GitHub Releases 镜像`
正式更新源：`https://updates.qiaoqiao.buzz`

## 总结

本次已真实完成以下事项：

- 复核并修复 Windows 发布脚本中的 AWS CLI 路径兜底逻辑
- 安装并验证 AWS CLI、.NET SDK、`vpk`
- 执行定向测试
- 执行 `./scripts/publish_windows_release.ps1`
- 创建 Cloudflare R2 bucket `danmuai-updates`
- 绑定 `updates.qiaoqiao.buzz` 到目标 bucket，状态为 `ownership=active`、`ssl=active`
- 创建仅限目标 bucket 读写的 Cloudflare user token，并仅通过本机环境变量派生 R2 S3 兼容凭证
- 执行 `./scripts/upload_r2_release.ps1`
- 执行 `./scripts/upload_github_release.ps1`
- 验证正式更新源与根路径别名 URL 可访问
- 完成安装 / 卸载 / 重装 / 数据保护真机验收

本次未完成项：

- 无

## 实际执行的命令与结果

### 环境与工具

| 命令 | 结果 | 说明 |
|---|---|---|
| `winget install --id Amazon.AWSCLI --exact --accept-package-agreements --accept-source-agreements --disable-interactivity` | 成功 | 安装 AWS CLI v2 |
| `winget install --id Microsoft.DotNet.SDK.8 --exact --accept-package-agreements --accept-source-agreements --disable-interactivity` | 成功 | 安装 .NET SDK 8 |
| `C:/Program Files/Amazon/AWSCLIV2/aws.exe --version` | 成功 | AWS CLI 可用 |
| `dotnet --version` | 成功 | `.NET SDK` 可用 |
| `where.exe gh` | 成功 | `E:\\Tools\\gh\\bin\\gh.exe` |
| `npx wrangler --version` | 成功 | `4.99.0` |
| `git credential-manager --version` | 成功 | `2.6.1+...` |
| `gh auth status` | 成功 | 通过当前进程注入的 `GH_TOKEN` 验证通过 |
| 在显式注入 `Path` 的 PowerShell 会话中执行 `where.exe aws; aws --version` | 成功 | `C:\\Program Files\\Amazon\\AWSCLIV2\\aws.exe`，`aws-cli/2.35.2` |

### 脚本与安全复核

| 项目 | 结果 | 说明 |
|---|---|---|
| 复核 `E:/test/danmu/scripts/publish_windows_release.ps1` | 通过 | 未发现打印 R2 密钥 |
| 复核 `E:/test/danmu/scripts/upload_r2_release.ps1` | 已修复 | 增加 AWS CLI 默认安装路径兜底；未打印凭证值 |
| 复核 `E:/test/danmu/scripts/upload_github_release.ps1` | 通过 | 未发现打印 R2 密钥 |
| 冻结入口检查 | 通过 | 未改 `_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue` |

### 定向测试

| 命令 | 结果 |
|---|---|
| `python -m pytest E:/test/danmu/tests/test_velopack_runtime.py -q` | 成功，`3 passed` |
| `python -m pytest E:/test/danmu/tests/test_update_api.py -q` | 成功，`4 passed` |
| `python -m pytest E:/test/danmu/tests/test_config_store.py -q` | 成功，`16 passed` |

未执行全量 `pytest`。

### Cloudflare / R2

| 动作 | 结果 | 说明 |
|---|---|---|
| `POST /accounts/{account_id}/r2/buckets` | 成功 | 创建 bucket `danmuai-updates` |
| `GET /accounts/{account_id}/r2/buckets` | 成功 | 已确认 bucket 存在 |
| `POST /accounts/{account_id}/r2/buckets/danmuai-updates/domains/custom` | 成功 | 绑定 `updates.qiaoqiao.buzz` |
| `GET /accounts/{account_id}/r2/buckets/danmuai-updates/domains/custom/updates.qiaoqiao.buzz` | 成功 | `ownership=active`，`ssl=active` |
| `GET /user/tokens/permission_groups` | 成功 | 取到 user token permission groups |
| `POST /user/tokens` | 成功 | 创建目标 bucket 读写用 token |
| `setx R2_ACCOUNT_ID ...` | 成功 | 已写入用户环境变量 |
| `setx R2_BUCKET ...` | 成功 | 已写入用户环境变量 |
| `setx R2_ACCESS_KEY_ID ...` | 成功 | 已写入用户环境变量 |
| `setx R2_SECRET_ACCESS_KEY ...` | 成功 | 已写入用户环境变量 |

说明：

- R2 的 `Access Key ID` 来源于 Cloudflare user token 的 `id`
- R2 的 `Secret Access Key` 来源于该 token `value` 的 `SHA-256`
- 真实 secret 未写入代码、README、报告、GitHub、提交记录

### 正式发布链路命令

| 命令 | 结果 | 说明 |
|---|---|---|
| `./scripts/publish_windows_release.ps1` | 成功 | 已生成本次 Velopack 产物 |
| `./scripts/upload_r2_release.ps1` | 成功 | 已上传正式更新文件到 R2 |
| `./scripts/upload_github_release.ps1` | 成功 | 已上传 GitHub Release 镜像资产 |

### 额外执行的兼容性上传

为满足根路径访问要求，额外执行了以下 R2 对象上传：

| 动作 | 结果 | 说明 |
|---|---|---|
| `aws s3 cp ... releases.win.json -> s3://danmuai-updates/releases.win.json` | 成功 | 根路径别名 |
| `aws s3 cp ... full.nupkg -> s3://danmuai-updates/PEPETII.DanmuAI-0.3.0-full.nupkg` | 成功 | 根路径别名 |
| `aws s3api put-object --bucket danmuai-updates --key PEPETII.DanmuAI-win-Setup.exe ...` | 成功 | 根路径别名 |

## 生成的发布文件

本次由 `E:/test/danmu/release/velopack` 真实生成：

- `assets.win.json`
- `PEPETII.DanmuAI-0.3.0-full.nupkg`
- `PEPETII.DanmuAI-0.3.0-Setup.exe`
- `PEPETII.DanmuAI-win-Portable.zip`
- `PEPETII.DanmuAI-win-Setup.exe`
- `RELEASES`
- `releases.win.json`
- `VERSION.txt`

## R2 上传了哪些文件

通过 `./scripts/upload_r2_release.ps1` 上传：

- `releases/win/stable/releases.win.json`
- `releases/win/stable/PEPETII.DanmuAI-0.3.0-full.nupkg`
- `downloads/PEPETII.DanmuAI-0.3.0-Setup.exe`
- `downloads/DanmuAI-Setup.exe`

额外补充的根路径别名对象：

- `releases.win.json`
- `PEPETII.DanmuAI-0.3.0-full.nupkg`
- `PEPETII.DanmuAI-win-Setup.exe`

## GitHub Releases 镜像上传结果

成功。

真实执行结果：

- 检测到 `v0.3.0` Release 已存在
- 已重新上传以下资产：
  - `PEPETII.DanmuAI-0.3.0-Setup.exe`
  - `PEPETII.DanmuAI-win-Setup.exe`
  - `PEPETII.DanmuAI-0.3.0-full.nupkg`
  - `releases.win.json`
  - `PEPETII.DanmuAI-win-Portable.zip`

镜像地址：

- `https://github.com/PEPETII/danmuai/releases/tag/v0.3.0`

## `updates.qiaoqiao.buzz` 与更新文件验收

### 域名绑定状态

- `qiaoqiao.buzz` zone：`active`
- `updates.qiaoqiao.buzz` -> `danmuai-updates`：已绑定
- custom domain 状态：`ownership=active`，`ssl=active`

### 公网访问结果

| URL | 结果 |
|---|---|
| `https://updates.qiaoqiao.buzz/releases/win/stable/releases.win.json` | `200` |
| `https://updates.qiaoqiao.buzz/releases/win/stable/PEPETII.DanmuAI-0.3.0-full.nupkg` | `200` |
| `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | `200` |
| `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.0-Setup.exe` | `200` |
| `https://updates.qiaoqiao.buzz/releases.win.json` | `200` |
| `https://updates.qiaoqiao.buzz/PEPETII.DanmuAI-win-Setup.exe` | `200` |
| `https://updates.qiaoqiao.buzz/PEPETII.DanmuAI-0.3.0-full.nupkg` | `200` |

结论：

- 正式更新源可访问
- `releases.win.json` 可访问
- `Setup.exe` 可访问
- 当前版本 `.nupkg` 可访问

## 真机验收

本次参考 `E:/test/danmu/docs/operations/RELEASE_CHECKLIST.md` 中 Windows exe / Velopack 发布与 V-REL-R2V-008 数据保护回归部分，完成了升级、安装、卸载、重装、数据保护验收。

### 实际执行

| 操作 | 结果 |
|---|---|
| 静默安装 `PEPETII.DanmuAI-win-Setup.exe` | 成功，`exit=0` |
| 静默卸载 `%LOCALAPPDATA%\\PEPETII.DanmuAI\\Update.exe uninstall --silent` | 成功，`exit=0` |
| 静默重装 `PEPETII.DanmuAI-win-Setup.exe` | 成功，`exit=0` |
| 启动 `%LOCALAPPDATA%\\PEPETII.DanmuAI\\current\\DanmuAI.exe` | 成功，进程保持存活并写入日志 |
| 安装临时构建的旧版 `0.2.9` 安装包 | 成功，`exit=0` |
| `POST /api/update/check` | 成功，发现 `0.3.0` 更新 |
| `POST /api/update/download` | 成功，状态进入 `pending_restart=true` |
| `POST /api/update/restart` | 连接在重启时断开，但随后升级成功 | 断开属于真实重启行为 |
| 升级后轮询 `GET /api/version` | 成功，版本回到 `0.3.0` |

### 数据保护结果

以下文件未被误删：

- `%APPDATA%/DanmuAI/config.db`
- `%APPDATA%/DanmuAI/.key`
- `%APPDATA%/DanmuAI/startup.log`

校验结果：

- `config.db` 的 SHA256 在安装前、安装后、重装后保持一致
- `.key` 的 SHA256 在安装前、安装后、重装后保持一致
- `startup.log` 始终保留，且在启动后继续追加写入

### 验收结论

| 项目 | 结果 |
|---|---|
| 升级 | 通过 |
| 卸载 | 通过 |
| 重装 | 通过 |
| 数据保护回归 | 通过 |

升级验收说明：

- 历史 `v0.2.0` 仓库标签尚未包含当前 Velopack 发布链路，因此本次使用当前工作树副本构建了一个仅降版号到 `0.2.9` 的旧包
- 该旧包与本次正式发布链路保持同一安装与更新机制，更适合验证当前 `0.2.9 -> 0.3.0` 升级链路
- 升级前后 `config.db` 与 `.key` 的 SHA256 保持一致，`startup.log` 保留

## 环境变量状态

用户环境变量存储状态：

- `R2_ACCOUNT_ID`：已存在
- `R2_ACCESS_KEY_ID`：已存在
- `R2_SECRET_ACCESS_KEY`：已存在
- `R2_BUCKET`：已存在

当前新开的 Codex 受控 PowerShell 进程状态：

- `R2_ACCOUNT_ID`：缺失
- `R2_ACCESS_KEY_ID`：缺失
- `R2_SECRET_ACCESS_KEY`：缺失
- `R2_BUCKET`：缺失

说明：

- `setx` 已成功写入用户环境变量存储
- 当前 Codex 宿主进程没有自动刷新环境，所以新开的受控 PowerShell 仍看不到这些值
- 本次发布实际执行时，已显式将所需环境变量注入执行进程，因此不影响本次发布完成
- 手工关闭并重新打开终端后，新的普通终端会话应可见这些变量
- AWS CLI 的用户 `Path` 本身已包含 `C:\Program Files\Amazon\AWSCLIV2`
- 但 Codex 受控 shell 同样持有旧 `Path` 快照，所以新开的受控进程里 `where.exe aws` 仍可能失败；脚本已通过兜底逻辑和执行进程内注入完成本次发布

## 密钥泄露风险

本次未发现 R2 密钥泄露风险。

已确认：

- 未将任何 R2 密钥写入代码、README、报告、GitHub 或提交记录
- 报告中只记录环境变量存在性和执行结果，不打印真实 secret
- 修复后的 `upload_r2_release.ps1` 不会输出凭证值
- GitHub 上传时使用的是本机 Git Credential Manager 中的 token，仅注入当前进程的 `GH_TOKEN`

## 已知剩余风险

1. **代码签名未完成**：当前安装包未 Authenticode 签名，Windows 可能显示 SmartScreen「未知发布者」；用户通常需「更多信息 → 仍要运行」。无法承诺彻底消除安全提示。详见 [docs/operations/WINDOWS_CODE_SIGNING.md](../docs/operations/WINDOWS_CODE_SIGNING.md)。
2. **根路径别名对象**：除契约主路径外，额外上传了根路径 `releases.win.json`、`PEPETII.DanmuAI-win-Setup.exe`、根目录 `.nupkg` 以兼容访问；**正式契约主路径**仍为 `releases/win/stable/` 与 `downloads/`（见 [docs/operations/WINDOWS_RELEASE_CONTRACT.md](../docs/operations/WINDOWS_RELEASE_CONTRACT.md)）。
3. **升级验收基线**：`0.2.9 -> 0.3.0` 升级使用工作树临时降版包验证，非历史 Git tag 产物；机制与正式链路一致，但旧版基线非归档 Release。
4. **维护者环境**：`R2_*` 经 `setx` 写入用户环境变量存储；IDE / 受控 shell 可能需重开终端才可见（见上文「环境变量状态」）。
5. **Supabase 公告链路**：`app_updates.release_url` 文档示例已对齐 R2 主下载；**线上 Supabase 表数据**是否已更新不在本次发布脚本范围内，需运维单独确认。

## 失败项与下一步

### 当前仍未完成项

1. 无

### 后续建议

1. 手工关闭并重新打开普通终端，确认 `where.exe aws`、`aws --version`、`R2_*` 变量在用户终端中直接可见
2. 保留本次正式更新源与 GitHub Release 镜像作为后续增量发布基线
