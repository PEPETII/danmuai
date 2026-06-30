#!/usr/bin/env python3
"""从 LiteLLM 和 Cherry Studio 源文件提取 AI 模型元数据，生成 data/ai-platforms/models.json"""

import json
import os
from datetime import date

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LITELLM_PATH = os.path.join(
    REPO_ROOT,
    "references",
    "ai-platforms",
    "litellm",
    "model_prices_and_context_window.json",
)
CHERRY_PATH = os.path.join(
    REPO_ROOT,
    "references",
    "ai-platforms",
    "cherry-studio",
    "packages",
    "provider-registry",
    "data",
    "models.json",
)
OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "ai-platforms", "models.json")

MAX_MODELS = 200


def extract_litellm(data: dict) -> list[dict]:
    """从 LiteLLM JSON 提取 mode=chat 且 (vision 或 function_calling) 的模型"""
    results = []
    for model_id, info in data.items():
        # 跳过 sample_spec
        if model_id == "sample_spec":
            continue

        mode = info.get("mode", "")
        if mode != "chat":
            continue

        supports_vision = info.get("supports_vision", False)
        supports_function_calling = info.get("supports_function_calling", False)

        if not supports_vision and not supports_function_calling:
            continue

        max_input = info.get("max_input_tokens")
        max_output = info.get("max_output_tokens")
        max_tokens = info.get("max_tokens")

        if max_input is not None and max_output is not None:
            context_window = max_input + max_output
        elif max_input is not None:
            context_window = max_input
        elif max_tokens is not None:
            context_window = max_tokens
        else:
            context_window = None

        input_cost = info.get("input_cost_per_token")
        output_cost = info.get("output_cost_per_token")

        input_per_m = round(input_cost * 1_000_000, 6) if input_cost else None
        output_per_m = round(output_cost * 1_000_000, 6) if output_cost else None

        results.append(
            {
                "id": model_id,
                "providerId": info.get("litellm_provider", ""),
                "name": model_id,
                "contextWindow": context_window,
                "maxInputTokens": max_input,
                "maxOutputTokens": max_output,
                "supportsVision": supports_vision if supports_vision else None,
                "supportsFunctionCalling": supports_function_calling
                if supports_function_calling
                else None,
                "supportsAudioInput": info.get("supports_audio_input") or None,
                "supportsReasoning": info.get("supports_reasoning") or None,
                "mode": mode,
                "pricing": {
                    "inputPerMTok": input_per_m,
                    "outputPerMTok": output_per_m,
                    "currency": "USD",
                },
                "capabilities": [],
                "sourceProject": "litellm",
                "sourceFile": "references/ai-platforms/litellm/model_prices_and_context_window.json",
            }
        )
    return results


def extract_cherry(data: dict) -> list[dict]:
    """从 Cherry Studio models.json 提取含 vision 或 function-call 能力的模型"""
    results = []
    models = data.get("models", [])
    for m in models:
        capabilities = m.get("capabilities", [])
        has_vision = "image-recognition" in capabilities
        has_fc = "function-call" in capabilities

        if not has_vision and not has_fc:
            continue

        model_id = m.get("id", "")
        owned_by = m.get("ownedBy", "")
        context_window = m.get("contextWindow")
        max_output = m.get("maxOutputTokens")

        # pricing
        pricing_obj = m.get("pricing", {})
        input_pricing = pricing_obj.get("input", {})
        output_pricing = pricing_obj.get("output", {})
        input_per_m = input_pricing.get("perMillionTokens")
        output_per_m = output_pricing.get("perMillionTokens")
        currency = input_pricing.get("currency", "USD")

        # supportsReasoning from reasoning.supportedEfforts
        reasoning = m.get("reasoning", {})
        supported_efforts = reasoning.get("supportedEfforts", [])
        supports_reasoning = (
            any(e != "none" for e in supported_efforts) if supported_efforts else None
        )

        # supportsAudioInput from inputModalities
        input_modalities = m.get("inputModalities", [])
        supports_audio = "audio" in input_modalities or None

        results.append(
            {
                "id": f"{owned_by}::{model_id}" if owned_by else model_id,
                "providerId": owned_by,
                "name": m.get("name", model_id),
                "contextWindow": context_window,
                "maxInputTokens": None,
                "maxOutputTokens": max_output,
                "supportsVision": has_vision if has_vision else None,
                "supportsFunctionCalling": has_fc if has_fc else None,
                "supportsAudioInput": supports_audio,
                "supportsReasoning": supports_reasoning,
                "mode": "chat",
                "pricing": {
                    "inputPerMTok": round(input_per_m, 6)
                    if input_per_m is not None
                    else None,
                    "outputPerMTok": round(output_per_m, 6)
                    if output_per_m is not None
                    else None,
                    "currency": currency,
                },
                "capabilities": capabilities,
                "sourceProject": "cherry-studio",
                "sourceFile": "references/ai-platforms/cherry-studio/packages/provider-registry/data/models.json",
            }
        )
    return results


