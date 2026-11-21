"""Modal infrastructure adapters implementing Domain ports (async .aio + sync worker helpers)."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from nomark.config import (
    APP_NAME,
    DOWNLOAD_LINK_TTL_SEC,
    LANG_RU,
    MODAL_MONTHLY_FREE_USD,
    TMP_DOWNLOADS_DIR,
    TMP_INPUTS_DIR,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import check_budget_status, current_month_key, empty_stats, merge_stat_delta
from nomark.infrastructure.media_io import cleanup_expired_dirs
from nomark.infrastructure.telegram_client import SyncTelegramClient
from nomark.presentation.i18n import t

log = logging.getLogger("nomark.modal_adapters")


class ModalStateStore:
    """Modal Dict adapter implementing the async StateStore port + sync helpers for compute workers."""

    def __init__(self, state_dict: Any, album_dict: Any) -> None:
        self._state = state_dict
        self._albums = album_dict

    # ---- Async StateStore Port (used by webhook & album coalescer) ----

    async def mark_update_seen(self, update_id: int) -> bool:
        key = f"upd:{update_id}"
        inserted = await self._state.put.aio(key, int(time.time()), skip_if_exists=True)
        return not inserted

    async def get_user_settings(self, user_id: int, *, default_lang: str) -> UserSettings:
        try:
            raw = await self._state.get.aio(f"user:{user_id}")
        except Exception:
            return UserSettings(lang=default_lang, lang_chosen=False)
        return UserSettings.from_raw(raw, default_lang=default_lang)

    async def save_user_settings(self, user_id: int, settings: UserSettings) -> None:
        await self._state.put.aio(f"user:{user_id}", settings.to_dict())

    async def get_stats(self, month: str) -> dict[str, Any]:
        try:
            raw = await self._state.get.aio(f"stats:{month}")
        except Exception:
            return empty_stats(month)
        if isinstance(raw, dict) and raw.get("month") == month:
            return raw
        return empty_stats(month)

    async def record_cache_hit(self, month: str) -> None:
        key = f"stats:{month}"
        try:
            current = await self._state.get.aio(key)
            updated = merge_stat_delta(current, month=month, field="cache_hits", tier="cpu", seconds=0.0, count=1)
            await self._state.put.aio(key, updated)
        except Exception as exc:
            log.warning("Failed to record cache hit: %s", exc)

    async def is_budget_guard_enabled(self) -> bool:
        try:
            val = await self._state.get.aio("budget_guard")
        except Exception:
            return True
        return True if val is None else bool(val)

    async def set_budget_guard_enabled(self, enabled: bool) -> None:
        await self._state.put.aio("budget_guard", bool(enabled))

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        try:
            val = await self._state.get.aio(f"job:{job_id}")
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    async def save_job(self, job_id: str, record: dict[str, Any]) -> None:
        try:
            await self._state.put.aio(f"job:{job_id}", record)
        except Exception as exc:
            log.warning("Failed to save job: %s", exc)

    async def get_erase_job(self, job_id: str) -> dict[str, Any] | None:
        try:
            val = await self._state.get.aio(f"erase_job:{job_id}")
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    async def save_erase_job(self, job_id: str, chat_id: int, record: dict[str, Any]) -> None:
        await asyncio.gather(
            self._state.put.aio(f"erase_job:{job_id}", record),
            self._state.put.aio(f"last_erase:{chat_id}", job_id),
        )

    async def get_last_erase_job(self, chat_id: int) -> dict[str, Any] | None:
        last_id = await self._state.get.aio(f"last_erase:{chat_id}")
        if not last_id:
            return None
        return await self.get_erase_job(str(last_id))

    async def get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        try:
            val = await self._state.get.aio(cache_key)
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    async def add_album_item(self, media_group_id: str, message_id: int, payload: dict[str, Any]) -> bool:
        await self._albums.put.aio(f"item:{media_group_id}:{message_id}", payload)
        return bool(await self._albums.put.aio(f"leader:{media_group_id}", int(time.time()), skip_if_exists=True))

    async def pop_album_items(self, media_group_id: str) -> list[dict[str, Any]]:
        prefix = f"item:{media_group_id}:"
        collected: list[tuple[int, dict[str, Any]]] = []
        try:
            keys: list[str] = []
            async for key in self._albums.keys.aio():
                if isinstance(key, str) and key.startswith(prefix):
                    keys.append(key)
            popped = await asyncio.gather(*(self._albums.pop.aio(k, None) for k in keys))
            for val in popped:
                if isinstance(val, dict):
                    collected.append((int(val.get("message_id", 0)), val))
            await self._albums.pop.aio(f"leader:{media_group_id}", None)
        except Exception as exc:
            log.error("Album pop failed: %s", exc)
            return []
        collected.sort(key=lambda pair: pair[0])
        return [item for _, item in collected]

    # ---- Sync helpers for CPU/GPU compute workers ----

    def load_stats_sync(self) -> dict[str, Any]:
        month = current_month_key()
        try:
            raw = self._state.get(f"stats:{month}")
        except Exception:
            return empty_stats(month)
        if isinstance(raw, dict) and raw.get("month") == month:
            return raw
        return empty_stats(month)

    def is_budget_guard_enabled_sync(self) -> bool:
        try:
            val = self._state.get("budget_guard")
        except Exception:
            return True
        return True if val is None else bool(val)

    def record_stat_sync(
        self,
        field: str | None,
        tier: str,
        seconds: float,
        count: int = 1,
        *,
        lang: str = LANG_RU,
    ) -> str:
        month = current_month_key()
        key = f"stats:{month}"
        try:
            current = self._state.get(key)
            updated = merge_stat_delta(current, month=month, field=field, tier=tier, seconds=seconds, count=count)
            self._state[key] = updated
            guard = self.is_budget_guard_enabled_sync()
            status, spend = check_budget_status(updated, guard_enabled=guard)
            if status in {"warn", "blocked"}:
                return t("budget.warn_line", lang, spend=spend, free=f"{MODAL_MONTHLY_FREE_USD:.0f}")
        except Exception as exc:
            log.warning("Failed to record stats: %s", exc)
        return ""

    def save_job_sync(self, job_id: str, record: dict[str, Any]) -> None:
        try:
            self._state[f"job:{job_id}"] = record
        except Exception as exc:
            log.warning("Failed to save job action state: %s", exc)

    def save_result_cache_sync(
        self,
        cache_key: str | None,
        *,
        out_file_id: str | None,
        delivery_method: str,
        file_path: Path,
        caption: str,
        lang: str = LANG_RU,
    ) -> None:
        if not cache_key or not out_file_id or delivery_method == "link":
            return
        try:
            self._state[cache_key] = {
                "out_file_id": out_file_id,
                "delivery_method": delivery_method,
                "out_file_name": file_path.name,
                "out_size": file_path.stat().st_size,
                "caption": caption,
                "lang": lang,
                "created_at": int(time.time()),
            }
        except Exception as exc:
            log.warning("Failed to save result cache: %s", exc)

    def save_erase_job_sync(self, job_id: str, chat_id: int, record: dict[str, Any]) -> None:
        self._state[f"erase_job:{job_id}"] = record
        self._state[f"last_erase:{chat_id}"] = job_id


class ModalVolumeHelper:
    """Safe wrapper around modal.Volume for caching, staging URL inputs, and >50 MB links."""

    def __init__(self, volume: Any) -> None:
        self._volume = volume

    def safe_reload(self) -> None:
        try:
            self._volume.reload()
        except Exception as exc:
            log.warning("Volume reload skipped: %s", exc)

    def safe_commit(self) -> None:
        try:
            self._volume.commit()
        except Exception as exc:
            log.warning("Volume commit warning: %s", exc)

    def publish_large_file(self, file_path: Path) -> str:
        import modal

        base_dir = Path(TMP_DOWNLOADS_DIR)
        base_dir.mkdir(parents=True, exist_ok=True)
        cleanup_expired_dirs(base_dir)

        token = uuid.uuid4().hex
        slot = base_dir / token
        slot.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, slot / file_path.name)
        meta = {"filename": file_path.name, "expires_at": time.time() + DOWNLOAD_LINK_TTL_SEC}
        (slot / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.safe_commit()

        endpoint_url = modal.Function.from_name(APP_NAME, "download_file_endpoint").get_web_url()
        return f"{endpoint_url}?token={token}"

    def fetch_input_file(
        self,
        tg: SyncTelegramClient,
        work_dir: Path,
        *,
        file_id: str | None,
        file_name: str,
        staged_path: str | None,
        lang: str = LANG_RU,
    ) -> Path:
        dst = work_dir / file_name
        if staged_path:
            self.safe_reload()
            staged = Path(staged_path)
            if not staged.exists():
                raise FileNotFoundError(t("err.staged_missing", lang))
            shutil.copy2(staged, dst)
            return dst
        if not file_id:
            raise ValueError(t("err.missing_file_ref", lang))
        return tg.download_file(file_id, dst)

    def cleanup_staged_input(self, staged_path: str | None) -> None:
        if not staged_path:
            return
        try:
            slot = Path(staged_path).parent
            if str(slot).startswith(TMP_INPUTS_DIR) and slot.exists():
                shutil.rmtree(slot, ignore_errors=True)
                self.safe_commit()
        except Exception:
            pass
