"""Boundary guard rule checks — 规则子包。

每个子模块负责一个职责域：
    web         Web 控制台 / API（不允许读私有字段、不允许绕过 ConfigService）
    runtime     运行时状态文档、线程模型文档、移除 LEGACY_RUNTIME_* 直写
    request     请求调度、timing service、metadata 边界
    config      配置连通性、ConfigService 委派、默认模型选择
    pipeline    生成管线投影、状态文件读写
    diagnostics 诊断快照（/api/diagnostics 经此出口，禁止 HTTP 直读私有字段）
    status      status snapshot 构造委派给 application/status_snapshot.py
    baseline    final-architecture-baseline.md 存在性

所有 ``check_*`` 函数签名一致：``(repo_root: Path, changed: dict[Path, str]) -> list[Finding]``；
个别全局规则只读 ``repo_root`` 即可。
"""
