# 发布后外部监控清单

> 用途：维护者在发布前后或定期检查公网发布源是否健康。
> 本清单不包含任何凭证；默认只执行公网只读 GET，Setup/Portable 使用有界 Range GET。

## 核心原则

```text
本地产物就绪 ≠ R2 feed 已切换 ≠ Setup/Portable alias 已切换 ≠ Supabase 元数据已对齐 ≠ GitHub 镜像已同步
```

本地 `release/velopack/` 通过校验，不能证明线上用户已经能下载新版本或应用内更新已经切换。以上状态必须分别确认。

## 必须监控的 URL

| 检查项 | URL | 方法 | 异常条件 |
|---|---|---|---|
| Velopack 更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable` | GET | 非 2xx、JSON 无法解析、无 `Full` 资产或 latest Full 版本不符合预期 |
| Setup 主下载 alias | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | 有界 Range GET | 非 206、体积小于 8 MiB、缺少 `MZ` 魔数、Range 被忽略或响应截断 |
| Portable alias | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` | 有界 Range GET | 非 206、体积小于 8 MiB、ZIP/EOCD/中央目录无效或根布局不符合 onedir 契约 |
| GitHub Releases 镜像 | `https://github.com/PEPETII/danmuai/releases` | GET | 页面不可达或非 2xx |
| Supabase `app_updates` | 无固定公开检查 URL | 人工或后端接口 | `latest_version` 或 `release_url` 与 R2 主入口不一致 |

R2（`updates.qiaoqiao.buzz`）是主更新源，GitHub Releases 仅是镜像；客户端 Velopack feed 不依赖 GitHub。

Supabase 的 `release_url` 默认应指向：

`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

## 只读自动检查

仓库提供 [`scripts/check_release_endpoints.ps1`](../../scripts/check_release_endpoints.ps1)：

- 只使用 GET/HEAD；Setup/Portable 最多读取 Setup 前 4 KiB、Portable 前 4 KiB 和后 1 MiB；
- 不上传、删除或修改 R2、Supabase 或 GitHub 数据；
- 不需要 R2 凭证、GitHub token 或 Supabase anon key；
- 失败时以非零退出码结束，便于计划任务或发布后检查捕获。

```powershell
# 日常巡检：检查可达性和 feed 结构
.\scripts\check_release_endpoints.ps1

# 发布后验收：要求 feed latest Full 与本次版本一致
.\scripts\check_release_endpoints.ps1 -ExpectedVersion "<version>"
```

发布验收至少使用 `-ExpectedVersion`，并单独记录 Feed、Setup、Portable、GitHub Releases 和 GitHub latest tag 的结果。脚本的成功只证明当前公网只读探针通过，不证明 Supabase 元数据已经更新。

## Supabase `app_updates` 验证

不要在脚本或仓库中硬编码 anon key。维护者应在 Supabase Table Editor 或已安全注入环境变量的本机接口中核对：

- 最新启用记录的 `latest_version` 与 `app/version.py`、Git tag 采用同一 semver；
- `release_url` 与 R2 Setup alias 一致，而不是已弃用的 GitHub 直链；
- 未配置 Supabase 时，`/api/update/channels` 可能回退到本地版本，不能作为线上发布成功证据。

## GitHub 镜像补充检查

确认发布页可访问、latest tag 与本次版本一致，并检查 Release 中包含当前 Setup、Portable、full package、delta package（如生成）和 `releases.win.json`。GitHub 镜像滞后不会阻断 R2 上的应用内更新，但必须在发布记录中注明并尽快补齐。

## 处理顺序

```text
1. 运行 check_release_endpoints.ps1 -ExpectedVersion <version>
2. 区分 DNS/CDN 故障、上传未完成、alias 未切换和 feed 未更新
3. 本地产物正确且线上对象异常时，重新核对 upload 脚本的目标与 manifest
4. 不直接手工改线上 feed；错误版本已对外时先保留当前 feed/alias 证据，再按负责人确认的回滚流程处理
5. 单独核对 Supabase app_updates，记录恢复时间和最终版本
```

## 建议频率

| 场景 | 频率 |
|---|---|
| R2 上传完成后 | 立即运行带版本号的只读检查，并核对 Supabase |
| 日常运行 | 每周一次 |
| 重大版本前后 | 发布前记录基线，发布后立即复检并在 1 小时内再次复检 |

计划任务账户无需 R2 写权限。

## 相关文档

- [`PACKAGING_WINDOWS.md`](PACKAGING_WINDOWS.md) — Windows 打包、产物校验和上传顺序
- [`scripts/check_release_endpoints.ps1`](../../scripts/check_release_endpoints.ps1) — 只读线上端点检查
- [`app/velopack_config.py`](../../app/velopack_config.py) — 客户端 feed URL 常量
