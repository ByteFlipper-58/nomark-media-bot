"""NoMark — Modal Composition Root & Serverless Worker Wiring.

Architecture (Clean Architecture + End-to-End Async I/O):
- `nomark.domain`: Pure entities (`UserSettings`, `MediaItem`), deterministic business rules,
  and async Port Protocols (`StateStore`, `TelegramGateway`, `JobDispatcher`).
- `nomark.presentation`: Bilingual RU/EN localization (`i18n`), inline keyboards, and HTML views.
- `nomark.application`: Pure async use-cases (`WebhookService`, `AlbumService`).
- `nomark.infrastructure`: Pooled async/sync Telegram HTTP clients, SSRF-safe media I/O,
  offline-first ML loaders + Wan 2.1 prompt_embeds cache, Modal Dict/Volume adapters,
  and CPU/GPU processing pipelines.
- `modal_app.py` (this file): Thin Modal Composition Root binding images, snapshots, secrets,
  volumes, and worker endpoints to `nomark.*`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import modal

try:
    from fastapi import HTTPException, Request
except ImportError:
    HTTPException = Exception  # type: ignore[misc, assignment]
    Request = Any  # type: ignore[misc, assignment]

from nomark.application.album_service import AlbumService
from nomark.application.webhook_service import WebhookService
from nomark.config import (
    ALBUM_DICT_NAME,
    APP_NAME,
    CACHE_DIR,
    EXIF_OFF,
    LANG_RU,
    SECRET_NAME,
    STATE_DICT_NAME,
    TMP_DOWNLOADS_DIR,
    VOLUME_NAME,
)
from nomark.domain.policies import verify_webhook_secret
from nomark.infrastructure.ml_loaders import (
    configure_cache_env,
    configure_cuda_perf,
    load_photo_engine_sdxl,
    load_video_vae_fast,
    load_wan21_fast,
)
from nomark.infrastructure.modal_adapters import ModalStateStore, ModalVolumeHelper
from nomark.infrastructure.pipelines import (
    notify_warmup_done,
    run_cpu_album_pipeline,
    run_cpu_erase_pipeline,
    run_cpu_file_pipeline,
    run_cpu_text_pipeline,
    run_gpu_album_pipeline,
    run_gpu_audio_pipeline,
    run_gpu_photo_pipeline,
    run_gpu_video_pipeline,
    run_gpu_zip_pipeline,
    run_url_job_pipeline,
)
from nomark.infrastructure.telegram_client import AsyncTelegramClient

log = logging.getLogger("nomark")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Modal App, Resources & Container Images
# ---------------------------------------------------------------------------

app = modal.App(APP_NAME)

model_cache = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
state_dict = modal.Dict.from_name(STATE_DICT_NAME, create_if_missing=True)
album_dict = modal.Dict.from_name(ALBUM_DICT_NAME, create_if_missing=True)
bot_secrets = modal.Secret.from_name(SECRET_NAME)

webhook_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("fastapi[standard]>=0.115", "httpx>=0.28")
    .add_local_python_source("nomark")
)

cpu_worker_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .uv_pip_install(
        "httpx>=0.28",
        "c2pa-python==0.38.0",
        "remove-ai-watermarks[migan,video,heif,audio,source-classify]==0.64.0",
    )
    .add_local_python_source("nomark")
)

gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .uv_pip_install(
        "httpx>=0.28",
        "c2pa-python==0.38.0",
        "remove-ai-watermarks[qwen-zimage,video,heif,audio-codec]==0.64.0",
    )
    .env({"TRANSFORMERS_VERBOSITY": "error"})
    .add_local_python_source("nomark")
)

# Pre-import lightweight libraries before CPU/GPU memory snapshots are captured.
# IMPORTANT: Keep huggingface_hub/diffusers/remove_ai_watermarks lazy until AFTER
# configure_cache_env() runs so HF_HUB_CACHE & HF_HUB_DISABLE_XET bind to /mnt/models.
with webhook_image.imports():
    import httpx  # noqa: F401

with cpu_worker_image.imports():
    import cv2  # noqa: F401
    import httpx as _cpu_httpx  # noqa: F401
    import piexif  # noqa: F401

with gpu_image.imports():
    import cv2 as _gpu_cv2  # noqa: F401
    import httpx as _gpu_httpx  # noqa: F401
    import piexif as _gpu_piexif  # noqa: F401
    import torch  # noqa: F401

# ---------------------------------------------------------------------------
# Composition Helpers (Adapters & Pooled Async Telegram Gateway)
# ---------------------------------------------------------------------------

_state_store = ModalStateStore(state_dict, album_dict)
_volume_helper = ModalVolumeHelper(model_cache)
_async_tg_client: AsyncTelegramClient | None = None


def _get_async_tg() -> AsyncTelegramClient:
    """Return a lazily initialized keep-alive AsyncTelegramClient (created after snapshot restore)."""
    global _async_tg_client
    if _async_tg_client is None:
        _async_tg_client = AsyncTelegramClient(os.environ["TELEGRAM_BOT_TOKEN"])
    return _async_tg_client


class ModalJobDispatcher:
    """Async JobDispatcher port backed by Modal `.spawn.aio(...)`."""

    async def spawn_cpu_file(self, **kwargs: Any) -> None:
        await cpu_process_file.spawn.aio(**kwargs)

    async def spawn_cpu_text(self, **kwargs: Any) -> None:
        await cpu_process_text.spawn.aio(**kwargs)

    async def spawn_cpu_erase(self, **kwargs: Any) -> None:
        await cpu_erase_region.spawn.aio(**kwargs)

    async def spawn_cpu_album(self, **kwargs: Any) -> None:
        await cpu_process_album.spawn.aio(**kwargs)

    async def spawn_url_job(self, **kwargs: Any) -> None:
        await process_url_job.spawn.aio(**kwargs)

    async def spawn_album_collector(self, **kwargs: Any) -> None:
        await collect_and_dispatch_album.spawn.aio(**kwargs)

    async def spawn_gpu_photo(self, **kwargs: Any) -> None:
        await PhotoGpuWorker().clean_photo.spawn.aio(**kwargs)

    async def spawn_gpu_photo_album(self, **kwargs: Any) -> None:
        await PhotoGpuWorker().clean_photo_album.spawn.aio(**kwargs)

    async def spawn_gpu_zip(self, **kwargs: Any) -> None:
        await PhotoGpuWorker().clean_zip.spawn.aio(**kwargs)

    async def spawn_gpu_audio(self, **kwargs: Any) -> None:
        await PhotoGpuWorker().clean_audio_file.spawn.aio(**kwargs)

    async def spawn_gpu_video_hd(self, **kwargs: Any) -> None:
        await VideoWanGpuWorker().clean_video.spawn.aio(**kwargs)

    async def spawn_gpu_video_fast(self, **kwargs: Any) -> None:
        await VideoFastGpuWorker().clean_video.spawn.aio(**kwargs)

    async def spawn_gpu_warmup(
        self,
        target: str,
        *,
        chat_id: int,
        status_message_id: int,
        lang: str,
    ) -> None:
        if target == "photo":
            await PhotoGpuWorker().warmup.spawn.aio(chat_id=chat_id, status_message_id=status_message_id, lang=lang)
        elif target == "vfast":
            await VideoFastGpuWorker().warmup.spawn.aio(chat_id=chat_id, status_message_id=status_message_id, lang=lang)
        elif target == "vwan":
            await VideoWanGpuWorker().warmup.spawn.aio(chat_id=chat_id, status_message_id=status_message_id, lang=lang)


class ModalSyncJobDispatcher:
    """Sync job dispatcher used by the remote URL fetcher worker."""

    def spawn_cpu_file(self, **kwargs: Any) -> None:
        cpu_process_file.spawn(**kwargs)

    def spawn_gpu_photo(self, **kwargs: Any) -> None:
        PhotoGpuWorker().clean_photo.spawn(**kwargs)

    def spawn_gpu_zip(self, **kwargs: Any) -> None:
        PhotoGpuWorker().clean_zip.spawn(**kwargs)

    def spawn_gpu_audio(self, **kwargs: Any) -> None:
        PhotoGpuWorker().clean_audio_file.spawn(**kwargs)

    def spawn_gpu_video_hd(self, **kwargs: Any) -> None:
        VideoWanGpuWorker().clean_video.spawn(**kwargs)

    def spawn_gpu_video_fast(self, **kwargs: Any) -> None:
        VideoFastGpuWorker().clean_video.spawn(**kwargs)


_async_dispatcher = ModalJobDispatcher()
_sync_dispatcher = ModalSyncJobDispatcher()

# ---------------------------------------------------------------------------
# Temporary File Download Endpoint (>50 MB cleaned videos/archives)
# ---------------------------------------------------------------------------


@app.function(
    image=webhook_image,
    volumes={CACHE_DIR: model_cache},
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=10)
@modal.fastapi_endpoint(method="GET")
async def download_file_endpoint(token: str = "") -> Any:
    from fastapi.responses import FileResponse

    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=400, detail="Invalid token")

    await model_cache.reload.aio()
    slot = Path(TMP_DOWNLOADS_DIR) / token
    meta_path = slot / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if time.time() > float(meta.get("expires_at", 0)):
            raise HTTPException(status_code=410, detail="Download link expired")
        raw_filename = str(meta["filename"])
        filename = Path(raw_filename).name
        if not filename or filename != raw_filename:
            raise HTTPException(status_code=404, detail="Invalid filename")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Corrupt metadata") from exc

    target = slot / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File missing")

    return FileResponse(path=str(target), filename=filename, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Async Album Coalescer (Telegram Media Group -> single warm GPU/CPU batch)
# ---------------------------------------------------------------------------


@app.function(
    image=webhook_image,
    secrets=[bot_secrets],
    timeout=60,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=8)
async def collect_and_dispatch_album(
    *,
    chat_id: int,
    media_group_id: str,
    first_message_id: int,
    settings_dict: dict[str, Any],
) -> None:
    service = AlbumService(
        state=_state_store,
        tg=_get_async_tg(),
        dispatcher=_async_dispatcher,
    )
    await service.collect_and_dispatch(
        chat_id=chat_id,
        media_group_id=media_group_id,
        first_message_id=first_message_id,
        settings_dict=settings_dict,
    )


# ---------------------------------------------------------------------------
# CPU Workers: Identify, C2PA-only, Visible marks, Manual Erase, Albums, Text, URL
# ---------------------------------------------------------------------------


@app.function(
    image=cpu_worker_image,
    cpu=4.0,
    memory=8192,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=600,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=4)
def cpu_process_file(
    *,
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
    run_cpu_file_pipeline(
        tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
        state=_state_store,
        vol=_volume_helper,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
        status_message_id=status_message_id,
        kind=kind,
        file_id=file_id,
        file_name=file_name,
        mode=mode,
        compressed_by_telegram=compressed_by_telegram,
        camera_exif=camera_exif,
        photo_output=photo_output,
        staged_path=staged_path,
        cache_key=cache_key,
        lang=lang,
    )


@app.function(
    image=cpu_worker_image,
    cpu=4.0,
    memory=8192,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=600,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=4)
def cpu_erase_region(
    *,
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
    run_cpu_erase_pipeline(
        tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
        state=_state_store,
        vol=_volume_helper,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
        status_message_id=status_message_id,
        kind=kind,
        file_id=file_id,
        file_name=file_name,
        corner=corner,
        custom_box=custom_box,
        camera_exif=camera_exif,
        photo_output=photo_output,
        staged_path=staged_path,
        lang=lang,
    )


@app.function(
    image=cpu_worker_image,
    cpu=4.0,
    memory=8192,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=600,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=2)
def cpu_process_album(
    *,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    items: list[dict[str, Any]],
    mode: str,
    camera_exif: str = EXIF_OFF,
    photo_output: str = "document",
    lang: str = LANG_RU,
) -> None:
    run_cpu_album_pipeline(
        tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
        state=_state_store,
        vol=_volume_helper,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
        status_message_id=status_message_id,
        items=items,
        mode=mode,
        camera_exif=camera_exif,
        photo_output=photo_output,
        lang=lang,
    )


@app.function(
    image=cpu_worker_image,
    secrets=[bot_secrets],
    timeout=60,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=8)
def cpu_process_text(
    *,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    raw_text: str,
    mode: str,
    lang: str = LANG_RU,
) -> None:
    run_cpu_text_pipeline(
        tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
        state=_state_store,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
        status_message_id=status_message_id,
        raw_text=raw_text,
        mode=mode,
        lang=lang,
    )


@app.function(
    image=cpu_worker_image,
    cpu=2.0,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=300,
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=4)
def process_url_job(
    *,
    chat_id: int,
    reply_to_message_id: int,
    status_message_id: int,
    url: str,
    settings_dict: dict[str, Any],
) -> None:
    run_url_job_pipeline(
        tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
        state=_state_store,
        vol=_volume_helper,
        dispatcher=_sync_dispatcher,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
        status_message_id=status_message_id,
        url=url,
        settings_dict=settings_dict,
    )


# ---------------------------------------------------------------------------
# GPU Worker 1: Photo (single, album, ZIP) + Audio on NVIDIA L4/A10G
# ---------------------------------------------------------------------------


@app.cls(
    image=gpu_image,
    gpu=["L4", "A10G"],
    cpu=4.0,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=900,
    startup_timeout=600,
    scaledown_window=210,
    max_containers=2,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
class PhotoGpuWorker:
    @modal.enter(snap=True)
    def load_snapshot(self) -> None:
        _volume_helper.safe_reload()
        configure_cache_env()
        configure_cuda_perf()
        self._engine: Any = None
        self._cache_committed = False
        self._get_engine()

    @modal.enter(snap=False)
    def on_restore(self) -> None:
        configure_cache_env()
        configure_cuda_perf()

    def _get_engine(self) -> Any:
        if self._engine is None:
            self._engine, downloaded = load_photo_engine_sdxl()
            if downloaded or not self._cache_committed:
                _volume_helper.safe_commit()
                self._cache_committed = True
        return self._engine

    @modal.method()
    def warmup(self, *, chat_id: int | None = None, status_message_id: int | None = None, lang: str = LANG_RU) -> str:
        started = time.monotonic()
        self._get_engine()
        notify_warmup_done(
            os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=chat_id,
            status_message_id=status_message_id,
            i18n_key="status.warm_photo_done",
            elapsed=time.monotonic() - started,
            lang=lang,
        )
        return "warm"

    @modal.method()
    def clean_photo(
        self,
        *,
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
        run_gpu_photo_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            get_engine=self._get_engine,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            file_id=file_id,
            file_name=file_name,
            compressed_by_telegram=compressed_by_telegram,
            natural_polish=natural_polish,
            photo_vendor=photo_vendor,
            camera_exif=camera_exif,
            photo_output=photo_output,
            staged_path=staged_path,
            cache_key=cache_key,
            lang=lang,
        )

    @modal.method()
    def clean_photo_album(
        self,
        *,
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
        run_gpu_album_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            get_engine=self._get_engine,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            items=items,
            natural_polish=natural_polish,
            photo_vendor=photo_vendor,
            camera_exif=camera_exif,
            photo_output=photo_output,
            lang=lang,
        )

    @modal.method()
    def clean_zip(
        self,
        *,
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
        run_gpu_zip_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            get_engine=self._get_engine,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            file_id=file_id,
            file_name=file_name,
            natural_polish=natural_polish,
            photo_vendor=photo_vendor,
            camera_exif=camera_exif,
            staged_path=staged_path,
            cache_key=cache_key,
            lang=lang,
        )

    @modal.method()
    def clean_audio_file(
        self,
        *,
        chat_id: int,
        reply_to_message_id: int,
        status_message_id: int,
        file_id: str | None,
        file_name: str,
        staged_path: str | None = None,
        cache_key: str | None = None,
        lang: str = LANG_RU,
    ) -> None:
        run_gpu_audio_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            file_id=file_id,
            file_name=file_name,
            staged_path=staged_path,
            cache_key=cache_key,
            lang=lang,
        )


# ---------------------------------------------------------------------------
# GPU Worker 2A: Fast Video SD-VAE HD on NVIDIA L4/A10G
# ---------------------------------------------------------------------------


@app.cls(
    image=gpu_image,
    gpu=["L4", "A10G"],
    cpu=8.0,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=600,
    startup_timeout=600,
    scaledown_window=210,
    max_containers=2,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
class VideoFastGpuWorker:
    @modal.enter(snap=True)
    def load_snapshot(self) -> None:
        _volume_helper.safe_reload()
        configure_cache_env()
        configure_cuda_perf()
        self._runtime: Any = None
        self._cache_committed = False
        self._get_runtime()

    @modal.enter(snap=False)
    def on_restore(self) -> None:
        configure_cache_env()
        configure_cuda_perf()

    def _get_runtime(self) -> Any:
        if self._runtime is None:
            self._runtime, downloaded = load_video_vae_fast()
            if downloaded or not self._cache_committed:
                _volume_helper.safe_commit()
                self._cache_committed = True
        return self._runtime

    @modal.method()
    def warmup(self, *, chat_id: int | None = None, status_message_id: int | None = None, lang: str = LANG_RU) -> str:
        started = time.monotonic()
        self._get_runtime()
        notify_warmup_done(
            os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=chat_id,
            status_message_id=status_message_id,
            i18n_key="status.warm_vfast_done",
            elapsed=time.monotonic() - started,
            lang=lang,
        )
        return "warm"

    @modal.method()
    def clean_video(
        self,
        *,
        chat_id: int,
        reply_to_message_id: int,
        status_message_id: int,
        file_id: str | None,
        file_name: str,
        clean_audio: bool,
        video_strength: str = "balanced",
        staged_path: str | None = None,
        cache_key: str | None = None,
        lang: str = LANG_RU,
    ) -> None:
        run_gpu_video_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            use_wan=False,
            get_runtime=self._get_runtime,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            file_id=file_id,
            file_name=file_name,
            clean_audio=clean_audio,
            video_strength=video_strength,
            natural_polish=False,
            staged_path=staged_path,
            cache_key=cache_key,
            lang=lang,
        )


# ---------------------------------------------------------------------------
# GPU Worker 2B: HD Video 3D Wan 2.1 on NVIDIA H100/A100-80GB
# ---------------------------------------------------------------------------


@app.cls(
    image=gpu_image,
    gpu=["H100", "A100-80GB"],
    cpu=4.0,
    memory=32768,
    volumes={CACHE_DIR: model_cache},
    secrets=[bot_secrets],
    timeout=1200,
    startup_timeout=600,
    scaledown_window=75,
    max_containers=2,
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},
)
class VideoWanGpuWorker:
    @modal.enter(snap=True)
    def load_snapshot(self) -> None:
        _volume_helper.safe_reload()
        configure_cache_env()
        configure_cuda_perf()
        self._runtime: Any = None
        self._cache_committed = False
        self._get_runtime()

    @modal.enter(snap=False)
    def on_restore(self) -> None:
        configure_cache_env()
        configure_cuda_perf()

    def _get_runtime(self) -> Any:
        if self._runtime is None:
            self._runtime, downloaded = load_wan21_fast()
            if downloaded or not self._cache_committed:
                _volume_helper.safe_commit()
                self._cache_committed = True
        return self._runtime

    @modal.method()
    def warmup(self, *, chat_id: int | None = None, status_message_id: int | None = None, lang: str = LANG_RU) -> str:
        started = time.monotonic()
        self._get_runtime()
        notify_warmup_done(
            os.environ["TELEGRAM_BOT_TOKEN"],
            chat_id=chat_id,
            status_message_id=status_message_id,
            i18n_key="status.warm_vwan_done",
            elapsed=time.monotonic() - started,
            lang=lang,
        )
        return "warm"

    @modal.method()
    def clean_video(
        self,
        *,
        chat_id: int,
        reply_to_message_id: int,
        status_message_id: int,
        file_id: str | None,
        file_name: str,
        clean_audio: bool,
        video_strength: str = "balanced",
        natural_polish: bool = True,
        staged_path: str | None = None,
        cache_key: str | None = None,
        lang: str = LANG_RU,
    ) -> None:
        run_gpu_video_pipeline(
            tg_token=os.environ["TELEGRAM_BOT_TOKEN"],
            state=_state_store,
            vol=_volume_helper,
            use_wan=True,
            get_runtime=self._get_runtime,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            status_message_id=status_message_id,
            file_id=file_id,
            file_name=file_name,
            clean_audio=clean_audio,
            video_strength=video_strength,
            natural_polish=natural_polish,
            staged_path=staged_path,
            cache_key=cache_key,
            lang=lang,
        )


# ---------------------------------------------------------------------------
# FastAPI Async Webhook Entrypoint (non-blocking httpx.AsyncClient + asyncio.gather)
# ---------------------------------------------------------------------------


@app.function(
    image=webhook_image,
    secrets=[bot_secrets],
    scaledown_window=180,
    max_containers=4,
    enable_memory_snapshot=True,
)
@modal.concurrent(max_inputs=10)
@modal.fastapi_endpoint(method="POST")
async def telegram_webhook(request: Request) -> Any:
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    received_secret = request.headers.get("x-telegram-bot-api-secret-token")
    if not verify_webhook_secret(received_secret, expected_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    service = WebhookService(
        state=_state_store,
        tg=_get_async_tg(),
        dispatcher=_async_dispatcher,
        allowed_users_raw=os.environ.get("ALLOWED_USER_IDS"),
    )
    return await service.handle_update(update)
