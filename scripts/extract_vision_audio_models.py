#!/usr/bin/env python3
"""Extract vision-understanding and audio models from Cherry Studio + LiteLLM reference data.

Outputs:
  data/ai-platforms/filtered-vision-understanding-models.json
  data/ai-platforms/filtered-audio-models.json
  data/ai-platforms/model-capability-map.json
  data/ai-platforms/model-selection-presets.json
"""

import json
import os
import sys
from datetime import date
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_CS = os.path.join(BASE, "references", "ai-platforms", "cherry-studio")
REF_LT = os.path.join(BASE, "references", "ai-platforms", "litellm")
DATA_OUT = os.path.join(BASE, "data", "ai-platforms")

# ── Load sources ──────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

cs_providers = load_json(os.path.join(REF_CS, "packages/provider-registry/data/providers.json"))
cs_models = load_json(os.path.join(REF_CS, "packages/provider-registry/data/models.json"))
cs_provider_models = load_json(os.path.join(REF_CS, "packages/provider-registry/data/provider-models.json"))
lt_models_raw = load_json(os.path.join(REF_LT, "model_prices_and_context_window.json"))

# Build provider lookup
cs_provider_map = {}
for p in cs_providers.get("providers", []):
    cs_provider_map[p["id"]] = p

# Build provider-models override lookup (by providerId::modelId)
cs_pm_map = {}
for o in cs_provider_models.get("overrides", []):
    key = f"{o.get('providerId','')}::{o.get('modelId','')}"
    cs_pm_map[key] = o

# ── Helper functions ──────────────────────────────────────────────────────────

def get_provider_base_url(provider_id, endpoint_type="openai-chat-completions"):
    p = cs_provider_map.get(provider_id)
    if not p:
        return None
    ec = p.get("endpointConfigs", {})
    # Try defaultChatEndpoint first
    default_ep = p.get("defaultChatEndpoint")
    if default_ep and default_ep in ec:
        return ec[default_ep].get("baseUrl")
    if endpoint_type in ec:
        return ec[endpoint_type].get("baseUrl")
    # Fallback: first endpoint with baseUrl
    for v in ec.values():
        if v.get("baseUrl"):
            return v["baseUrl"]
    return None

def get_provider_adapter_family(provider_id, endpoint_type="openai-chat-completions"):
    p = cs_provider_map.get(provider_id)
    if not p:
        return None
    ec = p.get("endpointConfigs", {})
    default_ep = p.get("defaultChatEndpoint")
    if default_ep and default_ep in ec:
        return ec[default_ep].get("adapterFamily")
    if endpoint_type in ec:
        return ec[endpoint_type].get("adapterFamily")
    for v in ec.values():
        if v.get("adapterFamily"):
            return v["adapterFamily"]
    return None

def infer_protocol(adapter_family):
    if not adapter_family:
        return "openai-compatible"
    af = adapter_family.lower()
    if "anthropic" in af: return "anthropic"
    if "google" in af or "gemini" in af: return "gemini"
    if "azure" in af: return "azure"
    if "ollama" in af: return "ollama"
    if "bedrock" in af: return "aws-bedrock"
    if "vertex" in af: return "vertex-ai"
    if "openrouter" in af: return "openrouter"
    return "openai-compatible"

def infer_auth_style(provider_id):
    if provider_id == "ollama": return "none"
    if provider_id == "aws-bedrock": return "iam-aws"
    if provider_id == "vertexai": return "iam-gcp"
    if provider_id == "azure-openai": return "api-key-azure"
    if provider_id == "copilot": return "oauth"
    return "bearer"

# ── Step 1: Cherry Studio vision models ───────────────────────────────────────

