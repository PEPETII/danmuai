# 发布后外部监控清单

> 用途：维护者**定期或发布前后**检查公网发布源是否健康。  
> **本清单不含任何凭证**；默认仅使用公网只读 GET（Setup/Portable 为有界 Range GET），不修改 R2 / Supabase / GitHub。

## 核心原则

```text
本地产物就绪  ≠  R2 feed 已切换  ≠  Setup/Portable alias 已切换  ≠  Supabase 元数据已对齐  ≠  GitHub 镜像已同步
```

本地 `release/velopack/` 通过校验，**不能**证明线上用户能下载或应用内更新能拉到新版本。四类状态须分开判定，详见 [RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md](RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md)。

## 必须监控的 URL

| 检查项 | URL | 方法 | 告警条件（任一即异常） |
|--------|-----|------|------------------------|
| Velopack 更新 feed | `https://updates.qiaoqiao.buzz/releases/win/stable` | GET | 非 2xx；JSON 无法解析；无 `Full` 资产；`latest Full` 版本低于预期 |
| Setup 主下载 alias | `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe` | GET Range（前 4 KiB） | 非 206；总大小小于 8 MiB；缺少 PE/MZ 魔数；Range 被忽略或响应截断 |
| Portable alias | `https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip` | GET Range（前 4 KiB + 后 1 MiB） | 非 206；总大小小于 8 MiB；缺少 ZIP 魔数；中央目录无法解析；根布局不是 `DanmuAI.exe` + `_internal/`，或检测到 Velopack portable stub |
| GitHub Releases 镜像 | `https://github.com/PEPETII/danmuai/releases` | GET | 非 2xx；页面不可达（**非**应用内 Velopack 主源，但影响备用下载与可见性） |
| Supabase `app_updates` | 无固定公网 URL（见下文） | 人工 / 后端接口 | `latest_version` 或 `release_url` 与 R2 主入口不一致 |

**主更新源**：R2（`updates.qiaoqiao.buzz`）。GitHub 仅为镜像；客户端 Velopack feed 不依赖 GitHub。

**Supabase 默认主下载 URL**（应与 Setup alias 一致）：

`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`

## 最小自动化：只读检查脚本

仓库提供 [`scripts/check_release_endpoints.ps1`](../../scripts/check_release_endpoints.ps1)：

- **仅**使用只读 GET；Setup/Portable 使用有界 Range GET，服务端不支持 Range 时 fail closed
- **不需要** R2 / Supabase / GitHub token
- **不**上传、删除或修改任何线上对象
- **不**在脚本或仓库中硬编码 anon key

### 用法

```powershell
Set-Location "E:/test/danmu"

# 日常巡检（不校验版本号，只检查可达性与 feed 结构）
.\scripts\check_release_endpoints.ps1

# 发布后验收：期望 feed latest Full = 本次发布版本
.\scripts\check_release_endpoints.ps1 -ExpectedVersion "0.3.8"

# 自定义超时（秒，默认 30）
.\scripts\check_release_endpoints.ps1 -ExpectedVersion "0.3.8" -TimeoutSec 45
```

### 脚本检查项

| 输出字段 | 含义 |
|----------|------|
| `HTTP` | 状态码 |
| `ContentLength` | 响应体大小（HEAD 或 GET 后） |
| `FeedLatestFull` | feed 中最高版本 `Full` 资产版本号 |
| `OK` / `FAIL` | 该项是否通过 |

Setup 和 Portable 的成功不仅表示 URL 可达：Setup 必须通过 8 MiB 最小大小与 `MZ` 检查；Portable 必须通过 8 MiB 最小大小、ZIP 魔数、EOCD/中央目录解析，以及根 `DanmuAI.exe` + `_internal/` 布局检查。脚本最多读取 Setup 前 4 KiB、Portable 前 4 KiB 和后 1 MiB，不默认下载完整发布包。

失败时脚本以非零退出码结束，便于 CI 或计划任务捕获（本工单**不**接入付费监控、**不**发送真实告警）。

## Supabase `app_updates` 验证（无 anon key 脚本）

`app_updates.release_url` 与 `latest_version` **不能**在仓库脚本中用硬编码 anon key 自动拉取。维护者任选其一：

### 方式 A：Supabase Table Editor（推荐）

1. 打开项目 → `app_updates` 表。
2. 确认存在 `enabled = true` 的最新行（按 `updated_at desc`）。
3. 核对：
   - `latest_version` = 本次发布 semver（与 `app/version.py`、Git tag 一致，可带或不带 `v` 前缀）。
   - `release_url` = `https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`（或负责人明确指定的主入口；**不得**指向已弃用的 GitHub 直链作为主下载）。

