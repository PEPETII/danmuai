# Windows 代码签名 — 后续阻塞项

> W-REL-R2V-SIGN-001：当前**无代码签名预算**，签名**不阻塞** R2 + Velopack 主链实施。

完整评估见 [reports/windows-code-signing-assessment.md](../../reports/windows-code-signing-assessment.md)。

## 预算与风险声明

| 项 | 说明 |
|----|------|
| 当前状态 | 无 EV/OV 代码签名证书预算 |
| 用户可见风险 | 未签名的 `Setup.exe` / `DanmuAI.exe` 可能触发 **Windows SmartScreen**「未知发布者」提示 |
| 承诺边界 | **无法承诺**彻底消除 SmartScreen；与下载源（R2 / GitHub）无关 |
| 用户操作 | 通常需「更多信息 → 仍要运行」；企业环境可能被策略拦截 |

## 证书类型对比（摘要）

| 类型 | SmartScreen | 成本 / 门槛 | CI 自动化 |
|------|-------------|-------------|-----------|
| 未签名 | 持续「未知发布者」 | 无 | — |
| OV 标准 | 证书声誉积累后缓解；续证后可能再警告 | 中；多为 USB HSM，PFX 导出受限 | USB HSM 需人工 PIN |
| EV 扩展验证 | **即时声誉** | 高；严格核验 + 硬件令牌 | 难 |
| Azure Artifact Signing | **即时声誉**（类 EV） | 约 USD $10/月 | **`az login` / OIDC**，最适合 CI |

依据 [Velopack Code Signing](https://docs.velopack.io/packaging/signing)：未签名按**文件**声誉；OV 按**证书**声誉；EV / Azure Artifact Signing 获即时 SmartScreen 信任。

**个人开发者长期首选候选**：Azure Artifact Signing（成本与自动化平衡）。传统 EV 在预算充足时 SmartScreen 体验最佳。

## 签名接入点（须在 vpk pack 阶段）

Velopack 要求在 **`vpk pack` 打包过程中**签名（`Update.exe`、Setup、nupkg 内 PE 分阶段生成）。**不推荐**仅在 PyInstaller 后或仅签最终 Setup。

| 阶段 | 接入位置 | 说明 |
|------|----------|------|
| 打包 | `velopack_pack.ps1` → `vpk pack ... --signParams` 或 `--azureTrustedSignFile` | 对 Setup、Update.exe 与包内 exe/dll 签名（默认签全部 PE） |
| 草案验签 | `scripts/sign_windows_release.ps1 -VerifyOnly` | `signtool verify`；**默认不执行**，需 `DANMU_CODE_SIGN=1` |
| 发布前（未来） | `publish_windows_release.ps1` 后可选验签 | 证书就绪后由 SIGN-005 接入，**非**默认路径 |
| 上传前（未来） | `upload_r2_release.ps1` | `DANMU_REQUIRE_SIGNED=1` 时拒绝未签名产物（可选门禁） |
| 文档 | [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)、[README.md](../../README.md) | 更新对外说明与检查项 |

### 应签文件

- `DanmuAI.exe`、`_internal` 下 exe/dll/pyd（Velopack 默认）
- Velopack 注入的 `Update.exe`
- `PEPETII.DanmuAI-*-Setup.exe`（含 R2 `downloads/DanmuAI-Setup.exe` 别名源）
- `*-full.nupkg` 内 PE（应用内更新须与首装签名一致）

## 环境变量（仅维护者本机 / CI secret，禁止入库）

| 变量 | 用途 |
|------|------|
| `DANMU_CODE_SIGN` | `1` = 启用签名或验签草案脚本；默认未设置 = 关闭 |
| `VPK_SIGN_PARAMS` | 传给 `vpk pack --signParams`（signtool 参数，不含 `sign` 子命令） |
| `VPK_AZURE_TRUSTED_SIGN_FILE` | Azure Artifact Signing 元数据 JSON **路径**（文件不入库） |
| `DANMU_REQUIRE_SIGNED` | 未来上传门禁（可选，默认关闭） |

Velopack CLI 选项亦可映射为 `VPK_*` 环境变量（见 [Packaging Overview](https://docs.velopack.io/packaging/overview)）。

**禁止入库**：PFX、证书密码、Token PIN、Azure 密钥、含 secret 的 metadata JSON、base64 证书 blob。

## 签名后建议新增验收

- [ ] `PEPETII.DanmuAI-*-Setup.exe` Authenticode 签名有效、RFC 3161 时间戳存在
- [ ] `signtool verify /pa /v` 对 Setup 通过
- [ ] 全新 Windows 10/11 VM：SmartScreen 不再拦截（或显著减少；OV 可能仍有短期警告）
- [ ] 应用内更新下载的二进制签名与首装一致
- [ ] 产物与 Git 中**无** PFX / 证书文件
- [ ] `THIRD_PARTY_NOTICES.md` 记录证书供应商与 HSM 要求（若适用）

## 后续实施工单

| 工单 | 内容 |
|------|------|
| SIGN-002 | 证书选型（ATS / OV / EV） |
| SIGN-003 | 本机单文件 `signtool` 验证 |
| SIGN-004 | `velopack_pack.ps1` 签名门控 |
| SIGN-005 | 验签 + RELEASE_CHECKLIST |
| SIGN-006 | VM SmartScreen 实测 |
| SIGN-007（可选） | CI OIDC 签名 |

## 相关文档

- [windows-code-signing-assessment.md](../../reports/windows-code-signing-assessment.md) — 独立评估报告
- [WINDOWS_RELEASE_CONTRACT.md](WINDOWS_RELEASE_CONTRACT.md) §5 无签名边界
- [PACKAGING_WINDOWS.md](PACKAGING_WINDOWS.md)
- [Velopack Code Signing](https://docs.velopack.io/packaging/signing)
