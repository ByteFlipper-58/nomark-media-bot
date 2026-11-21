"""Centralized constants, resource names, limits, and pricing configuration."""

from __future__ import annotations

import os

# Branding & Modal resource names (customizable via env vars for forks)
BOT_NAME = os.environ.get("NOMARK_BOT_NAME", "NoMark")
APP_NAME = os.environ.get("NOMARK_APP_NAME", "raiw-telegram-bot")
SECRET_NAME = os.environ.get("NOMARK_SECRET_NAME", "raiw-bot-secrets")
VOLUME_NAME = os.environ.get("NOMARK_VOLUME_NAME", "raiw-model-cache")
STATE_DICT_NAME = os.environ.get("NOMARK_STATE_DICT_NAME", "raiw-bot-state")
ALBUM_DICT_NAME = os.environ.get("NOMARK_ALBUM_DICT_NAME", "raiw-bot-albums")

CACHE_DIR = "/mnt/models"
TMP_DOWNLOADS_DIR = f"{CACHE_DIR}/tmp_downloads"
TMP_INPUTS_DIR = f"{CACHE_DIR}/tmp_inputs"
DOWNLOAD_LINK_TTL_SEC = 3600

# Telegram & transfer limits
TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB Bot API download limit
TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB Bot API upload limit
TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024  # 10 MB sendPhoto limit
URL_MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024  # 250 MB remote URL cap
MAX_ZIP_IMAGES = 40
MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB zip-bomb guard
ALBUM_COALESCE_DELAY_SEC = 2.5

# Supported file extensions
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".avif", ".bmp", ".tif", ".tiff"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv"})
AUDIO_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"})
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md", ".html", ".htm"})
OPENCV_WRITABLE_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})

# Processing modes
MODE_FULL_HD = "full_hd"
MODE_FULL_FAST = "full_fast"
MODE_VISIBLE = "visible"
MODE_ERASE = "erase"
MODE_C2PA_ONLY = "c2pa_only"
MODE_IDENTIFY = "identify"
VALID_MODES: frozenset[str] = frozenset(
    {MODE_FULL_HD, MODE_FULL_FAST, MODE_VISIBLE, MODE_ERASE, MODE_C2PA_ONLY, MODE_IDENTIFY}
)
DEFAULT_MODE = MODE_FULL_HD

# Video strength presets
STRENGTH_SOFT = "soft"
STRENGTH_BALANCED = "balanced"
STRENGTH_STRONG = "strong"
STRENGTH_ORDER: tuple[str, ...] = (STRENGTH_SOFT, STRENGTH_BALANCED, STRENGTH_STRONG)
VALID_STRENGTHS: frozenset[str] = frozenset(STRENGTH_ORDER)
DEFAULT_STRENGTH = STRENGTH_BALANCED

WAN_STRENGTH_VALUES: dict[str, float] = {
    STRENGTH_SOFT: 0.22,
    STRENGTH_BALANCED: 0.28,
    STRENGTH_STRONG: 0.36,
}
SDVAE_NOISE_VALUES: dict[str, float] = {
    STRENGTH_SOFT: 0.13,
    STRENGTH_BALANCED: 0.16,
    STRENGTH_STRONG: 0.22,
}

WAN21_INFERENCE_STEPS = 32
WAN21_GUIDANCE_SCALE = 2.0
WAN21_NATURAL_PROMPT = (
    "Raw realistic camera footage, natural human skin pores and fine micro-texture, "
    "sharp optical focus, authentic natural lighting, true-to-life details, unretouched."
)
WAN21_NEGATIVE_PROMPT = (
    "cartoon, anime, 3d render, CGI, plastic skin, waxy, airbrushed, overly smooth, "
    "illustration, painting, pixelated, blocky, compression artifacts, blurry, low quality, flicker"
)

# Photo source vendor profiles
VENDOR_AUTO = "auto"
VENDOR_GOOGLE = "google"
VENDOR_OPENAI = "openai"
VENDOR_META = "meta"
VENDOR_ORDER: tuple[str, ...] = (VENDOR_AUTO, VENDOR_GOOGLE, VENDOR_OPENAI, VENDOR_META)
VALID_VENDORS: frozenset[str] = frozenset(VENDOR_ORDER)
DEFAULT_VENDOR = VENDOR_AUTO

# Camera EXIF profiles
EXIF_OFF = "off"
EXIF_IPHONE = "iphone"
EXIF_SONY = "sony"
EXIF_ORDER: tuple[str, ...] = (EXIF_OFF, EXIF_IPHONE, EXIF_SONY)
VALID_EXIF_PROFILES: frozenset[str] = frozenset(EXIF_ORDER)
DEFAULT_EXIF = EXIF_OFF

# Photo output format
PHOTO_OUT_DOCUMENT = "document"
PHOTO_OUT_PHOTO = "photo"
VALID_PHOTO_OUTS: frozenset[str] = frozenset({PHOTO_OUT_DOCUMENT, PHOTO_OUT_PHOTO})
DEFAULT_PHOTO_OUT = PHOTO_OUT_DOCUMENT

# Languages
LANG_RU = "ru"
LANG_EN = "en"
LANG_ORDER: tuple[str, ...] = (LANG_RU, LANG_EN)
SUPPORTED_LANGS: frozenset[str] = frozenset(LANG_ORDER)
DEFAULT_LANG = LANG_EN

DEFAULT_CLEAN_AUDIO = True
DEFAULT_NATURAL_POLISH = True

CACHE_SCHEMA_VERSION = "v5"

# Approximate Modal Starter per-second rates (GPU + container CPU/RAM)
MODAL_MONTHLY_FREE_USD = 30.0
BUDGET_WARN_USD = 24.0
BUDGET_HARD_LIMIT_USD = 27.0
RATE_L4_PER_SEC = 0.00030
RATE_H100_PER_SEC = 0.00118
RATE_CPU_PER_SEC = 0.00004