cs_vision_models = []
for m in cs_models.get("models", []):
    caps = m.get("capabilities", [])
    has_image_recognition = "image-recognition" in caps
    has_image_generation = "image-generation" in caps
    has_embedding = "embedding" in caps
    has_ocr_only = False  # Cherry Studio doesn't have explicit OCR-only capability

    if not has_image_recognition:
        continue
    if has_image_generation and not has_image_recognition:
        continue
    if has_embedding and not has_image_recognition:
        continue

    # Parse providerId from id (format: providerId::modelId)
    model_full_id = m.get("id", "")
    if "::" in model_full_id:
        provider_id, model_id = model_full_id.split("::", 1)
    else:
        provider_id = ""
        model_id = model_full_id

    base_url = get_provider_base_url(provider_id)
    adapter_family = get_provider_adapter_family(provider_id)

    # Check for OCR-only patterns in name/description
    name_lower = (m.get("name", "") + " " + m.get("description", "")).lower()
    is_ocr_only = any(kw in name_lower for kw in ["ocr", "text extract", "document ai"])

    # Check for image-generation only
    is_image_gen_only = has_image_generation and not has_image_recognition

    # Check for video-generation only (not image understanding)
    is_video_gen_only = "video-generation" in caps and not has_image_recognition

    # Models with only video-generation + image-recognition but no text understanding → needsReview
    is_video_gen_primary = "video-generation" in caps and has_image_recognition

    cs_vision_models.append({
        "id": model_full_id,
        "provider": provider_id,
        "modelId": model_id,
        "displayName": m.get("name", model_id),
        "accessModes": {
            "protocol": infer_protocol(adapter_family),
            "authStyle": infer_auth_style(provider_id),
            "baseUrl": base_url,
        },
        "protocol": infer_protocol(adapter_family),
        "baseUrl": base_url,
        "supportsImageInput": True,
        "supportsVideoInput": "video-recognition" in caps,
        "isOcrOnly": is_ocr_only,
        "isImageGenerationOnly": is_image_gen_only,
        "contextWindow": m.get("contextWindow"),
        "maxOutputTokens": m.get("maxOutputTokens"),
        "maxInputTokens": m.get("maxInputTokens"),
        "pricing": m.get("pricing"),
        "capabilities": caps,
        "inputModalities": m.get("inputModalities", []),
        "sourceProject": "cherry-studio",
        "sourceFile": "packages/provider-registry/data/models.json",
        "evidenceField": "capabilities contains image-recognition",
        "confidence": "high" if has_image_recognition and not is_ocr_only and not is_video_gen_primary else "medium",
        "status": "exclude" if is_ocr_only or is_image_gen_only or is_video_gen_only else ("needsReview" if is_video_gen_primary else "candidate"),
        "notes": "OCR-only model" if is_ocr_only else ("Image-generation only" if is_image_gen_only else ("Video-generation primary" if is_video_gen_primary else "")),
    })

# ── Step 2: LiteLLM vision models ────────────────────────────────────────────

lt_vision_models = []
skip_keys = {"sample_spec"}
# Skip provider-prefixed variants — we only want base models
SKIP_PREFIXES = ("bedrock/", "azure/", "sagemaker/", "vertex_ai/", "databricks/", "cerebras/",
                  "sambanova/", "deepgram/", "assemblyai/", "openai/", "anthropic/", "huggingface/",
                  "ollama/", "ollama_chat/", "cloudflare/", "ai21/", "cohere/", "petals/",
                  "voyage/", "xinference/", "predibase/", "baseten/", "novita/", "litellm_proxy/")

# Known main providers for vision models
MAIN_PROVIDERS = {"openai", "anthropic", "google", "vertex_ai", "bedrock", "azure",
                   "doubao", "dashscope", "volcengine", "deepseek", "zhipu", "moonshot",
                   "minimax", "siliconflow", "groq", "mistral", "xai", "together_ai",
                   "fireworks_ai", "openrouter", "nvidia_nim", "hunyuan", "baidu"}

