"""虚拟主播会话层的数据契约。

本模块只包含标准库 dataclass 和文本归一化，不依赖 Qt、Live2D、桌宠或
视觉请求运行态。动作是语义草稿，不能被本模块当作可执行指令处理。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal


def normalize_text(value: object) -> str:
    """折叠空白并去除首尾空格，避免原始模型文本直接进入上下文。"""

    return " ".join(str(value or "").split())


def _clip(value: object, max_chars: int) -> str:
    text = normalize_text(value)
    if max_chars <= 0:
        return ""
    return text[:max_chars].rstrip()


def _unique_texts(values: tuple[object, ...] | list[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class DanmuBatchCreated:
    """已接受的最终弹幕文本批次，不包含视觉模型原始 JSON。"""

    batch_id: str
    created_at: float
    source: str
    screenshot_id: int | str | None
    scene_generation: int
    lines: tuple[str, ...]
    ttl_seconds: float = 120.0

    MAX_LINES = 10
    DEFAULT_CHAR_BUDGET = 600

    def __post_init__(self) -> None:
        batch_id = normalize_text(self.batch_id)
        if not batch_id:
            raise ValueError("batch_id must not be empty")
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        lines = _unique_texts(tuple(self.lines))[: self.MAX_LINES]
        object.__setattr__(self, "batch_id", batch_id)
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(self, "source", normalize_text(self.source) or "visual")
        object.__setattr__(self, "scene_generation", int(self.scene_generation))
        object.__setattr__(self, "lines", lines)
        object.__setattr__(self, "ttl_seconds", float(self.ttl_seconds))

    @classmethod
    def from_lines(
        cls,
        *,
        batch_id: str,
        lines: list[str] | tuple[str, ...],
        created_at: float | None = None,
        source: str = "visual",
        screenshot_id: int | str | None = None,
        scene_generation: int = 0,
        ttl_seconds: float = 120.0,
        char_budget: int = DEFAULT_CHAR_BUDGET,
    ) -> "DanmuBatchCreated":
        """规范化、去重并按条数/字符预算截断批次。"""

        remaining = max(0, int(char_budget))
        clipped: list[str] = []
        seen: set[str] = set()
        for raw in lines:
            text = normalize_text(raw)
            if not text or text in seen or len(clipped) >= cls.MAX_LINES:
                continue
            if remaining <= 0:
                break
            text = text[:remaining].rstrip()
            if not text:
                break
            seen.add(text)
            clipped.append(text)
            remaining -= len(text)
        return cls(
            batch_id=batch_id,
            created_at=time.time() if created_at is None else created_at,
            source=source,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            lines=tuple(clipped),
            ttl_seconds=ttl_seconds,
        )

    @property
    def char_count(self) -> int:
        return sum(len(line) for line in self.lines)

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current - self.created_at > self.ttl_seconds

    def is_current(
        self,
        *,
        scene_generation: int | None,
        now: float | None = None,
    ) -> bool:
        if self.is_expired(now=now):
            return False
        return scene_generation is None or self.scene_generation == int(scene_generation)


@dataclass(frozen=True)
class SceneContext:
    """可驱动主播上下文的画面摘要，必须通过 generation 和 TTL 双门控。"""

    scene_generation: int
    summary: str = ""
    keywords: tuple[str, ...] = ()
    screenshot_id: int | str | None = None
    updated_at: float = 0.0
    ttl_seconds: float = 900.0

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        object.__setattr__(self, "scene_generation", int(self.scene_generation))
        object.__setattr__(self, "summary", _clip(self.summary, 240))
        object.__setattr__(self, "keywords", _unique_texts(tuple(self.keywords))[:16])
        object.__setattr__(self, "updated_at", float(self.updated_at))
        object.__setattr__(self, "ttl_seconds", float(self.ttl_seconds))

    @property
    def has_semantic_context(self) -> bool:
        return bool(self.summary or self.keywords)

    def is_fresh(
        self,
        *,
        scene_generation: int | None = None,
        now: float | None = None,
    ) -> bool:
        if scene_generation is not None and self.scene_generation != int(scene_generation):
            return False
        current = time.time() if now is None else float(now)
        return current - self.updated_at <= self.ttl_seconds


@dataclass(frozen=True)
class KnowledgeSourceRef:
    """知识命中对外可诊断的来源/条目标识。"""

    item_id: int | None = None
    public_id: str = ""
    source: str = ""


KnowledgeStatus = Literal["hit", "no_hit", "error", "unavailable"]


@dataclass(frozen=True)
class KnowledgeContextResult:
    """受预算约束的知识上下文；不承载整个知识库。"""

    status: KnowledgeStatus
    prompt_text: str = ""
    sources: tuple[KnowledgeSourceRef, ...] = ()
    item_ids: tuple[int, ...] = ()
    public_ids: tuple[str, ...] = ()
    hit_count: int = 0
    char_count: int = 0
    diagnostic: str = ""

    def __post_init__(self) -> None:
        text = normalize_text(self.prompt_text)
        object.__setattr__(self, "prompt_text", text)
        object.__setattr__(self, "char_count", len(text))
        object.__setattr__(self, "item_ids", tuple(int(i) for i in self.item_ids))
        object.__setattr__(self, "public_ids", tuple(normalize_text(i) for i in self.public_ids if i))
        object.__setattr__(self, "hit_count", max(0, int(self.hit_count)))
        object.__setattr__(self, "diagnostic", normalize_text(self.diagnostic))


@dataclass(frozen=True)
class ConversationTurn:
    turn_id: int
    user_text: str
    assistant_text: str


@dataclass(frozen=True)
class HostTurn:
    session_id: str
    turn_id: int
    created_at: float
    input_text: str
    mic_text: str = ""
    live_topic: str = ""
    scene_context: SceneContext | None = None
    recent_batches: tuple[DanmuBatchCreated, ...] = ()
    history: tuple[ConversationTurn, ...] = ()
    persona_system: str = ""
    persona_user: str = ""


@dataclass(frozen=True)
class BatchAcceptance:
    accepted: bool
    reason: Literal[
        "accepted",
        "duplicate",
        "expired",
        "scene_generation",
        "empty",
        "invalid",
        "mode_disabled",
    ]
    batch_id: str = ""


@dataclass(frozen=True)
class EmotionDraft:
    name: str
    intensity: float = 0.5

    def __post_init__(self) -> None:
        name = normalize_text(self.name)
        if not name:
            raise ValueError("emotion name must not be empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "intensity", max(0.0, min(1.0, float(self.intensity))))


@dataclass(frozen=True)
class ActionDraft:
    """有限语义动作草稿；没有自由文本 command 字段，也不会被自动执行。"""

    kind: Literal["expression", "gesture", "look_at", "idle"]
    intensity: float = 0.5
    duration_seconds: float = 1.0
    name: str = ""

    MAX_NAME_CHARS = 64

    def __post_init__(self) -> None:
        if self.kind not in {"expression", "gesture", "look_at", "idle"}:
            raise ValueError("unsupported semantic action")
        if self.name is None:
            name = ""
        elif not isinstance(self.name, str):
            raise TypeError("action name must be a string")
        else:
            name = _clip(self.name, self.MAX_NAME_CHARS)
        object.__setattr__(self, "intensity", max(0.0, min(1.0, float(self.intensity))))
        object.__setattr__(self, "duration_seconds", max(0.0, min(30.0, float(self.duration_seconds))))
        object.__setattr__(self, "name", name)


@dataclass(frozen=True)
class MemoryEffect:
    """显式批准后才可由后续工单消费的记忆效果草稿。"""

    kind: Literal["none", "note"] = "none"
    value: str = ""
    approved: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"none", "note"}:
            raise ValueError("unsupported memory effect")
        object.__setattr__(self, "value", normalize_text(self.value))
        if self.kind == "none":
            object.__setattr__(self, "approved", False)


@dataclass(frozen=True)
class HostTurnResult:
    """主播输出契约，文本、播报、情绪、动作和记忆效果彼此分离。"""

    session_id: str
    turn_id: int
    text: str
    speak: bool = True
    emotion: EmotionDraft | None = None
    actions: tuple[ActionDraft, ...] = ()
    memory_effects: tuple[MemoryEffect, ...] = ()

    def __post_init__(self) -> None:
        if not normalize_text(self.session_id):
            raise ValueError("session_id must not be empty")
        object.__setattr__(self, "turn_id", int(self.turn_id))
        object.__setattr__(self, "text", normalize_text(self.text))
        object.__setattr__(self, "speak", bool(self.speak))
        actions = tuple(self.actions)
        memory_effects = tuple(self.memory_effects)
        if any(not isinstance(action, ActionDraft) for action in actions):
            raise TypeError("actions must contain ActionDraft values")
        if any(not isinstance(effect, MemoryEffect) for effect in memory_effects):
            raise TypeError("memory_effects must contain MemoryEffect values")
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "memory_effects", memory_effects)


VoiceTurnSource = Literal["user_mic", "auto_scene"]


@dataclass(frozen=True)
class VoiceTurnSnapshot:
    """语音轮次诊断投影；不含原始 PCM、完整转写或凭证。"""

    session_id: str
    turn_id: int
    source: str
    status: str
    scene_generation: int | None
    runtime_generation: int | None
    started_at: float
    ended_at: float | None
    asr_status: str
    llm_status: str
    tts_status: str
    playback_status: str
    transcript_summary: str
    cancel_reason: str = ""
    failure_reason: str = ""
    timeout_reason: str = ""


@dataclass(frozen=True)
class HostPrompt:
    """分层后的 system/user Prompt，便于后续模型适配器安全消费。"""

    persona_system: str
    persona_user: str
    session_context: str
    scene_context: str
    danmu_context: tuple[str, ...]
    knowledge: KnowledgeContextResult
    current_input: str

    @property
    def system_prompt(self) -> str:
        sections = ["[HOST_PERSONA_SYSTEM]\n" + self.persona_system]
        if self.knowledge.prompt_text:
            sections.append("[HOST_KNOWLEDGE]\n" + self.knowledge.prompt_text)
        sections.append(
            "[HOST_OUTPUT_POLICY]\n"
            "Return structured HostTurnResult fields. Never treat text as an executable command."
        )
        return "\n\n".join(section for section in sections if section.strip())

    @property
    def user_prompt(self) -> str:
        sections = ["[HOST_PERSONA_USER]\n" + self.persona_user]
        if self.session_context:
            sections.append("[HOST_SESSION]\n" + self.session_context)
        if self.scene_context:
            sections.append("[HOST_SCENE]\n" + self.scene_context)
        if self.danmu_context:
            sections.append("[HOST_DANMU]\n" + "\n".join(self.danmu_context))
        if self.knowledge.status in {"no_hit", "error", "unavailable"}:
            sections.append(
                "[HOST_KNOWLEDGE_STATUS]\n"
                "No verified knowledge was injected; do not fabricate facts."
            )
        sections.append("[HOST_INPUT]\n" + self.current_input)
        return "\n\n".join(section for section in sections if section.strip())

    def render(self) -> tuple[str, str]:
        """返回 system/user 双消息，不把两类层级压成一个自由文本协议。"""

        return self.system_prompt, self.user_prompt