def main():
    # 读取源文件
    with open(LITELLM_PATH, "r", encoding="utf-8") as f:
        litellm_data = json.load(f)
    with open(CHERRY_PATH, "r", encoding="utf-8") as f:
        cherry_data = json.load(f)

    litellm_models = extract_litellm(litellm_data)
    cherry_models = extract_cherry(cherry_data)

    print(f"LiteLLM 符合条件模型: {len(litellm_models)}")
    print(f"Cherry Studio 符合条件模型: {len(cherry_models)}")

    # 合并：优先 LiteLLM 的 vision 模型，然后 LiteLLM 的 function_calling 模型，
    # 最后补充 Cherry Studio 模型
    litellm_vision = [m for m in litellm_models if m["supportsVision"]]
    litellm_fc_only = [m for m in litellm_models if not m["supportsVision"]]
    cherry_vision = [m for m in cherry_models if m["supportsVision"]]
    cherry_fc_only = [m for m in cherry_models if not m["supportsVision"]]

    # 按 contextWindow 降序排序每个子集
    for subset in [litellm_vision, litellm_fc_only, cherry_vision, cherry_fc_only]:
        subset.sort(
            key=lambda x: (x.get("contextWindow") or 0), reverse=True
        )

    # 去重：用 model id 的核心部分去重（Cherry Studio 的 id 可能与 LiteLLM 有重叠）
    seen_ids = set()
    final_models = []

    def add_models(model_list, limit):
        count = 0
        for m in model_list:
            if len(final_models) >= MAX_MODELS:
                break
            # 去重 key：用 name 小写核心部分
            dedup_key = m["id"].lower()
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)
            final_models.append(m)
            count += 1
            if count >= limit:
                break
        return count

    # 分配配额：vision 优先
    add_models(litellm_vision, 120)
    add_models(cherry_vision, 40)
    add_models(litellm_fc_only, 30)
    add_models(cherry_fc_only, 10)

    print(f"最终输出模型数: {len(final_models)}")

    output = {
        "description": "AI模型元数据，数据来源: LiteLLM + Cherry Studio",
        "generatedAt": date.today().isoformat(),
        "models": final_models,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"已写入: {OUTPUT_PATH}")

    # 统计
    vision_count = sum(1 for m in final_models if m["supportsVision"])
    fc_count = sum(1 for m in final_models if m["supportsFunctionCalling"])
    litellm_count = sum(1 for m in final_models if m["sourceProject"] == "litellm")
    cherry_count = sum(1 for m in final_models if m["sourceProject"] == "cherry-studio")
    print(f"Vision 模型: {vision_count}, Function Calling 模型: {fc_count}")
    print(f"LiteLLM: {litellm_count}, Cherry Studio: {cherry_count}")


if __name__ == "__main__":
    main()
