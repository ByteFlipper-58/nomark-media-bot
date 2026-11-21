"""Pure async Telegram webhook router & use-case controller (zero Modal/HTTP coupling)."""

from __future__ import annotations

import asyncio
import html
import logging
import time
import uuid
from typing import Any

from nomark.config import (
    EXIF_OFF,
    MODE_C2PA_ONLY,
    MODE_ERASE,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    MODE_VISIBLE,
    PHOTO_OUT_PHOTO,
    SUPPORTED_LANGS,
    TELEGRAM_MAX_DOWNLOAD_BYTES,
    VALID_MODES,
    VALID_STRENGTHS,
)
from nomark.domain.models import MediaItem, UserSettings
from nomark.domain.policies import (
    build_result_cache_key,
    check_budget_status,
    current_month_key,
    extract_media_from_message,
    extract_url_from_text,
    infer_lang_from_telegram_user,
    is_user_allowed,
    parse_box_coords,
)
from nomark.domain.ports import JobDispatcher, StateStore, TelegramGateway
from nomark.presentation.i18n import corner_label, exif_label, strength_label, t, vendor_label
from nomark.presentation.keyboards import (
    build_erase_corner_keyboard,
    build_language_picker_keyboard,
    build_menu_keyboard,
    build_result_keyboard,
    build_settings_keyboard,
    build_stats_keyboard,
    build_warmup_keyboard,
)
from nomark.presentation.views import (
    build_budget_blocked_text,
    build_language_picker_text,
    build_settings_text,
    build_warmup_text,
    build_welcome_text,
    format_stats_text,
)

log = logging.getLogger("nomark.webhook")