for model_id, info in lt_models_raw.items():
    if model_id in skip_keys:
        continue
    if not isinstance(info, dict):
        continue

    supports_vision = info.get("supports_vision", False)
    mode = info.get("mode", "")
    if not supports_vision:
        continue
    if mode not in ("chat", ""):
        continue

    # Skip provider-prefixed variants (keep base model only)
    if any(model_id.startswith(p) for p in SKIP_PREFIXES):
        continue

    # Only keep models from known main providers
    provider = info.get("litellm_provider", "unknown")
    if provider not in MAIN_PROVIDERS:
        continue

    max_in = info.get("max_input_tokens") or info.get("max_tokens")
    max_out = info.get("max_output_tokens") or info.get("max_tokens")
    icpt = info.get("input_cost_per_token")
    ocpt = info.get("output_cost_per_token")

    # Detect OCR-only / image-gen-only by name patterns
    name_lower = model_id.lower()
    is_ocr_only = any(kw in name_lower for kw in ["ocr", "text-extract"])
    is_image_gen_only = mode == "image_generation"

    lt_vision_models.append({
        "id": model_id,
        "provider": provider,
        "modelId": model_id,
        "displayName": model_id,
        "accessModes": {
            "protocol": infer_protocol(provider),
            "authStyle": "bearer",
            "baseUrl": None,
        },
        "protocol": infer_protocol(provider),
        "baseUrl": None,
        "supportsImageInput": True,
        "supportsVideoInput": None,
        "isOcrOnly": is_ocr_only,
        "isImageGenerationOnly": is_image_gen_only,
        "contextWindow": (max_in or 0) + (max_out or 0) if max_in and max_out else max_in or max_out or None,
        "maxOutputTokens": max_out,
        "maxInputTokens": max_in,
        "pricing": {
            "inputPerMTok": round(icpt * 1_000_000, 4) if icpt else None,
            "outputPerMTok": round(ocpt * 1_000_000, 4) if ocpt else None,
            "currency": "USD",
        },
        "capabilities": [],
        "inputModalities": ["image", "text"] if supports_vision else ["text"],
        "sourceProject": "litellm",
        "sourceFile": "model_prices_and_context_window.json",
        "evidenceField": "supports_vision=true",
        "confidence": "high" if supports_vision and not is_ocr_only else "medium",
        "status": "exclude" if is_ocr_only or is_image_gen_only else "candidate",
        "notes": "OCR-only" if is_ocr_only else ("Image-generation only" if is_image_gen_only else ""),
    })

# ── Step 3: Merge & deduplicate vision models ────────────────────────────────

# Priority: Cherry Studio has richer metadata; LiteLLM has pricing.
# If same modelId appears in both, merge.

cs_vision_by_mid = {}
for m in cs_vision_models:
    cs_vision_by_mid[m["modelId"]] = m

lt_vision_by_mid = {}
for m in lt_vision_models:
    lt_vision_by_mid[m["modelId"]] = m

merged_vision = []
seen_model_ids = set()

# Start with Cherry Studio models (richer metadata)
for m in cs_vision_models:
    mid = m["modelId"]
    if mid in seen_model_ids:
        continue
    seen_model_ids.add(mid)

    # If LiteLLM has pricing, supplement
    lt_m = lt_vision_by_mid.get(mid)
    if lt_m and lt_m.get("pricing", {}).get("inputPerMTok") and not m.get("pricing"):
        m["pricing"] = lt_m["pricing"]
        m["sourceProject"] = "cherry-studio+litellm"

    merged_vision.append(m)

# Add LiteLLM-only models
for m in lt_vision_models:
    mid = m["modelId"]
    if mid in seen_model_ids:
        continue
    seen_model_ids.add(mid)
    merged_vision.append(m)

# Filter out excluded models, separate candidates and needsReview
vision_candidates = []
vision_needs_review = []
vision_excluded = []

for m in merged_vision:
    if m["status"] == "exclude":
        vision_excluded.append(m)
    elif m["confidence"] in ("low", "needs-review"):
        vision_needs_review.append(m)
    else:
        vision_candidates.append(m)

# Sort candidates by contextWindow descending
vision_candidates.sort(key=lambda x: x.get("contextWindow") or 0, reverse=True)

# ── Step 4: Audio models ─────────────────────────────────────────────────────

# Cherry Studio audio models
cs_audio_transcription = []
cs_audio_understanding = []
cs_audio_needs_review = []

