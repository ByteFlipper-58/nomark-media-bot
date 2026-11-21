"""CPU & GPU media processing execution pipelines (decoupled from Modal decorators)."""

from __future__ import annotations

import html
import json
import logging
import os
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from nomark.config import (
    CACHE_DIR,
    DOWNLOAD_LINK_TTL_SEC,
    EXIF_OFF,
    LANG_RU,
    MODE_C2PA_ONLY,
    MODE_ERASE,
    MODE_FULL_FAST,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    MODE_VISIBLE,
    PHOTO_OUT_PHOTO,
    SDVAE_NOISE_VALUES,
    TELEGRAM_MAX_DOWNLOAD_BYTES,
    TELEGRAM_MAX_UPLOAD_BYTES,
    TELEGRAM_PHOTO_MAX_BYTES,
    TMP_INPUTS_DIR,
    WAN21_CHUNK_FRAMES,
    WAN21_GUIDANCE_SCALE,
    WAN21_INFERENCE_STEPS,
    WAN21_OVERLAP_FRAMES,
    WAN_STRENGTH_VALUES,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import (
    check_budget_status,
    choose_output_filename,
    clamp_custom_box,
    compute_corner_box,
    resolve_photo_vendor,
)
from nomark.infrastructure.media_io import (
    apply_natural_film_polish,
    cleanup_expired_dirs,
    download_url_safe,
    ensure_video_mp4_if_needed,
    extract_images_from_zip,
    inject_camera_exif,
    pack_files_to_zip,
)
from nomark.infrastructure.ml_loaders import configure_cache_env
from nomark.infrastructure.modal_adapters import ModalStateStore, ModalVolumeHelper
from nomark.infrastructure.telegram_client import SyncTelegramClient
from nomark.presentation.i18n import corner_label, exif_label, strength_label, t, vendor_label
from nomark.presentation.keyboards import (
    build_erase_corner_keyboard,
    build_result_keyboard,
    build_stats_keyboard,
)
from nomark.presentation.views import (
    build_budget_blocked_text,
    format_audio_identify_report,
    format_error_text,
    format_image_identify_report,
    format_text_identify_report,
    format_video_identify_report,
)

log = logging.getLogger("nomark.pipelines")


class SyncJobDispatcher(Protocol):
    """Sync spawn interface used by URL fetcher worker to hand off staged inputs."""

    def spawn_cpu_file(self, **kwargs: Any) -> None: ...

    def spawn_gpu_photo(self, **kwargs: Any) -> None: ...

    def spawn_gpu_zip(self, **kwargs: Any) -> None: ...

    def spawn_gpu_audio(self, **kwargs: Any) -> None: ...

    def spawn_gpu_video_hd(self, **kwargs: Any) -> None: ...

    def spawn_gpu_video_fast(self, **kwargs: Any) -> None: ...


# ---------------------------------------------------------------------------
# Delivery & Action Persistence Helpers
# ---------------------------------------------------------------------------


def _safe_edit_status(tg: SyncTelegramClient, chat_id: int, message_id: int, text: str) -> None:
    """Best-effort progress update so transient Telegram 429/network blips never abort a batch."""
    try:
        tg.edit_message_text(chat_id, message_id, text)
    except Exception as exc:
        log.debug("Non-fatal status edit skipped: %s", exc)


def _hf_cache_snapshot_count() -> int:
    hub_dir = Path(CACHE_DIR) / "hf" / "hub"
    if not hub_dir.exists():
        return 0
    try:
        return sum(1 for _ in hub_dir.iterdir())
    except Exception:
        return 0


def deliver_file(
    tg: SyncTelegramClient,
    vol: ModalVolumeHelper,
    *,
    chat_id: int,
    file_path: Path,
    kind: str,
    caption: str,
    reply_to_message_id: int | None,
    photo_output: str = "document",
    reply_markup: dict[str, Any] | None = None,
    lang: str = LANG_RU,
) -> tuple[str | None, str]:
    """Deliver output via Telegram, falling back to a 1-hour Modal link when >50 MB."""
    size = file_path.stat().st_size
    if size > TELEGRAM_MAX_UPLOAD_BYTES:
        mb = size / (1024 * 1024)
        url = vol.publish_large_file(file_path)
        tg.send_message(
            chat_id,
            t("cap.large_file", lang, caption=caption, mb=mb, url=html.escape(url)),
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return None, "link"

    if kind == "image":
        if photo_output == PHOTO_OUT_PHOTO and size <= TELEGRAM_PHOTO_MAX_BYTES:
            try:
                fid = tg.send_photo(
                    chat_id,
                    file_path,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup,
                )
                return fid, "photo"
            except Exception as photo_exc:
                log.warning("sendPhoto failed (%s), falling back to sendDocument", photo_exc)
        fid = tg.send_document(
            chat_id,
            file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return fid, "document"

    if kind == "video":
        if file_path.suffix.lower() == ".mp4":
            fid = tg.send_video(
                chat_id,
                file_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
            return fid, "video"
        fid = tg.send_document(
            chat_id,
            file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return fid, "document"

    if kind == "audio":
        if file_path.suffix.lower() in {".mp3", ".m4a", ".ogg", ".opus"}:
            fid = tg.send_audio(
                chat_id,
                file_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
            return fid, "audio"
        fid = tg.send_document(
            chat_id,
            file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return fid, "document"

    fid = tg.send_document(
        chat_id,
        file_path,
        caption=caption,
        reply_to_message_id=reply_to_message_id,
        reply_markup=reply_markup,
    )
    return fid, "document"


def deliver_with_actions(
    tg: SyncTelegramClient,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    *,
    chat_id: int,
    file_path: Path,
    kind: str,
    caption: str,
    reply_to_message_id: int | None,
    mode: str,
    src_file_id: str | None,
    src_file_name: str,
    src_compressed: bool = False,
    video_strength: str = "balanced",
    clean_audio: bool = True,
    natural_polish: bool = True,
    photo_vendor: str = "auto",
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    """Deliver file with post-result inline action buttons and persist job + result cache."""
    job_id = uuid.uuid4().hex[:10]
    will_have_tg_output = file_path.stat().st_size <= TELEGRAM_MAX_DOWNLOAD_BYTES
    markup = build_result_keyboard(
        job_id,
        kind=kind,
        mode=mode,
        video_strength=video_strength,
        has_source_file=bool(src_file_id),
        has_output_file=will_have_tg_output,
        lang=lang,
    )
    out_file_id, delivery_method = deliver_file(
        tg,
        vol,
        chat_id=chat_id,
        file_path=file_path,
        kind=kind,
        caption=caption,
        reply_to_message_id=reply_to_message_id,
        photo_output=photo_output,
        reply_markup=markup,
        lang=lang,
    )
    state.save_result_cache_sync(
        cache_key,
        out_file_id=out_file_id,
        delivery_method=delivery_method,
        file_path=file_path,
        caption=caption,
        lang=lang,
    )
    state.save_job_sync(
        job_id,
        {
            "kind": kind,
            "mode": mode,
            "src_file_id": src_file_id,
            "src_file_name": src_file_name,
            "src_compressed": src_compressed,
            "out_file_id": out_file_id,
            "out_file_name": file_path.name,
            "out_compressed": delivery_method == "photo",
            "video_strength": video_strength,
            "clean_audio": clean_audio,
            "natural_polish": natural_polish,
            "photo_vendor": photo_vendor,
            "camera_exif": camera_exif,
            "photo_output": photo_output,
            "cache_key": cache_key,
            "lang": lang,
            "created_at": int(time.time()),
        },
    )


def notify_warmup_done(
    tg_token: str,
    *,
    chat_id: int | None,
    status_message_id: int | None,
    i18n_key: str,
    elapsed: float,
    lang: str = LANG_RU,
) -> None:
    if not chat_id or not status_message_id:
        return
    try:
        with SyncTelegramClient(tg_token) as tg:
            tg.edit_message_text(chat_id, status_message_id, t(i18n_key, lang, sec=elapsed))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CPU Worker Pipelines
# ---------------------------------------------------------------------------


def run_cpu_file_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    kind: str,
    file_id: str | None,
    file_name: str,
    mode: str,
    compressed_by_telegram: bool,
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    staged_path: str | None = None,
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    vol.safe_reload()
    configure_cache_env()

    started = time.monotonic()
    cache_dirty = False

    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_cpu_") as tmp:
                work_dir = Path(tmp)
                action = "upload_video" if kind == "video" else ("upload_voice" if kind == "audio" else "upload_document")
                tg.send_chat_action(chat_id, action)
                src = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )

                # ---- TEXT FILE ----
                if kind == "text_file":
                    import remove_ai_watermarks as raiw

                    if mode == MODE_IDENTIFY:
                        report = raiw.identify_text(src)
                        tg.edit_message_text(chat_id, status_message_id, format_text_identify_report(report, lang=lang))
                    else:
                        out = work_dir / choose_output_filename(file_name, "text_file")
                        res = raiw.remove_text_metadata(src, out)
                        elapsed = time.monotonic() - started
                        caption = t(
                            "cap.text_done",
                            lang,
                            sec=elapsed,
                            codepoints=res.removed_codepoints,
                            markers=len(res.detected_markers),
                        )
                        deliver_file(
                            tg,
                            vol,
                            chat_id=chat_id,
                            file_path=out,
                            kind="text_file",
                            caption=caption,
                            reply_to_message_id=reply_to_message_id,
                            lang=lang,
                        )
                        tg.delete_message(chat_id, status_message_id)
                    state.record_stat_sync("texts", "cpu", time.monotonic() - started, lang=lang)
                    return

                # ---- IDENTIFY MODE ----
                if mode == MODE_IDENTIFY:
                    if kind == "image":
                        import remove_ai_watermarks as raiw
                        from remove_ai_watermarks.identify import identify

                        report = identify(src, check_visible=True, check_invisible=False)
                        source_cls = None
                        try:
                            tg.edit_message_text(chat_id, status_message_id, t("status.identify_pixels", lang))
                            source_cls = raiw.classify_source(src)
                            cache_dirty = True
                        except Exception as cls_exc:
                            log.warning("classify_source skipped: %s", cls_exc)
                        text = format_image_identify_report(
                            report,
                            source_cls=source_cls,
                            compressed_by_telegram=compressed_by_telegram,
                            lang=lang,
                        )
                    elif kind == "video":
                        import remove_ai_watermarks as raiw

                        report = raiw.identify_video(src, check_visible=True, check_audio=False)
                        text = format_video_identify_report(report, lang=lang)
                    elif kind == "audio":
                        import remove_ai_watermarks as raiw

                        report = raiw.identify_audio(src, check_invisible=False)
                        text = format_audio_identify_report(report, lang=lang)
                    else:
                        text = t("err.zip_identify_unsupported", lang)

                    tg.edit_message_text(chat_id, status_message_id, text)
                    if cache_dirty:
                        vol.safe_commit()
                    state.record_stat_sync("identify_jobs", "cpu", time.monotonic() - started, lang=lang)
                    return

                # ---- ZIP BATCH ON CPU (VISIBLE OR C2PA_ONLY) ----
                if kind == "zip":
                    import remove_ai_watermarks as raiw
                    from remove_ai_watermarks.metadata import remove_ai_metadata

                    extract_dir = work_dir / "extracted"
                    images = extract_images_from_zip(src, extract_dir)
                    if not images:
                        raise ValueError(t("err.zip_no_images", lang))

                    cleaned_pairs: list[tuple[Path, str]] = []
                    out_dir = work_dir / "cleaned"
                    out_dir.mkdir(exist_ok=True)
                    removed_marks_total = 0

                    for idx, img_path in enumerate(images, start=1):
                        if idx == 1 or idx % 4 == 0 or idx == len(images):
                            _safe_edit_status(
                                tg,
                                chat_id,
                                status_message_id,
                                t("status.zip_cpu_progress", lang, idx=idx, n=len(images)),
                            )
                        orig_name = img_path.name.split("_", 1)[1] if "_" in img_path.name else img_path.name
                        if mode == MODE_VISIBLE:
                            out_name = choose_output_filename(orig_name, "image")
                            out_img = out_dir / f"{idx:03d}_{out_name}"
                            vis_res = raiw.remove_visible_detailed(img_path, out_img, backend="migan", strip_metadata=True)
                            cache_dirty = True
                            if vis_res.labels:
                                removed_marks_total += 1
                        else:
                            out_name = f"{Path(orig_name).stem}_clean{img_path.suffix.lower() or '.png'}"
                            out_img = out_dir / f"{idx:03d}_{out_name}"
                            remove_ai_metadata(img_path, out_img)
                        if camera_exif != EXIF_OFF:
                            out_img = inject_camera_exif(out_img, camera_exif)
                            out_name = Path(out_name).with_suffix(out_img.suffix).name
                        cleaned_pairs.append((out_img, out_name))

                    out_zip = work_dir / choose_output_filename(file_name, "zip")
                    pack_files_to_zip(cleaned_pairs, out_zip)
                    elapsed = time.monotonic() - started
                    mode_note = (
                        t("cap.zip_mode_visible", lang, n=removed_marks_total)
                        if mode == MODE_VISIBLE
                        else t("cap.zip_mode_c2pa", lang)
                    )
                    exif_note = f"\n{t('cap.exif_line', lang, exif=exif_label(camera_exif, lang))}" if camera_exif != EXIF_OFF else ""
                    caption = t(
                        "cap.zip_cpu_done",
                        lang,
                        sec=elapsed,
                        count=len(cleaned_pairs),
                        mode_note=mode_note,
                        exif_note=exif_note,
                    )
                    out_fid, delivery_method = deliver_file(
                        tg,
                        vol,
                        chat_id=chat_id,
                        file_path=out_zip,
                        kind="zip",
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        lang=lang,
                    )
                    state.save_result_cache_sync(
                        cache_key,
                        out_file_id=out_fid,
                        delivery_method=delivery_method,
                        file_path=out_zip,
                        caption=caption,
                        lang=lang,
                    )
                    tg.delete_message(chat_id, status_message_id)
                    if cache_dirty:
                        vol.safe_commit()
                    state.record_stat_sync("zips", "cpu", elapsed, count=1, lang=lang)
                    state.record_stat_sync("photos", "cpu", 0.0, count=len(cleaned_pairs), lang=lang)
                    return

                # ---- VISIBLE MARK REMOVAL MODE (MI-GAN ONNX CPU) ----
                if mode == MODE_VISIBLE:
                    import remove_ai_watermarks as raiw

                    if kind == "image":
                        out = work_dir / choose_output_filename(file_name, "image")
                        tg.edit_message_text(chat_id, status_message_id, t("status.visible_img", lang))
                        vis_res = raiw.remove_visible_detailed(src, out, backend="migan", strip_metadata=True)
                        cache_dirty = True
                        if camera_exif != EXIF_OFF:
                            out = inject_camera_exif(out, camera_exif)
                        elapsed = time.monotonic() - started
                        labels = (
                            ", ".join(html.escape(lb) for lb in vis_res.labels)
                            if vis_res.labels
                            else t("cap.visible_none_img", lang)
                        )
                        exif_line = f"\n{t('cap.exif_line', lang, exif=exif_label(camera_exif, lang))}" if camera_exif != EXIF_OFF else ""
                        caption = t("cap.visible_img_done", lang, sec=elapsed, labels=labels, exif_line=exif_line)
                        deliver_with_actions(
                            tg,
                            state,
                            vol,
                            chat_id=chat_id,
                            file_path=out,
                            kind="image",
                            caption=caption,
                            reply_to_message_id=reply_to_message_id,
                            mode=MODE_VISIBLE,
                            src_file_id=file_id,
                            src_file_name=file_name,
                            src_compressed=compressed_by_telegram,
                            camera_exif=camera_exif,
                            photo_output=photo_output,
                            cache_key=cache_key,
                            lang=lang,
                        )
                    elif kind == "video":
                        out = work_dir / choose_output_filename(file_name, "video")
                        tg.edit_message_text(chat_id, status_message_id, t("status.visible_vid", lang))
                        vis_vid = raiw.remove_video_visible(src, out, mark="auto", backend="migan", strip_metadata=True)
                        cache_dirty = True
                        if vis_vid.output is not None and vis_vid.output.exists():
                            elapsed = time.monotonic() - started
                            caption = t(
                                "cap.visible_vid_done",
                                lang,
                                sec=elapsed,
                                mark=html.escape(vis_vid.mark),
                                removed=vis_vid.removed_frames,
                                total=vis_vid.total_frames,
                            )
                            final_path = vis_vid.output
                        else:
                            meta_res = raiw.remove_video_metadata(src, out)
                            elapsed = time.monotonic() - started
                            caption = t("cap.visible_vid_none", lang, sec=elapsed, n=len(meta_res.detected))
                            final_path = meta_res.output
                        deliver_with_actions(
                            tg,
                            state,
                            vol,
                            chat_id=chat_id,
                            file_path=final_path,
                            kind="video",
                            caption=caption,
                            reply_to_message_id=reply_to_message_id,
                            mode=MODE_VISIBLE,
                            src_file_id=file_id,
                            src_file_name=file_name,
                            cache_key=cache_key,
                            lang=lang,
                        )
                    elif kind == "audio":
                        out = work_dir / f"{src.stem}_clean{src.suffix.lower() or '.mp3'}"
                        res = raiw.remove_audio_metadata(src, out)
                        elapsed = time.monotonic() - started
                        caption = t("cap.audio_meta_done", lang, sec=elapsed, before=len(res.detected), after=len(res.remaining))
                        deliver_with_actions(
                            tg,
                            state,
                            vol,
                            chat_id=chat_id,
                            file_path=res.output,
                            kind="audio",
                            caption=caption,
                            reply_to_message_id=reply_to_message_id,
                            mode=MODE_VISIBLE,
                            src_file_id=file_id,
                            src_file_name=file_name,
                            cache_key=cache_key,
                            lang=lang,
                        )
                    tg.delete_message(chat_id, status_message_id)
                    if cache_dirty:
                        vol.safe_commit()
                    state.record_stat_sync("visible_jobs", "cpu", time.monotonic() - started, lang=lang)
                    return

                # ---- C2PA_ONLY MODE ----
                if kind == "image":
                    from remove_ai_watermarks.metadata import get_ai_metadata, remove_ai_metadata

                    before_markers = get_ai_metadata(src)
                    out = work_dir / f"{src.stem}_clean{src.suffix.lower() or '.png'}"
                    remove_ai_metadata(src, out)
                    if camera_exif != EXIF_OFF:
                        out = inject_camera_exif(out, camera_exif)
                    after_markers = get_ai_metadata(out)
                    elapsed = time.monotonic() - started
                    caption_lines = [
                        t("cap.c2pa_img_title", lang, sec=elapsed),
                        t("cap.c2pa_fields", lang, before=len(before_markers), after=len(after_markers)),
                        t("cap.c2pa_synthid_note", lang),
                    ]
                    if camera_exif != EXIF_OFF:
                        caption_lines.append(t("cap.exif_line", lang, exif=exif_label(camera_exif, lang)))
                    if compressed_by_telegram:
                        caption_lines.append(t("cap.tg_doc_tip", lang))
                    deliver_with_actions(
                        tg,
                        state,
                        vol,
                        chat_id=chat_id,
                        file_path=out,
                        kind="image",
                        caption="\n".join(caption_lines),
                        reply_to_message_id=reply_to_message_id,
                        mode=MODE_C2PA_ONLY,
                        src_file_id=file_id,
                        src_file_name=file_name,
                        src_compressed=compressed_by_telegram,
                        camera_exif=camera_exif,
                        photo_output=photo_output,
                        cache_key=cache_key,
                        lang=lang,
                    )
                elif kind == "video":
                    import remove_ai_watermarks as raiw

                    out = work_dir / f"{src.stem}_clean{src.suffix.lower() or '.mp4'}"
                    result = raiw.remove_video_metadata(src, out)
                    elapsed = time.monotonic() - started
                    caption = t("cap.c2pa_vid_done", lang, sec=elapsed, before=len(result.detected), after=len(result.remaining))
                    deliver_with_actions(
                        tg,
                        state,
                        vol,
                        chat_id=chat_id,
                        file_path=result.output,
                        kind="video",
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        mode=MODE_C2PA_ONLY,
                        src_file_id=file_id,
                        src_file_name=file_name,
                        cache_key=cache_key,
                        lang=lang,
                    )
                elif kind == "audio":
                    import remove_ai_watermarks as raiw

                    out = work_dir / f"{src.stem}_clean{src.suffix.lower() or '.mp3'}"
                    result = raiw.remove_audio_metadata(src, out)
                    elapsed = time.monotonic() - started
                    caption = t("cap.audio_meta_done", lang, sec=elapsed, before=len(result.detected), after=len(result.remaining))
                    deliver_with_actions(
                        tg,
                        state,
                        vol,
                        chat_id=chat_id,
                        file_path=result.output,
                        kind="audio",
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        mode=MODE_C2PA_ONLY,
                        src_file_id=file_id,
                        src_file_name=file_name,
                        cache_key=cache_key,
                        lang=lang,
                    )

                tg.delete_message(chat_id, status_message_id)
                state.record_stat_sync("c2pa_jobs", "cpu", time.monotonic() - started, lang=lang)
        except Exception as exc:
            log.error("cpu_process_file failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass
        finally:
            vol.cleanup_staged_input(staged_path)


def _resolve_erase_box(
    *,
    width: int,
    height: int,
    corner: str | None,
    custom_box: tuple[int, int, int, int] | None,
    lang: str,
) -> tuple[int, int, int, int]:
    if custom_box is not None:
        clamped = clamp_custom_box(custom_box, width, height)
        if clamped is None:
            x, y, bw, bh = custom_box
            raise ValueError(t("err.coords_oob", lang, x=x, y=y, bw=bw, bh=bh, w=width, h=height))
        return clamped
    return compute_corner_box(width, height, corner or "br")


def run_cpu_erase_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    kind: str,
    file_id: str | None,
    file_name: str,
    corner: str | None = None,
    custom_box: tuple[int, int, int, int] | None = None,
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    staged_path: str | None = None,
    lang: str = LANG_RU,
) -> None:
    """Erase a chosen corner or custom (x,y,w,h) region from a photo or video via MI-GAN."""
    vol.safe_reload()
    configure_cache_env()

    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_erase_") as tmp:
                work_dir = Path(tmp)
                tg.send_chat_action(chat_id, "upload_video" if kind == "video" else "upload_document")
                src = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )

                if kind == "image":
                    from remove_ai_watermarks import image_io, region_eraser
                    from remove_ai_watermarks.metadata import strip_written_output

                    bgr, alpha = image_io.read_bgr_and_alpha(src)
                    if bgr is None:
                        raise ValueError(t("err.img_read", lang))
                    h, w = bgr.shape[:2]
                    box = _resolve_erase_box(width=w, height=h, corner=corner, custom_box=custom_box, lang=lang)
                    zone_label = corner_label(corner, lang) if corner else f"{box[0]},{box[1]},{box[2]},{box[3]}"

                    tg.edit_message_text(chat_id, status_message_id, t("status.erase_img", lang, zone=zone_label))
                    erased = region_eraser.erase(bgr, boxes=[box], backend="migan", dilate=4)
                    out = work_dir / choose_output_filename(file_name, "image")
                    if not image_io.write_bgr_with_alpha(out, erased, alpha, display_tags_from=src, orientation_applied=False):
                        raise OSError(t("err.img_write", lang))
                    strip_written_output(out)
                    if camera_exif != EXIF_OFF:
                        out = inject_camera_exif(out, camera_exif)
                    vol.safe_commit()

                    elapsed = time.monotonic() - started
                    exif_line = f"\n{t('cap.exif_line', lang, exif=exif_label(camera_exif, lang))}" if camera_exif != EXIF_OFF else ""
                    caption = t(
                        "cap.erase_img_done",
                        lang,
                        sec=elapsed,
                        zone=html.escape(zone_label),
                        box=f"{box[0]},{box[1]},{box[2]},{box[3]}",
                        exif_line=exif_line,
                    )
                    deliver_with_actions(
                        tg,
                        state,
                        vol,
                        chat_id=chat_id,
                        file_path=out,
                        kind="image",
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        mode=MODE_ERASE,
                        src_file_id=file_id,
                        src_file_name=file_name,
                        camera_exif=camera_exif,
                        photo_output=photo_output,
                        lang=lang,
                    )
                else:
                    import remove_ai_watermarks as raiw
                    from remove_ai_watermarks.video_invisible import _probe_video

                    w, h, _fps = _probe_video(src)
                    box = _resolve_erase_box(width=w, height=h, corner=corner, custom_box=custom_box, lang=lang)
                    zone_label = corner_label(corner, lang) if corner else f"{box[0]},{box[1]},{box[2]},{box[3]}"
                    out = work_dir / choose_output_filename(file_name, "video")

                    tg.edit_message_text(chat_id, status_message_id, t("status.erase_vid", lang, zone=zone_label))
                    res = raiw.remove_video_region(
                        src,
                        out,
                        regions=[box],
                        backend="migan",
                        dilate=4,
                        strip_metadata=True,
                    )
                    vol.safe_commit()

                    elapsed = time.monotonic() - started
                    caption = t(
                        "cap.erase_vid_done",
                        lang,
                        sec=elapsed,
                        zone=html.escape(zone_label),
                        erased=res.erased_frames,
                        total=res.total_frames,
                    )
                    deliver_with_actions(
                        tg,
                        state,
                        vol,
                        chat_id=chat_id,
                        file_path=res.output,
                        kind="video",
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        mode=MODE_ERASE,
                        src_file_id=file_id,
                        src_file_name=file_name,
                        lang=lang,
                    )

                tg.delete_message(chat_id, status_message_id)
                state.record_stat_sync("erase_jobs", "cpu", time.monotonic() - started, lang=lang)
        except Exception as exc:
            log.error("cpu_erase_region failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass


def run_cpu_album_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    items: list[dict[str, Any]],
    mode: str,
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    lang: str = LANG_RU,
) -> None:
    """Process a Telegram photo album on CPU (C2PA-only, Visible MI-GAN, or Identify)."""
    vol.safe_reload()
    configure_cache_env()

    started = time.monotonic()
    cache_dirty = False

    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_cpu_album_") as tmp:
                work_dir = Path(tmp)
                if mode == MODE_IDENTIFY:
                    import remove_ai_watermarks as raiw
                    from remove_ai_watermarks.identify import identify

                    summary_lines = [t("cap.album_identify_title", lang, n=len(items))]
                    for idx, item in enumerate(items, start=1):
                        src = tg.download_file(item["file_id"], work_dir / f"{idx:02d}_{item['file_name']}")
                        rep = identify(src, check_visible=True, check_invisible=False)
                        cls_str = ""
                        try:
                            sc = raiw.classify_source(src)
                            cache_dirty = True
                            cls_str = t(
                                "cap.album_identify_cls",
                                lang,
                                label=html.escape(str(sc.label)),
                                conf=sc.confidence * 100,
                            )
                        except Exception:
                            pass
                        verdict = t("cap.album_identify_ai" if rep.is_ai_generated else "cap.album_identify_clean", lang)
                        summary_lines.append(f"{idx}. <b>{verdict}</b>{cls_str}")
                    tg.edit_message_text(chat_id, status_message_id, "\n".join(summary_lines))
                    if cache_dirty:
                        vol.safe_commit()
                    state.record_stat_sync("identify_jobs", "cpu", time.monotonic() - started, count=len(items), lang=lang)
                    return

                import remove_ai_watermarks as raiw
                from remove_ai_watermarks.metadata import remove_ai_metadata

                processed = 0
                for idx, item in enumerate(items, start=1):
                    _safe_edit_status(
                        tg,
                        chat_id,
                        status_message_id,
                        t("status.album_cpu_progress", lang, idx=idx, n=len(items)),
                    )
                    src = tg.download_file(item["file_id"], work_dir / f"{idx:02d}_{item['file_name']}")
                    if mode == MODE_VISIBLE:
                        out = work_dir / f"{idx:02d}_{choose_output_filename(item['file_name'], 'image')}"
                        raiw.remove_visible_detailed(src, out, backend="migan", strip_metadata=True)
                        cache_dirty = True
                    else:
                        out = work_dir / f"{idx:02d}_{src.stem}_clean{src.suffix.lower() or '.png'}"
                        remove_ai_metadata(src, out)
                    if camera_exif != EXIF_OFF:
                        out = inject_camera_exif(out, camera_exif)
                    deliver_file(
                        tg,
                        vol,
                        chat_id=chat_id,
                        file_path=out,
                        kind="image",
                        caption=t("cap.album_item_cpu", lang, idx=idx, n=len(items)),
                        reply_to_message_id=reply_to_message_id if idx == 1 else None,
                        photo_output=photo_output,
                        lang=lang,
                    )
                    processed += 1

                elapsed = time.monotonic() - started
                tg.edit_message_text(
                    chat_id,
                    status_message_id,
                    t("cap.album_cpu_done", lang, sec=elapsed, done=processed, n=len(items)),
                )
                if cache_dirty:
                    vol.safe_commit()
                state.record_stat_sync("albums", "cpu", elapsed, count=1, lang=lang)
                state.record_stat_sync("photos", "cpu", 0.0, count=processed, lang=lang)
        except Exception as exc:
            log.error("cpu_process_album failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass


def run_cpu_text_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    raw_text: str,
    mode: str,
    lang: str = LANG_RU,
) -> None:
    import remove_ai_watermarks as raiw

    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            if mode == MODE_IDENTIFY:
                report = raiw.identify_text(raw_text)
                tg.edit_message_text(chat_id, status_message_id, format_text_identify_report(report, lang=lang))
            else:
                res = raiw.remove_text_metadata(raw_text)
                elapsed = time.monotonic() - started
                header = t(
                    "cap.text_done",
                    lang,
                    sec=elapsed,
                    codepoints=res.removed_codepoints,
                    markers=len(res.detected_markers),
                )
                full_html = f"{header}\n\n<pre>{html.escape(res.cleaned_text)}</pre>"
                if len(full_html) <= 4000:
                    tg.edit_message_text(chat_id, status_message_id, full_html)
                else:
                    with tempfile.TemporaryDirectory(prefix="nomark_txt_") as tmp:
                        out = Path(tmp) / "cleaned_text.txt"
                        out.write_text(res.cleaned_text, encoding="utf-8")
                        tg.send_document(chat_id, out, caption=header, reply_to_message_id=reply_to_message_id)
                        tg.delete_message(chat_id, status_message_id)
            state.record_stat_sync("texts", "cpu", time.monotonic() - started, lang=lang)
        except Exception as exc:
            log.error("cpu_process_text failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass


def run_url_job_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    dispatcher: SyncJobDispatcher,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    url: str,
    settings_dict: dict[str, Any],
) -> None:
    vol.safe_reload()
    configure_cache_env()

    settings = UserSettings.from_raw(settings_dict)
    lang = settings.lang

    with SyncTelegramClient(tg_token) as tg:
        try:
            base_dir = Path(TMP_INPUTS_DIR)
            base_dir.mkdir(parents=True, exist_ok=True)
            cleanup_expired_dirs(base_dir)

            token = uuid.uuid4().hex
            slot = base_dir / token
            downloaded, kind = download_url_safe(url, slot)
            (slot / "meta.json").write_text(
                json.dumps({"expires_at": time.time() + DOWNLOAD_LINK_TTL_SEC}),
                encoding="utf-8",
            )
            vol.safe_commit()

            mb = downloaded.stat().st_size / (1024 * 1024)
            tg.edit_message_text(chat_id, status_message_id, t("status.url_downloaded", lang, mb=mb))

            if settings.mode == MODE_ERASE:
                if kind not in {"image", "video"}:
                    vol.cleanup_staged_input(str(downloaded))
                    tg.edit_message_text(chat_id, status_message_id, t("err.erase_only_media", lang))
                    return
                job_id = uuid.uuid4().hex[:10]
                state.save_erase_job_sync(
                    job_id,
                    chat_id,
                    {
                        "kind": kind,
                        "file_id": None,
                        "staged_path": str(downloaded),
                        "file_name": downloaded.name,
                        "reply_to_message_id": reply_to_message_id,
                    },
                )
                tg.edit_message_text(
                    chat_id,
                    status_message_id,
                    t("status.erase_choose_url", lang, mb=mb),
                    reply_markup=build_erase_corner_keyboard(job_id, lang=lang),
                )
                return

            if settings.mode in {MODE_C2PA_ONLY, MODE_IDENTIFY, MODE_VISIBLE} or kind == "text_file":
                dispatcher.spawn_cpu_file(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    status_message_id=status_message_id,
                    kind=kind,
                    file_id=None,
                    file_name=downloaded.name,
                    mode=settings.mode,
                    compressed_by_telegram=False,
                    camera_exif=settings.camera_exif,
                    photo_output=settings.photo_output,
                    staged_path=str(downloaded),
                    lang=lang,
                )
                return

            stats = state.load_stats_sync()
            guard_on = state.is_budget_guard_enabled_sync()
            b_status, spend = check_budget_status(stats, guard_enabled=guard_on)
            if b_status == "blocked":
                vol.cleanup_staged_input(str(downloaded))
                tg.edit_message_text(
                    chat_id,
                    status_message_id,
                    build_budget_blocked_text(spend, lang),
                    reply_markup=build_stats_keyboard(budget_guard=guard_on, lang=lang),
                )
                return

            if kind == "image":
                dispatcher.spawn_gpu_photo(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    status_message_id=status_message_id,
                    file_id=None,
                    file_name=downloaded.name,
                    compressed_by_telegram=False,
                    natural_polish=settings.natural_polish,
                    photo_vendor=settings.photo_vendor,
                    camera_exif=settings.camera_exif,
                    photo_output=settings.photo_output,
                    staged_path=str(downloaded),
                    lang=lang,
                )
                return

            if kind == "zip":
                dispatcher.spawn_gpu_zip(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    status_message_id=status_message_id,
                    file_id=None,
                    file_name=downloaded.name,
                    natural_polish=settings.natural_polish,
                    photo_vendor=settings.photo_vendor,
                    camera_exif=settings.camera_exif,
                    staged_path=str(downloaded),
                    lang=lang,
                )
                return

            if kind == "audio":
                dispatcher.spawn_gpu_audio(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    status_message_id=status_message_id,
                    file_id=None,
                    file_name=downloaded.name,
                    staged_path=str(downloaded),
                    lang=lang,
                )
                return

            if settings.mode == MODE_FULL_HD:
                dispatcher.spawn_gpu_video_hd(
                    chat_id=chat_id,
                    reply_to_message_id=reply_to_message_id,
                    status_message_id=status_message_id,
                    file_id=None,
                    file_name=downloaded.name,
                    clean_audio=settings.clean_audio,
                    video_strength=settings.video_strength,
                    natural_polish=settings.natural_polish,
                    staged_path=str(downloaded),
                    lang=lang,
                )
                return

            dispatcher.spawn_gpu_video_fast(
                chat_id=chat_id,
                reply_to_message_id=reply_to_message_id,
                status_message_id=status_message_id,
                file_id=None,
                file_name=downloaded.name,
                clean_audio=settings.clean_audio,
                video_strength=settings.video_strength,
                staged_path=str(downloaded),
                lang=lang,
            )
        except Exception as exc:
            log.error("process_url_job failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# GPU Photo, Album, ZIP & Audio Pipelines
# ---------------------------------------------------------------------------


def process_one_photo(
    src: Path,
    out: Path,
    *,
    engine: Any,
    natural_polish: bool,
    photo_vendor: str,
    camera_exif: str,
) -> tuple[Path, Any, dict[str, str], dict[str, str], str, Any]:
    import remove_ai_watermarks as raiw
    from remove_ai_watermarks.api import InvisibleOptions
    from remove_ai_watermarks.identify import identify
    from remove_ai_watermarks.metadata import get_ai_metadata

    before_report = identify(src, check_visible=False, check_invisible=False)
    before_meta = get_ai_metadata(src)

    eff_vendor, explicit_strength = resolve_photo_vendor(photo_vendor, before_report.platform)
    hf_token = os.environ.get("HF_TOKEN") or None
    opts = InvisibleOptions(
        pipeline="sdxl-zimage",
        vendor=eff_vendor,
        strength=explicit_strength,
        hf_token=hf_token,
        humanize=2.5 if natural_polish else 0.0,
    )
    result = raiw.remove_all(
        src,
        out,
        invisible=opts,
        force=True,
        engine=engine,
    )
    final_out = out
    if camera_exif != EXIF_OFF:
        final_out = inject_camera_exif(final_out, camera_exif)
    after_meta = get_ai_metadata(final_out)
    return final_out, before_report, before_meta, after_meta, eff_vendor, result


def run_gpu_photo_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    get_engine: Callable[[], Any],
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    file_id: str | None,
    file_name: str,
    compressed_by_telegram: bool,
    natural_polish: bool = True,
    photo_vendor: str = "auto",
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    staged_path: str | None = None,
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_photo_gpu_") as tmp:
                work_dir = Path(tmp)
                tg.send_chat_action(chat_id, "upload_document")
                src = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )
                out = work_dir / choose_output_filename(src.name, "image")

                _safe_edit_status(tg, chat_id, status_message_id, t("status.photo_cleaning", lang))
                hf_before = _hf_cache_snapshot_count()
                engine = get_engine()
                final_out, before_report, before_meta, after_meta, eff_vendor, result = process_one_photo(
                    src,
                    out,
                    engine=engine,
                    natural_polish=natural_polish,
                    photo_vendor=photo_vendor,
                    camera_exif=camera_exif,
                )
                if _hf_cache_snapshot_count() > hf_before:
                    vol.safe_commit()

                elapsed = time.monotonic() - started
                warn_note = state.record_stat_sync("photos", "l4", elapsed, lang=lang)

                vendor_title = vendor_label(eff_vendor, lang)
                caption_lines = [
                    t("cap.photo_gpu_title", lang, sec=elapsed),
                    t("cap.photo_gpu_cleaned", lang, vendor=vendor_title),
                    t("cap.photo_gpu_meta", lang, before=len(before_meta), after=len(after_meta)),
                ]
                if camera_exif != EXIF_OFF:
                    caption_lines.append(t("cap.exif_line", lang, exif=exif_label(camera_exif, lang)))
                if before_report.platform:
                    caption_lines.append(t("cap.photo_gpu_source", lang, platform=html.escape(before_report.platform)))
                if result.visible_label:
                    caption_lines.append(t("cap.photo_gpu_visible", lang, label=html.escape(result.visible_label)))
                if compressed_by_telegram:
                    caption_lines.append(t("cap.tg_doc_tip_quality", lang))
                if warn_note:
                    caption_lines.append(warn_note.strip())

                deliver_with_actions(
                    tg,
                    state,
                    vol,
                    chat_id=chat_id,
                    file_path=final_out,
                    kind="image",
                    caption="\n".join(caption_lines),
                    reply_to_message_id=reply_to_message_id,
                    mode=MODE_FULL_HD,
                    src_file_id=file_id,
                    src_file_name=file_name,
                    src_compressed=compressed_by_telegram,
                    natural_polish=natural_polish,
                    photo_vendor=photo_vendor,
                    camera_exif=camera_exif,
                    photo_output=photo_output,
                    cache_key=cache_key,
                    lang=lang,
                )
                tg.delete_message(chat_id, status_message_id)
        except Exception as exc:
            log.error("PhotoGpuWorker.clean_photo failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass
        finally:
            vol.cleanup_staged_input(staged_path)


def run_gpu_album_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    get_engine: Callable[[], Any],
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    items: list[dict[str, Any]],
    natural_polish: bool = True,
    photo_vendor: str = "auto",
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    lang: str = LANG_RU,
) -> None:
    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_album_gpu_") as tmp:
                work_dir = Path(tmp)
                _safe_edit_status(tg, chat_id, status_message_id, t("status.album_warming", lang, n=len(items)))
                hf_before = _hf_cache_snapshot_count()
                engine = get_engine()
                done = 0
                failed = 0

                for idx, item in enumerate(items, start=1):
                    _safe_edit_status(tg, chat_id, status_message_id, t("status.album_progress", lang, idx=idx, n=len(items)))
                    try:
                        src = tg.download_file(item["file_id"], work_dir / f"{idx:02d}_{item['file_name']}")
                        out = work_dir / f"{idx:02d}_{choose_output_filename(item['file_name'], 'image')}"
                        final_out, _rep, _bm, _am, eff_vendor, _res = process_one_photo(
                            src,
                            out,
                            engine=engine,
                            natural_polish=natural_polish,
                            photo_vendor=photo_vendor,
                            camera_exif=camera_exif,
                        )
                        exif_str = f" · {exif_label(camera_exif, lang)}" if camera_exif != EXIF_OFF else ""
                        deliver_file(
                            tg,
                            vol,
                            chat_id=chat_id,
                            file_path=final_out,
                            kind="image",
                            caption=t(
                                "cap.album_item_gpu",
                                lang,
                                idx=idx,
                                n=len(items),
                                vendor=vendor_label(eff_vendor, lang),
                                exif=exif_str,
                            ),
                            reply_to_message_id=reply_to_message_id if idx == 1 else None,
                            photo_output=photo_output,
                            lang=lang,
                        )
                        done += 1
                    except Exception as item_exc:
                        log.warning("Album item %d failed: %s", idx, item_exc)
                        failed += 1

                if _hf_cache_snapshot_count() > hf_before:
                    vol.safe_commit()

                elapsed = time.monotonic() - started
                warn_note = state.record_stat_sync("albums", "l4", elapsed, count=1, lang=lang)
                state.record_stat_sync("photos", "l4", 0.0, count=done, lang=lang)
                fail_str = t("cap.album_fail_suffix", lang, n=failed) if failed else ""
                tg.edit_message_text(
                    chat_id,
                    status_message_id,
                    t("cap.album_gpu_done", lang, sec=elapsed, done=done, n=len(items), fail=fail_str, warn=warn_note),
                )
        except Exception as exc:
            log.error("PhotoGpuWorker.clean_photo_album failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass


def run_gpu_zip_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    get_engine: Callable[[], Any],
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    file_id: str | None,
    file_name: str,
    natural_polish: bool = True,
    photo_vendor: str = "auto",
    camera_exif: str = EXIF_OFF,
    staged_path: str | None = None,
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_zip_gpu_") as tmp:
                work_dir = Path(tmp)
                tg.send_chat_action(chat_id, "upload_document")
                src_zip = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )

                extract_dir = work_dir / "extracted"
                images = extract_images_from_zip(src_zip, extract_dir)
                if not images:
                    raise ValueError(t("err.zip_no_images", lang))

                _safe_edit_status(tg, chat_id, status_message_id, t("status.zip_gpu_warming", lang, n=len(images)))
                hf_before = _hf_cache_snapshot_count()
                engine = get_engine()
                out_dir = work_dir / "cleaned"
                out_dir.mkdir(exist_ok=True)
                cleaned_pairs: list[tuple[Path, str]] = []
                failed = 0

                for idx, img_path in enumerate(images, start=1):
                    _safe_edit_status(tg, chat_id, status_message_id, t("status.zip_gpu_progress", lang, idx=idx, n=len(images)))
                    orig_name = img_path.name.split("_", 1)[1] if "_" in img_path.name else img_path.name
                    arc_name = choose_output_filename(orig_name, "image")
                    out_img = out_dir / f"{idx:03d}_{arc_name}"
                    try:
                        final_img, *_ = process_one_photo(
                            img_path,
                            out_img,
                            engine=engine,
                            natural_polish=natural_polish,
                            photo_vendor=photo_vendor,
                            camera_exif=camera_exif,
                        )
                        arc_name = Path(arc_name).with_suffix(final_img.suffix).name
                        cleaned_pairs.append((final_img, arc_name))
                    except Exception as item_exc:
                        log.warning("ZIP item %s failed: %s", orig_name, item_exc)
                        failed += 1

                if _hf_cache_snapshot_count() > hf_before:
                    vol.safe_commit()

                if not cleaned_pairs:
                    raise RuntimeError(t("err.zip_all_failed", lang))

                out_zip = work_dir / choose_output_filename(src_zip.name, "zip")
                pack_files_to_zip(cleaned_pairs, out_zip)
                elapsed = time.monotonic() - started
                warn_note = state.record_stat_sync("zips", "l4", elapsed, count=1, lang=lang)
                state.record_stat_sync("photos", "l4", 0.0, count=len(cleaned_pairs), lang=lang)
                fail_note = t("cap.fail_line", lang, n=failed) if failed else ""
                exif_note = f"\n{t('cap.exif_line', lang, exif=exif_label(camera_exif, lang))}" if camera_exif != EXIF_OFF else ""
                caption = t(
                    "cap.zip_gpu_done",
                    lang,
                    sec=elapsed,
                    count=len(cleaned_pairs),
                    fail_note=fail_note,
                    exif_note=exif_note,
                    warn_note=warn_note,
                )
                out_fid, delivery_method = deliver_file(
                    tg,
                    vol,
                    chat_id=chat_id,
                    file_path=out_zip,
                    kind="zip",
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    lang=lang,
                )
                state.save_result_cache_sync(
                    cache_key,
                    out_file_id=out_fid,
                    delivery_method=delivery_method,
                    file_path=out_zip,
                    caption=caption,
                    lang=lang,
                )
                tg.delete_message(chat_id, status_message_id)
        except Exception as exc:
            log.error("PhotoGpuWorker.clean_zip failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass
        finally:
            vol.cleanup_staged_input(staged_path)


def run_gpu_audio_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    file_id: str | None,
    file_name: str,
    staged_path: str | None = None,
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    import remove_ai_watermarks as raiw

    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            with tempfile.TemporaryDirectory(prefix="nomark_audio_gpu_") as tmp:
                work_dir = Path(tmp)
                tg.send_chat_action(chat_id, "upload_voice")
                src = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )
                out = work_dir / choose_output_filename(src.name, "audio")

                tg.edit_message_text(chat_id, status_message_id, t("status.audio_cleaning", lang))
                try:
                    res = raiw.remove_audio_all(
                        src,
                        out,
                        include_invisible=True,
                        vendor="google",
                        method="auto",
                        vocoder_device="cuda",
                        verify=False,
                        allow_unverified=True,
                        allow_quality_override=False,
                    )
                except Exception as first_exc:
                    if "quality" in str(first_exc).lower():
                        res = raiw.remove_audio_all(
                            src,
                            out,
                            include_invisible=True,
                            vendor="google",
                            method="auto",
                            vocoder_device="cuda",
                            verify=False,
                            allow_unverified=True,
                            allow_quality_override=True,
                        )
                    else:
                        raise

                vol.safe_commit()
                elapsed = time.monotonic() - started
                warn_note = state.record_stat_sync("audios", "l4", elapsed, lang=lang)
                dac_state = t("cap.audio_dac_on" if res.invisible_applied else "cap.audio_dac_off", lang)
                caption = t(
                    "cap.audio_gpu_done",
                    lang,
                    sec=elapsed,
                    before=len(res.detected_metadata),
                    after=len(res.remaining_metadata),
                    dac_state=dac_state,
                    warn=warn_note,
                )
                deliver_with_actions(
                    tg,
                    state,
                    vol,
                    chat_id=chat_id,
                    file_path=res.output,
                    kind="audio",
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    mode=MODE_FULL_HD,
                    src_file_id=file_id,
                    src_file_name=file_name,
                    cache_key=cache_key,
                    lang=lang,
                )
                tg.delete_message(chat_id, status_message_id)
        except Exception as exc:
            log.error("PhotoGpuWorker.clean_audio_file failed: %s\n%s", exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass
        finally:
            vol.cleanup_staged_input(staged_path)


# ---------------------------------------------------------------------------
# GPU Video SynthID + C2PA (+ optional DAC Audio) Pipeline
# ---------------------------------------------------------------------------


def run_gpu_video_pipeline(
    *,
    tg_token: str,
    state: ModalStateStore,
    vol: ModalVolumeHelper,
    use_wan: bool,
    get_runtime: Callable[[], Any],
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    file_id: str | None,
    file_name: str,
    clean_audio: bool,
    video_strength: str,
    natural_polish: bool,
    staged_path: str | None = None,
    cache_key: str | None = None,
    lang: str = LANG_RU,
) -> None:
    started = time.monotonic()
    with SyncTelegramClient(tg_token) as tg:
        try:
            prep_key = "status.video_prep_hd" if use_wan else "status.video_prep_fast"
            tg.edit_message_text(chat_id, status_message_id, t(prep_key, lang))
            runtime = get_runtime()

            import remove_ai_watermarks as raiw
            from remove_ai_watermarks import video_audio
            from remove_ai_watermarks.metadata import get_ai_metadata

            profile = "wan21-synthid-experimental" if use_wan else "synthid"
            mode = MODE_FULL_HD if use_wan else MODE_FULL_FAST
            s_label = strength_label(video_strength, lang)

            with tempfile.TemporaryDirectory(prefix="nomark_video_gpu_") as tmp:
                work_dir = Path(tmp)
                tg.send_chat_action(chat_id, "upload_video")
                src = vol.fetch_input_file(
                    tg,
                    work_dir,
                    file_id=file_id,
                    file_name=file_name,
                    staged_path=staged_path,
                    lang=lang,
                )

                before_meta = get_ai_metadata(src)
                work_src = ensure_video_mp4_if_needed(src, work_dir, needs_isobmff=use_wan)
                visual_out = work_dir / f"{work_src.stem}_visual{work_src.suffix.lower() or '.mp4'}"
                polished_out = work_dir / f"{work_src.stem}_polished{work_src.suffix.lower() or '.mp4'}"
                final_out = work_dir / choose_output_filename(work_src.name, "video")

                extra_kwargs: dict[str, Any] = {}
                mode_caption = t("cap.video_mode_hd" if use_wan else "cap.video_mode_fast", lang)
                if use_wan:
                    from remove_ai_watermarks import video_wan

                    video_wan.WAN21_INFERENCE_STEPS = WAN21_INFERENCE_STEPS
                    video_wan.WAN21_GUIDANCE_SCALE = WAN21_GUIDANCE_SCALE
                    video_wan._PROFILE_STRENGTHS["wan21-synthid-experimental"] = WAN_STRENGTH_VALUES.get(
                        video_strength, 0.28
                    )
                else:
                    from remove_ai_watermarks.video_invisible import _probe_video

                    src_w, src_h, _src_fps = _probe_video(work_src)
                    extra_kwargs["long_side"] = max(512, min(max(src_w, src_h), 1280))
                    extra_kwargs["fps"] = None
                    extra_kwargs["noise_std"] = SDVAE_NOISE_VALUES.get(video_strength, 0.16)
                    extra_kwargs["temporal_stabilize"] = True

                status_icon = "🎬" if use_wan else "⚡"
                _safe_edit_status(
                    tg,
                    chat_id,
                    status_message_id,
                    t("status.video_running", lang, icon=status_icon, mode_caption=mode_caption, strength=s_label),
                )

                if use_wan:
                    inv_result = raiw.remove_video_wan_experimental(
                        work_src,
                        visual_out,
                        profile=profile,
                        device="cuda",
                        quality="master" if natural_polish else "delivery",
                        chunk_frames=WAN21_CHUNK_FRAMES,
                        overlap_frames=WAN21_OVERLAP_FRAMES,
                        _runtime=runtime,
                    )
                else:
                    inv_result = raiw.remove_video_invisible(
                        work_src,
                        visual_out,
                        profile=profile,
                        device="cuda",
                        _runtime=runtime,
                        **extra_kwargs,
                    )

                output_to_send = inv_result.output
                if use_wan and natural_polish:
                    _safe_edit_status(tg, chat_id, status_message_id, t("status.video_polish", lang))
                    output_to_send = apply_natural_film_polish(output_to_send, polished_out)
                    if inv_result.output != output_to_send:
                        inv_result.output.unlink(missing_ok=True)

                audio_label = t("cap.video_audio_none", lang)
                streams = video_audio.stream_inventory(output_to_send)
                has_audio = any(s.get("codec_type") == "audio" for s in streams)
                if has_audio:
                    if clean_audio:
                        _safe_edit_status(tg, chat_id, status_message_id, t("status.video_audio", lang))
                        try:
                            audio_res = video_audio.remove_video_audio_all_streams(
                                output_to_send,
                                final_out,
                                vendor="google",
                                method="auto",
                                vocoder_device="cuda",
                                verify=False,
                                allow_unverified=True,
                                allow_quality_override=False,
                            )
                        except Exception as first_exc:
                            if "quality" in str(first_exc).lower():
                                final_out.unlink(missing_ok=True)
                                audio_res = video_audio.remove_video_audio_all_streams(
                                    output_to_send,
                                    final_out,
                                    vendor="google",
                                    method="auto",
                                    vocoder_device="cuda",
                                    verify=False,
                                    allow_unverified=True,
                                    allow_quality_override=True,
                                )
                            else:
                                raise
                        if not audio_res.skipped and audio_res.output is not None:
                            output_to_send = audio_res.output
                            audio_label = t("cap.video_audio_clean", lang)
                            vol.safe_commit()
                        else:
                            audio_label = t("cap.video_audio_copy", lang)
                    else:
                        audio_label = t("cap.video_audio_copy", lang)

                if output_to_send != final_out:
                    output_to_send.replace(final_out)
                    output_to_send = final_out

                after_meta = get_ai_metadata(output_to_send)
                elapsed = time.monotonic() - started
                metrics = inv_result.metrics
                warn_note = state.record_stat_sync(
                    "videos_hd" if use_wan else "videos_fast",
                    "h100" if use_wan else "l4",
                    elapsed,
                    lang=lang,
                )

                _safe_edit_status(tg, chat_id, status_message_id, t("status.video_uploading", lang))
                caption_lines = [
                    t("cap.photo_gpu_title", lang, sec=elapsed),
                    t(
                        "cap.video_done_mode",
                        lang,
                        mode=mode_caption,
                        strength=s_label,
                        w=metrics.width,
                        h=metrics.height,
                        fps=metrics.fps,
                    ),
                    t("cap.video_done_cleaned", lang),
                    t("cap.photo_gpu_meta", lang, before=len(before_meta), after=len(after_meta)),
                    t("cap.video_done_audio", lang, audio=audio_label),
                ]
                if warn_note:
                    caption_lines.append(warn_note.strip())

                deliver_with_actions(
                    tg,
                    state,
                    vol,
                    chat_id=chat_id,
                    file_path=output_to_send,
                    kind="video",
                    caption="\n".join(caption_lines),
                    reply_to_message_id=reply_to_message_id,
                    mode=mode,
                    src_file_id=file_id,
                    src_file_name=file_name,
                    video_strength=video_strength,
                    clean_audio=clean_audio,
                    natural_polish=natural_polish,
                    cache_key=cache_key,
                    lang=lang,
                )
                tg.delete_message(chat_id, status_message_id)
        except Exception as exc:
            worker = "VideoWanGpuWorker" if use_wan else "VideoFastGpuWorker"
            log.error("%s.clean_video failed: %s\n%s", worker, exc, traceback.format_exc())
            try:
                tg.edit_message_text(chat_id, status_message_id, format_error_text(exc, lang))
            except Exception:
                pass
        except BaseException as cancel_exc:
            worker = "VideoWanGpuWorker" if use_wan else "VideoFastGpuWorker"
            log.warning("%s.clean_video interrupted/timed out: %s", worker, cancel_exc.__class__.__name__)
            try:
                tg.edit_message_text(
                    chat_id,
                    status_message_id,
                    format_error_text(TimeoutError("Processing timed out or was cancelled by worker limit."), lang),
                )
            except Exception:
                pass
            raise
        finally:
            vol.cleanup_staged_input(staged_path)