class WebhookService:
    """Handles incoming Telegram updates completely asynchronously via injected ports."""

    def __init__(
        self,
        *,
        state: StateStore,
        tg: TelegramGateway,
        dispatcher: JobDispatcher,
        allowed_users_raw: str | None = None,
    ) -> None:
        self._state = state
        self._tg = tg
        self._dispatcher = dispatcher
        self._allowed_raw = allowed_users_raw

    async def handle_update(self, update: dict[str, Any]) -> dict[str, Any]:
        update_id = update.get("update_id")
        if update_id is not None:
            try:
                if await self._state.mark_update_seen(int(update_id)):
                    return {"ok": True, "duplicate": True}
            except Exception as exc:
                log.warning("Update dedup check skipped: %s", exc)

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            return await self._handle_callback(callback)

        message = update.get("message")
        if isinstance(message, dict):
            return await self._handle_message(message)

        return {"ok": True}

    async def _is_gpu_budget_blocked(self, chat_id: int, reply_to: int | None = None, *, lang: str) -> bool:
        stats, guard_on = await asyncio.gather(
            self._state.get_stats(current_month_key()),
            self._state.is_budget_guard_enabled(),
        )
        status, spend = check_budget_status(stats, guard_enabled=guard_on)
        if status == "blocked":
            await self._tg.send_message(
                chat_id,
                build_budget_blocked_text(spend, lang),
                reply_to_message_id=reply_to,
                reply_markup=build_stats_keyboard(budget_guard=guard_on, lang=lang),
            )
            return True
        return False

    # -----------------------------------------------------------------------
    # Inline Keyboard Callbacks
    # -----------------------------------------------------------------------

    async def _handle_callback(self, callback: dict[str, Any]) -> dict[str, Any]:
        cb_id = str(callback.get("id", ""))
        from_user = callback.get("from") or {}
        user_id = from_user.get("id")
        inferred_lang = infer_lang_from_telegram_user(from_user)

        if not is_user_allowed(user_id, self._allowed_raw):
            await self._tg.answer_callback_query(cb_id, t("err.access_denied", inferred_lang))
            return {"ok": True, "denied": True}

        msg = callback.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        message_id = msg.get("message_id")
        data = str(callback.get("data") or "")
        settings = await self._state.get_user_settings(int(user_id), default_lang=inferred_lang)
        lang = settings.lang

        # 1. First-start language picker
        if data.startswith("lang:"):
            chosen = data.split(":", 1)[1]
            if chosen in SUPPORTED_LANGS:
                settings = settings.with_updates(lang=chosen, lang_chosen=True)
                tasks = [
                    self._state.save_user_settings(int(user_id), settings),
                    self._tg.answer_callback_query(cb_id, t("cb.lang_updated", chosen)),
                ]
                if chat_id and message_id:
                    tasks.append(
                        self._tg.edit_message_text(
                            int(chat_id),
                            int(message_id),
                            build_welcome_text(settings),
                            reply_markup=build_menu_keyboard(settings),
                        )
                    )
                await asyncio.gather(*tasks)
                return {"ok": True, "lang": chosen}
            await self._tg.answer_callback_query(cb_id)
            return {"ok": True}

        # 2. Open fresh main menu beneath a cleaned file
        if data == "nav:main_new":
            tasks = [self._tg.answer_callback_query(cb_id)]
            if chat_id:
                tasks.append(
                    self._tg.send_message(
                        int(chat_id),
                        build_welcome_text(settings),
                        reply_markup=build_menu_keyboard(settings),
                    )
                )
            await asyncio.gather(*tasks)
            return {"ok": True}

        # 3. Manual corner erase selection
        if data.startswith("erase:"):
            return await self._handle_erase_callback(
                cb_id=cb_id,
                data=data,
                chat_id=chat_id,
                message_id=message_id,
                settings=settings,
            )

        # 4. Post-result actions (check / retry / upgrade / recompute)
        if data.startswith("act:"):
            return await self._handle_action_callback(
                cb_id=cb_id,
                data=data,
                chat_id=chat_id,
                message_id=message_id,
                settings=settings,
            )

        # 5. On-demand GPU warmup buttons
        if data.startswith("warm:") and chat_id:
            return await self._handle_warmup_callback(cb_id=cb_id, data=data, chat_id=int(chat_id), lang=lang)

        # 6. Menu / Settings / Stats navigation
        return await self._handle_menu_callback(
            cb_id=cb_id,
            data=data,
            user_id=int(user_id),
            chat_id=chat_id,
            message_id=message_id,
            settings=settings,
        )

    async def _handle_erase_callback(
        self,
        *,
        cb_id: str,
        data: str,
        chat_id: Any,
        message_id: Any,
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang
        parts = data.split(":")
        if len(parts) != 3 or not chat_id:
            await self._tg.answer_callback_query(cb_id)
            return {"ok": True}

        _, job_id, corner = parts
        job = await self._state.get_erase_job(job_id)
        if not isinstance(job, dict):
            await self._tg.answer_callback_query(cb_id, t("cb.expired_file", lang))
            return {"ok": True}

        zone = corner_label(corner, lang)
        _, status_id = await asyncio.gather(
            self._tg.answer_callback_query(cb_id, t("cb.erasing", lang, zone=zone)),
            self._tg.send_message(
                int(chat_id),
                t("status.erase_start", lang, zone=zone),
                reply_to_message_id=job.get("reply_to_message_id"),
            ),
        )
        await self._dispatcher.spawn_cpu_erase(
            chat_id=int(chat_id),
            reply_to_message_id=int(job.get("reply_to_message_id") or message_id),
            status_message_id=status_id,
            kind=str(job["kind"]),
            file_id=job.get("file_id"),
            file_name=str(job["file_name"]),
            corner=corner,
            camera_exif=settings.camera_exif,
            photo_output=settings.photo_output,
            staged_path=job.get("staged_path"),
            lang=lang,
        )
        return {"ok": True, "dispatched": "cpu_erase"}

    async def _handle_action_callback(
        self,
        *,
        cb_id: str,
        data: str,
        chat_id: Any,
        message_id: Any,
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        job_id = parts[2] if len(parts) > 2 else ""
        job = await self._state.get_job(job_id) if job_id else None
        if not isinstance(job, dict) or not chat_id:
            await self._tg.answer_callback_query(cb_id, t("cb.expired_job", lang))
            return {"ok": True}

        if action == "check":
            out_fid = job.get("out_file_id")
            if not out_fid:
                await self._tg.answer_callback_query(cb_id, t("cb.no_file_check", lang))
                return {"ok": True}
            _, status_id = await asyncio.gather(
                self._tg.answer_callback_query(cb_id, t("cb.checking", lang)),
                self._tg.send_message(
                    int(chat_id),
                    t("status.identify_result", lang),
                    reply_to_message_id=message_id,
                ),
            )
            await self._dispatcher.spawn_cpu_file(
                chat_id=int(chat_id),
                reply_to_message_id=int(message_id),
                status_message_id=status_id,
                kind=str(job["kind"]),
                file_id=str(out_fid),
                file_name=str(job.get("out_file_name") or "result.bin"),
                mode=MODE_IDENTIFY,
                compressed_by_telegram=bool(job.get("out_compressed", False)),
                lang=lang,
            )
            return {"ok": True, "dispatched": "act_check"}

        if action == "retry" and len(parts) >= 4:
            new_strength = parts[3]
            src_fid = job.get("src_file_id")
            if new_strength not in VALID_STRENGTHS or not src_fid:
                await self._tg.answer_callback_query(cb_id, t("cb.retry_unavailable", lang))
                return {"ok": True}
            if await self._is_gpu_budget_blocked(int(chat_id), message_id, lang=lang):
                await self._tg.answer_callback_query(cb_id, t("cb.budget_active", lang))
                return {"ok": True, "blocked_by_budget": True}
            s_lbl = strength_label(new_strength, lang)
            _, status_id = await asyncio.gather(
                self._tg.answer_callback_query(cb_id, t("cb.retrying", lang, val=s_lbl)),
                self._tg.send_message(
                    int(chat_id),
                    t("status.video_retry", lang, strength=s_lbl),
                    reply_to_message_id=message_id,
                ),
            )
            if job.get("mode") == MODE_FULL_HD:
                await self._dispatcher.spawn_gpu_video_hd(
                    chat_id=int(chat_id),
                    reply_to_message_id=int(message_id),
                    status_message_id=status_id,
                    file_id=str(src_fid),
                    file_name=str(job.get("src_file_name") or "video.mp4"),
                    clean_audio=bool(job.get("clean_audio", True)),
                    video_strength=new_strength,
                    natural_polish=bool(job.get("natural_polish", True)),
                    lang=lang,
                )
            else:
                await self._dispatcher.spawn_gpu_video_fast(
                    chat_id=int(chat_id),
                    reply_to_message_id=int(message_id),
                    status_message_id=status_id,
                    file_id=str(src_fid),
                    file_name=str(job.get("src_file_name") or "video.mp4"),
                    clean_audio=bool(job.get("clean_audio", True)),
                    video_strength=new_strength,
                    lang=lang,
                )
            return {"ok": True, "dispatched": "act_retry"}

        if action == "upgrade":
            src_fid = job.get("src_file_id")
            if not src_fid or job.get("kind") != "image":
                await self._tg.answer_callback_query(cb_id, t("cb.unavailable", lang))
                return {"ok": True}
            if await self._is_gpu_budget_blocked(int(chat_id), message_id, lang=lang):
                await self._tg.answer_callback_query(cb_id, t("cb.budget_active", lang))
                return {"ok": True, "blocked_by_budget": True}
            _, status_id = await asyncio.gather(
                self._tg.answer_callback_query(cb_id, t("cb.starting_full", lang)),
                self._tg.send_message(
                    int(chat_id),
                    t("status.photo_upgrade", lang),
                    reply_to_message_id=message_id,
                ),
            )
            await self._dispatcher.spawn_gpu_photo(
                chat_id=int(chat_id),
                reply_to_message_id=int(message_id),
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=str(job.get("src_file_name") or "image.png"),
                compressed_by_telegram=bool(job.get("src_compressed", False)),
                natural_polish=settings.natural_polish,
                photo_vendor=settings.photo_vendor,
                camera_exif=settings.camera_exif,
                photo_output=settings.photo_output,
                lang=lang,
            )
            return {"ok": True, "dispatched": "act_upgrade"}

        if action == "recompute":
            return await self._handle_recompute_action(
                cb_id=cb_id,
                chat_id=int(chat_id),
                message_id=int(message_id),
                job=job,
                settings=settings,
            )

        await self._tg.answer_callback_query(cb_id)
        return {"ok": True}

    async def _handle_recompute_action(
        self,
        *,
        cb_id: str,
        chat_id: int,
        message_id: int,
        job: dict[str, Any],
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang
        src_fid = job.get("src_file_id")
        j_kind = str(job.get("kind") or "")
        j_mode = str(job.get("mode") or settings.mode)
        j_name = str(job.get("src_file_name") or "file.bin")
        j_cache_key = job.get("cache_key")

        if not src_fid or not j_kind:
            await self._tg.answer_callback_query(cb_id, t("cb.recompute_unavailable", lang))
            return {"ok": True}

        if j_mode in {MODE_C2PA_ONLY, MODE_VISIBLE}:
            _, status_id = await asyncio.gather(
                self._tg.answer_callback_query(cb_id, t("cb.recomputing", lang)),
                self._tg.send_message(chat_id, t("status.recompute", lang), reply_to_message_id=message_id),
            )
            await self._dispatcher.spawn_cpu_file(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                kind=j_kind,
                file_id=str(src_fid),
                file_name=j_name,
                mode=j_mode,
                compressed_by_telegram=bool(job.get("src_compressed", False)),
                camera_exif=str(job.get("camera_exif") or settings.camera_exif),
                photo_output=str(job.get("photo_output") or settings.photo_output),
                cache_key=j_cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "act_recompute_cpu"}

        if await self._is_gpu_budget_blocked(chat_id, message_id, lang=lang):
            await self._tg.answer_callback_query(cb_id, t("cb.budget_active", lang))
            return {"ok": True, "blocked_by_budget": True}

        _, status_id = await asyncio.gather(
            self._tg.answer_callback_query(cb_id, t("cb.recomputing_gpu", lang)),
            self._tg.send_message(chat_id, t("status.recompute_gpu", lang), reply_to_message_id=message_id),
        )
        if j_kind == "image":
            await self._dispatcher.spawn_gpu_photo(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=j_name,
                compressed_by_telegram=bool(job.get("src_compressed", False)),
                natural_polish=bool(job.get("natural_polish", True)),
                photo_vendor=str(job.get("photo_vendor") or "auto"),
                camera_exif=str(job.get("camera_exif") or EXIF_OFF),
                photo_output=str(job.get("photo_output") or "document"),
                cache_key=j_cache_key,
                lang=lang,
            )
        elif j_kind == "zip":
            await self._dispatcher.spawn_gpu_zip(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=j_name,
                natural_polish=bool(job.get("natural_polish", True)),
                photo_vendor=str(job.get("photo_vendor") or "auto"),
                camera_exif=str(job.get("camera_exif") or EXIF_OFF),
                cache_key=j_cache_key,
                lang=lang,
            )
        elif j_kind == "audio":
            await self._dispatcher.spawn_gpu_audio(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=j_name,
                cache_key=j_cache_key,
                lang=lang,
            )
        elif j_mode == MODE_FULL_HD:
            await self._dispatcher.spawn_gpu_video_hd(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=j_name,
                clean_audio=bool(job.get("clean_audio", True)),
                video_strength=str(job.get("video_strength") or "balanced"),
                natural_polish=bool(job.get("natural_polish", True)),
                cache_key=j_cache_key,
                lang=lang,
            )
        else:
            await self._dispatcher.spawn_gpu_video_fast(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=str(src_fid),
                file_name=j_name,
                clean_audio=bool(job.get("clean_audio", True)),
                video_strength=str(job.get("video_strength") or "balanced"),
                cache_key=j_cache_key,
                lang=lang,
            )
        return {"ok": True, "dispatched": "act_recompute_gpu"}

    async def _handle_warmup_callback(self, *, cb_id: str, data: str, chat_id: int, lang: str) -> dict[str, Any]:
        target = data.split(":", 1)[1]
        if target not in {"photo", "vfast", "vwan"}:
            await self._tg.answer_callback_query(cb_id)
            return {"ok": True}
        if await self._is_gpu_budget_blocked(chat_id, lang=lang):
            await self._tg.answer_callback_query(cb_id, t("cb.budget_active", lang))
            return {"ok": True, "blocked_by_budget": True}

        cb_key = {"photo": "cb.warming_photo", "vfast": "cb.warming_vfast", "vwan": "cb.warming_vwan"}[target]
        st_key = {"photo": "status.warm_photo_start", "vfast": "status.warm_vfast_start", "vwan": "status.warm_vwan_start"}[target]
        _, status_id = await asyncio.gather(
            self._tg.answer_callback_query(cb_id, t(cb_key, lang)),
            self._tg.send_message(chat_id, t(st_key, lang)),
        )
        await self._dispatcher.spawn_gpu_warmup(target, chat_id=chat_id, status_message_id=status_id, lang=lang)
        return {"ok": True, "dispatched": f"warm_{target}"}

    async def _handle_menu_callback(
        self,
        *,
        cb_id: str,
        data: str,
        user_id: int,
        chat_id: Any,
        message_id: Any,
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang
        view = "main"
        toast: str | None = None
        save_settings = False
        new_guard: bool | None = None

        if data.startswith("mode:"):
            new_mode = data.split(":", 1)[1]
            if new_mode in VALID_MODES:
                settings = settings.with_updates(mode=new_mode)
                save_settings = True
                toast = t("cb.mode_updated", lang)
        elif data == "nav:settings":
            view = "settings"
        elif data == "nav:stats":
            view = "stats"
        elif data == "nav:warmup":
            view = "warmup"
        elif data == "nav:main":
            view = "main"
        elif data == "set:budget_guard":
            view = "stats"
            cur_guard = await self._state.is_budget_guard_enabled()
            new_guard = not cur_guard
            await self._state.set_budget_guard_enabled(new_guard)
            toast = t("cb.budget_guard", lang, state=t("state.on" if new_guard else "state.off", lang))
        elif data == "set:strength":
            view = "settings"
            settings = settings.with_updates(video_strength=settings.next_strength())
            save_settings = True
            toast = t("cb.strength", lang, val=strength_label(settings.video_strength, lang))
        elif data == "set:vendor":
            view = "settings"
            settings = settings.with_updates(photo_vendor=settings.next_vendor())
            save_settings = True
            toast = t("cb.vendor", lang, val=vendor_label(settings.photo_vendor, lang))
        elif data == "set:exif":
            view = "settings"
            settings = settings.with_updates(camera_exif=settings.next_exif())
            save_settings = True
            toast = t("cb.exif", lang, val=exif_label(settings.camera_exif, lang))
        elif data == "set:polish":
            view = "settings"
            settings = settings.with_updates(natural_polish=not settings.natural_polish)
            save_settings = True
            toast = t("cb.polish", lang, state=t("state.on" if settings.natural_polish else "state.off", lang))
        elif data == "set:photo_out":
            view = "settings"
            new_out = PHOTO_OUT_PHOTO if settings.photo_output != PHOTO_OUT_PHOTO else "document"
            settings = settings.with_updates(photo_output=new_out)
            save_settings = True
            toast = t("cb.photo_out", lang)
        elif data == "set:audio":
            view = "settings"
            settings = settings.with_updates(clean_audio=not settings.clean_audio)
            save_settings = True
            toast = t("cb.audio", lang, state=t("state.on" if settings.clean_audio else "state.off", lang))
        elif data == "set:lang":
            view = "settings"
            new_lang = settings.next_lang()
            settings = settings.with_updates(lang=new_lang, lang_chosen=True)
            lang = new_lang
            save_settings = True
            toast = t("cb.lang_updated", lang)

        # Render the updated screen concurrently with toast + settings save!
        tasks: list[Any] = [self._tg.answer_callback_query(cb_id, toast)]
        if save_settings:
            tasks.append(self._state.save_user_settings(user_id, settings))

        if chat_id and message_id:
            if view == "settings":
                tasks.append(
                    self._tg.edit_message_text(
                        int(chat_id),
                        int(message_id),
                        build_settings_text(settings),
                        reply_markup=build_settings_keyboard(settings),
                    )
                )
            elif view == "stats":
                stats = await self._state.get_stats(current_month_key())
                guard_on = new_guard if new_guard is not None else await self._state.is_budget_guard_enabled()
                tasks.append(
                    self._tg.edit_message_text(
                        int(chat_id),
                        int(message_id),
                        format_stats_text(stats, budget_guard=guard_on, lang=lang),
                        reply_markup=build_stats_keyboard(budget_guard=guard_on, lang=lang),
                    )
                )
            elif view == "warmup":
                tasks.append(
                    self._tg.edit_message_text(
                        int(chat_id),
                        int(message_id),
                        build_warmup_text(lang),
                        reply_markup=build_warmup_keyboard(lang),
                    )
                )
            else:
                tasks.append(
                    self._tg.edit_message_text(
                        int(chat_id),
                        int(message_id),
                        build_welcome_text(settings),
                        reply_markup=build_menu_keyboard(settings),
                    )
                )

        await asyncio.gather(*tasks)
        return {"ok": True, "view": view}

    # -----------------------------------------------------------------------
    # Regular Messages (Commands, Text, URLs, Media, Albums)
    # -----------------------------------------------------------------------

    async def _handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        chat_id = (message.get("chat") or {}).get("id")
        message_id = message.get("message_id")
        from_user = message.get("from") or {}
        user_id = from_user.get("id")
        text = str(message.get("text") or "").strip()

        if not chat_id:
            return {"ok": True}

        inferred_lang = infer_lang_from_telegram_user(from_user)
        if not is_user_allowed(user_id, self._allowed_raw):
            await self._tg.send_message(int(chat_id), t("err.private_bot", inferred_lang), reply_to_message_id=message_id)
            return {"ok": True, "denied": True}

        settings = await self._state.get_user_settings(int(user_id), default_lang=inferred_lang)

        if text.startswith("/"):
            cmd_result = await self._handle_command(
                text=text,
                message=message,
                chat_id=int(chat_id),
                message_id=int(message_id),
                settings=settings,
            )
            if cmd_result is not None:
                return cmd_result

        media = extract_media_from_message(message)
        if media is None:
            return await self._handle_text_fallback(
                text=text,
                chat_id=int(chat_id),
                message_id=int(message_id),
                settings=settings,
            )

        return await self._handle_media(
            message=message,
            media=media,
            chat_id=int(chat_id),
            message_id=int(message_id),
            settings=settings,
        )

    async def _handle_command(
        self,
        *,
        text: str,
        message: dict[str, Any],
        chat_id: int,
        message_id: int,
        settings: UserSettings,
    ) -> dict[str, Any] | None:
        lang = settings.lang

        if text.startswith("/start"):
            if not settings.lang_chosen:
                await self._tg.send_message(
                    chat_id,
                    build_language_picker_text(),
                    reply_markup=build_language_picker_keyboard(),
                )
                return {"ok": True, "onboarding": "language_picker"}
            await self._tg.send_message(chat_id, build_welcome_text(settings), reply_markup=build_menu_keyboard(settings))
            return {"ok": True, "command": "start"}

        if text.startswith(("/help", "/menu")):
            await self._tg.send_message(chat_id, build_welcome_text(settings), reply_markup=build_menu_keyboard(settings))
            return {"ok": True, "command": "help"}

        if text.startswith("/settings"):
            await self._tg.send_message(chat_id, build_settings_text(settings), reply_markup=build_settings_keyboard(settings))
            return {"ok": True, "command": "settings"}

        if text.startswith("/stats"):
            stats, guard_on = await asyncio.gather(
                self._state.get_stats(current_month_key()),
                self._state.is_budget_guard_enabled(),
            )
            await self._tg.send_message(
                chat_id,
                format_stats_text(stats, budget_guard=guard_on, lang=lang),
                reply_markup=build_stats_keyboard(budget_guard=guard_on, lang=lang),
            )
            return {"ok": True, "command": "stats"}

        if text.startswith("/text"):
            payload_text = text[5:].strip()
            if not payload_text:
                reply_msg = message.get("reply_to_message") or {}
                payload_text = str(reply_msg.get("text") or reply_msg.get("caption") or "").strip()
            if not payload_text:
                await self._tg.send_message(chat_id, t("err.text_usage", lang), reply_to_message_id=message_id)
                return {"ok": True}
            status_id = await self._tg.send_message(chat_id, t("status.text_clean", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_cpu_text(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                raw_text=payload_text,
                mode=settings.mode,
                lang=lang,
            )
            return {"ok": True, "dispatched": "cpu_text"}

        return None

    async def _handle_text_fallback(
        self,
        *,
        text: str,
        chat_id: int,
        message_id: int,
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang

        # Manual erase box 'x,y,w,h'
        box_candidate = parse_box_coords(text, 100000, 100000)
        if box_candidate is not None:
            erase_job = await self._state.get_last_erase_job(chat_id)
            if isinstance(erase_job, dict):
                status_id = await self._tg.send_message(
                    chat_id,
                    t("status.erase_box", lang, box=html.escape(text)),
                    reply_to_message_id=message_id,
                )
                await self._dispatcher.spawn_cpu_erase(
                    chat_id=chat_id,
                    reply_to_message_id=message_id,
                    status_message_id=status_id,
                    kind=str(erase_job["kind"]),
                    file_id=erase_job.get("file_id"),
                    file_name=str(erase_job["file_name"]),
                    custom_box=box_candidate,
                    camera_exif=settings.camera_exif,
                    photo_output=settings.photo_output,
                    staged_path=erase_job.get("staged_path"),
                    lang=lang,
                )
                return {"ok": True, "dispatched": "erase_custom_box"}

        # Remote URL (>20 MB support)
        remote_url = extract_url_from_text(text)
        if remote_url:
            status_id = await self._tg.send_message(chat_id, t("status.url_downloading", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_url_job(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                url=remote_url,
                settings_dict=settings.to_dict(),
            )
            return {"ok": True, "dispatched": "url"}

        await self._tg.send_message(chat_id, t("err.no_media_help", lang), reply_to_message_id=message_id)
        return {"ok": True}

    async def _handle_media(
        self,
        *,
        message: dict[str, Any],
        media: MediaItem,
        chat_id: int,
        message_id: int,
        settings: UserSettings,
    ) -> dict[str, Any]:
        lang = settings.lang

        if media.file_size is not None and media.file_size > TELEGRAM_MAX_DOWNLOAD_BYTES:
            mb = media.file_size / (1024 * 1024)
            await self._tg.send_message(chat_id, t("err.too_large", lang, mb=mb), reply_to_message_id=message_id)
            return {"ok": True, "rejected": "too_large"}

        # 1. Telegram Album (Media Group) Coalescing
        media_group_id = message.get("media_group_id")
        if media_group_id and media.kind == "image" and settings.mode != MODE_ERASE:
            mg_id = str(media_group_id)
            item_payload = {
                "message_id": message_id,
                "file_id": media.file_id,
                "file_name": media.file_name,
                "compressed_by_telegram": media.compressed_by_telegram,
            }
            is_leader = await self._state.add_album_item(mg_id, message_id, item_payload)
            if is_leader:
                await self._dispatcher.spawn_album_collector(
                    chat_id=chat_id,
                    media_group_id=mg_id,
                    first_message_id=message_id,
                    settings_dict=settings.to_dict(),
                )
            return {"ok": True, "album_leader": is_leader}

        # 2. Manual Erase Mode (corner selector grid)
        if settings.mode == MODE_ERASE:
            if media.kind not in {"image", "video"}:
                await self._tg.send_message(chat_id, t("err.erase_only_media", lang), reply_to_message_id=message_id)
                return {"ok": True}
            job_id = uuid.uuid4().hex[:10]
            await asyncio.gather(
                self._state.save_erase_job(
                    job_id,
                    chat_id,
                    {
                        "kind": media.kind,
                        "file_id": media.file_id,
                        "file_name": media.file_name,
                        "reply_to_message_id": message_id,
                    },
                ),
                self._tg.send_message(
                    chat_id,
                    t("status.erase_choose", lang),
                    reply_to_message_id=message_id,
                    reply_markup=build_erase_corner_keyboard(job_id, lang=lang),
                ),
            )
            return {"ok": True, "awaiting_corner": job_id}

        # 3. Instant Result Cache Lookup (0s, $0 GPU!)
        cache_key = build_result_cache_key(
            file_unique_id=media.file_unique_id,
            kind=media.kind,
            mode=settings.mode,
            video_strength=settings.video_strength,
            natural_polish=settings.natural_polish,
            clean_audio=settings.clean_audio,
            photo_vendor=settings.photo_vendor,
            camera_exif=settings.camera_exif,
            photo_output=settings.photo_output,
        )
        if cache_key:
            cached = await self._state.get_cached_result(cache_key)
            if isinstance(cached, dict) and cached.get("out_file_id"):
                hit = await self._deliver_cached_result(
                    cached=cached,
                    cache_key=cache_key,
                    media=media,
                    chat_id=chat_id,
                    message_id=message_id,
                    settings=settings,
                )
                if hit:
                    return {"ok": True, "cache_hit": True}

        # 4. CPU-only routes (always exempt from GPU budget guard)
        if settings.mode in {MODE_C2PA_ONLY, MODE_IDENTIFY, MODE_VISIBLE} or media.kind == "text_file":
            label_map = {
                MODE_IDENTIFY: t("status.identify", lang),
                MODE_VISIBLE: t("status.visible_start", lang),
                MODE_C2PA_ONLY: t("status.c2pa_start", lang),
            }
            label = t("status.text_file", lang) if media.kind == "text_file" else label_map[settings.mode]
            status_id = await self._tg.send_message(chat_id, label, reply_to_message_id=message_id)
            await self._dispatcher.spawn_cpu_file(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                kind=media.kind,
                file_id=media.file_id,
                file_name=media.file_name,
                mode=settings.mode,
                compressed_by_telegram=media.compressed_by_telegram,
                camera_exif=settings.camera_exif,
                photo_output=settings.photo_output,
                cache_key=cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "cpu"}

        # 5. GPU routes (enforce monthly budget guard)
        if await self._is_gpu_budget_blocked(chat_id, message_id, lang=lang):
            return {"ok": True, "blocked_by_budget": True}

        if media.kind == "image":
            status_id = await self._tg.send_message(chat_id, t("status.photo_start", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_gpu_photo(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=media.file_id,
                file_name=media.file_name,
                compressed_by_telegram=media.compressed_by_telegram,
                natural_polish=settings.natural_polish,
                photo_vendor=settings.photo_vendor,
                camera_exif=settings.camera_exif,
                photo_output=settings.photo_output,
                cache_key=cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "gpu_photo"}

        if media.kind == "zip":
            status_id = await self._tg.send_message(chat_id, t("status.zip_gpu_start", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_gpu_zip(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=media.file_id,
                file_name=media.file_name,
                natural_polish=settings.natural_polish,
                photo_vendor=settings.photo_vendor,
                camera_exif=settings.camera_exif,
                cache_key=cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "gpu_zip"}

        if media.kind == "audio":
            status_id = await self._tg.send_message(chat_id, t("status.audio_start", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_gpu_audio(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=media.file_id,
                file_name=media.file_name,
                cache_key=cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "gpu_audio"}

        if settings.mode == MODE_FULL_HD:
            status_id = await self._tg.send_message(chat_id, t("status.video_hd_start", lang), reply_to_message_id=message_id)
            await self._dispatcher.spawn_gpu_video_hd(
                chat_id=chat_id,
                reply_to_message_id=message_id,
                status_message_id=status_id,
                file_id=media.file_id,
                file_name=media.file_name,
                clean_audio=settings.clean_audio,
                video_strength=settings.video_strength,
                natural_polish=settings.natural_polish,
                cache_key=cache_key,
                lang=lang,
            )
            return {"ok": True, "dispatched": "gpu_video_wan"}

        status_id = await self._tg.send_message(chat_id, t("status.video_fast_start", lang), reply_to_message_id=message_id)
        await self._dispatcher.spawn_gpu_video_fast(
            chat_id=chat_id,
            reply_to_message_id=message_id,
            status_message_id=status_id,
            file_id=media.file_id,
            file_name=media.file_name,
            clean_audio=settings.clean_audio,
            video_strength=settings.video_strength,
            cache_key=cache_key,
            lang=lang,
        )
        return {"ok": True, "dispatched": "gpu_video_fast"}

    async def _deliver_cached_result(
        self,
        *,
        cached: dict[str, Any],
        cache_key: str,
        media: MediaItem,
        chat_id: int,
        message_id: int,
        settings: UserSettings,
    ) -> bool:
        lang = settings.lang
        job_id = uuid.uuid4().hex[:10]
        out_size = int(cached.get("out_size") or 0)
        delivery_method = str(cached.get("delivery_method") or "document")
        same_lang = cached.get("lang") == lang
        base_caption = str(cached.get("caption")) if (same_lang and cached.get("caption")) else t("cap.done_default", lang)
        cached_caption = t("cap.cached_prefix", lang, base=base_caption)
        markup = build_result_keyboard(
            job_id,
            kind=media.kind,
            mode=settings.mode,
            video_strength=settings.video_strength,
            has_source_file=True,
            has_output_file=out_size > 0 and out_size <= TELEGRAM_MAX_DOWNLOAD_BYTES,
            is_cached=True,
            lang=lang,
        )
        try:
            sent_fid = await self._tg.send_cached_file(
                chat_id,
                delivery_method=delivery_method,
                file_id=str(cached["out_file_id"]),
                caption=cached_caption,
                reply_to_message_id=message_id,
                reply_markup=markup,
            )
            await asyncio.gather(
                self._state.save_job(
                    job_id,
                    {
                        "kind": media.kind,
                        "mode": settings.mode,
                        "src_file_id": media.file_id,
                        "src_file_name": media.file_name,
                        "src_compressed": media.compressed_by_telegram,
                        "out_file_id": sent_fid or str(cached["out_file_id"]),
                        "out_file_name": str(cached.get("out_file_name") or media.file_name),
                        "out_compressed": delivery_method == "photo",
                        "video_strength": settings.video_strength,
                        "clean_audio": settings.clean_audio,
                        "natural_polish": settings.natural_polish,
                        "photo_vendor": settings.photo_vendor,
                        "camera_exif": settings.camera_exif,
                        "photo_output": settings.photo_output,
                        "cache_key": cache_key,
                        "lang": lang,
                        "created_at": int(time.time()),
                    },
                ),
                self._state.record_cache_hit(current_month_key()),
            )
            return True
        except Exception as exc:
            log.warning("Cached delivery failed (%s), falling back to fresh processing", exc)
            return False
