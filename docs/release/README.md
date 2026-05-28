# Release notes

GitHub Release 正文可从此目录复制。

| 版本 | 文档 | 建议 tag | Windows 附件 |
|------|------|----------|----------------|
| 2026-05-29 | [2026-05-29.md](2026-05-29.md) | `v2026.05.29` | `release/DanmuAI-windows-x64.zip`（本地构建，已 gitignore） |
| 2026-05-27 | [2026-05-27.md](2026-05-27.md) | `v2026.05.27` | 同上 |

## Windows x64 构建

在仓库根目录执行（需 Windows + Python 3.12+）：

```powershell
.\scripts\publish_windows_release.ps1
```

产物（不入库）：

| 路径 | 说明 |
|------|------|
| `release/DanmuAI-windows-x64/` | 完整 onedir，直接运行 `DanmuAI.exe` |
| `release/DanmuAI-windows-x64.zip` | 上传 GitHub Release 的压缩包 |

等价于 `build_exe.ps1` → 复制 `dist\DanmuAI\` → 打 zip。构建前请退出正在运行的 `DanmuAI.exe`。

发布前检查：[RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md)
