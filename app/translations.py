from PyQt6.QtCore import QLocale, QObject, pyqtSignal

from app.supported_languages import DEFAULT_LANGUAGE, is_supported
from app.translations_danmu import TRANSLATIONS_EN as DANMU_EN
from app.translations_danmu import TRANSLATIONS_ZH as DANMU_ZH
from app.translations_pet import TRANSLATIONS_EN as PET_EN
from app.translations_pet import TRANSLATIONS_ZH as PET_ZH
from app.translations_settings import TRANSLATIONS_EN as SETTINGS_EN
from app.translations_settings import TRANSLATIONS_ZH as SETTINGS_ZH
from app.translations_tts import TRANSLATIONS_EN as TTS_EN
from app.translations_tts import TRANSLATIONS_ZH as TTS_ZH
from app.translations_tray import TRANSLATIONS_EN as TRAY_EN
from app.translations_tray import TRANSLATIONS_ZH as TRAY_ZH
from app.translations_ui import TRANSLATIONS_EN as UI_EN
from app.translations_ui import TRANSLATIONS_ZH as UI_ZH

TRANSLATIONS = {
    "zh": {**UI_ZH, **DANMU_ZH, **SETTINGS_ZH, **TTS_ZH, **TRAY_ZH, **PET_ZH},
    "en": {**UI_EN, **DANMU_EN, **SETTINGS_EN, **TTS_EN, **TRAY_EN, **PET_EN},
}


class Translator(QObject):
    language_changed = pyqtSignal()
    _instance = None
    _lang = "zh"

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def detect_system_language(cls) -> str:
        locale_name = QLocale.system().name().lower()
        if locale_name.startswith("zh"):
            return "zh"
        return "en"

    @classmethod
    def resolve_language(cls, configured_lang: str = "") -> str:
        if isinstance(configured_lang, str):
            code = configured_lang.strip().lower()
            if is_supported(code):
                return code
        return cls.detect_system_language()

    @classmethod
    def set_language(cls, lang: str):
        if not is_supported(lang):
            lang = DEFAULT_LANGUAGE
        if cls._lang != lang:
            cls._lang = lang
            if cls._instance:
                cls._instance.language_changed.emit()

    @classmethod
    def get_language(cls) -> str:
        return cls._lang

    @classmethod
    def tr(cls, key: str, default: str = "", **params) -> str:
        lang_dict = TRANSLATIONS.get(cls._lang, {})
        text = lang_dict.get(key, default or key)
        if params:
            for name, value in params.items():
                text = text.replace(f"{{{name}}}", str(value))
        return text


def tr(key: str, default: str = "", **params) -> str:
    return Translator.tr(key, default, **params)
