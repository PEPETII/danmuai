# DanmuAI 上线前发布风险审查报告

> **历史发布审查快照（2026-07-07）**：版本、线上端点与门禁结果均可能漂移，不能据此决定当前是否发布。现行 Windows 打包入口见 [PACKAGING_WINDOWS.md](operations/PACKAGING_WINDOWS.md)，实际发布仍须重新执行其门禁与线上验证。

审查日期：2026-07-07  
仓库：`E:/test/danmu`  
当前版本：`app/version.py::__version__ = 0.3.8`  
结论：**当前不建议直接上线**。建议先修复发布门控、测试漂移、发布文档缺口，并补齐线上验证与回滚演练。

## 0. 审查边界与证据

本报告仅基于当前本地工作树、仓库脚本、文档和本地命令结果；未执行 R2、Supabase、GitHub Releases 的线上访问、上传或配置修改。所有线上下载源切换、Supabase `app_updates.release_url`、GitHub 镜像资产状态均列为待人工确认。

当前工作区已有大量未提交改动。`git diff --name-only` 在写入本报告前显示 `app/`、`scripts/`、`tests/`、`web/static/` 多处已修改；这些改动不属于本报告新增文件，不能把当前树直接视为稳定发布基线。

本轮已执行的本地验证：

| 命令 | 结果 | 结论 |
|------|------|------|
| `.\scripts\publish_windows_release.ps1 -DryRun` | 失败 | 当前本地存在 `web/static/supabase-config.js`，被发布守卫拦截；不会进入构建/打包。报告未记录任何 key 值。 |
| `python -m pytest "tests/test_packaging_supabase_exclude.py" "tests/test_release_channels.py" "tests/test_update_api.py" "tests/test_upload_r2_release_order.py" -q -x` | `25 passed, 1 failed` | 失败点：`tests/test_release_channels.py::test_release_channels_api_route`，实际 `latest_version` 为 `0.3.7`，测试期望 `0.4.0`。 |

当前发布链事实：

- 主链路：`PyInstaller onedir -> Velopack -> Cloudflare R2 -> GitHub Releases mirror`。
- 主入口：`https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe`。
- 便携入口：`https://updates.qiaoqiao.buzz/downloads/PEPETII.DanmuAI-win-Portable.zip`。
- 自动更新 feed：`https://updates.qiaoqiao.buzz/releases/win/stable`。
- GitHub Releases 仅作为镜像，不是主更新源。
- MSI 链路已被 W-REL-CLEANUP-001 反转；`docs/operations/W-REL-MSI-*` 和 `reports/W-REL-MSI-*` 只能当历史资料。

## 1. 发布流程风险

| 风险 | 级别 | 已确认事实 | 影响 | 建议 |
|------|------|------------|------|------|
| 当前发布 DryRun 无法通过 | 高 | `publish_windows_release.ps1 -DryRun` 因 `web/static/supabase-config.js` 中止。 | 发布流程在当前本机状态下不能进入构建，更不能上传。 | 发布前将真实 Supabase 本地配置移出 `web/static/`，改用脚本认可的临时位置或环境变量；不要使用含 `supabase-config` 的备份文件名。 |
| 构建手册与脚本守卫冲突 | 高 | `docs/operations/IDE_WINDOWS_BUILD_PLAYBOOK.md` 建议临时改名为 `supabase-config.js.codex-release-backup`；当前 `publish_windows_release.ps1` 默认拦截任何包含 `supabase-config` 的非 allowlist 文件。 | 按手册操作仍会失败，容易误判为脚本坏或环境坏。 | 修正文档：备份文件应移动到 `web/static/` 外，或改为不含 `supabase-config` 的安全路径；同时给出恢复步骤。 |
| 发布文档引用缺失文件 | 中 | `docs/operations/WINDOWS_RELEASE_CONTRACT.md`、`RELEASE_CHECKLIST.md`、`WINDOWS_CODE_SIGNING.md`、`WINDOWS_RELEASE_BASELINE.md` 当前不存在，但手册和脚本注释仍引用其中部分文件。 | IDE/人工发布时可能按过期入口操作，尤其是签名、检查清单和发布契约。 | 以 `docs/operations/PACKAGING_WINDOWS.md` 作为当前权威文档；补建或删除缺失引用，避免历史文档路径误导。 |
| 本地成功与线上切换容易混淆 | 高 | 现有链路分为本地 `release/velopack/` 生成、R2 上传、GitHub 镜像上传、线上 URL 验证。 | 本地产物存在不等于 `DanmuAI-Setup.exe` alias 或 feed 已经切换，可能导致用户仍下载旧版本。 | 发布检查必须分开记录“本地产物就绪”“R2 feed 已切换”“Setup alias 已切换”“Portable alias 已切换”“GitHub mirror 已同步”。 |
| 回滚策略不够脚本化 | 高 | 当前上传脚本支持上传与 latest alias copy，但未看到一键回滚到上一版本 alias/feed 的受控脚本。 | feed 或 Setup alias 发布错误时，恢复依赖人工 S3 操作，出错面大。 | 新增回滚 runbook：记录上一版 version、feed、Setup/Portable alias 源对象；提供 dry-run 和 head-object 校验；禁止删除保留清单内资产。 |
| 发布前工作区未冻结 | 中 | 当前 `git diff --name-only` 显示大量业务、脚本、测试、Web 静态文件已改动。 | 发布产物可能混入未评审或未验收变更。 | 发布前要求干净工作区或明确 release branch/commit hash；`VERSION.txt` 中的 Git hash 应与要发布的 commit 一致。 |

