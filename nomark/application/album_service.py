"""Async Telegram album coalescing use-case."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from nomark.config import (
    ALBUM_COALESCE_DELAY_SEC,
    MODE_C2PA_ONLY,
    MODE_IDENTIFY,
    MODE_VISIBLE,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import check_budget_status, current_month_key
from nomark.domain.ports import JobDispatcher, StateStore, TelegramGateway
from nomark.presentation.i18n import t
from nomark.presentation.keyboards import build_stats_keyboard
from nomark.presentation.views import build_budget_blocked_text

log = logging.getLogger("nomark.album")


class AlbumService:
    """Coalesce Telegram media_group_id photo bursts onto a single warm worker."""

    def __init__(
        self,
        *,
        state: StateStore,
        tg: TelegramGateway,
        dispatcher: JobDispatcher,
        delay_sec: float = ALBUM_COALESCE_DELAY_SEC,
    ) -> None:
        self._state = state
        self._tg = tg
        self._dispatcher = dispatcher
        self._delay_sec = delay_sec

    async def collect_and_dispatch(
        self,
        *,
        chat_id: int,
        media_group_id: str,
        first_message_id: int,
        settings_dict: dict[str, Any],
    ) -> dict[str, Any]:
        if self._delay_sec > 0:
            await asyncio.sleep(self._delay_sec)

        items = await self._state.pop_album_items(media_group_id)
        if not items:
            return {"ok": True, "count": 0}

        settings = UserSettings.from_raw(settings_dict)
        lang = settings.lang

        if settings.mode in {MODE_C2PA_ONLY, MODE_VISIBLE, MODE_IDENTIFY}:
            status_id = await self._tg.send_message(
                chat_id,
                t("status.album_cpu", lang, n=len(items)),
                reply_to_message_id=first_message_id,
            )
            await self._dispatcher.spawn_cpu_album(
                chat_id=chat_id,
                reply_to_message_id=first_message_id,
                status_message_id=status_id,
                items=items,
                mode=settings.mode,
                camera_exif=settings.camera_exif,
                photo_output=settings.photo_output,
                lang=lang,
            )
            return {"ok": True, "dispatched": "cpu_album", "count": len(items)}

        # GPU album -> check monthly budget guard concurrently
        stats, guard_on = await asyncio.gather(
            self._state.get_stats(current_month_key()),
            self._state.is_budget_guard_enabled(),
        )
        b_status, spend = check_budget_status(stats, guard_enabled=guard_on)
        if b_status == "blocked":
            await self._tg.send_message(
                chat_id,
                build_budget_blocked_text(spend, lang),
                reply_to_message_id=first_message_id,
                reply_markup=build_stats_keyboard(budget_guard=guard_on, lang=lang),
            )
            return {"ok": True, "blocked_by_budget": True, "count": len(items)}

        status_id = await self._tg.send_message(
            chat_id,
            t("status.album_gpu", lang, n=len(items)),
            reply_to_message_id=first_message_id,
        )
        await self._dispatcher.spawn_gpu_photo_album(
            chat_id=chat_id,
            reply_to_message_id=first_message_id,
            status_message_id=status_id,
            items=items,
            natural_polish=settings.natural_polish,
            photo_vendor=settings.photo_vendor,
            camera_exif=settings.camera_exif,
            photo_output=settings.photo_output,
            lang=lang,
        )
        return {"ok": True, "dispatched": "gpu_album", "count": len(items)}
