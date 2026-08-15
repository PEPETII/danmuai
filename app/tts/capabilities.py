"""Capability checks shared by providers, manager, and future UI adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.tts.types import TtsCapabilities, TtsUnsupportedCapabilityError

if TYPE_CHECKING:
    from app.tts.types import TtsRequest


class CapabilityResolver:
    """Validate request options against a model's declarative capabilities."""

    _OPTION_CAPABILITIES = {
        "style_prompt": "style_prompt",
        "emotion": "emotion",
        "speed": "speed",
        "pitch": "pitch",
        "volume": "volume",
        "streaming": "streaming",
    }

    def supports(self, capabilities: TtsCapabilities, capability: str) -> bool:
        if capability == "output_format":
            return bool(capabilities.output_formats)
        return bool(getattr(capabilities, capability, False))

    def require(self, capabilities: TtsCapabilities, capability: str) -> None:
        if capability == "output_format":
            raise TtsUnsupportedCapabilityError(capability)
        if not self.supports(capabilities, capability):
            raise TtsUnsupportedCapabilityError(capability)

    def validate_request(self, request: TtsRequest, capabilities: TtsCapabilities) -> None:
        for field_name, capability in self._OPTION_CAPABILITIES.items():
            value = getattr(request, field_name)
            active = (
                bool(value)
                if field_name == "streaming"
                else value is not None and value != ""
            )
            if active:
                self.require(capabilities, capability)
        output_format = request.output_format.strip().lower()
        if output_format not in capabilities.output_formats:
            raise TtsUnsupportedCapabilityError(f"output_format:{output_format}")


__all__ = ["CapabilityResolver", "TtsCapabilities"]
