# W-REL-CLEANUP-001 执行提示词

> 你只执行**当前工单**，不要实现未来功能，不要顺手重构无关代码，不要自行决定新的发布架构。

---

## 当前工单

- **工单 ID**：`W-REL-CLEANUP-001`
- **标题**：清除旧 `DanmuAI-windows-x64.zip` / `MSI` / 旧命名安装产物链路，对外发布统一收敛为 `Setup.exe + Portable.zip`，并归档历史链路

## 执行前必须阅读

1. [AGENTS.md](../../AGENTS.md)
2. [.local-ai/prompts/IDE_AGENT_RULES.md](../../.local-ai/prompts/IDE_AGENT_RULES.md)
3. [docs/operations/WINDOWS_RELEASE_CONTRACT.md](./WINDOWS_RELEASE_CONTRACT.md)
4. [docs/operations/PACKAGING_WINDOWS.md](./PACKAGING_WINDOWS.md)
5. [docs/operations/RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md)
6. [README.md](../../README.md)
7. [scripts/upload_r2_release.ps1](../../scripts/upload_r2_release.ps1)
8. [scripts/upload_github_release.ps1](../../scripts/upload_github_release.ps1)
9. [scripts/publish_windows_release.ps1](../../scripts/publish_windows_release.ps1)
10. 本提示词下方“具体需求”“禁止修改区域”“验收标准”

## 目标

将当前 Windows 发布链整理为：

- **对外主入口**：`DanmuAI-Setup.exe`
- **对外便携入口**：`PEPETII.DanmuAI-win-Portable.zip`

并完成以下收敛：

- 停止生成、上传、文档引用旧 `DanmuAI-windows-x64.zip`
- 停止生成、上传、文档引用 `MSI`
- 将仓库内历史旧发布产物与旧链路残留归档到 `release/_legacy_local/`
- 将 `release/_legacy_local/` 加入 Git 忽略，禁止后续误提交
- 删除线上旧文件，但**不得**误删支撑 `Setup.exe` / `Portable.zip` 正常发布、升级、追溯所必需的内部文件

## 官方前提

本工单的“只保留 `Setup.exe + Portable.zip`”仅指：

- **用户可见的对外发布入口**
- **对外文档与下载说明**
- **正式上传与镜像出口**

本工单**不是**简单粗暴删除一切非这两个文件的内部资产。凡是支撑 `Setup.exe` / `Portable.zip` 正常发布、别名分发、升级、追溯所需的内部文件，必须先识别、列白名单、再保留。

## 必须遵守

1. 不得为了“表面只剩两个文件”而破坏当前 `Setup.exe` / `Portable.zip` 的发布或更新链。
2. 必须先识别“内部必需资产白名单”，再删除旧链路和线上旧文件。
3. `release/_legacy_local/` 仅用于本地/仓库内历史归档；该目录必须被 Git 忽略。
4. 不得引入新安装器技术栈；不得改成 Inno Setup、NSIS、自研安装器。
5. 不得修改 R2 / GitHub / Supabase 凭证管理方式。
6. 不得顺手修改 Windows 发布链之外的业务逻辑。
7. 线上旧文件删除必须以“删除废弃入口、保留新链路必需资产”为原则，禁止无清单删除。

## 允许修改的区域

```text
README.md
.gitignore
website/index.html
web/static/modules/app-update-banner.js
app/release_channels.py
supabase/migrations/003_app_updates.sql
supabase/README.md
scripts/publish_windows_release.ps1
scripts/upload_r2_release.ps1
scripts/upload_github_release.ps1
scripts/README.md
docs/operations/WINDOWS_RELEASE_CONTRACT.md
docs/operations/PACKAGING_WINDOWS.md
docs/operations/RELEASE_CHECKLIST.md
docs/operations/*.md
docs/release/*.md
release/
tests/test_release_channels.py
reports/
```

## 禁止修改的区域

