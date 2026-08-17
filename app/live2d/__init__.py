"""独立的 Live2D 虚拟主播运行时候选。

该包只提供模型、渲染和参数控制边界，不在导入时创建 Qt/Live2D 对象，
也不依赖桌宠、Overlay、Web API 或 DanmuApp。正式装配须等待 001 门禁。
"""

from .host import HostResult, HostState, Live2DHostFacade
from .model_loader import (
    Live2DModelLoader,
    ModelCapabilities,
    ModelLoadResult,
    ParameterSpec,
)
from .parameters import Live2DParameterController, ParameterUpdate
from .renderer import (
    Live2DRenderBackend,
    Live2DRenderer,
    QtOpenGLLive2DBackend,
    RendererState,
)

__all__ = [
    "HostResult",
    "HostState",
    "Live2DHostFacade",
    "Live2DModelLoader",
    "Live2DParameterController",
    "Live2DRenderBackend",
    "Live2DRenderer",
    "ModelCapabilities",
    "ModelLoadResult",
    "ParameterSpec",
    "ParameterUpdate",
    "QtOpenGLLive2DBackend",
    "RendererState",
]