## 2. 打包风险

| 风险 | 级别 | 已确认事实 | 影响 | 建议 |
|------|------|------------|------|------|
| Python 依赖未锁定 | 高 | `requirements.txt` 和 `requirements-dev.txt` 使用范围约束，例如 `PyQt6>=6.6,<7`、`pyinstaller>=6.10,<7`，未见锁文件。 | 同一版本应用在不同时间打包可能解析到不同依赖，产生不可复现构建。 | 增加 Windows 发布专用锁定文件或生成 `pip freeze` artifact；CI 与本机发布都使用同一锁文件。 |
| PyInstaller hiddenimports 依赖手工维护 | 中 | `DanmuAI.spec` 显式列出大量 `hiddenimports`，新增模块须人工同步。 | 新功能可在源码运行通过，但打包后缺模块崩溃。 | 保留现有白名单，同时为新增子包建立打包 smoke；发布前启动 frozen exe 并访问关键页面。 |
| CI artifact 校验偏浅 | 中 | `.github/workflows/ci.yml` 检查 Setup、full.nupkg、feed、exe 存在，但未覆盖 Portable 根目录结构、delta、无 MSI、签名、hash manifest、体积趋势。 | CI 绿灯不代表可发；Portable 或 delta 问题可能到人工验收才暴露。 | CI 增加检查：Portable 解压根目录含 `DanmuAI.exe` + `_internal/`；`release/velopack/` 无 `*.msi`；feed latest Full 等于当前版本；生成 SHA256 清单。 |
| Delta 生成依赖旧 full 包或线上 bootstrap | 中 | `publish_windows_release.ps1` 在本地无旧 full 包时默认从 stable feed bootstrap；可用 `-SkipDeltaBootstrap` 禁用。 | 弱网或线上 feed 异常会影响本地打包；跳过后可能没有 delta。 | 发布报告必须记录 delta 是否生成、feed 是否含 `Type: Delta`；若无 delta，明确全量更新兜底是否可接受。 |
| 代码签名默认关闭 | 中 | `DANMU_CODE_SIGN=1` 才启用签名；默认未签名。 | Windows SmartScreen、企业策略、用户信任均受影响。 | 短期保留 SmartScreen 用户说明；中期接入 Azure Artifact Signing 或 OV/EV，并在上传前增加可选签名门禁。 |
| 体积与性能趋势缺少门控 | 中 | 当前脚本记录产物名和大小校验，但未看到历史体积阈值或启动性能阈值。 | 依赖膨胀、资源误打包、启动变慢可能在上线后才被发现。 | 保存每次 release artifact size、frozen 启动耗时、Web 控制台 ready 耗时，超过阈值时阻断发布。 |

## 3. 更新机制风险