```text
app/（除 app/release_channels.py 外）
main.py
tests/（除 tests/test_release_channels.py 外）
requirements.txt
requirements-dev.txt
package.json
锁文件
.env / 凭证 / 密钥文件
与 Windows 发布链无关的任意代码路径
```

## 具体需求

### 1. 先做内部资产盘点，再动删除逻辑

先识别并明确三类文件：

1. **对外发布物**
   - `DanmuAI-Setup.exe`
   - `PEPETII.DanmuAI-win-Portable.zip`
2. **内部必需资产**
   - 一切支撑 `Setup.exe` / `Portable.zip` 正常发布、别名分发、升级、追溯所需的完整内部文件集合
   - 例如：版本化产物、feed、更新包、别名复制依赖文件（是否保留以实际链路核实为准）
3. **历史废弃资产**
   - 旧 zip
   - `MSI`
   - 已废弃旧命名入口
   - 不再参与当前正式发布链的历史残留文档/脚本引用/本地产物

要求：

- 在代码或文档改动前，先将“内部必需资产白名单”落到文档中
- 白名单必须清楚说明“为什么保留”
- 后续清理动作必须以该白名单为边界

### 2. 停止旧 zip 链路

停止生成、上传、文档引用以下旧链路：

- `DanmuAI-windows-x64.zip`
- `DanmuAI-windows-x64.zip.sha256`

要求：

- 当前有效脚本中不得再生成它们
- 当前有效脚本中不得再上传它们
- 当前有效文档中不得再把它们当作有效下载物

### 3. 停止 MSI 链路

停止生成、上传、文档引用所有 `MSI` 相关链路。

要求：

- `MSI` 不再作为对外入口
- `MSI` 不再作为备选入口
- 当前发布脚本不再以 `MSI` 为目标产物
- 当前 R2 / GitHub 上传脚本不再上传 `MSI`
- 文档中不再把 `MSI` 描述为推荐下载、主入口或备选入口

### 4. 收敛对外发布入口

统一全仓对外发布口径为：

- 主下载：`DanmuAI-Setup.exe`
- 便携版：`PEPETII.DanmuAI-win-Portable.zip`

要求：

- `README.md`
- `website/index.html`
- `web/static/modules/app-update-banner.js`
- `app/release_channels.py`
- `supabase/migrations/003_app_updates.sql`
- `supabase/README.md`
- `docs/operations/*`
- `docs/release/*`

以上所有当前有效路径中的下载入口与文案必须统一。

### 5. 归档历史链路

将仓库内历史旧发布产物与历史旧链路残留归档到：

```text
release/_legacy_local/
```

要求：

- 仅归档历史废弃资产
- 不得把当前新链路仍依赖的内部必需资产错误移入归档目录
- 为该目录新增简短说明文档，说明其用途、来源、为什么禁止提交

### 6. Git 忽略规则

更新 `.gitignore`：

- 忽略 `release/_legacy_local/`
- 防止后续将历史归档重新提交入库

### 7. 线上旧文件删除方案

工单必须产出明确的线上删除清单与保留清单。

要求：

- 删除废弃线上文件
- 保留新链路必需文件
- 不能写成模糊描述，必须列到文件名/文件模式级别
- 删除动作若不在本工单直接执行，也必须在报告中给出运维可执行清单

### 8. 发布脚本收敛

检查并修改：

- `scripts/publish_windows_release.ps1`
- `scripts/upload_r2_release.ps1`
- `scripts/upload_github_release.ps1`
- 其他实际参与当前 Windows 发布链的脚本

要求：

- 脚本只面向新链路
- 保留并整理新链路所需内部资产
- 不再引用旧 zip / `MSI`
- 不再对外输出旧入口 URL

### 9. 发布契约与检查清单同步

同步更新：

- `docs/operations/WINDOWS_RELEASE_CONTRACT.md`
- `docs/operations/PACKAGING_WINDOWS.md`
- `docs/operations/RELEASE_CHECKLIST.md`
- `scripts/README.md`

要求：

