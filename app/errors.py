"""DanmuAI 统一异常层次。

推荐捕获顺序：``AppError`` 子类 → 标准库具体异常 → 顶层边界兜底（日志 + HTTP 500）。

本模块仅定义类型锚点；全项目迁移到子类分多工单逐步推进。
"""

from __future__ import annotations


class AppError(Exception):
    """所有项目自定义异常的基类。"""


class ValidationError(AppError):
    """输入校验失败。"""


class NotFoundError(AppError):
    """资源未找到。"""


class AuthError(AppError):
    """鉴权失败。"""


class ConfigError(AppError):
    """配置相关错误。"""


class TtsError(AppError):
    """TTS 请求或响应解析失败。"""
