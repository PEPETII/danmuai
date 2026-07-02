"""DanmuAI 运行期环境变量注册表（AGENTS.md A.6 为权威表）。

刻意保持极简：单一 dataclass + dict + getter，无校验器 / 无副作用 / 无框架。
新增 env 只需在 REGISTRY 加一行 + 调用点用 ``get_env``。零依赖（仅 os + dataclasses，
不 import Qt / app 任何模块），保证 ``main_launch.py`` 在 ``DanmuApp.__init__``
之前可安全调用。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EnvVar:
    name: str
    default: str
    desc: str


REGISTRY: dict[str, EnvVar] = {
    "DANMU_API_SCHEDULE_DEBUG": EnvVar("DANMU_API_SCHEDULE_DEBUG", "", "API 调度日志"),
    "DANMU_MIN_API_INTERVAL_MS": EnvVar("DANMU_MIN_API_INTERVAL_MS", "", "防 API 冷启动连打(ms)"),
    "DANMU_REPLY_PIPELINE_LOG": EnvVar("DANMU_REPLY_PIPELINE_LOG", "", "主链路 reply pipeline 日志"),
    "DANMU_IMAGE_METRICS": EnvVar("DANMU_IMAGE_METRICS", "", "压缩指标 debug 日志"),
    "DANMU_DEDUP_PROFILE": EnvVar("DANMU_DEDUP_PROFILE", "", "去重统计 profile"),
    "DANMU_OVERLAY_PROFILE": EnvVar("DANMU_OVERLAY_PROFILE", "", "Overlay 渲染 profile 日志"),
    "DANMU_STARTUP_TRACE": EnvVar("DANMU_STARTUP_TRACE", "", "启动链路 trace 日志"),
    "DANMU_SUPABASE_URL": EnvVar("DANMU_SUPABASE_URL", "", "Supabase URL 覆盖"),
    "DANMU_SUPABASE_ANON_KEY": EnvVar("DANMU_SUPABASE_ANON_KEY", "", "Supabase anon key 覆盖"),
    "DANMU_QT_UI": EnvVar("DANMU_QT_UI", "", "启动即拒绝（与 --qt-ui 同效）"),
    "DANMU_WEB_CONSOLE": EnvVar("DANMU_WEB_CONSOLE", "", "启动即拒绝（=0 时）"),
    "DANMU_WEB_LAUNCH": EnvVar("DANMU_WEB_LAUNCH", "", "等同 --web-browser"),
    "DANMU_BILILIVE_DM_PUSH_URL": EnvVar("DANMU_BILILIVE_DM_PUSH_URL", "", "B站直播弹幕推送 URL"),
    "DANMU_BILILIVE_DM_PUSH": EnvVar("DANMU_BILILIVE_DM_PUSH", "", "B站直播弹幕推送开关（=0 关闭）"),
    "DANMU_BILILIVE_DM_PLUGIN_SECRET": EnvVar(
        "DANMU_BILILIVE_DM_PLUGIN_SECRET",
        "",
        "bililive_dm 插件桥接共享密钥（覆盖 secret 文件）",
    ),
}

__all__ = ["EnvVar", "REGISTRY", "get"]


def get(name: str, default: Optional[str] = None) -> str:
    """读取已注册的环境变量；default 为 None 时使用 REGISTRY 中的默认值。

    KeyError 表示该变量未注册——应先在 REGISTRY 加一行。
    """
    var = REGISTRY[name]
    return os.environ.get(name, default if default is not None else var.default)