- 明确区分“对外发布物 / 内部必需资产 / 历史废弃资产”
- 明确当前正式策略为 `Setup.exe + Portable.zip`
- 明确历史归档路径与 Git 忽略策略

## 非目标

- 不重写桌面程序业务代码
- 不替换 Velopack
- 不重做自动更新机制
- 不处理代码签名
- 不修复与本工单无关的发布问题
- 不删除未核实用途的内部更新资产
- 不修改非 Windows 发布链功能

## 验收标准

- [ ] 已输出“内部必需资产白名单”，并写明每项保留原因
- [ ] 当前有效流程不再生成 `DanmuAI-windows-x64.zip`
- [ ] 当前有效流程不再上传 `DanmuAI-windows-x64.zip`
- [ ] 当前有效流程不再生成 `MSI`
- [ ] 当前有效流程不再上传 `MSI`
- [ ] `README.md`、官网、发布文档、应用内手动下载链接仅保留 `Setup.exe` 与 `Portable.zip`
- [ ] `DanmuAI-Setup.exe` 为唯一主推荐入口
- [ ] `PEPETII.DanmuAI-win-Portable.zip` 为唯一便携入口
- [ ] `release/_legacy_local/` 已创建
- [ ] `release/_legacy_local/` 已加入 `.gitignore`
- [ ] 仓库内历史旧发布产物已迁入 `release/_legacy_local/` 或清理
- [ ] 发布脚本已收敛到新链路
- [ ] 发布契约文档已统一
- [ ] 已产出线上删除清单与保留清单
- [ ] 新链路未被破坏，`Setup.exe` / `Portable.zip` 所需内部资产完整可用

## 手动验证步骤

1. 全局搜索以下关键字，确认当前有效路径不再使用它们：
   - `DanmuAI-windows-x64.zip`
   - `Installer.msi`
   - `PEPETII.DanmuAI-win-Setup.exe`
2. 检查 `README.md` 下载说明，仅保留 `DanmuAI-Setup.exe` 与 `PEPETII.DanmuAI-win-Portable.zip`
3. 检查 `website/index.html` 下载区，确认无旧 zip、无 `MSI`
4. 检查 `scripts/publish_windows_release.ps1`，确认只面向新链路
5. 检查 `scripts/upload_r2_release.ps1` 与 `scripts/upload_github_release.ps1`，确认无旧 zip / `MSI` 上传逻辑
6. 检查 `docs/operations/WINDOWS_RELEASE_CONTRACT.md`，确认契约已统一
7. 检查 `.gitignore`，确认 `release/_legacy_local/` 被忽略
8. 检查 `release/_legacy_local/` 中仅包含历史废弃资产，不包含当前新链路依赖文件
9. 核对线上删除清单与保留清单
10. 完成一次本地发布演练，确认 `Setup.exe` / `Portable.zip` 及其内部更新链资产完整可用

## 已知风险与注意事项

1. **最大风险是误删内部必需资产**：必须先盘点白名单，再做删除。
2. **“对外只保留两个文件”不等于“内部只允许两个文件”**：若链路需要版本化资产、feed、更新包，必须保留。
3. **线上删除风险高**：任何线上删除动作都必须先有白名单与删除清单。
4. **历史 release note 可能仍有旧引用**：若属于历史归档，可保留在归档区；若属于当前有效文档，必须修正。
5. **归档目录禁止提交**：若 `.gitignore` 未生效，后续很容易被误提交。

## 如果发现范围外问题

不要顺手修复。记录到完成报告“发现但未处理的问题”章节，必要时单开后续工单。

## 完成后必须给出

1. 修改文件列表
2. 内部必需资产白名单
3. 历史废弃资产清单
4. 线上保留清单
5. 线上删除清单
6. 归档目录说明
7. 新发布链说明（用户可见层）
8. 剩余风险与未处理问题

## 完成后报告格式

使用项目现有完成报告模板；必须明确区分：

- 已完成
- 未完成
- 明确放弃
- 发现但未处理
