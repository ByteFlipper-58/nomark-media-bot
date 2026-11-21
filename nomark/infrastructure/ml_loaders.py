"""ML model loading, offline-first Volume cache, CUDA tuning, and Wan 2.1 fast-path."""

from __future__ import annotations

import gc
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from nomark.config import (
    CACHE_DIR,
    WAN21_GUIDANCE_SCALE,
    WAN21_INFERENCE_STEPS,
    WAN21_NATURAL_PROMPT,
    WAN21_NEGATIVE_PROMPT,
)

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
            log.info("CUDA device ready: %s", torch.cuda.get_device_name(0))
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


class _CfgPipeProxy:
    """Thin wrapper injecting precomputed negative_prompt_embeds when CFG is enabled."""

    def __init__(self, pipe: Any, negative_prompt_embeds: Any | None) -> None:
        self._pipe = pipe
        self._negative_prompt_embeds = negative_prompt_embeds

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if (
            self._negative_prompt_embeds is not None
            and float(kwargs.get("guidance_scale", 1.0)) > 1.0
            and "negative_prompt_embeds" not in kwargs
        ):
            kwargs["negative_prompt_embeds"] = self._negative_prompt_embeds
        return self._pipe(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipe, name)


def _wan21_cfg_cache_path(model_id: str, revision: str, prompt: str, negative_prompt: str) -> Path:
    digest = hashlib.sha256(f"{model_id}|{revision}|{prompt}|{negative_prompt}".encode("utf-8")).hexdigest()[:12]
    return Path(CACHE_DIR) / f"wan21_cfg_embeds_{digest}.pt"


def load_wan21_fast() -> tuple[Any, bool]:
    """Load Wan 2.1 on CUDA with cached positive + negative embeddings (skips 9.4 GB UMT5-XXL)."""
    import torch
    from remove_ai_watermarks import video_wan

    video_wan.WAN21_DEFAULT_PROMPT = WAN21_NATURAL_PROMPT
    video_wan.WAN21_DEFAULT_NEGATIVE_PROMPT = WAN21_NEGATIVE_PROMPT
    video_wan.WAN21_INFERENCE_STEPS = WAN21_INFERENCE_STEPS
    video_wan.WAN21_GUIDANCE_SCALE = WAN21_GUIDANCE_SCALE

    embeds_path = _wan21_cfg_cache_path(
        video_wan.WAN21_MODEL_ID,
        video_wan.WAN21_MODEL_REVISION,
        WAN21_NATURAL_PROMPT,
        WAN21_NEGATIVE_PROMPT,
    )

    if embeds_path.exists():
        try:
            def _fast_loader(local_only: bool) -> Any:
                from diffusers.models.autoencoders.autoencoder_kl_wan import AutoencoderKLWan
                from diffusers.pipelines.wan.pipeline_wan_video2video import WanVideoToVideoPipeline
                from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler

                bundle = torch.load(embeds_path, map_location="cuda", weights_only=True)
                prompt_embeds = bundle["prompt"].to(device="cuda", dtype=torch.bfloat16)
                neg_embeds = bundle["negative"].to(device="cuda", dtype=torch.bfloat16)

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
                log.info("Loaded Wan 2.1 CFG fast-path (skipped 9.4 GB UMT5-XXL; local_only=%s)", local_only)
                return video_wan.VideoWanRuntime(
                    model=video_wan.WAN21_MODEL_ID,
                    revision=video_wan.WAN21_MODEL_REVISION,
                    resolved_device="cuda",
                    pipe=_CfgPipeProxy(pipe, neg_embeds),
                    prompt_embeds=prompt_embeds,
                )

            return with_offline_hf_fallback(_fast_loader)
        except Exception as fast_exc:
            log.warning("Wan 2.1 CFG fast-path fallback to full encoder: %s", fast_exc)

    # First-time build: encode both positive & negative prompts on CPU, free 9.4 GB UMT5-XXL, cache to Volume.
    def _full_cfg_loader(local_only: bool) -> Any:
        from diffusers.models.autoencoders.autoencoder_kl_wan import AutoencoderKLWan
        from diffusers.pipelines.wan.pipeline_wan_video2video import WanVideoToVideoPipeline
        from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler

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
            torch_dtype=torch.bfloat16,
            local_files_only=local_only,
        )
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config,
            flow_shift=video_wan.WAN21_FLOW_SHIFT,
        )
        with torch.inference_mode():
            cpu_pos, cpu_neg = pipe.encode_prompt(
                prompt=WAN21_NATURAL_PROMPT,
                negative_prompt=WAN21_NEGATIVE_PROMPT,
                device=torch.device("cpu"),
                num_videos_per_prompt=1,
                do_classifier_free_guidance=True,
            )
        prompt_embeds = cpu_pos.to(device="cuda", dtype=torch.bfloat16)
        neg_embeds = cpu_neg.to(device="cuda", dtype=torch.bfloat16)
        if hasattr(pipe, "text_encoder"):
            pipe.text_encoder = None
        if hasattr(pipe, "tokenizer"):
            pipe.tokenizer = None
        gc.collect()

        pipe.to("cuda")
        pipe.set_progress_bar_config(disable=True)
        torch.cuda.empty_cache()

        try:
            tmp_pt = embeds_path.with_suffix(".pt.tmp")
            torch.save({"prompt": cpu_pos.detach().cpu(), "negative": cpu_neg.detach().cpu()}, tmp_pt)
            tmp_pt.replace(embeds_path)
            log.info("Cached Wan 2.1 CFG prompt/negative embeds to %s", embeds_path)
        except Exception as save_exc:
            log.warning("Failed to cache Wan 2.1 CFG embeds: %s", save_exc)

        return video_wan.VideoWanRuntime(
            model=video_wan.WAN21_MODEL_ID,
            revision=video_wan.WAN21_MODEL_REVISION,
            resolved_device="cuda",
            pipe=_CfgPipeProxy(pipe, neg_embeds),
            prompt_embeds=prompt_embeds,
        )

    runtime, downloaded = with_offline_hf_fallback(_full_cfg_loader)
    return runtime, downloaded or embeds_path.exists()