for m in cs_models.get("models", []):
    caps = m.get("capabilities", [])
    input_mods = m.get("inputModalities", [])
    has_audio_recognition = "audio-recognition" in caps
    has_audio_transcript = "audio-transcript" in caps
    has_audio_generation = "audio-generation" in caps
    has_audio_input = "audio" in input_mods

    if not (has_audio_recognition or has_audio_transcript or has_audio_input):
        continue

    model_full_id = m.get("id", "")
    if "::" in model_full_id:
        provider_id, model_id = model_full_id.split("::", 1)
    else:
        provider_id = ""
        model_id = model_full_id

    base_url = get_provider_base_url(provider_id)
    adapter_family = get_provider_adapter_family(provider_id)

    # Classify
    if has_audio_transcript:
        category = "transcription"
    elif has_audio_recognition and has_audio_input:
        category = "directAudioUnderstanding"
    elif has_audio_recognition:
        category = "needsReview"
    else:
        category = "needsReview"

    if has_audio_generation and not has_audio_recognition and not has_audio_transcript:
        category = "exclude"

    entry = {
        "id": model_full_id,
        "provider": provider_id,
        "modelId": model_id,
        "displayName": m.get("name", model_id),
        "category": category,
        "accessModes": {
            "protocol": infer_protocol(adapter_family),
            "authStyle": infer_auth_style(provider_id),
            "baseUrl": base_url,
        },
        "protocol": infer_protocol(adapter_family),
        "endpointPath": None,
        "baseUrl": base_url,
        "supportsAudioInput": has_audio_input or has_audio_recognition,
        "supportsTranscription": has_audio_transcript,
        "supportsStreaming": None,
        "isTTS": has_audio_generation and not has_audio_recognition,
        "isAudioGeneration": has_audio_generation,
        "pricing": m.get("pricing"),
        "capabilities": caps,
        "sourceProject": "cherry-studio",
        "sourceFile": "packages/provider-registry/data/models.json",
        "evidenceField": f"capabilities: {', '.join(c for c in caps if 'audio' in c)}",
        "confidence": "high" if category in ("transcription", "directAudioUnderstanding") else "medium",
        "status": "candidate" if category != "exclude" else "exclude",
        "notes": "",
    }

    if category == "transcription":
        cs_audio_transcription.append(entry)
    elif category == "directAudioUnderstanding":
        cs_audio_understanding.append(entry)
    elif category == "needsReview":
        cs_audio_needs_review.append(entry)

# LiteLLM audio models
lt_transcription = []
lt_audio_understanding = []
lt_audio_needs_review = []

for model_id, info in lt_models_raw.items():
    if model_id in skip_keys or not isinstance(info, dict):
        continue
    if any(model_id.startswith(p) for p in SKIP_PREFIXES):
        continue

    mode = info.get("mode", "")
    supports_audio = info.get("supports_audio_input", False)
    provider = info.get("litellm_provider", "unknown")

    # Only keep models from known providers
    if provider not in MAIN_PROVIDERS:
        continue

    if mode == "audio_transcription":
        lt_transcription.append({
            "id": model_id,
            "provider": provider,
            "modelId": model_id,
            "displayName": model_id,
            "category": "transcription",
            "accessModes": {"protocol": "openai-compatible", "authStyle": "bearer", "baseUrl": None},
            "protocol": "openai-compatible",
            "endpointPath": "/audio/transcriptions",
            "baseUrl": None,
            "supportsAudioInput": True,
            "supportsTranscription": True,
            "supportsStreaming": None,
            "isTTS": False,
            "isAudioGeneration": False,
            "pricing": {
                "inputPerMTok": round(info.get("input_cost_per_token", 0) * 1_000_000, 4) if info.get("input_cost_per_token") else None,
                "outputPerMTok": None,
                "currency": "USD",
            },
            "sourceProject": "litellm",
            "sourceFile": "model_prices_and_context_window.json",
            "evidenceField": "mode=audio_transcription",
            "confidence": "high",
            "status": "candidate",
            "notes": "",
        })
    elif mode == "audio_speech":
        # TTS - skip
        continue
    elif supports_audio and mode == "chat":
        lt_audio_understanding.append({
            "id": model_id,
            "provider": provider,
            "modelId": model_id,
            "displayName": model_id,
            "category": "directAudioUnderstanding",
            "accessModes": {"protocol": infer_protocol(provider), "authStyle": "bearer", "baseUrl": None},
            "protocol": infer_protocol(provider),
            "endpointPath": None,
            "baseUrl": None,
            "supportsAudioInput": True,
            "supportsTranscription": False,
            "supportsStreaming": None,
            "isTTS": False,
            "isAudioGeneration": False,
            "pricing": {
                "inputPerMTok": round(info.get("input_cost_per_token", 0) * 1_000_000, 4) if info.get("input_cost_per_token") else None,
                "outputPerMTok": round(info.get("output_cost_per_token", 0) * 1_000_000, 4) if info.get("output_cost_per_token") else None,
                "currency": "USD",
            },
            "contextWindow": (info.get("max_input_tokens") or 0) + (info.get("max_output_tokens") or 0) or None,
            "sourceProject": "litellm",
            "sourceFile": "model_prices_and_context_window.json",
            "evidenceField": "supports_audio_input=true, mode=chat",
            "confidence": "high",
            "status": "candidate",
            "notes": "",
        })

