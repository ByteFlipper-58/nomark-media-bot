"""Async Port Protocols (Dependency Inversion boundary for Clean Architecture)."""

from __future__ import annotations

from typing import Any, Protocol

from nomark.domain.models import UserSettings


class StateStore(Protocol):
    """Async persistence port for user settings, stats, jobs, caches, and album buffers."""

    async def mark_update_seen(self, update_id: int) -> bool:
        """Return True if update_id was already seen (duplicate), else record and return False."""
        ...

    async def get_user_settings(self, user_id: int, *, default_lang: str) -> UserSettings: ...

    async def save_user_settings(self, user_id: int, settings: UserSettings) -> None: ...

    async def get_stats(self, month: str) -> dict[str, Any]: ...

    async def record_cache_hit(self, month: str) -> None: ...

    async def is_budget_guard_enabled(self) -> bool: ...

    async def set_budget_guard_enabled(self, enabled: bool) -> None: ...

    async def get_job(self, job_id: str) -> dict[str, Any] | None: ...

    async def save_job(self, job_id: str, record: dict[str, Any]) -> None: ...

    async def get_erase_job(self, job_id: str) -> dict[str, Any] | None: ...

    async def save_erase_job(self, job_id: str, chat_id: int, record: dict[str, Any]) -> None: ...

    async def get_last_erase_job(self, chat_id: int) -> dict[str, Any] | None: ...

    async def get_cached_result(self, cache_key: str) -> dict[str, Any] | None: ...

    async def add_album_item(self, media_group_id: str, message_id: int, payload: dict[str, Any]) -> bool:
        """Store an album item and return True if this caller became the album leader."""
        ...

    async def pop_album_items(self, media_group_id: str) -> list[dict[str, Any]]:
        """Atomically drain and return sorted album items for a media_group_id."""
        ...


class TelegramGateway(Protocol):
    """Non-blocking async Telegram Bot API gateway used by application services."""

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> int: ...

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None: ...

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None: ...

    async def send_cached_file(
        self,
        chat_id: int,
        *,
        delivery_method: str,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None: ...


class JobDispatcher(Protocol):
    """Async port for spawning background CPU/GPU worker jobs."""

    async def spawn_cpu_file(self, **kwargs: Any) -> None: ...

    async def spawn_cpu_text(self, **kwargs: Any) -> None: ...

    async def spawn_cpu_erase(self, **kwargs: Any) -> None: ...

    async def spawn_cpu_album(self, **kwargs: Any) -> None: ...

    async def spawn_url_job(self, **kwargs: Any) -> None: ...

    async def spawn_album_collector(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_photo(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_photo_album(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_zip(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_audio(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_video_hd(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_video_fast(self, **kwargs: Any) -> None: ...

    async def spawn_gpu_warmup(self, target: str, *, chat_id: int, status_message_id: int, lang: str) -> None: ...
