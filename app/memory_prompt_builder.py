"""Build three-section memory prompt blocks with character budgets."""

from __future__ import annotations

from app.memory.bullet_dedup import BulletDedupMemory
from app.memory.scene_context import SceneContextMemory
from app.memory.types import MEMORY_MODE_DEDUP_ONLY, MEMORY_MODE_STRONG

BUDGET_DEDUP_ONLY = 220
BUDGET_SCENE_CARD = 450
BUDGET_STRONG = 700

_CONFLICT_LINE = "必须以当前截图为最高优先级；以上记忆仅作辅助，冲突时忽略记忆。"


def _join_list(items: list[str], sep: str = "；") -> str:
    return sep.join(x for x in items if x)


def build_scene_state_section(ctx: SceneContextMemory) -> str:
    if ctx.is_empty() and not ctx.tone_hint:
        return ""
    lines = ["【当前场景状态】"]
    if ctx.scene_type:
        lines.append(f"类型：{ctx.scene_type}")
    if ctx.scene_summary:
        lines.append(f"摘要：{ctx.scene_summary}")
    if ctx.stable_facts:
        lines.append(f"稳定事实：{_join_list(ctx.stable_facts)}")
    if ctx.volatile_facts:
        lines.append(f"易变事实：{_join_list(ctx.volatile_facts)}")
    if ctx.open_threads:
        lines.append(f"未闭合线索：{_join_list(ctx.open_threads)}")
    if ctx.last_focus:
        lines.append(f"当前焦点：{ctx.last_focus}")
    if ctx.tone_hint:
        lines.append(f"语气提示：{ctx.tone_hint}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_dedup_section(dedup: BulletDedupMemory) -> str:
    if dedup.is_empty():
        return ""
    lines = ["【最近弹幕去重】"]
    texts = [b.text for b in dedup.recent_bullets[-5:]]
    if texts:
        lines.append(f"最近上屏：{_join_list(texts)}")
    if dedup.recent_angles:
        lines.append(f"已用表达角度：{_join_list(dedup.recent_angles)}")
    if dedup.avoid_angles:
        lines.append(f"下轮避免角度：{_join_list(dedup.avoid_angles)}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_constraints_section() -> str:
    return "\n".join(
        [
            "【生成约束】",
            f"- {_CONFLICT_LINE}",
            "- 不要重复最近已用的表达角度与句式。",
            "- 每条弹幕仍需遵守人格输出契约。",
        ]
    )


def _budget_for_mode(memory_mode: str) -> int:
    if memory_mode == MEMORY_MODE_STRONG:
        return BUDGET_STRONG
    if memory_mode == MEMORY_MODE_DEDUP_ONLY:
        return BUDGET_DEDUP_ONLY
    return BUDGET_SCENE_CARD


def _trim_to_budget(parts: list[str], budget: int) -> str:
    block = "\n\n".join(p for p in parts if p)
    if len(block) <= budget:
        return block
    constraints = build_constraints_section()
    if len(constraints) >= budget:
        return constraints[:budget]
    remaining = budget - len(constraints) - 2
    body_parts = [p for p in parts if p and p != constraints]
    body = "\n\n".join(body_parts)
    if len(body) > remaining:
        body = body[: max(0, remaining - 3)] + "..."
    return f"{body}\n\n{constraints}" if body else constraints


def build_memory_prompt_block(
    ctx: SceneContextMemory,
    dedup: BulletDedupMemory,
    memory_mode: str,
) -> str:
    mode = (memory_mode or "off").strip().lower()
    if mode == "off":
        return ""

    constraints = build_constraints_section()
    dedup_sec = build_dedup_section(dedup)

    if mode == MEMORY_MODE_DEDUP_ONLY:
        parts = [p for p in (dedup_sec, constraints) if p]
        return _trim_to_budget(parts, _budget_for_mode(mode))

    scene_sec = build_scene_state_section(ctx)
    parts = [p for p in (scene_sec, dedup_sec, constraints) if p]
    return _trim_to_budget(parts, _budget_for_mode(mode))


def append_memory_to_user_pt(user_pt: str, block: str) -> str:
    if not block:
        return user_pt
    return f"{user_pt.rstrip()}\n\n{block}"
