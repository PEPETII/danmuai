# Codex 完成报告

> 工单 ID：Windows 发布链 1/2/3 收口  
> 完成时间：2026-06-13  
> 执行者：Codex

---

## 1. 修改摘要

本次按顺序完成了 Windows 发布链的 3 个目标：增量更新发布链、首装自定义路径验证、卸载入口与用户数据保留。  
发布脚本已支持 `full + delta` 双轨产物，并在本地缺少历史 full 包时从 stable feed bootstrap 后再打包。  
客户端仍沿用 Velopack 官方 `UpdateManager` / `Update.exe` 机制，没有引入自研 patch 生成或合并逻辑。  
卸载默认保留 `%APPDATA%\DanmuAI\`，仅在用户显式选择且二次确认后才删除用户数据。

## 2. 修改的文件

- `E:/test/danmu/scripts/publish_windows_release.ps1`
- `E:/test/danmu/scripts/velopack_pack.ps1`
- `E:/test/danmu/scripts/upload_r2_release.ps1`
- `E:/test/danmu/scripts/upload_github_release.ps1`
- `E:/test/danmu/app/uninstall_service.py`
- `E:/test/danmu/app/velopack_runtime.py`
- `E:/test/danmu/app/tray.py`
- `E:/test/danmu/tests/test_uninstall_service.py`
- `E:/test/danmu/tests/test_velopack_runtime.py`
- `E:/test/danmu/tests/test_web_launch.py`
- `E:/test/danmu/docs/operations/WINDOWS_RELEASE_BASELINE.md`
- `E:/test/danmu/docs/operations/WINDOWS_RELEASE_CONTRACT.md`
- `E:/test/danmu/docs/operations/PACKAGING_WINDOWS.md`
- `E:/test/danmu/docs/operations/RELEASE_CHECKLIST.md`
- `E:/test/danmu/docs/release/README.md`
- `E:/test/danmu/scripts/README.md`
- `E:/test/danmu/reports/windows-release-final-check.md`

## 3. 未修改的关键区域

- 未修改 `app/`：否（仅修改 `app/tray.py`、`app/velopack_runtime.py`，新增 `app/uninstall_service.py`）
- 未修改 `web/`：否（本工单未以 `web/` 为核心落点；工作树存在既有改动，但本工单目标未依赖 `web/`）
- 未修改 `main.py`：是
- 其他：
  - 未在客户端实现自研 patch 生成/合并
  - 未将 R2 凭证、安装路径密钥写入仓库
  - 未改回 COS / Inno Setup / zip 主分发
  - 未默认删除 `%APPDATA%\DanmuAI\`

## 4. 运行的命令

```bash
python -m pytest E:/test/danmu/tests/test_uninstall_service.py -q -x
python -m pytest E:/test/danmu/tests/test_velopack_runtime.py -q -x
python -m pytest E:/test/danmu/tests/test_update_api.py -q -x
python -m pytest E:/test/danmu/tests/test_web_launch.py -q -x
python -m py_compile E:/test/danmu/app/uninstall_service.py E:/test/danmu/app/tray.py E:/test/danmu/app/velopack_runtime.py

E:/test/danmu/release/velopack/PEPETII.DanmuAI-0.3.1-Setup.exe --silent --installto E:/test/danmu/.tmp/velopack-install-verify2
E:/test/danmu/.tmp/velopack-install-verify2/Update.exe uninstall --silent
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 分批测试（IDE_AGENT_RULES §10） | 通过 | 仅运行相关测试文件，未执行全量 pytest |
| boundary_guard | 未运行 | 本工单不触及主链路调度与 boundary_guard 规则 |
| py_compile | 通过 | `app/uninstall_service.py`、`app/tray.py`、`app/velopack_runtime.py` |
| 实机安装/卸载验证 | 通过 | 自定义安装路径 + 默认卸载保留 `%APPDATA%` 数据 |
| 发布产物核对 | 通过 | `releases.win.json` 含 `0.3.1 Full`、`0.3.1 Delta`、`0.3.0 Full` |

### 5.1 分批测试报告（代码工单）

- **未执行全量**：确认未运行 `pytest` / `pytest tests` / `python -m pytest`（无文件参数）
- **批次 1**：`python -m pytest E:/test/danmu/tests/test_uninstall_service.py -q -x`，`3 passed`
- **批次 2**：`python -m pytest E:/test/danmu/tests/test_velopack_runtime.py -q -x`，`3 passed`
- **批次 3**：`python -m pytest E:/test/danmu/tests/test_update_api.py -q -x`，`4 passed`
- **批次 4**：`python -m pytest E:/test/danmu/tests/test_web_launch.py -q -x`，`15 passed`
- **未覆盖说明**：未跑与本工单无关的主链路、麦克风、人格、前端其余批次
- **结论**：相关批次足以支撑本工单验收

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | `release/velopack/releases.win.json` 同时含 Full + Delta | 实际包含 `0.3.1 Full`、`0.3.1 Delta`、`0.3.0 Full` | 是 |
| 2 | `Setup.exe --installto <DIR>` 可安装到自定义路径 | `PEPETII.DanmuAI-0.3.1-Setup.exe --silent --installto E:/test/danmu/.tmp/velopack-install-verify2` 成功，`exit=0` | 是 |
| 3 | 自定义路径安装后仍通过 Velopack 卸载 | `Update.exe uninstall --silent` 成功，`exit=0` | 是 |
| 4 | 默认卸载后程序目录删除 | `E:/test/danmu/.tmp/velopack-install-verify2` 已删除 | 是 |
| 5 | 默认卸载后 `%APPDATA%/DanmuAI/config.db`、`.key` 保留 | 隔离伪造的 `config.db`、`.key` 均仍存在 | 是 |

## 7. 风险与注意事项

- `release/velopack/releases.win.json` 当前为本地验证产物，若后续重新打包或清理产物目录，需要重新确认 feed 仍含 `Full + Delta`。
- `app/version.py` 已回退到 `0.3.0` 源码基线；本次 `0.3.1` 仅用于验证产物与升级链，不应误当作源码待发布版本。
- 卸载删除用户数据依赖 Velopack fast callback，必须保持“先在 UI 收集确认，再在 callback 内快速执行删除”的模式，不能把交互搬进 callback。

## 8. 发现但未处理的问题

| 问题 ID | 简述 | 已记录 |
|---------|------|--------|
| 无 | 无 | 是 |

## 9. 已更新的文档

- [ ] `docs/workflow/当前仓库状态.md`
- [ ] `docs/workflow/工单列表.md`
- [x] 其他：`docs/operations/WINDOWS_RELEASE_BASELINE.md`
- [x] 其他：`docs/operations/WINDOWS_RELEASE_CONTRACT.md`
- [x] 其他：`docs/operations/PACKAGING_WINDOWS.md`
- [x] 其他：`docs/operations/RELEASE_CHECKLIST.md`
- [x] 其他：`docs/release/README.md`
- [x] 其他：`scripts/README.md`

## 10. 建议下一个工单

- 将本地已验证的 `0.3.1` 产物在受控环境中完成正式上传，并对线上 `releases.win.json` 做一次发布后核对。
