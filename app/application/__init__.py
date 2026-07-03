"""DanmuApp 边界收口层：只读投影、状态快照与 Web 配置写入。

例外（W-GENPIPELINE-EXTRACT）：generation_pipeline.py 承载回复消费与三路分发，
经 app.reply_timer.start() 驱动；该文件由 check_generation_pipeline_service 规则治理。
其余模块不含 QTimer/QThreadPool、不触发主链路；详见 docs/final-architecture-baseline.md。

层级约束（application/ 只读消费 DanmuApp 时）：
    - 禁止经 getattr 读取 DanmuApp 以下划线开头的属性
    - 禁止经实例 __dict__ 直读私有字段
    - 禁止 _safe_app_attr 访问以下划线开头的属性名
    - 禁止调用 DanmuApp 以下划线开头的私有方法（如 live status 组装）
    - 只读数据须经 DanmuApp 公开 property 或 DanmuAppWebFacadeMixin 方法
    - generation_pipeline.py 行为层可写回 DanmuApp 字段（由 boundary_guard 治理），
      但读路径仍应优先公开 façade（如 optional_* 访问器）
"""