| 风险 | 级别 | 已确认事实 | 影响 | 建议 |
|------|------|------------|------|------|
| 发布通道测试漂移 | 高 | 定向测试失败：`tests/test_release_channels.py::test_release_channels_api_route` 仍 patch `release_channels.fetch_app_update()`；当前 `app/web_api/update.py` 走 `fetch_app_update_result()`。 | 更新通道 API 的测试不能可靠覆盖真实依赖，发布前门控信号失真。 | 修复测试 patch 点或调整 API 依赖注入；重新运行发布/更新定向测试直到绿色。 |
| 缺少灰度通道 | 高 | 当前客户端 feed 固定为 stable：`https://updates.qiaoqiao.buzz/releases/win/stable`。 | 一旦 stable feed 发布错误，所有安装版用户都可能收到错误更新。 | 增加 `stable` / `canary` 或百分比灰度策略；至少先发布 canary feed，再人工提升 stable alias。 |
| Supabase 发布弹窗与 Velopack 更新是两条链 | 中 | Web 发布公告使用 Supabase `app_updates.release_url`，应用内更新使用 Velopack feed。 | Supabase 指向新下载但 Velopack feed 未切，或反向不一致，会造成用户看到的版本状态混乱。 | 发布后同时验证 `/api/update/channels`、Supabase enabled row、R2 Setup alias、R2 feed latest Full。 |
| 旧版升级兼容需每次抽样 | 中 | 历史 Setup smoke 已验证安装、卸载、数据保留，但本次未执行真实旧版升级。 | 本次变更可能破坏从上一稳定版到当前版的路径。 | 每次正式发布至少抽样 `previous stable -> current`：检查 `check/download/restart`、`config.db`、`.key`、`startup.log` 保留。 |
| 数据迁移框架当前为空 | 中 | `app/config_migrations.py` 建立 `schema_version`，当前 `MIGRATIONS` 为空；许多配置迁移仍依赖运行期懒迁移。 | 新版本新增 schema 或配置字段时，升级回滚行为不够集中可审计。 | 新增持久化结构时必须登记迁移函数和回滚兼容说明；发布报告列出 schema_version 变化。 |
| 下载中断与恢复体验待验证 | 中 | `app/update_service.py` 有 download phase、progress、error 状态；未执行真实断网/中断下载演练。 | 用户弱网下载失败后可能卡在错误状态或重复下载。 | 在验收中加入断网、重启、重复点击下载、pending_restart 后退出再启动的场景。 |

## 4. 网络连接风险

| 风险 | 级别 | 已确认事实 | 影响 | 建议 |
|------|------|------------|------|------|
| 前端 Supabase 直连缺少显式超时 | 中 | `web/static/supabase-client.js` 直接使用 `fetch` 调 PostgREST；未看到统一 `AbortController` 超时封装。 | Supabase 网络慢或被墙时，公告、反馈、错误报告、教程链接可能长时间等待。 | 为 Supabase fetch 增加超时、可取消、错误分类和退避；UI 层显示离线兜底。 |
| 后端 Supabase 有超时与缓存，但线上行仍需确认 | 中 | `app/supabase_app_updates.py` 使用 `httpx.Timeout(8.0, connect=4.0)` 和 300s 缓存/陈旧兜底。 | 客户端可离线兜底，但线上 row 错误仍会传播错误下载链接。 | 发布后人工或脚本验证 Supabase enabled row 的 `latest_version`、`release_url`、`message`。 |
| R2 上传校验缺少 hash manifest | 中 | `scripts/upload_r2_release.ps1` 上传后 `head-object` 校验 ContentLength；未看到发布级 SHA256 manifest。 | 大文件同尺寸损坏概率低但不可完全排除；用户无法校验下载。 | 为 Setup、Portable、full/delta nupkg 生成 SHA256 清单并上传；报告中记录 hash。 |
| AI 上游超时存在，但弱网策略不统一 | 中 | AI 客户端使用 httpx timeout、request wall clock、first content timeout；不同路径有各自处理。 | 模型供应商网络波动时，用户体验与日志归因可能不一致。 | 将各上游调用的 timeout、重试、用户提示、日志字段集中成发布检查表。 |
| 诊断 SSE token 暴露风险待收敛 | 中 | `web/static/modules/diagnostics.js` 将 token 放入 `/api/diagnostics/events?token=...` URL。 | URL 可能进入浏览器日志、代理日志或调试截图。 | 改为连接后首条消息认证，或至少避免在 console 输出完整 URL；发布前检查日志脱敏覆盖该场景。 |
| 生产网络验证未执行 | 高 | 本报告未访问 `updates.qiaoqiao.buzz`、Supabase、GitHub Releases。 | 不能证明线上源当前可达、版本正确或缓存已刷新。 | 发布前执行外部验证：HTTP 200、Content-Length、SHA256、feed latest Full/Delta、Setup alias 和 Portable alias 版本一致。 |

## 5. 正式上线准备风险

