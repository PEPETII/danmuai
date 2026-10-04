from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "persona_prompt_eval.py"
    spec = importlib.util.spec_from_file_location("persona_prompt_eval", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eval_mod = _load_module()


def test_extract_json_array_from_markdown_block():
    raw = """```json
["这波真有了", "空枪也太狠了", "绷不住"]
```"""
    assert eval_mod.extract_json_array(raw) == ["这波真有了", "空枪也太狠了", "绷不住"]


def test_extract_json_array_falls_back_to_lines():
    raw = "1. 这也能空\n2. 离谱\n3. 真给我看笑了"
    assert eval_mod.extract_json_array(raw) == ["这也能空", "离谱", "真给我看笑了"]


def test_parse_comments_filters_placeholders_and_dedupes():
    raw = '["评论1", "comment 2", "这也能空", "这也能空", "真有你的"]'
    assert eval_mod.parse_comments(raw, reply_count=5) == ["这也能空", "真有你的"]


def test_rule_score_penalizes_ai_tone_and_cliches():
    scene = eval_mod.SceneSample(
        scene_id="fps",
        scene_text="主播绕后空枪",
        keywords=("绕后", "空枪"),
    )
    comments = eval_mod.parse_comments(
        '["从画面可以看出你空枪了", "请注意准星", "前排", "外卖", "评论1"]',
        reply_count=5,
    )
    score = eval_mod.score_rule_batch(
        comments=comments,
        scene=scene,
        reply_count=5,
        total_tokens=700,
        token_target_per_call=600,
    )
    assert score["naturalness"] < 4.5
    assert score["total"] < 6.2


def test_rule_score_rewards_relevance_and_diversity():
    scene = eval_mod.SceneSample(
        scene_id="moba",
        scene_text="残血反打",
        keywords=("残血", "反打", "团战"),
    )
    comments = [
        "残血还能反打啊",
        "这团战也太极限了",
        "对面真追出事了",
        "这下真翻了",
        "绷不住，硬生生打回来了",
    ]
    score = eval_mod.score_rule_batch(
        comments=comments,
        scene=scene,
        reply_count=5,
        total_tokens=420,
        token_target_per_call=600,
    )
    assert score["relevance"] > 6.5
    assert score["diversity"] > 8.0
    assert score["total"] > 7.0


def test_aggregate_candidate_runs_exposes_final_score_and_avg_tokens():
    aggregate = eval_mod.aggregate_candidate_runs(
        [
            {"format": 9.0, "relevance": 8.0, "naturalness": 7.0, "diversity": 8.0, "concision": 9.0, "cost": 8.0, "total": 8.1},
            {"format": 8.0, "relevance": 7.5, "naturalness": 8.5, "diversity": 7.0, "concision": 8.0, "cost": 9.0, "total": 8.0},
        ],
        [430, 470],
    )
    assert aggregate["final_score"] == 8.05
    assert aggregate["avg_tokens"] == 450.0


def test_v2_eval_fixtures_cover_all_personae_and_keep_contract_in_harness():
    root = Path(__file__).resolve().parents[1]
    reply_count, candidates = eval_mod.load_candidates(
        root / "data" / "prompt_eval" / "persona_candidates.json"
    )
    scenes = eval_mod.load_scene_samples(
        root / "data" / "prompt_eval" / "scene_samples.json"
    )

    assert reply_count == 5
    assert len(candidates) == 28
    assert len({candidate.persona_id for candidate in candidates}) == 14
    assert 25 <= len(scenes) <= 40
    assert all(candidate.feature_groups for candidate in candidates)

    candidate = candidates[0]
    prompt = eval_mod.build_user_prompt(candidate, scenes[0], reply_count)
    assert "仅返回 JSON 字符串数组" in prompt
    assert "\\n" not in candidate.user_prompt_template
    assert "\n" in candidate.user_prompt_template
    assert "仅返回 JSON 字符串数组" not in candidate.system_prompt
    assert "仅返回 JSON 字符串数组" not in candidate.user_prompt_template


def test_persona_scores_include_distinctiveness_and_consistency():
    scene = eval_mod.SceneSample(
        scene_id="aqua",
        scene_text="计划失败，角色突然落水",
        keywords=("失败", "落水"),
    )
    comments = ["又失败了", "这下直接落水", "自信呢", "绷不住"]
    score = eval_mod.score_rule_batch(
        comments=comments,
        scene=scene,
        reply_count=4,
        total_tokens=400,
        token_target_per_call=600,
        feature_groups=(("失败", "翻车"), ("自信", "膨胀"), ("落水", "危险")),
    )

    assert score["persona_distinctiveness"] > 5.0
    assert score["persona_consistency"] > 5.0
    assert score["total"] > 0.0
