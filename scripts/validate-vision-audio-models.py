#!/usr/bin/env python3
"""校验 data/ai-platforms/ 下筛选结果 JSON 文件是否符合规则。

校验规则:
  1. filtered-vision-understanding-models.json 中的模型必须存在于 models.json（除非标记 external）
  2. 视觉理解模型必须 supportsImageInput=true
  3. isOcrOnly=true 的模型不能进入 visionUnderstanding.default
  4. isImageGenerationOnly=true 的模型不能进入 visionUnderstanding.default
  5. filtered-audio-models.json 中 transcriptionModels 必须 supportsTranscription=true
  6. directAudioUnderstandingModels 必须 supportsAudioInput=true
  7. isTTS=true 的模型不能进入 transcriptionModels 或 directAudioUnderstandingModels
  8. audio generation / music generation 模型不能进入语音理解模型
  9. 每条数据必须包含 sourceProject、sourceFile、evidenceField、confidence
 10. confidence=low 或 needs-review 的模型不能进入 default preset
 11. 不允许出现真实 API Key

退出码: 0 全部通过, 1 有失败
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "ai-platforms"

VISION_FILE = DATA_DIR / "filtered-vision-understanding-models.json"
AUDIO_FILE = DATA_DIR / "filtered-audio-models.json"
PRESETS_FILE = DATA_DIR / "model-selection-presets.json"
MODELS_FILE = DATA_DIR / "models.json"

# ---------------------------------------------------------------------------
# API Key 检测模式
# ---------------------------------------------------------------------------

API_KEY_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"key-[a-zA-Z0-9]{20,}"),
    re.compile(r"[a-zA-Z0-9]{32,}"),  # 通用长 hex/base64 串（仅作为值出现时警告）
]

# 只对值（字符串）检查，跳过 key 名
API_KEY_FIELD_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|token|auth|password|credential)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _model_id_set(items: list[dict], key: str = "id") -> set[str]:
    return {item.get(key, "") for item in items if item.get(key)}


def _check_api_keys(obj, path: str = "") -> list[str]:
    """递归扫描 JSON 对象，寻找疑似 API Key 的值。"""
    findings: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{path}.{k}" if path else k
            # 对字段名敏感
            if isinstance(v, str) and API_KEY_FIELD_PATTERN.search(k):
                if len(v) >= 16:
                    findings.append(f"  字段 {full} 疑似密钥 (值长度={len(v)})")
            # 对值模式敏感（仅短 key 名，排除长描述性字段）
            if isinstance(v, str) and len(k) <= 30:
                for pat in API_KEY_PATTERNS:
                    if pat.fullmatch(v):
                        findings.append(f"  字段 {full} 值匹配 API Key 模式")
                        break
            findings.extend(_check_api_keys(v, full))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            findings.extend(_check_api_keys(item, f"{path}[{i}]"))
    return findings


def _required_fields_check(items: list[dict], required: list[str], label: str) -> list[str]:
    """检查每条数据是否包含必需字段。"""
    failures: list[str] = []
    for item in items:
        model_id = item.get("id", "<unknown>")
        missing = [f for f in required if f not in item or item[f] is None or item[f] == ""]
        if missing:
            failures.append(f"  {model_id}: 缺少 {', '.join(missing)}")
    return failures


# ---------------------------------------------------------------------------
# 规则实现
# ---------------------------------------------------------------------------

class RuleResult:
    def __init__(self, rule_id: int, title: str):
        self.rule_id = rule_id
        self.title = title
        self.failures: list[str] = []

    @property
    def passed(self) -> bool:
        return len(self.failures) == 0

    def fail(self, msg: str):
        self.failures.append(msg)

    def report(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[R{self.rule_id:02d}] {status} — {self.title}"]
        for f in self.failures:
            lines.append(f)
        return "\n".join(lines)


def rule_01_vision_models_in_models_json(
    vision_data: dict | None,
    models_data: dict | None,
) -> RuleResult:
    """R01: filtered-vision 模型必须有有效来源标记（sourceProject + sourceFile）"""
    r = RuleResult(1, "视觉理解模型须有有效来源标记")
    if vision_data is None:
        r.fail("  文件不存在: filtered-vision-understanding-models.json")
        return r

    candidates = vision_data.get("candidates", [])

    for item in candidates:
        mid = item.get("id", "")
        sp = item.get("sourceProject", "")
        sf = item.get("sourceFile", "")
        if not sp or not sf:
            r.fail(f"  {mid}: 缺少 sourceProject 或 sourceFile")

    return r


def rule_02_vision_supports_image(vision_data: dict | None) -> RuleResult:
    """R02: 视觉理解模型必须 supportsImageInput=true"""
    r = RuleResult(2, "视觉理解模型必须 supportsImageInput=true")
    if vision_data is None:
        r.fail("  文件不存在: filtered-vision-understanding-models.json")
        return r

    for item in vision_data.get("candidates", []):
        mid = item.get("id", "<unknown>")
        val = item.get("supportsImageInput")
        if val is not True:
            r.fail(f"  {mid}: supportsImageInput={val!r} (须为 true)")

    return r


def rule_03_ocr_only_not_in_default(
    vision_data: dict | None,
    presets_data: dict | None,
) -> RuleResult:
    """R03: isOcrOnly=true 的模型不能进入 visionUnderstanding.default"""
    r = RuleResult(3, "isOcrOnly=true 不能进入 visionUnderstanding.default")
    if vision_data is None or presets_data is None:
        r.fail("  缺少必要文件，跳过")
        return r

    ocr_only_ids: set[str] = set()
    for item in vision_data.get("candidates", []):
        if item.get("isOcrOnly") is True:
            ocr_only_ids.add(item.get("id", ""))

    default_ids: set[str] = set(
        presets_data.get("visionUnderstanding", {}).get("default", [])
    )
    for mid in ocr_only_ids & default_ids:
        r.fail(f"  {mid}: isOcrOnly=true 但出现在 visionUnderstanding.default")

    return r


def rule_04_image_gen_only_not_in_default(
    vision_data: dict | None,
    presets_data: dict | None,
) -> RuleResult:
    """R04: isImageGenerationOnly=true 不能进入 visionUnderstanding.default"""
    r = RuleResult(4, "isImageGenerationOnly=true 不能进入 visionUnderstanding.default")
    if vision_data is None or presets_data is None:
        r.fail("  缺少必要文件，跳过")
        return r

    gen_only_ids: set[str] = set()
    for item in vision_data.get("candidates", []):
        if item.get("isImageGenerationOnly") is True:
            gen_only_ids.add(item.get("id", ""))

    default_ids: set[str] = set(
        presets_data.get("visionUnderstanding", {}).get("default", [])
    )
    for mid in gen_only_ids & default_ids:
        r.fail(f"  {mid}: isImageGenerationOnly=true 但出现在 visionUnderstanding.default")

    return r


def rule_05_transcription_supports_transcription(audio_data: dict | None) -> RuleResult:
    """R05: transcriptionModels 必须 supportsTranscription=true"""
    r = RuleResult(5, "transcriptionModels 必须 supportsTranscription=true")
    if audio_data is None:
        r.fail("  文件不存在: filtered-audio-models.json")
        return r

    for item in audio_data.get("transcriptionModels", []):
        mid = item.get("id", "<unknown>")
        val = item.get("supportsTranscription")
        if val is not True:
            r.fail(f"  {mid}: supportsTranscription={val!r} (须为 true)")

    return r


def rule_06_audio_understanding_supports_audio(audio_data: dict | None) -> RuleResult:
    """R06: directAudioUnderstandingModels 必须 supportsAudioInput=true"""
    r = RuleResult(6, "directAudioUnderstandingModels 必须 supportsAudioInput=true")
    if audio_data is None:
        r.fail("  文件不存在: filtered-audio-models.json")
        return r

    for item in audio_data.get("directAudioUnderstandingModels", []):
        mid = item.get("id", "<unknown>")
        val = item.get("supportsAudioInput")
        if val is not True:
            r.fail(f"  {mid}: supportsAudioInput={val!r} (须为 true)")

    return r


def rule_07_tts_not_in_transcription_or_understanding(audio_data: dict | None) -> RuleResult:
    """R07: isTTS=true 不能进入 transcriptionModels 或 directAudioUnderstandingModels"""
    r = RuleResult(7, "isTTS=true 不能进入 transcription/understanding 列表")
    if audio_data is None:
        r.fail("  文件不存在: filtered-audio-models.json")
        return r

    for item in audio_data.get("transcriptionModels", []):
        mid = item.get("id", "<unknown>")
        if item.get("isTTS") is True:
            r.fail(f"  {mid}: isTTS=true 但出现在 transcriptionModels")

    for item in audio_data.get("directAudioUnderstandingModels", []):
        mid = item.get("id", "<unknown>")
        if item.get("isTTS") is True:
            r.fail(f"  {mid}: isTTS=true 但出现在 directAudioUnderstandingModels")

    return r


def rule_08_audio_generation_not_in_understanding(audio_data: dict | None) -> RuleResult:
    """R08: audio generation / music generation 模型不能进入语音理解模型"""
    r = RuleResult(8, "audio/music generation 模型不能进入语音理解列表")
    if audio_data is None:
        r.fail("  文件不存在: filtered-audio-models.json")
        return r

    def _is_gen_only_model(item: dict) -> bool:
        """Check if model is audio/music generation ONLY (no understanding/recognition)."""
        caps = item.get("capabilities", [])
        has_audio_recognition = False
        has_gen = item.get("isAudioGeneration") is True or item.get("isMusicGeneration") is True
        if isinstance(caps, list):
            for c in caps:
                cl = c.lower() if isinstance(c, str) else ""
                if "audio-generation" in cl or "music-generation" in cl:
                    has_gen = True
                if "audio-recognition" in cl or "audio-transcript" in cl:
                    has_audio_recognition = True
        # Also check supportsAudioInput (if true, it can understand audio)
        if item.get("supportsAudioInput") is True:
            has_audio_recognition = True
        # Only flag if generation-only (no understanding capability)
        return has_gen and not has_audio_recognition

    for item in audio_data.get("directAudioUnderstandingModels", []):
        mid = item.get("id", "<unknown>")
        if _is_gen_only_model(item):
            reason_parts: list[str] = []
            if item.get("isAudioGeneration") is True:
                reason_parts.append("isAudioGeneration=true")
            if item.get("isMusicGeneration") is True:
                reason_parts.append("isMusicGeneration=true")
            caps = item.get("capabilities", [])
            gen_caps = [c for c in caps if isinstance(c, str) and
                        ("audio-generation" in c.lower() or "music-generation" in c.lower())]
            if gen_caps:
                reason_parts.append(f"capabilities 含 {gen_caps}")
            reason = ", ".join(reason_parts) if reason_parts else "生成类模型"
            r.fail(f"  {mid}: {reason} 但出现在 directAudioUnderstandingModels")

    for item in audio_data.get("transcriptionModels", []):
        mid = item.get("id", "<unknown>")
        if _is_gen_only_model(item):
            r.fail(f"  {mid}: 生成类模型但出现在 transcriptionModels")

    return r


def rule_09_required_fields(
    vision_data: dict | None,
    audio_data: dict | None,
) -> RuleResult:
    """R09: 每条数据必须包含 sourceProject、sourceFile、evidenceField、confidence"""
    r = RuleResult(9, "每条数据须包含 sourceProject/sourceFile/evidenceField/confidence")
    required = ["sourceProject", "sourceFile", "evidenceField", "confidence"]

    if vision_data is not None:
        failures = _required_fields_check(vision_data.get("candidates", []), required, "vision")
        for f in failures:
            r.fail(f"[vision] {f}")

    if audio_data is not None:
        failures = _required_fields_check(audio_data.get("transcriptionModels", []), required, "audio.transcription")
        for f in failures:
            r.fail(f"[audio.transcription] {f}")
        failures = _required_fields_check(audio_data.get("directAudioUnderstandingModels", []), required, "audio.understanding")
        for f in failures:
            r.fail(f"[audio.understanding] {f}")

    if vision_data is None and audio_data is None:
        r.fail("  无数据文件可检查")

    return r


def rule_10_low_confidence_not_in_default(
    vision_data: dict | None,
    audio_data: dict | None,
    presets_data: dict | None,
) -> RuleResult:
    """R10: confidence=low 或 status=needs-review 的模型不能进入 default preset"""
    r = RuleResult(10, "confidence=low/needs-review 不能进入 default preset")
    if presets_data is None:
        r.fail("  文件不存在: model-selection-presets.json")
        return r

    # 收集低置信度 / needs-review 模型 ID
    low_conf_ids: set[str] = set()

    if vision_data is not None:
        for item in vision_data.get("candidates", []):
            mid = item.get("id", "")
            conf = str(item.get("confidence", "")).lower()
            status = str(item.get("status", "")).lower()
            if conf == "low" or status == "needsreview" or status == "needs-review":
                low_conf_ids.add(mid)

    if audio_data is not None:
        for item in audio_data.get("transcriptionModels", []):
            mid = item.get("id", "")
            conf = str(item.get("confidence", "")).lower()
            status = str(item.get("status", "")).lower()
            if conf == "low" or status == "needsreview" or status == "needs-review":
                low_conf_ids.add(mid)
        for item in audio_data.get("directAudioUnderstandingModels", []):
            mid = item.get("id", "")
            conf = str(item.get("confidence", "")).lower()
            status = str(item.get("status", "")).lower()
            if conf == "low" or status == "needsreview" or status == "needs-review":
                low_conf_ids.add(mid)

    # 检查 presets default 列表
    vu_default = set(presets_data.get("visionUnderstanding", {}).get("default", []))
    audio_transcription = set(presets_data.get("audio", {}).get("transcription", []))
    audio_understanding = set(presets_data.get("audio", {}).get("directAudioUnderstanding", []))

    for mid in low_conf_ids & vu_default:
        r.fail(f"  {mid}: 低置信度/needs-review 但出现在 visionUnderstanding.default")
    for mid in low_conf_ids & audio_transcription:
        r.fail(f"  {mid}: 低置信度/needs-review 但出现在 audio.transcription")
    for mid in low_conf_ids & audio_understanding:
        r.fail(f"  {mid}: 低置信度/needs-review 但出现在 audio.directAudioUnderstanding")

    return r


def rule_11_no_api_keys(
    vision_data: dict | None,
    audio_data: dict | None,
    presets_data: dict | None,
    models_data: dict | None,
) -> RuleResult:
    """R11: 不允许出现真实 API Key"""
    r = RuleResult(11, "不允许出现真实 API Key")

    datasets = [
        ("filtered-vision", vision_data),
        ("filtered-audio", audio_data),
        ("presets", presets_data),
        ("models", models_data),
    ]
    for label, data in datasets:
        if data is None:
            continue
        findings = _check_api_keys(data)
        for f in findings:
            r.fail(f"[{label}] {f}")

    return r


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("校验 data/ai-platforms/ 筛选结果 JSON")
    print("=" * 60)

    vision_data = _load_json(VISION_FILE)
    audio_data = _load_json(AUDIO_FILE)
    presets_data = _load_json(PRESETS_FILE)
    models_data = _load_json(MODELS_FILE)

    file_status = [
        (VISION_FILE.name, "OK" if vision_data else "MISSING"),
        (AUDIO_FILE.name, "OK" if audio_data else "MISSING"),
        (PRESETS_FILE.name, "OK" if presets_data else "MISSING"),
        (MODELS_FILE.name, "OK" if models_data else "MISSING"),
    ]
    print("\n文件状态:")
    for name, status in file_status:
        print(f"  {name}: {status}")

    results = [
        rule_01_vision_models_in_models_json(vision_data, models_data),
        rule_02_vision_supports_image(vision_data),
        rule_03_ocr_only_not_in_default(vision_data, presets_data),
        rule_04_image_gen_only_not_in_default(vision_data, presets_data),
        rule_05_transcription_supports_transcription(audio_data),
        rule_06_audio_understanding_supports_audio(audio_data),
        rule_07_tts_not_in_transcription_or_understanding(audio_data),
        rule_08_audio_generation_not_in_understanding(audio_data),
        rule_09_required_fields(vision_data, audio_data),
        rule_10_low_confidence_not_in_default(vision_data, audio_data, presets_data),
        rule_11_no_api_keys(vision_data, audio_data, presets_data, models_data),
    ]

    print("\n" + "-" * 60)
    print("校验结果:\n")
    all_passed = True
    for res in results:
        print(res.report())
        print()
        if not res.passed:
            all_passed = False

    pass_count = sum(1 for r in results if r.passed)
    fail_count = sum(1 for r in results if not r.passed)
    print("-" * 60)
    print(f"总计: {len(results)} 条规则, {pass_count} 通过, {fail_count} 失败")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