# Deduplicate audio models
def dedup_audio(lists):
    seen = set()
    result = []
    for lst in lists:
        for m in lst:
            key = m["modelId"]
            if key not in seen:
                seen.add(key)
                result.append(m)
    return result

all_transcription = dedup_audio([cs_audio_transcription, lt_transcription])
all_audio_understanding = dedup_audio([cs_audio_understanding, lt_audio_understanding])
all_audio_needs_review = cs_audio_needs_review

# ── Step 5: Write output files ────────────────────────────────────────────────

today = date.today().isoformat()

# 1. filtered-vision-understanding-models.json
vision_out = {
    "description": "视觉理解模型筛选结果 — 仅包含明确支持图片输入并能理解图片内容的模型",
    "generatedAt": today,
    "filterCriteria": "supportsImageInput=true, isOcrOnly=false, isImageGenerationOnly=false, mode=chat",
    "candidates": vision_candidates,
    "needsReview": vision_needs_review,
    "excluded": [{"id": m["id"], "modelId": m["modelId"], "reason": m.get("notes", "unknown")} for m in vision_excluded],
}

# 2. filtered-audio-models.json
audio_out = {
    "description": "语音模型筛选结果 — 包含语音转写和直接音频理解模型",
    "generatedAt": today,
    "transcriptionModels": all_transcription,
    "directAudioUnderstandingModels": all_audio_understanding,
    "needsReviewAudioModels": all_audio_needs_review,
}

# 3. model-capability-map.json
cap_map = {}
for m in vision_candidates:
    mid = m["modelId"]
    cap_map[mid] = {
        "provider": m["provider"],
        "visionUnderstanding": True,
        "ocrOnly": m.get("isOcrOnly", False),
        "imageGeneration": "image-generation" in m.get("capabilities", []),
        "audioTranscription": False,
        "directAudioUnderstanding": False,
        "tts": False,
        "textChat": True,
        "sourceProject": m["sourceProject"],
        "sourceFile": m["sourceFile"],
        "confidence": m["confidence"],
    }
for m in all_transcription:
    mid = m["modelId"]
    if mid in cap_map:
        cap_map[mid]["audioTranscription"] = True
    else:
        cap_map[mid] = {
            "provider": m["provider"],
            "visionUnderstanding": False,
            "ocrOnly": False,
            "imageGeneration": False,
            "audioTranscription": True,
            "directAudioUnderstanding": False,
            "tts": False,
            "textChat": False,
            "sourceProject": m["sourceProject"],
            "sourceFile": m["sourceFile"],
            "confidence": m["confidence"],
        }
for m in all_audio_understanding:
    mid = m["modelId"]
    if mid in cap_map:
        cap_map[mid]["directAudioUnderstanding"] = True
    else:
        cap_map[mid] = {
            "provider": m["provider"],
            "visionUnderstanding": False,
            "ocrOnly": False,
            "imageGeneration": False,
            "audioTranscription": False,
            "directAudioUnderstanding": True,
            "tts": False,
            "textChat": True,
            "sourceProject": m["sourceProject"],
            "sourceFile": m["sourceFile"],
            "confidence": m["confidence"],
        }

cap_map_out = {
    "description": "模型能力映射 — 视觉理解 + 语音能力",
    "generatedAt": today,
    "models": cap_map,
}

