"""Pure domain entities and value objects (zero external dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nomark.config import (
    DEFAULT_CLEAN_AUDIO,
    DEFAULT_EXIF,
    DEFAULT_LANG,
    DEFAULT_MODE,
    DEFAULT_NATURAL_POLISH,
    DEFAULT_PHOTO_OUT,
    DEFAULT_STRENGTH,
    DEFAULT_VENDOR,
    EXIF_ORDER,
    LANG_ORDER,
    LANG_RU,
    STRENGTH_ORDER,
    SUPPORTED_LANGS,
    VALID_EXIF_PROFILES,
    VALID_MODES,
    VALID_PHOTO_OUTS,
    VALID_STRENGTHS,
    VALID_VENDORS,
    VENDOR_ORDER,
)
from nomark.domain.policies import normalize_lang


@dataclass(frozen=True)
class UserSettings:
    """Immutable per-user preferences persisted in the state store."""

    mode: str = DEFAULT_MODE
    clean_audio: bool = DEFAULT_CLEAN_AUDIO
    video_strength: str = DEFAULT_STRENGTH
    natural_polish: bool = DEFAULT_NATURAL_POLISH
    photo_output: str = DEFAULT_PHOTO_OUT
    photo_vendor: str = DEFAULT_VENDOR
    camera_exif: str = DEFAULT_EXIF
    lang: str = LANG_RU
    lang_chosen: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "clean_audio": self.clean_audio,
            "video_strength": self.video_strength,
            "natural_polish": self.natural_polish,
            "photo_output": self.photo_output,
            "photo_vendor": self.photo_vendor,
            "camera_exif": self.camera_exif,
            "lang": self.lang,
            "lang_chosen": self.lang_chosen,
        }

    @classmethod
    def from_raw(cls, raw: Any, *, default_lang: str = LANG_RU) -> UserSettings:
        fallback_lang = normalize_lang(default_lang, fallback=DEFAULT_LANG)
        if isinstance(raw, str) and raw in VALID_MODES:
            return cls(mode=raw, lang=fallback_lang, lang_chosen=False)
        if not isinstance(raw, dict):
            return cls(lang=fallback_lang, lang_chosen=False)
        mode = raw.get("mode", DEFAULT_MODE)
        if mode not in VALID_MODES:
            mode = DEFAULT_MODE
        strength = raw.get("video_strength", DEFAULT_STRENGTH)
        if strength not in VALID_STRENGTHS:
            strength = DEFAULT_STRENGTH
        photo_out = raw.get("photo_output", DEFAULT_PHOTO_OUT)
        if photo_out not in VALID_PHOTO_OUTS:
            photo_out = DEFAULT_PHOTO_OUT
        vendor = raw.get("photo_vendor", DEFAULT_VENDOR)
        if vendor not in VALID_VENDORS:
            vendor = DEFAULT_VENDOR
        exif = raw.get("camera_exif", DEFAULT_EXIF)
        if exif not in VALID_EXIF_PROFILES:
            exif = DEFAULT_EXIF
        raw_lang = raw.get("lang")
        lang = raw_lang if isinstance(raw_lang, str) and raw_lang in SUPPORTED_LANGS else fallback_lang
        return cls(
            mode=mode,
            clean_audio=bool(raw.get("clean_audio", DEFAULT_CLEAN_AUDIO)),
            video_strength=strength,
            natural_polish=bool(raw.get("natural_polish", DEFAULT_NATURAL_POLISH)),
            photo_output=photo_out,
            photo_vendor=vendor,
            camera_exif=exif,
            lang=lang,
            lang_chosen=bool(raw.get("lang_chosen", False)),
        )

    def with_updates(self, **changes: Any) -> UserSettings:
        data = self.to_dict()
        data.update(changes)
        return UserSettings.from_raw(data, default_lang=self.lang)

    def next_strength(self) -> str:
        idx = STRENGTH_ORDER.index(self.video_strength)
        return STRENGTH_ORDER[(idx + 1) % len(STRENGTH_ORDER)]

    def next_vendor(self) -> str:
        idx = VENDOR_ORDER.index(self.photo_vendor)
        return VENDOR_ORDER[(idx + 1) % len(VENDOR_ORDER)]

    def next_exif(self) -> str:
        idx = EXIF_ORDER.index(self.camera_exif)
        return EXIF_ORDER[(idx + 1) % len(EXIF_ORDER)]

    def next_lang(self) -> str:
        idx = LANG_ORDER.index(self.lang) if self.lang in LANG_ORDER else 0
        return LANG_ORDER[(idx + 1) % len(LANG_ORDER)]


@dataclass(frozen=True)
class MediaItem:
    """Normalized media attachment extracted from a Telegram message."""

    kind: str  # "image" | "video" | "audio" | "text_file" | "zip"
    file_id: str
    file_name: str
    file_size: int | None
    compressed_by_telegram: bool = False
    file_unique_id: str | None = None
