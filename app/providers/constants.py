"""Shared provider HTTP constants (avoid circular imports with ai_client).

独立模块原因：``THINKING_DISABLED`` 同时被 ``ai_client`` 与 ``providers/adapters`` 引用，
将其放在最底层（不导入 PyQt、不导入 ai_client）可避免循环依赖。
"""

# 思考模式 payload：豆包/MiMo 等 Responses 或 Chat Completions 路径的 thinking 字段。
# disabled 用于关闭思考（避免返回 reasoning_content 或空内容）；enabled 用于开启思考模式。
# 详见 docs/ai-project-context.md「思考模式」一节。
THINKING_DISABLED = {"type": "disabled"}
THINKING_ENABLED = {"type": "enabled"}
