"""ComfyUI Pinch Voice Translation - Dub and translate audio/video using Pinch AI."""

from .nodes import PinchVoiceTranslation, PinchVoiceTranslationStatus

NODE_CLASS_MAPPINGS = {
    "PinchVoiceTranslation": PinchVoiceTranslation,
    "PinchVoiceTranslationStatus": PinchVoiceTranslationStatus,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PinchVoiceTranslation": "Pinch Voice Translation (Dubbing)",
    "PinchVoiceTranslationStatus": "Pinch Voice Translation Status",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
