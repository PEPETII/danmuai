# DanmuAI Windows v0.3.0 发布后收尾与冻结

日期：2026-06-11  
仓库：`E:/test/danmu`  
当前版本：`v0.3.0`  
发布状态：**完成**（本次仅文档收尾与冻结，未重复执行发布脚本）

---

## 冻结主链路

```text
PyInstaller onedir → Velopack → Cloudflare R2 → GitHub Releases 镜像
```

契约与基线文档：

- [docs/operations/WINDOWS_RELEASE_CONTRACT.md](../docs/operations/WINDOWS_RELEASE_CONTRACT.md)
- [docs/operations/WINDOWS_RELEASE_BASELINE.md](../docs/operations/WINDOWS_RELEASE_BASELINE.md)

v0.3.0 实跑记录：[reports/windows-release-final-check.md](windows-release-final-check.md)

---

## 主更新源

| 项 | 值 |
|---|---|
| 平台 | Cloudflare R2 |
| Bucket | `danmuai-updates` |
| 自定义域 | `https://updates.qiaoqiao.buzz` |
| 更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable` |
| 客户端配置 | [app/velopack_config.py](../app/velopack_config.py) |

---

## 用户主下载入口

**主下载（latest 别名）**：<https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe>

版本化真资产：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-0.3.0-Setup.exe`

---

## GitHub Releases 镜像状态

- Tag：`v0.3.0`
- 状态：镜像资产已上传成功
- 地址：<https://github.com/PEPETII/danmuai/releases/tag/v0.3.0>
- 角色：**备用镜像**，非主真源

详见 [windows-release-final-check.md § GitHub Releases 镜像上传结果](windows-release-final-check.md)。

---

## 真机验收结论

| 场景 | 结论 |
|------|------|
| 静默安装 | 通过 |
| 静默卸载 | 通过 |
| 静默重装 | 通过 |
| 应用启动与日志写入 | 通过 |
| `0.2.9 → 0.3.0` 应用内升级 | 通过 |

详见 [windows-release-final-check.md § 真机验收](windows-release-final-check.md)。

---

## 数据保护结论

以下用户数据在安装、卸载、重装、升级后均保留：

- `%APPDATA%/DanmuAI/config.db`（SHA256 前后一致）
- `%APPDATA%/DanmuAI/.key`（SHA256 前后一致）
- `%APPDATA%/DanmuAI/startup.log`（保留并持续追加）

**结论：数据保护回归通过。**

---

## 密钥泄露核查结论

**只读核查范围**：仓库 tracked 文件、README、reports、scripts、`git diff` 工作区变更、`git diff --cached` 暂存区。

**核查方法**：

- 搜索 `R2_SECRET_ACCESS_KEY`、`R2_ACCESS_KEY_ID`、`CLOUDFLARE.*TOKEN`、`AKIA…` 等模式
- 检查 `git ls-files` 是否跟踪 `.env`
- 检查是否存在 `R2_* = <明文>` 赋值

**结论：未发现密钥泄露。**

命中文件均为变量名、脚本注释、`setx …` 省略号占位或文档说明，无真实 Access Key / Secret Key / Cloudflare Token 明文。`.env` 已在 `.gitignore` 中排除且未入库。

---

## README 入口核查结论

**通过，无需修改。**

- 主下载统一指向：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`
- GitHub Releases 仅作镜像/备用说明
- 保留 SmartScreen 风险说明，未夸大代码签名状态

---

## 本次文档冻结清单

| 文件 | 变更 |
|------|------|
| [reports/windows-release-final-check.md](windows-release-final-check.md) | 增补「已知剩余风险」 |
| [reports/windows-release-post-freeze.md](windows-release-post-freeze.md) | 新建（本文） |
| [docs/operations/WINDOWS_RELEASE_BASELINE.md](../docs/operations/WINDOWS_RELEASE_BASELINE.md) | 更新为 v0.3.0 冻结事实 |
| [docs/operations/PACKAGING_WINDOWS.md](../docs/operations/PACKAGING_WINDOWS.md) | 更新发布基线表与检查项 |
| [scripts/README.md](../scripts/README.md) | 明确 R2 主真源 / GitHub 镜像 |
| [supabase/README.md](../supabase/README.md) | `app_updates.release_url` 示例对齐 R2 |
| [README.md](../README.md) | 无改动（入口已符合要求） |

**未改动**：`main.py` 冻结入口（`_trigger_api_call`、`_on_ai_reply`、`_consume_reply_queue`）；未重跑发布脚本；未向仓库写入任何 R2 凭证。

---

## 已知剩余风险（摘要）

完整列表见 [windows-release-final-check.md § 已知剩余风险](windows-release-final-check.md)。

1. 代码签名未完成 → SmartScreen「未知发布者」仍可能出现
2. R2 根路径别名对象为兼容性补充，契约主路径仍为 `releases/win/stable/` 与 `downloads/`
3. 升级验收使用临时 `0.2.9` 包，非历史 tag 产物
4. 维护者 `R2_*` 环境变量需重开终端方可在部分 shell 中可见
5. Supabase 线上 `app_updates` 表 `release_url` 需运维单独确认是否已指向 R2

---

## 后续独立工单建议

| 工单方向 | 说明 |
|----------|------|
| Windows 代码签名 | W-REL-R2V-SIGN-001；`vpk --signParams`、验签门禁；见 [WINDOWS_CODE_SIGNING.md](../docs/operations/WINDOWS_CODE_SIGNING.md) |
| SmartScreen 信任优化 | 依赖签名与声誉积累；不承诺无提示 |
| 发布流程自动化 | CI 注入 R2 secret、`publish → upload_r2 → upload_github` 流水线 |
| 发布失败回滚预案 | R2 对象版本 / 恢复上一版 `releases.win.json` 与 `DanmuAI-Setup.exe` 别名策略 |
| Supabase 线上对齐 | 确认 `app_updates.release_url` 已指向 R2 主下载 |
| Web 更新兜底 URL | [web/static/modules/app-update-banner.js](../web/static/modules/app-update-banner.js) 中 `DEFAULT_RELEASE_URL` 仍默认 GitHub；建议后续改为 R2 或从 Supabase 统一注入 |

---

## 禁止事项（冻结后仍适用）

- 不得改回 COS、Inno Setup、zip 主分发
- 不得将 GitHub Releases 重新定义为主真源
- 不得把 R2 密钥写入仓库、README、报告、日志或提交记录
- 不得在未授权工单中改动 `main.py` 主链路冻结入口