### 方式 B：本机已配置环境变量的后端接口

在**已注入** `DANMU_SUPABASE_URL` + `DANMU_SUPABASE_ANON_KEY` 的本机（勿将 key 写入仓库）：

```powershell
# 先启动应用或仅 uvicorn 控制台后：
Invoke-RestMethod -Uri "http://127.0.0.1:18765/api/update/channels" | ConvertTo-Json -Depth 5
```

核对返回的 `latest_version`、`release_url` 与 R2 feed / Setup alias 一致。  
未配置 Supabase 时 API 会回退本地 `app/version.py`，**不能**据此判断线上发布是否成功。

### 方式 C：PostgREST（仅运维本机、手动）

```text
GET {SUPABASE_URL}/rest/v1/app_updates?select=latest_version,release_url,enabled,updated_at&enabled=eq.true&order=updated_at.desc&limit=1
apikey: <anon key>
Authorization: Bearer <anon key>
```

密钥仅从本机环境或密码管理器读取，**禁止**提交到 git。

## GitHub Releases 镜像（补充）

| 检查 | 说明 |
|------|------|
| 发布页可访问 | `https://github.com/PEPETII/danmuai/releases` 返回 200 |
| 最新 Release 标签 | 与 `$ExpectedVersion` 一致（脚本可选调用 GitHub API `.../releases/latest`，无需 token 对公开仓库） |
| 资产存在 | Release 含 Setup / Portable 或说明以 R2 为主（镜像策略见 `upload_github_release.ps1`） |

镜像滞后于 R2 **不**阻断应用内 Velopack 更新，但应在 24h 内补齐，避免用户仅依赖 GitHub 时下载旧版。

## 告警触发条件（汇总）

在**未**接入 UptimeRobot / Pingdom 等付费平台的前提下，维护者将下列任一情况视为需处理：

1. **Feed**：HTTP 非 2xx，或 `latest Full` ≠ 预期版本，或 feed JSON 损坏。
2. **Setup / Portable alias**：HTTP 非 206、Range 被忽略/截断、总大小小于 8 MiB、魔数错误，或 Portable 根布局不符合直接 onedir 归档契约。
3. **版本漂移**：feed `latest Full`、`app_updates.latest_version`、`app/version.py` 三者长期不一致。
4. **`release_url` 错误**：Supabase 指向非 R2 主 Setup URL，或指向 404。
5. **GitHub 镜像**：发布页长期不可达，或最新 Release 明显落后于 R2 feed（>1 个补丁版本）。
6. **CDN/R2 部分失败**：仅 HTTP 200 但体积与上一版 `head-object` 差异巨大 → 按 [RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md](RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md) 用 R2 `head-object` 复核（需本机 R2 只读凭证，**非**本脚本默认路径）。

本工单**不**自动发邮件/钉钉/短信；负责人根据脚本退出码或巡检表人工升级。

## 维护者处理顺序

```text
1. 运行 check_release_endpoints.ps1（带 -ExpectedVersion）
2. 若失败 → 区分：DNS/CDN 故障 vs 上传未完成 vs alias 未切换 vs feed 未更新
3. 查阅 RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md「只读验证」与「四种状态」
4. 本地产物正确 → 考虑 forward-fix（重跑 upload_r2_release.ps1），勿在未备份 feed 时手工改 JSON
5. 错误版本已对外 → 负责人确认后按 Runbook 回滚 alias / feed
6. 单独核对 Supabase app_updates（Table Editor 或 /api/update/channels）
7. 择机同步 GitHub Releases 镜像
8. 记录事件与恢复时间（内部发布日志即可；无需改本仓库）
```

## 建议巡检频率

| 场景 | 频率 |
|------|------|
| 每次 R2 上传完成后 | 立即运行脚本 + Supabase 人工核对 |
| 生产空闲期 | 每周 1 次只读脚本 |
| 大促 / 重大版本前 | 发布前记录基线；发布后 1h 内复检 |

可将 `check_release_endpoints.ps1` 加入 Windows 计划任务；任务账户**无需** R2 写权限。

## 相关文档

- [RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md](RELEASE_ONLINE_VERIFY_AND_ROLLBACK.md) — 上传前后验证与回滚
- [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md) — 打包与上传
- [supabase/README.md](../../supabase/README.md) — `app_updates` 表说明
- [`app/velopack_config.py`](../../app/velopack_config.py) — 客户端 feed URL 常量
