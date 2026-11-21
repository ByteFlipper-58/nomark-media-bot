"""HTML message & provenance inspection report renderers."""

from __future__ import annotations

import html
from typing import Any

from nomark.config import (
    BOT_NAME,
    BUDGET_HARD_LIMIT_USD,
    LANG_RU,
    MODAL_MONTHLY_FREE_USD,
    PHOTO_OUT_DOCUMENT,
    SDVAE_NOISE_VALUES,
    WAN_STRENGTH_VALUES,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import current_month_key, estimate_spend_usd
from nomark.presentation.i18n import (
    LANG_LABELS,
    exif_label,
    mode_description,
    mode_label,
    strength_label,
    t,
    vendor_label,
)


def build_language_picker_text() -> str:
    return (
        f"<b>{BOT_NAME}</b> — Choose your language / Выбери язык\n\n"
        "🇬🇧 Select your interface language to continue.\n"
        "🇷🇺 Выбери язык интерфейса для начала работы.\n\n"
        "<i>You can switch it anytime in ⚙️ Settings (/settings).</i>"
    )


def build_welcome_text(settings: UserSettings) -> str:
    lang = settings.lang
    return t(
        "welcome.text",
        lang,
        mode_label=html.escape(mode_label(settings.mode, lang)),
        mode_desc=html.escape(mode_description(settings.mode, lang)),
        strength=strength_label(settings.video_strength, lang),
        vendor=vendor_label(settings.photo_vendor, lang),
        exif=exif_label(settings.camera_exif, lang),
        polish=t("state.on_lower" if settings.natural_polish else "state.off_lower", lang),
        audio=t("state.on_lower" if settings.clean_audio else "state.off_lower", lang),
    )


def build_settings_text(settings: UserSettings) -> str:
    lang = settings.lang
    return t(
        "settings.text",
        lang,
        strength=strength_label(settings.video_strength, lang),
        wan_s=WAN_STRENGTH_VALUES[settings.video_strength],
        vae_s=SDVAE_NOISE_VALUES[settings.video_strength],
        vendor=vendor_label(settings.photo_vendor, lang),
        exif=exif_label(settings.camera_exif, lang),
        polish_desc=t("settings.polish_on" if settings.natural_polish else "settings.polish_off", lang),
        photo_desc=t(
            "photo_out.document_desc" if settings.photo_output == PHOTO_OUT_DOCUMENT else "photo_out.photo_desc",
            lang,
        ),
        audio_desc=t("settings.audio_on" if settings.clean_audio else "settings.audio_off", lang),
        lang_label=LANG_LABELS.get(lang, lang),
    )


def build_warmup_text(lang: str = LANG_RU) -> str:
    return t("warmup.text", lang)


def build_budget_blocked_text(spend: float, lang: str = LANG_RU) -> str:
    return t(
        "budget.blocked",
        lang,
        spend=spend,
        limit=f"{BUDGET_HARD_LIMIT_USD:.0f}",
        free=f"{MODAL_MONTHLY_FREE_USD:.0f}",
    )


def format_error_text(exc: Exception, lang: str = LANG_RU) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    if len(msg) > 500:
        msg = msg[:500] + "..."
    return t("err.header", lang, msg=html.escape(msg))


def format_stats_text(stats: dict[str, Any], *, budget_guard: bool = True, lang: str = LANG_RU) -> str:
    month = html.escape(str(stats.get("month") or current_month_key()))
    spend = estimate_spend_usd(stats)
    remaining = max(0.0, MODAL_MONTHLY_FREE_USD - spend)
    l4_min = float(stats.get("l4_sec", 0.0)) / 60.0
    h100_min = float(stats.get("h100_sec", 0.0)) / 60.0
    cpu_min = float(stats.get("cpu_sec", 0.0)) / 60.0
    guard_line = (
        t("stats.guard_on", lang, limit=f"{BUDGET_HARD_LIMIT_USD:.0f}")
        if budget_guard
        else t("stats.guard_off", lang)
    )
    return t(
        "stats.text",
        lang,
        month=month,
        photos=int(stats.get("photos", 0)),
        albums=int(stats.get("albums", 0)),
        zips=int(stats.get("zips", 0)),
        videos_hd=int(stats.get("videos_hd", 0)),
        videos_fast=int(stats.get("videos_fast", 0)),
        visible_jobs=int(stats.get("visible_jobs", 0)),
        erase_jobs=int(stats.get("erase_jobs", 0)),
        audios=int(stats.get("audios", 0)),
        texts=int(stats.get("texts", 0)),
        c2pa_jobs=int(stats.get("c2pa_jobs", 0)),
        identify_jobs=int(stats.get("identify_jobs", 0)),
        cache_hits=int(stats.get("cache_hits", 0)),
        h100_min=h100_min,
        l4_min=l4_min,
        cpu_min=cpu_min,
        spend=spend,
        free=f"{MODAL_MONTHLY_FREE_USD:.0f}",
        remaining=remaining,
        guard_line=guard_line,
    )


def format_image_identify_report(
    report: Any,
    *,
    source_cls: Any | None = None,
    compressed_by_telegram: bool = False,
    lang: str = LANG_RU,
) -> str:
    verdict = t("report.img.verdict_ai" if report.is_ai_generated else "report.img.verdict_clean", lang)
    platform = html.escape(str(report.platform or t("report.unknown", lang)))

    lines = [
        t("report.img.title", lang),
        t("report.img.meta_line", lang, verdict=verdict),
        t("report.img.platform_line", lang, platform=platform),
    ]

    if getattr(report, "watermarks", None):
        wms = ", ".join(html.escape(str(w)) for w in report.watermarks)
        lines.append(t("report.img.marks_line", lang, wms=wms))

    if source_cls is not None:
        cls_label = html.escape(str(getattr(source_cls, "label", "unknown")))
        sub = getattr(source_cls, "version_subfamily", None)
        conf = float(getattr(source_cls, "confidence", 0.0) or 0.0)
        synth_prob = float(getattr(source_cls, "synthetic_probability", 0.0) or 0.0)
        synth_det = bool(getattr(source_cls, "synthetic_detected", False))
        sub_str = f" / {html.escape(str(sub))}" if sub else ""
        lines.append(t("report.img.cls_header", lang))
        lines.append(t("report.img.cls_source", lang, label=cls_label, sub=sub_str, conf=conf * 100))
        lines.append(
            t(
                "report.img.cls_ai",
                lang,
                yn=t("report.yes" if synth_det else "report.no_unconfirmed", lang),
                prob=synth_prob * 100,
            )
        )

    signals = getattr(report, "signals", None) or []
    if signals:
        lines.append(t("report.signals_header", lang))
        for sig in signals[:8]:
            lines.append(f"  – <code>{html.escape(str(sig.name))}</code>: {html.escape(str(sig.detail))}")

    if compressed_by_telegram:
        lines.append(t("report.img.tg_compressed", lang))
    else:
        lines.append(t("report.img.synthid_note", lang))
    return "\n".join(lines)


def format_video_identify_report(report: Any, *, lang: str = LANG_RU) -> str:
    verdict = t("report.img.verdict_ai" if report.is_ai_generated else "report.img.verdict_clean", lang)
    platform = html.escape(str(report.platform or t("report.unknown", lang)))

    lines = [
        t("report.vid.title", lang),
        t("report.vid.status", lang, verdict=verdict),
        t("report.vid.platform", lang, platform=platform),
        t("report.vid.meta", lang, found=t("report.found" if report.has_ai_metadata else "report.not_found", lang)),
    ]
    if getattr(report, "visible_mark", None):
        lines.append(t("report.vid.visible", lang, mark=html.escape(str(report.visible_mark))))

    markers = getattr(report, "metadata_markers", None) or {}
    if markers:
        keys = ", ".join(html.escape(str(k)) for k in list(markers.keys())[:10])
        lines.append(t("report.fields", lang, keys=keys))

    hints = getattr(report, "invisible_watermark_hints", None) or ()
    if hints:
        hints_text = "; ".join(html.escape(str(h)) for h in hints[:4])
        lines.append(t("report.vid.hints", lang, hints=hints_text))

    lines.append(t("report.vid.note", lang))
    return "\n".join(lines)


def format_audio_identify_report(report: Any, *, lang: str = LANG_RU) -> str:
    markers = getattr(report, "metadata_markers", None) or {}
    status = getattr(report, "watermark_status", "unverified")
    meta_val = t("report.aud.found_n", lang, n=len(markers)) if markers else t("report.not_found", lang)
    lines = [
        t("report.aud.title", lang),
        t("report.aud.meta", lang, val=meta_val),
        t("report.aud.status", lang, status=html.escape(str(status))),
    ]
    if markers:
        keys = ", ".join(html.escape(str(k)) for k in list(markers.keys())[:10])
        lines.append(t("report.fields", lang, keys=keys))
    rec = getattr(report, "recommended_recipe", None)
    if rec:
        lines.append(t("report.aud.rec", lang, rec=html.escape(str(rec))))
    return "\n".join(lines)


def format_text_identify_report(report: Any, *, lang: str = LANG_RU) -> str:
    has_stego = bool(report.is_ai_generated or report.stego_codepoint_count)
    verdict = t("report.txt.verdict_ai" if has_stego else "report.txt.verdict_clean", lang)
    lines = [
        t("report.txt.title", lang),
        t("report.txt.status", lang, verdict=verdict),
        t("report.txt.unicode", lang, count=int(getattr(report, "stego_codepoint_count", 0))),
        t("report.txt.c2pa", lang, yn=t("report.yes" if getattr(report, "has_ai_metadata", False) else "report.no", lang)),
    ]
    if getattr(report, "platform", None):
        lines.append(t("report.vid.platform", lang, platform=html.escape(str(report.platform))))
    signals = getattr(report, "signals", None) or ()
    if signals:
        sigs = ", ".join(html.escape(str(s)) for s in signals[:8])
        lines.append(t("report.txt.signals", lang, sigs=sigs))
    return "\n".join(lines)