| 风险 | 级别 | 已确认事实 | 影响 | 建议 |
|------|------|------------|------|------|
| 外部监控与报警不足 | 高 | 仓库有本地日志、诊断面板、错误反馈，但未看到对 R2 feed、Setup alias、Supabase row、GitHub mirror 的持续监控报警。 | 线上资产失效、缓存漂移或 Supabase 配置错误可能长期无人发现。 | 建立定时监控：feed 可解析、latest version 正确、Setup/Portable 可下载、Supabase release_url 正确；异常通知维护者。 |
| 错误追踪依赖用户反馈 | 中 | `web/static/modules/app-error-reporting.js` 支持错误报告，`app/logger.py` 有脱敏日志。 | 用户不提交时缺少主动崩溃追踪；安装/启动失败可能没有上报。 | 明确是否引入外部错误追踪；若不引入，至少在发布说明中写清日志路径与反馈收集方式。 |
| 发布健康检查缺少标准状态页 | 中 | Web 控制台有 `/api/status`、`/api/diagnostics`，但发布链未要求启动 frozen exe 后执行健康检查。 | 打包后 UI/pywebview/uvicorn 依赖缺失可能漏过。 | 发布前在干净 Windows 环境启动安装版，检查 `/api/version`、`/api/update/status`、Web 控制台、托盘、日志路径。 |
| 灰度/蓝绿缺失 | 高 | R2 stable feed 是单一正式源；未看到蓝绿发布或逐步提升机制。 | 错误 feed 一旦切换会立即影响全部用户。 | 至少引入 canary feed；正式 stable 切换前先由测试安装版验证 canary。 |
| 安全发布基线不完整 | 中 | 已有 Supabase 打包守卫、日志脱敏、本地 loopback token；但签名、hash、监控、凭证轮换流程不完整。 | 安全事故或误发布后的排查成本高。 | 建立 release security checklist：无真实配置打包、签名/未签名声明、hash、R2 secret 仅环境变量、Supabase anon 权限复核。 |
| 用户侧 SmartScreen 风险仍存在 | 中 | 代码签名默认关闭，未签名 Setup 可能出现未知发布者提示。 | 首装转化降低，用户误判为恶意软件。 | 未签名前在 README、下载页、发布说明保持一致说明；签名接入后做干净 VM 首装验证。 |

## 6. 建议的上线阻断项

上线前建议至少完成以下阻断项：

1. 修复 `publish_windows_release.ps1 -DryRun` 当前失败状态，确保真实本地 Supabase 配置不会阻断发布。
2. 修复 `tests/test_release_channels.py::test_release_channels_api_route` 的测试漂移，并重新运行发布/更新定向测试。
3. 修正 `docs/operations/IDE_WINDOWS_BUILD_PLAYBOOK.md` 中 `supabase-config.js.codex-release-backup` 的错误备份建议。
4. 明确当前权威发布文档，补建或移除缺失的 `WINDOWS_RELEASE_CONTRACT.md`、`RELEASE_CHECKLIST.md`、`WINDOWS_CODE_SIGNING.md` 引用。
5. 在干净工作区或明确 release commit 上执行完整本地发布链：`publish_windows_release.ps1`、产物检查、Portable 解压检查、feed 检查。
6. 发布前准备回滚 runbook：上一版 feed、Setup alias、Portable alias、GitHub mirror 回退步骤。
7. 发布后执行线上验证：R2 feed、Setup alias、Portable alias、Supabase row、GitHub mirror。

## 7. 建议的改进优先级

| 优先级 | 工作项 | 目标 |
|--------|--------|------|
| P0 | 发布守卫与测试漂移修复 | 让本地发布门控可信。 |
| P0 | 线上验证清单和回滚 runbook | 让错误发布可快速恢复。 |
| P1 | 依赖锁定和 artifact hash manifest | 提升可复现性与下载可校验性。 |
| P1 | canary feed 或灰度策略 | 降低 stable 全量事故面。 |
| P1 | CI 增强 Portable/delta/no-MSI/签名检查 | 减少人工验收遗漏。 |
| P2 | 外部监控报警和错误追踪策略 | 提升上线后可观测性。 |
| P2 | 代码签名接入 | 降低 SmartScreen 与企业环境阻力。 |

## 8. 本次未做事项

- 未修改业务代码、API、schema、构建脚本、测试或 CI。
- 未访问或修改 R2、Supabase、GitHub Releases。
- 未运行完整构建、上传、安装、卸载、旧版升级或真实下载验证。
- 未记录 `web/static/supabase-config.js` 中的任何 URL/key 具体值。

## 9. 最终判定

当前仓库已有成熟发布链基础，但本轮证据显示上线前门控仍不够可靠：本地 DryRun 被阻断，发布通道测试失败，发布文档存在缺失引用和错误操作建议，线上验证与回滚策略未脚本化。

因此建议状态为：**暂缓上线，先完成 P0 阻断项，再进入正式发布候选验证。**