# 4. model-selection-presets.json
# Categorize vision models — prioritize DanmuAI-relevant providers
DANMUAI_PROVIDERS = {"openai", "anthropic", "gemini", "deepseek", "doubao", "dashscope",
                      "zhipu", "moonshot", "siliconflow", "minimax", "groq", "mistral",
                      "xai", "together_ai", "fireworks_ai", "openrouter", "hunyuan", "baidu",
                      "volcengine", "nvidia_nim"}

vision_default = []
vision_low_cost = []
vision_high_quality = []
vision_local = []
vision_needs_review_ids = []

for m in vision_candidates:
    mid = m["modelId"]
    provider = m["provider"]
    caps = m.get("capabilities", [])
    pricing = m.get("pricing") or {}
    in_per_m = pricing.get("inputPerMTok") or pricing.get("input", {}).get("perMillionTokens")
    cw = m.get("contextWindow") or 0

    # Skip video-generation-primary models from default presets
    if "video-generation" in caps and "function-call" not in caps:
        continue

    # Local providers
    if provider in ("ollama", "lmstudio", "gpustack"):
        vision_local.append(mid)
        continue

    # Only include DanmuAI-relevant providers in presets
    if provider not in DANMUAI_PROVIDERS:
        continue

    vision_default.append(mid)
    # Low cost: input < $0.5/MTok
    if in_per_m is not None and in_per_m <= 0.5:
        vision_low_cost.append(mid)
    # High quality: large context or known high-quality
    if cw >= 128000 or provider in ("openai", "anthropic", "gemini"):
        vision_high_quality.append(mid)

for m in vision_needs_review:
    vision_needs_review_ids.append(m["modelId"])

# Audio presets
audio_transcription_ids = [m["modelId"] for m in all_transcription]
audio_understanding_ids = [m["modelId"] for m in all_audio_understanding]
audio_needs_review_ids = [m["modelId"] for m in all_audio_needs_review]

presets_out = {
    "description": "UI推荐预设 — 视觉理解 + 语音模型",
    "generatedAt": today,
    "visionUnderstanding": {
        "default": vision_default[:20],
        "lowCost": vision_low_cost[:15],
        "highQuality": vision_high_quality[:15],
        "local": vision_local[:10],
        "needsReview": vision_needs_review_ids[:15],
    },
    "audio": {
        "transcription": audio_transcription_ids[:10],
        "directAudioUnderstanding": audio_understanding_ids[:15],
        "needsReview": audio_needs_review_ids[:10],
    },
}

# Write all files
os.makedirs(DATA_OUT, exist_ok=True)

for fname, data in [
    ("filtered-vision-understanding-models.json", vision_out),
    ("filtered-audio-models.json", audio_out),
    ("model-capability-map.json", cap_map_out),
    ("model-selection-presets.json", presets_out),
]:
    path = os.path.join(DATA_OUT, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    count_label = ""
    if "candidates" in data:
        count_label = f"candidates={len(data['candidates'])}, needsReview={len(data['needsReview'])}, excluded={len(data['excluded'])}"
    elif "transcriptionModels" in data:
        count_label = f"transcription={len(data['transcriptionModels'])}, directAudio={len(data['directAudioUnderstandingModels'])}, needsReview={len(data['needsReviewAudioModels'])}"
    elif "models" in data:
        count_label = f"models={len(data['models'])}"
    elif "visionUnderstanding" in data:
        v = data["visionUnderstanding"]
        a = data["audio"]
        count_label = f"vision_default={len(v['default'])}, audio_transcription={len(a['transcription'])}"
    print(f"  Written: {fname} ({count_label})")

# ── Stats ─────────────────────────────────────────────────────────────────────

print(f"\n=== Summary ===")
print(f"Vision candidates: {len(vision_candidates)}")
print(f"Vision needsReview: {len(vision_needs_review)}")
print(f"Vision excluded: {len(vision_excluded)}")
print(f"Audio transcription: {len(all_transcription)}")
print(f"Audio direct understanding: {len(all_audio_understanding)}")
print(f"Audio needsReview: {len(all_audio_needs_review)}")
print(f"Capability map entries: {len(cap_map)}")
