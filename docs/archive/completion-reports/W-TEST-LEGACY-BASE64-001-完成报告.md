# Codex 完成报告

> 工单 ID：W-TEST-LEGACY-BASE64-001  
> 完成时间：2026-06-02  
> 执行者：Codex

---

## 1. 修改摘要

修复 `ConfigStore.get_api_key()` 与 `get_tts_api_key()` 的边界缺陷：当 `*_encrypted` 存在但解密失败时，不再直接返回空串，而是继续回退到 legacy base64 的 `*_encoded`。新增 `test_decrypt_failure_with_legacy_base64_keeps_old_key` 验证旧 key 可继续读取。

## 2. 修改的文件

- `app/config_store.py`
- `tests/test_p1_key_encryption.py`
- `docs/bug-audit/TEST-GAPS.md`
- `docs/当前仓库状态.md`
- `docs/工单列表.md`
- `docs/templates/Codex完成报告/W-TEST-LEGACY-BASE64-001-完成报告.md`

## 3. 未修改的关键区域

- 未修改 `main.py`：是
- 未修改 `web/static/**`：是
- 未修改 `community-site/**`：是
- 未修改 `supabase/**`：是

## 4. 运行的命令

```bash
python -m pytest tests/test_p1_key_encryption.py tests/test_config_store.py -q
python scripts/boundary_guard.py
```

## 5. 构建/测试结果

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `tests/test_p1_key_encryption.py tests/test_config_store.py` | 通过 | `22 passed` |
| boundary_guard | 通过 | `Boundary Guard: PASS` |

## 6. 手动验证步骤

| 步骤 | 预期 | 实际 | 通过 |
|------|------|------|------|
| 1 | 加密值损坏但 legacy base64 仍在时，继续读取旧 key | 返回旧 key 而不是空串 | `test_decrypt_failure_with_legacy_base64_keeps_old_key` 通过 | 是 |

## 7. 风险与注意事项

- 本票只修复 legacy fallback 行为，不改变 Fernet 正常读写路径。
- `api_key_encoded` / `tts_api_key_encoded` 仍是不安全兼容存储，仅用于历史回退。

## 8. 发现但未处理的问题

- `TEST-GAPS` 仍有端口占用恢复、完整 happy path、渲染性能、长期稳定性等后续维护项。

## 9. 已更新的文档

- [x] [docs/bug-audit/TEST-GAPS.md](../../bug-audit/TEST-GAPS.md)
- [x] [docs/当前仓库状态.md](../../当前仓库状态.md)
- [x] [docs/工单列表.md](../../工单列表.md)
- [x] 本完成报告

## 10. 建议下一个工单

- 下一张更像产品/运行态问题的最小票：端口占用恢复，或完整 happy path。
