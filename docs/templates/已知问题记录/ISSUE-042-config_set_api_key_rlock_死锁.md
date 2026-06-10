# ISSUE-042 — `ConfigStore.set_api_key` 与 `set` 嵌套持非可重入锁死锁

## 问题 ID

ISSUE-042

## 发现时间

2026-06-08

## 发现来源

W-RACE-001 验证全量 pytest 时发现 `tests/test_p1_key_encryption.py::TestP1002_Base64FallbackWarning::test_warning_when_setting_api_key_without_crypto` 在 `_write_lock.acquire()` 死锁。

## 所属模块

`app/config_store.py`、`tests/test_p1_key_encryption.py`

## 问题描述

`app/config_store.py:263-286` `set_api_key(key)`：

```python
def set_api_key(self, key: str):
    with self._write_lock:           # 第一次获取（非可重入 Lock）
        ...
        else:
            ...
            self.set("api_key_encoded", encoded)   # 第二次获取 → 死锁
```

`self.set` 内部 (`app/config_store.py:178`) 也 `with self._write_lock`。`threading.Lock` **非可重入**，同线程第二次 `acquire()` 永久阻塞。

W-CONC-001（commit `54bd8ba`）重构 `set_api_key` 时将 `with self._write_lock:` 提到方法最外层，但 `else` 分支保留对 `self.set(...)` 的调用，导致嵌套持锁。

## 影响范围

- 仅开发/测试：生产路径 `set_api_key` 走加密分支（`if _HAS_CRYPTO and self._fernet`），仅当用户安装 `cryptography` 失败、且无 Fernet 密钥时退化到 base64 分支；该退化路径在生产主流程不会触发。
- 测试：`test_p1_key_encryption.py` 的 base64 降级用例在 `_write_lock.acquire()` 永久阻塞，单条测试 30s 内不返回。

## 严重程度

中

## 是否阻塞当前工单

否：W-RACE-001 验证通过 `--ignore=tests/test_p1_key_encryption.py` 跳过该文件，全量 pytest 其他用例 1059 passed, 4 skipped。修复 ISSUE-042 需要 W-CONC-001 范围内的代码改动（`app/config_store.py` / `tests/test_p1_key_encryption.py`），不在 W-RACE-001 范围。

## 临时处理方式

W-RACE-001 验证时 `--ignore=tests/test_p1_key_encryption.py --ignore=tests/test_p1_sqlite_concurrency.py` 跳过这两个挂起测试；其他用例全部通过。

## 建议后续工单

W-RLOCK-001：将 `ConfigStore._write_lock` 替换为 `threading.RLock`，或在 `set_api_key` 退化分支直接走 `self.conn.execute` + `self._cache[key] = value`（与加密分支对称），不再调用 `self.set`。

## 备注

- 复现：cd E:\test\danmu && .\.venv-build\Scripts\python.exe -m pytest "tests/test_p1_key_encryption.py::TestP1002_Base64FallbackWarning::test_warning_when_setting_api_key_without_crypto" -q --timeout=10
- 期望：1 passed；实际：30s 内 `_write_lock.acquire()` 阻塞后超时。
- 同一 commit 还引入 `test_acceptance_gates.py` 在 `git_diff.read_text` 偶发卡死（与本 ISSUE 无关，独立问题，可选登记）。
- 关联 commit：`54bd8ba 提交当前项目更改（不包含 Markdown 文件）`（W-CONC-001）。
