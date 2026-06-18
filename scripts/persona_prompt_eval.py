"""独立人格提示词评测脚本。

先做与主程序解耦的候选 prompt 测试，不修改现有人格集成链路。

支持两种运行方式：

1. ``--dry-run``：仅检查候选文件、场景样本、执行计划与输出路径
2. 真实 Ark 调用：顺序跑候选 prompt，统计 token、规则分与候选排名

默认只做低成本规则评测；若后续需要更高精度，可在此基础上追加 LLM judge。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 220
DEFAULT_TEMPERATURE = 0.9
DEFAULT_MAX_TOTAL_TOKENS = 2_000_000
DEFAULT_TOKEN_TARGET_PER_CALL = 600
DEFAULT_OUTPUT_DIR = Path("reports/persona-prompt-eval")

AI_TONE_PATTERNS = (
    "主播你",
    "很遗憾",
    "请注意",
    "从画面可以看出",
    "表现得很好",
    "建议",
    "作为",
    "可以看到",
)

PLACEHOLDER_PATTERNS = (
    re.compile(r"^(?:评论|弹幕)\s*\d+$", re.IGNORECASE),
    re.compile(r"^comment\s*\d+$", re.IGNORECASE),
)

OVERUSED_CLICHES = (
    "前排",
    "外卖",
    "吃瓜",
)


@dataclass(frozen=True)
class SceneSample:
    scene_id: str
    scene_text: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PromptCandidate:
    persona_id: str
    persona_name: str
    candidate_id: str
    persona_goal: str
    system_prompt: str
    user_prompt_template: str


@dataclass(frozen=True)
class GenerationResult:
    comments: tuple[str, ...]
    raw_text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_scene_samples(path: Path) -> list[SceneSample]:
    payload = load_json(path)
    scenes: list[SceneSample] = []
    for item in payload.get("scenes", []):
        scenes.append(
            SceneSample(
                scene_id=str(item["id"]),
                scene_text=str(item["scene_text"]),
                keywords=tuple(str(keyword) for keyword in item.get("keywords", [])),
            )
        )
    return scenes


def load_candidates(path: Path) -> tuple[int, list[PromptCandidate]]:
    payload = load_json(path)
    reply_count = int(payload.get("meta", {}).get("reply_count", 5))
    candidates: list[PromptCandidate] = []
    for persona in payload.get("personae", []):
        persona_id = str(persona["id"])
        persona_name = str(persona["display_name"])
        persona_goal = str(persona.get("persona_goal", ""))
        for candidate in persona.get("candidates", []):
            candidates.append(
                PromptCandidate(
                    persona_id=persona_id,
                    persona_name=persona_name,
                    candidate_id=str(candidate["id"]),
                    persona_goal=persona_goal,
                    system_prompt=str(candidate["system_prompt"]),
                    user_prompt_template=str(candidate["user_prompt_template"]),
                )
            )
    return reply_count, candidates


def filter_candidates(candidates: list[PromptCandidate], persona_filter: str) -> list[PromptCandidate]:
    if not persona_filter or persona_filter == "all":
        return candidates
    wanted = {part.strip() for part in persona_filter.split(",") if part.strip()}
    return [candidate for candidate in candidates if candidate.persona_id in wanted]


def build_user_prompt(candidate: PromptCandidate, scene: SceneSample, reply_count: int) -> str:
    keywords_text = "、".join(scene.keywords) if scene.keywords else "无"
    return candidate.user_prompt_template.format(
        scene_text=scene.scene_text,
        keywords_text=keywords_text,
        reply_count=reply_count,
        persona_goal=candidate.persona_goal,
    )


def normalize_comment(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r'^[\s"\']+', "", value)
    value = re.sub(r'[\s"\']+$', "", value)
    value = re.sub(r"^[\-\*\d\.\)\(、\s]+", "", value)
    return value.strip()


def is_placeholder_comment(text: str) -> bool:
    normalized = normalize_comment(text)
    if not normalized:
        return True
    return any(pattern.fullmatch(normalized) for pattern in PLACEHOLDER_PATTERNS)


def extract_json_array(raw_text: str) -> list[str]:
    stripped = (raw_text or "").strip()
    if not stripped:
        return []
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, list):
            return [normalize_comment(str(item)) for item in payload]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*\]", stripped)
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, list):
                return [normalize_comment(str(item)) for item in payload]
        except json.JSONDecodeError:
            pass

    lines: list[str] = []
    for line in stripped.splitlines():
        normalized = normalize_comment(line)
        if normalized:
            lines.append(normalized)
    return lines


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = normalize_comment(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def parse_comments(raw_text: str, reply_count: int) -> list[str]:
    comments = extract_json_array(raw_text)
    comments = [comment for comment in comments if not is_placeholder_comment(comment)]
    comments = dedupe_preserve_order(comments)
    return comments[:reply_count]


def count_keyword_hits(comments: list[str], keywords: tuple[str, ...]) -> tuple[int, int]:
    if not comments or not keywords:
        return 0, 0
    hit_keywords = 0
    hit_comments = 0
    lowered_comments = [comment.lower() for comment in comments]
    for keyword in keywords:
        if keyword.lower() in "".join(lowered_comments):
            hit_keywords += 1
    for comment in lowered_comments:
        if any(keyword.lower() in comment for keyword in keywords):
            hit_comments += 1
    return hit_keywords, hit_comments


def clamp_score(value: float, lower: float = 0.0, upper: float = 10.0) -> float:
    return max(lower, min(upper, value))


def average_text_length(comments: list[str]) -> float:
    if not comments:
        return 0.0
    return sum(len(comment) for comment in comments) / len(comments)


def count_ai_tone_hits(comments: list[str]) -> int:
    joined = "\n".join(comments)
    return sum(1 for phrase in AI_TONE_PATTERNS if phrase in joined)


def count_overused_cliches(comments: list[str]) -> int:
    joined = "\n".join(comments)
    return sum(joined.count(phrase) for phrase in OVERUSED_CLICHES)


def score_format(comments: list[str], reply_count: int) -> float:
    if not comments:
        return 0.0
    diff = abs(len(comments) - reply_count)
    return clamp_score(10.0 - diff * 2.5)


def score_relevance(comments: list[str], keywords: tuple[str, ...]) -> float:
    if not comments:
        return 0.0
    if not keywords:
        return 6.0
    keyword_hits, comment_hits = count_keyword_hits(comments, keywords)
    keyword_ratio = keyword_hits / max(1, len(keywords))
    comment_ratio = comment_hits / max(1, len(comments))
    return clamp_score(keyword_ratio * 6.0 + comment_ratio * 4.0)


def score_naturalness(comments: list[str]) -> float:
    if not comments:
        return 0.0
    score = 10.0
    score -= count_ai_tone_hits(comments) * 2.5
    score -= count_overused_cliches(comments) * 1.6
    if any(is_placeholder_comment(comment) for comment in comments):
        score -= 4.0
    if all(comment.endswith(("。", "！")) for comment in comments):
        score -= 1.0
    return clamp_score(score)


def score_diversity(comments: list[str]) -> float:
    if not comments:
        return 0.0
    unique_ratio = len(set(comments)) / len(comments)
    prefix_ratio = len({comment[:3] for comment in comments if comment}) / len(comments)
    return clamp_score(unique_ratio * 6.0 + prefix_ratio * 4.0)


def score_concision(comments: list[str]) -> float:
    if not comments:
        return 0.0
    avg_len = average_text_length(comments)
    if avg_len < 2:
        return 2.0
    if avg_len <= 14:
        return 10.0
    if avg_len <= 20:
        return 8.0
    if avg_len <= 28:
        return 5.5
    if avg_len <= 36:
        return 3.0
    return 1.0


def score_cost(total_tokens: int, token_target_per_call: int) -> float:
    if total_tokens <= token_target_per_call:
        return 10.0
    overflow_ratio = (total_tokens - token_target_per_call) / max(1, token_target_per_call)
    return clamp_score(10.0 - overflow_ratio * 8.0)


def score_rule_batch(
    comments: list[str],
    scene: SceneSample,
    reply_count: int,
    total_tokens: int,
    token_target_per_call: int,
) -> dict[str, float]:
    format_score = score_format(comments, reply_count)
    relevance_score = score_relevance(comments, scene.keywords)
    naturalness_score = score_naturalness(comments)
    diversity_score = score_diversity(comments)
    concision_score = score_concision(comments)
    cost_score = score_cost(total_tokens, token_target_per_call)
    total = (
        format_score * 0.18
        + relevance_score * 0.27
        + naturalness_score * 0.23
        + diversity_score * 0.16
        + concision_score * 0.08
        + cost_score * 0.08
    )
    return {
        "format": round(format_score, 3),
        "relevance": round(relevance_score, 3),
        "naturalness": round(naturalness_score, 3),
        "diversity": round(diversity_score, 3),
        "concision": round(concision_score, 3),
        "cost": round(cost_score, 3),
        "total": round(total, 3),
    }


def aggregate_candidate_runs(run_scores: list[dict[str, float]], token_totals: list[int]) -> dict[str, float]:
    if not run_scores:
        return {
            "avg_total": 0.0,
            "avg_format": 0.0,
            "avg_relevance": 0.0,
            "avg_naturalness": 0.0,
            "avg_diversity": 0.0,
            "avg_concision": 0.0,
            "avg_cost": 0.0,
            "avg_tokens": 0.0,
            "final_score": 0.0,
        }
    def _avg(key: str) -> float:
        return sum(item[key] for item in run_scores) / len(run_scores)

    avg_total = _avg("total")
    avg_tokens = sum(token_totals) / max(1, len(token_totals))
    return {
        "avg_total": round(avg_total, 3),
        "avg_format": round(_avg("format"), 3),
        "avg_relevance": round(_avg("relevance"), 3),
        "avg_naturalness": round(_avg("naturalness"), 3),
        "avg_diversity": round(_avg("diversity"), 3),
        "avg_concision": round(_avg("concision"), 3),
        "avg_cost": round(_avg("cost"), 3),
        "avg_tokens": round(avg_tokens, 3),
        "final_score": round(avg_total, 3),
    }


def parse_responses_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    return "\n".join(chunks).strip()


def parse_usage(payload: dict[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return input_tokens, output_tokens


def request_ark_generation(
    client: httpx.Client,
    *,
    endpoint: str,
    api_key: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_output_tokens: int,
) -> GenerationResult:
    url = f"{endpoint.rstrip('/')}/responses"
    payload = {
        "model": model_id,
        "instructions": system_prompt,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_prompt,
                    }
                ],
            }
        ],
        "stream": False,
        "temperature": temperature,
        "thinking": {"type": "disabled"},
        "max_output_tokens": max_output_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    raw_text = parse_responses_text(data)
    input_tokens, output_tokens = parse_usage(data)
    total_tokens = input_tokens + output_tokens
    comments = tuple(parse_comments(raw_text, reply_count=64))
    return GenerationResult(
        comments=comments,
        raw_text=raw_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="独立人格提示词评测脚本")
    parser.add_argument("--api-key", default=os.getenv("ARK_API_KEY", ""), help="火山方舟 API Key")
    parser.add_argument("--model-id", default=os.getenv("ARK_MODEL_ID", ""), help="火山方舟模型/接入点 ID")
    parser.add_argument("--endpoint", default=os.getenv("ARK_ENDPOINT", DEFAULT_ENDPOINT), help="Ark endpoint")
    parser.add_argument(
        "--candidates",
        default="data/prompt_eval/persona_candidates.json",
        help="候选提示词 JSON 路径",
    )
    parser.add_argument(
        "--samples",
        default="data/prompt_eval/scene_samples.json",
        help="场景样本 JSON 路径",
    )
    parser.add_argument("--persona", default="all", help="只评测指定 persona_id，多个逗号分隔")
    parser.add_argument("--runs-per-scene", type=int, default=2, help="每个场景重复调用次数")
    parser.add_argument("--max-scenes", type=int, default=0, help="限制场景数，0 表示全部")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE, help="采样温度")
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        help="单次请求最大输出 token",
    )
    parser.add_argument(
        "--max-total-tokens",
        type=int,
        default=DEFAULT_MAX_TOTAL_TOKENS,
        help="真实调用累计 token 上限",
    )
    parser.add_argument(
        "--token-target-per-call",
        type=int,
        default=DEFAULT_TOKEN_TARGET_PER_CALL,
        help="规则评分中的单次目标 token",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="评测结果输出目录",
    )
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC, help="单次请求超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="仅打印执行计划，不发起 API 请求")
    return parser


def truncate_scenes(scenes: list[SceneSample], max_scenes: int) -> list[SceneSample]:
    if max_scenes <= 0:
        return scenes
    return scenes[:max_scenes]


def build_plan_summary(candidates: list[PromptCandidate], scenes: list[SceneSample], runs_per_scene: int) -> dict[str, Any]:
    persona_ids = sorted({candidate.persona_id for candidate in candidates})
    return {
        "persona_count": len(persona_ids),
        "candidate_count": len(candidates),
        "scene_count": len(scenes),
        "runs_per_scene": runs_per_scene,
        "total_calls": len(candidates) * len(scenes) * runs_per_scene,
        "personae": persona_ids,
    }


def run_evaluation(args: argparse.Namespace) -> int:
    candidates_path = Path(args.candidates)
    samples_path = Path(args.samples)
    output_dir = ensure_output_dir(Path(args.output_dir))

    reply_count, all_candidates = load_candidates(candidates_path)
    filtered_candidates = filter_candidates(all_candidates, args.persona)
    scenes = truncate_scenes(load_scene_samples(samples_path), args.max_scenes)
    plan = build_plan_summary(filtered_candidates, scenes, args.runs_per_scene)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_path = output_dir / f"eval-{timestamp}.json"
    summary_path = output_dir / f"eval-{timestamp}.md"

    if args.dry_run:
        dry_payload = {
            "mode": "dry-run",
            "candidates_path": str(candidates_path),
            "samples_path": str(samples_path),
            "output_json": str(result_path),
            "output_markdown": str(summary_path),
            "plan": plan,
        }
        print(json.dumps(dry_payload, ensure_ascii=False, indent=2))
        return 0

    if not args.api_key.strip():
        print("缺少 --api-key 或环境变量 ARK_API_KEY", file=sys.stderr)
        return 2
    if not args.model_id.strip():
        print("缺少 --model-id 或环境变量 ARK_MODEL_ID", file=sys.stderr)
        return 2
    if not filtered_candidates:
        print("没有匹配到候选 persona", file=sys.stderr)
        return 2
    if not scenes:
        print("场景样本为空", file=sys.stderr)
        return 2

    total_tokens_used = 0
    per_candidate_runs: dict[str, list[dict[str, Any]]] = {}

    timeout = httpx.Timeout(args.timeout_sec)
    with httpx.Client(timeout=timeout) as client:
        for candidate in filtered_candidates:
            candidate_key = f"{candidate.persona_id}:{candidate.candidate_id}"
            per_candidate_runs[candidate_key] = []
            for scene in scenes:
                for run_index in range(args.runs_per_scene):
                    if total_tokens_used >= args.max_total_tokens:
                        break
                    user_prompt = build_user_prompt(candidate, scene, reply_count)
                    generation = request_ark_generation(
                        client,
                        endpoint=args.endpoint,
                        api_key=args.api_key.strip(),
                        model_id=args.model_id.strip(),
                        system_prompt=candidate.system_prompt,
                        user_prompt=user_prompt,
                        temperature=args.temperature,
                        max_output_tokens=args.max_output_tokens,
                    )
                    comments = list(generation.comments[:reply_count])
                    batch_score = score_rule_batch(
                        comments=comments,
                        scene=scene,
                        reply_count=reply_count,
                        total_tokens=generation.total_tokens,
                        token_target_per_call=args.token_target_per_call,
                    )
                    total_tokens_used += generation.total_tokens
                    per_candidate_runs[candidate_key].append(
                        {
                            "scene_id": scene.scene_id,
                            "run_index": run_index + 1,
                            "comments": comments,
                            "raw_text": generation.raw_text,
                            "input_tokens": generation.input_tokens,
                            "output_tokens": generation.output_tokens,
                            "total_tokens": generation.total_tokens,
                            "rule_score": batch_score,
                        }
                    )
                if total_tokens_used >= args.max_total_tokens:
                    break
            if total_tokens_used >= args.max_total_tokens:
                break

    ranking: list[dict[str, Any]] = []
    for candidate in filtered_candidates:
        candidate_key = f"{candidate.persona_id}:{candidate.candidate_id}"
        runs = per_candidate_runs.get(candidate_key, [])
        scores = [item["rule_score"] for item in runs]
        token_totals = [int(item["total_tokens"]) for item in runs]
        aggregate = aggregate_candidate_runs(scores, token_totals)
        ranking.append(
            {
                "persona_id": candidate.persona_id,
                "persona_name": candidate.persona_name,
                "candidate_id": candidate.candidate_id,
                "persona_goal": candidate.persona_goal,
                "aggregate": aggregate,
                "runs": runs,
            }
        )

    ranking.sort(
        key=lambda item: (
            item["aggregate"]["final_score"],
            -item["aggregate"]["avg_tokens"],
        ),
        reverse=True,
    )

    result_payload = {
        "generated_at": timestamp,
        "endpoint": args.endpoint,
        "model_id": args.model_id,
        "reply_count": reply_count,
        "plan": plan,
        "total_tokens_used": total_tokens_used,
        "ranking": ranking,
    }
    result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(render_markdown_summary(result_payload), encoding="utf-8")

    print(f"评测完成：{result_path}")
    print(f"摘要输出：{summary_path}")
    print(f"累计 tokens：{total_tokens_used}")
    for row in ranking[:10]:
        print(
            f"- {row['persona_id']} / {row['candidate_id']}: "
            f"{row['aggregate']['final_score']} 分, "
            f"平均 tokens {row['aggregate']['avg_tokens']}"
        )
    return 0


def render_markdown_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# 人格提示词评测结果",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- 模型：`{payload['model_id']}`",
        f"- 累计 tokens：`{payload['total_tokens_used']}`",
        f"- 候选数：`{payload['plan']['candidate_count']}`",
        f"- 场景数：`{payload['plan']['scene_count']}`",
        f"- 每场景重复次数：`{payload['plan']['runs_per_scene']}`",
        "",
        "## 排名",
        "",
        "| 排名 | Persona | Candidate | Final | Avg Tokens | Relevance | Naturalness | Diversity |",
        "|------|---------|-----------|-------|------------|-----------|-------------|-----------|",
    ]
    for index, row in enumerate(payload.get("ranking", []), start=1):
        aggregate = row["aggregate"]
        lines.append(
            f"| {index} | {row['persona_name']} | {row['candidate_id']} | "
            f"{aggregate['final_score']} | {aggregate['avg_tokens']} | "
            f"{aggregate['avg_relevance']} | {aggregate['avg_naturalness']} | "
            f"{aggregate['avg_diversity']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = build_cli()
    args = parser.parse_args()
    return run_evaluation(args)


if __name__ == "__main__":
    raise SystemExit(main())
