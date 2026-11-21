"""ML model loading, offline-first Volume cache, CUDA tuning, and Wan 2.1 fast-path."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from nomark.config import CACHE_DIR, WAN21_NATURAL_PROMPT

log = logging.getLogger("nomark.ml")


def sync_hf_constants(*, offline: bool | None = None) -> None:
    """Keep huggingface_hub.constants synced with /mnt/models even if imported earlier."""
    hf_const = sys.modules.get("huggingface_hub.constants")
    if hf_const is None:
        return
    hf_home = f"{CACHE_DIR}/hf"
    hf_hub = f"{CACHE_DIR}/hf/hub"
    hf_const.HF_HOME = hf_home
    hf_const.HF_HUB_CACHE = hf_hub
    hf_const.HUGGINGFACE_HUB_CACHE = hf_hub
    hf_const.HF_HUB_DISABLE_XET = True
    if offline is not None:
        hf_const.HF_HUB_OFFLINE = offline


def configure_cache_env() -> None:
    """Point HF/Torch caches to the mounted Modal Volume and keep hf_xet off the Volume."""
    os.environ["HF_HOME"] = f"{CACHE_DIR}/hf"
    os.environ["HUGGINGFACE_HUB_CACHE"] = f"{CACHE_DIR}/hf/hub"
    os.environ["TORCH_HOME"] = f"{CACHE_DIR}/torch"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_XET_CACHE"] = "/tmp/hf_xet"
    Path(f"{CACHE_DIR}/hf/hub").mkdir(parents=True, exist_ok=True)
    Path(f"{CACHE_DIR}/torch").mkdir(parents=True, exist_ok=True)
    sync_hf_constants()


def configure_cuda_perf() -> None:
    """Enable lossless-quality TF32 + cuDNN autotuning on Ada/Ampere/Hopper GPUs."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision("high")
    except Exception:
        pass


def with_offline_hf_fallback(loader_fn: Any) -> tuple[Any, bool]:
    """Try loading weights strictly from local Modal Volume first (0 HF API calls)."""
    prev_hf = os.environ.get("HF_HUB_OFFLINE")
    prev_tr = os.environ.get("TRANSFORMERS_OFFLINE")
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        sync_hf_constants(offline=True)
        return loader_fn(True), False
    except Exception as offline_exc:
        log.info("Offline cache miss (%s), fetching from Hugging Face...", offline_exc.__class__.__name__)
    finally:
        if prev_hf is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev_hf
        if prev_tr is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = prev_tr
        sync_hf_constants(offline=bool(prev_hf == "1"))

    return loader_fn(False), True


def load_photo_engine_sdxl() -> tuple[Any, bool]:
    """Load SDXL-ZImage and eagerly preload global SDXL + ControlNet weights into VRAM."""
    from remove_ai_watermarks.invisible_engine import InvisibleEngine

    hf_token = os.environ.get("HF_TOKEN") or None

    def _build(_local_only: bool) -> Any:
        eng = InvisibleEngine(pipeline="sdxl-zimage", hf_token=hf_token, cpu_offload=False)
        eng.preload(global_only=True)
        return eng

    return with_offline_hf_fallback(_build)


def load_video_vae_fast() -> tuple[Any, bool]:
    from remove_ai_watermarks.video_invisible import load_video_vae_runtime

    return with_offline_hf_fallback(lambda _local_only: load_video_vae_runtime(device="cuda"))


def _wan21_prompt_cache_path(model_id: str, revision: str, prompt: str) -> Path:
    digest = hashlib.sha256(f"{model_id}|{revision}|{prompt}".encode("utf-8")).hexdigest()[:12]
    return Path(CACHE_DIR) / f"wan21_prompt_embeds_{digest}.pt"


def load_wan21_fast() -> tuple[Any, bool]:
    """Load Wan 2.1 on CUDA, skipping the 9.4 GB UMT5-XXL encoder when prompt_embeds is cached."""
    import torch
    from remove_ai_watermarks import video_wan

    video_wan.WAN21_DEFAULT_PROMPT = WAN21_NATURAL_PROMPT
    embeds_path = _wan21_prompt_cache_path(
        video_wan.WAN21_MODEL_ID,
        video_wan.WAN21_MODEL_REVISION,
        WAN21_NATURAL_PROMPT,
    )

    if embeds_path.exists():
        try:
            def _fast_loader(local_only: bool) -> Any:
                from diffusers.models.autoencoders.autoencoder_kl_wan import AutoencoderKLWan
                from diffusers.pipelines.wan.pipeline_wan_video2video import WanVideoToVideoPipeline
                from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler

                prompt_embeds = torch.load(embeds_path, map_location="cuda", weights_only=True).to(
                    device="cuda", dtype=torch.bfloat16
                )
                vae = AutoencoderKLWan.from_pretrained(
                    video_wan.WAN21_MODEL_ID,
                    subfolder="vae",
                    revision=video_wan.WAN21_MODEL_REVISION,
                    torch_dtype=torch.float32,
                    local_files_only=local_only,
                )
                vae.enable_tiling()
                vae.enable_slicing()
                pipe = WanVideoToVideoPipeline.from_pretrained(
                    video_wan.WAN21_MODEL_ID,
                    revision=video_wan.WAN21_MODEL_REVISION,
                    vae=vae,
                    text_encoder=None,
                    tokenizer=None,
                    torch_dtype=torch.bfloat16,
                    local_files_only=local_only,
                )
                pipe.scheduler = UniPCMultistepScheduler.from_config(
                    pipe.scheduler.config,
                    flow_shift=video_wan.WAN21_FLOW_SHIFT,
                )
                pipe.to("cuda")
                pipe.set_progress_bar_config(disable=True)
                torch.cuda.empty_cache()
                log.info("Loaded Wan 2.1 fast-path (skipped 9.4 GB UMT5-XXL; local_only=%s)", local_only)
                return video_wan.VideoWanRuntime(
                    model=video_wan.WAN21_MODEL_ID,
                    revision=video_wan.WAN21_MODEL_REVISION,
                    resolved_device="cuda",
                    pipe=pipe,
                    prompt_embeds=prompt_embeds,
                )

            return with_offline_hf_fallback(_fast_loader)
        except Exception as fast_exc:
            log.warning("Wan 2.1 fast-path fallback to full loader: %s", fast_exc)

    runtime, downloaded = with_offline_hf_fallback(
        lambda local_only: video_wan.load_video_wan_runtime(device="cuda", local_files_only=local_only)
    )
    if runtime.prompt_embeds is not None:
        try:
            tmp_pt = embeds_path.with_suffix(".pt.tmp")
            torch.save(runtime.prompt_embeds.detach().cpu(), tmp_pt)
            tmp_pt.replace(embeds_path)
            downloaded = True
            log.info("Cached Wan 2.1 prompt_embeds to %s", embeds_path)
        except Exception as save_exc:
            log.warning("Failed to cache Wan 2.1 prompt_embeds: %s", save_exc)
    return runtime, downloaded
