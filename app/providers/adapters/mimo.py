"""Xiaomi MiMo OpenAI-compatible adapter.

MiMo 特殊路径（与豆包 Responses 路径对比）：
- MiMo 走 **Chat Completions**（非豆包 Responses），endpoint 形如
  ``https://api.xiaomimimo.com/v1``；调 ``patch_openai_chat_body`` 而非 ``stream_doubao_responses``。
- 视觉 user content 顺序为 ``[image, text]``（与 DefaultOpenAIAdapter 相反；
  MiMo mimo-v2.5 期望图片先于文本）。
- 麦克风音频路径：mimo-v2.5 在 user content 追加 ``{"type": "input_audio",
  "input_audio": {"data": <data-uri>}}``；**data 字段内嵌 data URI 字符串**，与豆包
  Responses 的 ``input_audio`` + ``audio_url``（外链）方式不同。
- 思考模式：MiMo 需要显式 ``thinking: {"type":"disabled"}`` 关闭（默认不传时易返回空）；
  见 ``THINKING_DISABLED`` 与 W-MIMO-MIC-001。
- max_tokens 字段名是 ``max_completion_tokens``（OpenAI 较新规范），由
  ``caps.max_tokens_field`` 注入。
"""

from __future__ import annotations

from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.capabilities import ProviderCapabilities
from app.providers.thinking import apply_thinking_disabled


class MimoOpenAIAdapter(DefaultOpenAIAdapter):
    def build_vision_user_content(
        self,
        user_pt: str,
        image_data_uri: str,
        audio_data_uri: str | None = None,
    ) -> list[dict]:
        image_part = {"type": "image_url", "image_url": {"url": image_data_uri}}
        text_part = {"type": "text", "text": user_pt}
        # MiMo 顺序：image 先于 text（与 DefaultOpenAIAdapter 相反）
        parts = [image_part, text_part]
        if audio_data_uri:
            # mimo-v2.5 开麦：input_audio + input_audio.data（data URI 内嵌）
            # 与豆包 Responses 的 input_audio + audio_url（外链）不同
            parts.append(
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_data_uri},
                }
            )
        return parts

    def patch_openai_chat_body(
        self,
        data: dict,
        *,
        max_tokens: int,
        caps: ProviderCapabilities,
    ) -> None:
        # 移除上游 max_tokens 注入，由 caps.max_tokens_field 重新设置（MiMo 用 max_completion_tokens）
        data.pop("max_tokens", None)
        # MiMo 不支持 stream_options.include_usage，强制清除避免百炼/MiMo 400
        data.pop("stream_options", None)
        # thinking_param=True 默认关闭思考（MiMo 默认 enabled 易返回空 content）
        if caps.thinking_param:
            apply_thinking_disabled(data, caps=caps)
        if max_tokens > 0:
            data[caps.max_tokens_field] = max_tokens

    def patch_probe_body(self, data: dict, *, caps: ProviderCapabilities) -> None:
        if "max_tokens" not in data:
            if caps.thinking_param:
                apply_thinking_disabled(data, caps=caps)
            return
        max_tokens = int(data.pop("max_tokens") or 1)
        self.patch_openai_chat_body(data, max_tokens=max_tokens, caps=caps)
