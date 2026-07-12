"""ConfigStore 包：保持向后兼容的重新导出。

原 ``app/config_store.py``（单文件）已拆分为子包：
- ``storage.py``：``ConfigStore`` 类主体、常量、``_HAS_CRYPTO``
- ``crypto.py``：Fernet 加密辅助、密钥管理、异常类
- ``pool.py``：自定义弹幕池 CRUD 函数重新导出（实现仍位于 ``app/danmu_pool.py``）
- ``storage_meme.py``：烂梗库 ``meme_barrage_library`` 表 CRUD 实现
- ``storage_models.py``：custom_models 档案与 API Key 加解密读写实现
- ``storage_legacy.py``：system_flags 读写与 legacy API 启动期迁移

所有原 ``from app.config_store import X`` 调用方无需改动。
``patch("app.config_store._HAS_CRYPTO", ...)`` 通过 ``storage.py`` 内的
``_cs_pkg._HAS_CRYPTO`` 属性访问形式生效。

``os`` / ``subprocess`` 在原单文件中为模块级 import，被测试以
``monkeypatch.setattr("app.config_store.os.name", ...)`` /
``patch("app.config_store.subprocess.run")`` 方式 patch；此处重新导入以保留这些
属性路径（``os`` / ``subprocess`` 为模块单例，patch 经包属性解析后仍作用于
``crypto.py`` 内同名 import 的同一模块对象）。
"""
import os  # noqa: F401 — 重新导出以保留 app.config_store.os 属性路径（测试 monkeypatch 依赖）
import subprocess  # noqa: F401 — 重新导出以保留 app.config_store.subprocess 属性路径（测试 patch 依赖）

from .storage import (
    CONFIG_DIR,
    CONFIG_FILE,
    _HAS_CRYPTO,
    _KEY_FILE,
    _SQLITE_CACHED_STATEMENTS,
    _SENSITIVE_CONFIG_KEYS,
    _redact_config_value_for_log,
    ConfigStore,
)
from .crypto import (
    ConfigStoreCryptoUnavailableError,
    _backup_corrupted_key_file,
    _migrate_custom_model_shape,
    canonicalize_custom_model_profile,
    _restrict_key_file_permissions,
)
from .pool import (
    get_custom_danmu_pool_for_store,
    set_custom_danmu_pool_for_store,
)

__all__ = [
    "ConfigStore",
    "ConfigStoreCryptoUnavailableError",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "get_custom_danmu_pool_for_store",
    "set_custom_danmu_pool_for_store",
    "_restrict_key_file_permissions",
    "_migrate_custom_model_shape",
    "canonicalize_custom_model_profile",
    "_HAS_CRYPTO",
]
