"""ConfigStore 子包：自定义弹幕池 CRUD 函数的重新导出。

历史上下文：``get_custom_danmu_pool_for_store`` / ``set_custom_danmu_pool_for_store``
的实际实现位于 ``app/danmu_pool.py``（``ConfigStore`` 通过方法内的局部 import 调用它们）。
本模块仅提供向后兼容的导入路径，使 ``from app.config_store import get_custom_danmu_pool_for_store``
可用；不复制任何业务逻辑，``app/danmu_pool.py`` 未做任何改动。
"""
from app.danmu_pool import (
    get_custom_danmu_pool_for_store,
    set_custom_danmu_pool_for_store,
)

__all__ = [
    "get_custom_danmu_pool_for_store",
    "set_custom_danmu_pool_for_store",
]
