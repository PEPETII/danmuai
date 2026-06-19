# Windows 发布现状基线

> 冻结事实以仓库当前实现为准；本文总结 v0.3.x 的 Windows 发布、更新、安装路径与卸载边界。

## 当前正式主链路

```text
PyInstaller onedir -> Velopack -> Cloudflare R2 -> GitHub Releases（镜像）
```

| 环节 | 基线事实 |
|------|----------|
| 构建 | `.\scripts\build_exe.ps1` -> `dist\DanmuAI\` |
| 打包 | `.\scripts\publish_windows_release.ps1` -> `release\velopack\` |
| 主真源 | `.\scripts\upload_r2_release.ps1` -> `https://updates.qiaoqiao.buzz/` |
| 镜像 | `.\scripts\upload_github_release.ps1` -> GitHub Releases，仅镜像 |
| 应用内更新 | `app/update_service.py` + Velopack `UpdateManager` |
| 用户数据 | `%APPDATA%\DanmuAI\` |
| 程序目录 | 默认 `%LocalAppData%\PEPETII.DanmuAI\`，但安装根可被 Velopack 安装器覆盖 |

## 增量更新基线

- `releases.win.json` 是唯一更新 feed 契约。
- 升级发布时，`release\velopack\` 应同时包含当前版本的 `*-full.nupkg` 与 `*-delta.nupkg`。
- `publish_windows_release.ps1` 不再清空整个 `release\velopack\`；当本地缺少上一版 full 包时，会默认从 `https://updates.qiaoqiao.buzz/releases/win/stable` bootstrap 旧资产，再执行 `vpk pack`。
- `upload_r2_release.ps1` 与 `upload_github_release.ps1` 都会上传 `*-delta.nupkg`；客户端仍沿用 Velopack 官方增量策略与 full 回退策略，不实现自研补丁逻辑。

## 安装路径基线

- Velopack 官方支持 `Setup.exe --installto <DIR>` 自定义首装路径。
- 如果后续需要 MSI，也可使用 `--msi --instLocation` 或 `VELOPACK_INSTALLDIR`。
- 当前仓库运行时代码没有把安装根写死到 `%LocalAppData%\PEPETII.DanmuAI\`；更新仍依赖 Velopack 自身定位 `Update.exe` 与 manifest，因此自定义安装根不会破坏应用内就地更新。

## 卸载基线

- 官方卸载入口仍是 Windows“应用和功能 / 程序和功能”里的 Velopack 卸载项。
- 应用内提供托盘“卸载应用”入口，实际仍调用同一个 Velopack `Update.exe --uninstall`。
- 默认仅删除程序目录，不删除 `%APPDATA%\DanmuAI\`。
- 若用户显式选择“卸载并删除用户数据”，需要二次确认；确认后通过 `on_before_uninstall_fast_callback` 删除 `%APPDATA%\DanmuAI\`。

## 明确禁止

- 不回退到 COS / Inno Setup / zip 主分发。
- 不把 R2 凭证写入仓库。
- 不在客户端实现自研 patch 生成、diff 或补丁合并。
- 不默认删除 `%APPDATA%\DanmuAI\`。

## 相关文档

- [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md)
- [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md)
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
- [reports/windows-release-post-freeze.md](../../reports/windows-release-post-freeze.md)
