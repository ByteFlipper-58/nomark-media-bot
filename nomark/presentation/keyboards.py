"""Inline keyboard builders for Telegram (all callback_data strictly <= 64 bytes)."""

from __future__ import annotations

from typing import Any

from nomark.config import (
    BUDGET_HARD_LIMIT_USD,
    DEFAULT_STRENGTH,
    LANG_EN,
    LANG_RU,
    MODE_C2PA_ONLY,
    MODE_ERASE,
    MODE_FULL_FAST,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    MODE_VISIBLE,
    PHOTO_OUT_DOCUMENT,
    STRENGTH_ORDER,
)
from nomark.domain.models import UserSettings
from nomark.presentation.i18n import (
    LANG_LABELS,
    corner_label,
    exif_label,
    mode_label,
    strength_label,
    t,
    vendor_label,
)


def build_language_picker_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": LANG_LABELS[LANG_RU], "callback_data": f"lang:{LANG_RU}"},
                {"text": LANG_LABELS[LANG_EN], "callback_data": f"lang:{LANG_EN}"},
            ]
        ]
    }


def build_menu_keyboard(settings: UserSettings) -> dict[str, Any]:
    lang = settings.lang

    def _mode_btn(mode_key: str) -> dict[str, str]:
        prefix = "✅ " if settings.mode == mode_key else ""
        return {"text": f"{prefix}{mode_label(mode_key, lang)}", "callback_data": f"mode:{mode_key}"}

    return {
        "inline_keyboard": [
            [_mode_btn(MODE_FULL_HD)],
            [_mode_btn(MODE_FULL_FAST)],
            [_mode_btn(MODE_VISIBLE)],
            [_mode_btn(MODE_ERASE)],
            [_mode_btn(MODE_C2PA_ONLY)],
            [_mode_btn(MODE_IDENTIFY)],
            [
                {"text": t("btn.settings", lang), "callback_data": "nav:settings"},
                {"text": t("btn.stats", lang), "callback_data": "nav:stats"},
            ],
            [
                {"text": t("btn.warmup", lang), "callback_data": "nav:warmup"},
            ],
        ]
    }


def build_warmup_keyboard(lang: str = LANG_RU) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": t("btn.warm_photo", lang), "callback_data": "warm:photo"}],
            [{"text": t("btn.warm_vfast", lang), "callback_data": "warm:vfast"}],
            [{"text": t("btn.warm_vwan", lang), "callback_data": "warm:vwan"}],
            [{"text": t("btn.back_modes", lang), "callback_data": "nav:main"}],
        ]
    }


def build_settings_keyboard(settings: UserSettings) -> dict[str, Any]:
    lang = settings.lang
    s_label = strength_label(settings.video_strength, lang)
    v_label = vendor_label(settings.photo_vendor, lang)
    e_label = exif_label(settings.camera_exif, lang)
    polish_state = t("state.on" if settings.natural_polish else "state.off", lang)
    photo_label = t("photo_out.document_btn" if settings.photo_output == PHOTO_OUT_DOCUMENT else "photo_out.photo_btn", lang)
    audio_state = t("state.on" if settings.clean_audio else "state.off", lang)
    audio_icon = "🔊" if settings.clean_audio else "🔇"
    lang_val = LANG_LABELS.get(lang, lang)

    return {
        "inline_keyboard": [
            [{"text": t("btn.set_strength", lang, val=s_label), "callback_data": "set:strength"}],
            [{"text": t("btn.set_vendor", lang, val=v_label), "callback_data": "set:vendor"}],
            [{"text": t("btn.set_exif", lang, val=e_label), "callback_data": "set:exif"}],
            [{"text": t("btn.set_polish", lang, val=polish_state), "callback_data": "set:polish"}],
            [{"text": t("btn.set_photo_out", lang, val=photo_label), "callback_data": "set:photo_out"}],
            [{"text": t("btn.set_audio", lang, icon=audio_icon, val=audio_state), "callback_data": "set:audio"}],
            [{"text": t("btn.set_lang", lang, val=lang_val), "callback_data": "set:lang"}],
            [{"text": t("btn.back_modes", lang), "callback_data": "nav:main"}],
        ]
    }


def build_stats_keyboard(*, budget_guard: bool = True, lang: str = LANG_RU) -> dict[str, Any]:
    guard_state = t("state.on" if budget_guard else "state.off", lang)
    guard_text = t("btn.budget_guard", lang, limit=f"{BUDGET_HARD_LIMIT_USD:.0f}", state=guard_state)
    return {
        "inline_keyboard": [
            [{"text": guard_text, "callback_data": "set:budget_guard"}],
            [
                {"text": t("btn.refresh", lang), "callback_data": "nav:stats"},
                {"text": t("btn.back", lang), "callback_data": "nav:main"},
            ],
        ]
    }


def build_erase_corner_keyboard(job_id: str, lang: str = LANG_RU) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": corner_label("tl", lang), "callback_data": f"erase:{job_id}:tl"},
                {"text": corner_label("tr", lang), "callback_data": f"erase:{job_id}:tr"},
            ],
            [
                {"text": corner_label("bl", lang), "callback_data": f"erase:{job_id}:bl"},
                {"text": corner_label("br", lang), "callback_data": f"erase:{job_id}:br"},
            ],
            [
                {"text": corner_label("bc", lang), "callback_data": f"erase:{job_id}:bc"},
                {"text": corner_label("center", lang), "callback_data": f"erase:{job_id}:center"},
            ],
        ]
    }


def build_result_keyboard(
    job_id: str,
    *,
    kind: str,
    mode: str,
    video_strength: str = DEFAULT_STRENGTH,
    has_source_file: bool = True,
    has_output_file: bool = True,
    is_cached: bool = False,
    lang: str = LANG_RU,
) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []

    if is_cached and has_source_file:
        rows.append([{"text": t("btn.recompute", lang), "callback_data": f"act:recompute:{job_id}"}])

    if kind == "video" and has_source_file and mode in {MODE_FULL_HD, MODE_FULL_FAST}:
        other_strengths = [s for s in STRENGTH_ORDER if s != video_strength]
        rows.append(
            [
                {"text": f"🔁 {strength_label(s, lang)}", "callback_data": f"act:retry:{job_id}:{s}"}
                for s in other_strengths
            ]
        )

    if kind == "image" and has_source_file and mode in {MODE_C2PA_ONLY, MODE_VISIBLE, MODE_ERASE}:
        rows.append([{"text": t("btn.upgrade_synthid", lang), "callback_data": f"act:upgrade:{job_id}"}])

    bottom: list[dict[str, str]] = []
    if has_output_file and kind in {"image", "video", "audio"}:
        bottom.append({"text": t("btn.verify_result", lang), "callback_data": f"act:check:{job_id}"})
    bottom.append({"text": t("btn.menu", lang), "callback_data": "nav:main_new"})
    rows.append(bottom)

    return {"inline_keyboard": rows}
