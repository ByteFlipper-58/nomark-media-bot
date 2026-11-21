"""Pure domain rules & deterministic business logic (zero I/O, stdlib only)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import re
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomark.config import (
    AUDIO_EXTENSIONS,
    BUDGET_HARD_LIMIT_USD,
    BUDGET_WARN_USD,
    CACHE_SCHEMA_VERSION,
    DEFAULT_CLEAN_AUDIO,
    DEFAULT_EXIF,
    DEFAULT_LANG,
    DEFAULT_NATURAL_POLISH,
    DEFAULT_PHOTO_OUT,
    DEFAULT_STRENGTH,
    DEFAULT_VENDOR,
    IMAGE_EXTENSIONS,
    LANG_EN,
    LANG_RU,
    MODE_ERASE,
    MODE_FULL_FAST,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    OPENCV_WRITABLE_IMAGE_EXTENSIONS,
    RATE_CPU_PER_SEC,
    RATE_H100_PER_SEC,
    RATE_L4_PER_SEC,
    SUPPORTED_LANGS,
    TEXT_EXTENSIONS,
    VENDOR_GOOGLE,
    VENDOR_META,
    VENDOR_OPENAI,
    VIDEO_EXTENSIONS,
)

if TYPE_CHECKING:
    from nomark.domain.models import MediaItem

_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)
_BOX_RE = re.compile(r"^\s*(\d+)\s*[,;\s]\s*(\d+)\s*[,;\s]\s*(\d+)\s*[,;\s]\s*(\d+)\s*$")
_CIS_LANG_PREFIXES: tuple[str, ...] = ("ru", "uk", "be", "kk")


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------


def normalize_lang(lang: str | None, *, fallback: str = DEFAULT_LANG) -> str:
    """Normalize a language code into a supported language ('ru' or 'en')."""
    if not lang:
        return fallback
    code = lang.strip().lower()
    if code in SUPPORTED_LANGS:
        return code
    if any(code.startswith(p) for p in _CIS_LANG_PREFIXES):
        return LANG_RU
    return LANG_EN


def infer_lang_from_telegram_user(from_user: dict[str, Any] | None) -> str:
    """Guess default UI language from Telegram's user.language_code."""
    if not isinstance(from_user, dict):
        return DEFAULT_LANG
    return normalize_lang(str(from_user.get("language_code") or ""), fallback=DEFAULT_LANG)


# ---------------------------------------------------------------------------
# Auth & security policies
# ---------------------------------------------------------------------------


def verify_webhook_secret(received: str | None, expected: str | None) -> bool:
    """Validate Telegram's X-Telegram-Bot-Api-Secret-Token header."""
    if not expected:
        return True
    if not received:
        return False
    return hmac.compare_digest(received.strip(), expected.strip())


def parse_allowed_user_ids(raw: str | None) -> frozenset[int]:
    """Parse comma/space-separated numeric Telegram user IDs."""
    if not raw or not raw.strip():
        return frozenset()
    ids: set[int] = set()
    for token in re.split(r"[\s,;]+", raw.strip()):
        if token and token.lstrip("-").isdigit():
            ids.add(int(token))
    return frozenset(ids)


def is_user_allowed(user_id: int | None, allowed_raw: str | None) -> bool:
    """Allow everyone when ALLOWED_USER_IDS is empty, else require membership."""
    allowed = parse_allowed_user_ids(allowed_raw)
    if not allowed:
        return True
    if user_id is None:
        return False
    return user_id in allowed


# ---------------------------------------------------------------------------
# Photo vendor & region geometry policies
# ---------------------------------------------------------------------------


def resolve_photo_vendor(requested_vendor: str, detected_platform: str | None) -> tuple[str, float | None]:
    """Resolve effective vendor & optional strength override for sdxl-zimage."""
    if requested_vendor == VENDOR_OPENAI:
        return "openai", None
    if requested_vendor == VENDOR_META:
        return "meta", 0.20
    if requested_vendor == VENDOR_GOOGLE:
        return "google", None

    plat = (detected_platform or "").casefold()
    if any(k in plat for k in ("openai", "chatgpt", "dall")):
        return "openai", None
    if "meta" in plat:
        return "meta", 0.20
    return "google", None


def compute_corner_box(width: int, height: int, corner: str) -> tuple[int, int, int, int]:
    """Compute a clamped (x, y, w, h) rectangle for erasing a corner/region watermark."""
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image/video dimensions")

    if corner == "tl":
        bw, bh = max(16, round(width * 0.24)), max(16, round(height * 0.11))
        x, y = 0, 0
    elif corner == "tr":
        bw, bh = max(16, round(width * 0.24)), max(16, round(height * 0.11))
        x, y = width - bw, 0
    elif corner == "bl":
        bw, bh = max(16, round(width * 0.26)), max(16, round(height * 0.12))
        x, y = 0, height - bh
    elif corner == "br":
        bw, bh = max(16, round(width * 0.26)), max(16, round(height * 0.12))
        x, y = width - bw, height - bh
    elif corner == "bc":
        bw, bh = max(16, round(width * 0.36)), max(16, round(height * 0.11))
        x, y = (width - bw) // 2, height - bh
    elif corner == "center":
        bw, bh = max(16, round(width * 0.36)), max(16, round(height * 0.16))
        x, y = (width - bw) // 2, (height - bh) // 2
    else:
        raise ValueError(f"Unknown erase corner: {corner}")

    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    bw = max(1, min(bw, width - x))
    bh = max(1, min(bh, height - y))
    return (x, y, bw, bh)


def parse_box_coords(text: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Parse manual 'x,y,w,h' coordinates clamped to media dimensions."""
    m = _BOX_RE.match(text or "")
    if not m:
        return None
    x, y, bw, bh = (int(m.group(i)) for i in range(1, 5))
    if bw <= 0 or bh <= 0 or x >= width or y >= height:
        return None
    return (x, y, min(bw, width - x), min(bh, height - y))


def clamp_custom_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int] | None:
    """Clamp user-supplied (x, y, w, h) coordinates to actual media bounds, or None if invalid."""
    x, y, bw, bh = box
    if x < 0 or y < 0 or bw <= 0 or bh <= 0 or x >= width or y >= height:
        return None
    return (x, y, min(bw, width - x), min(bh, height - y))


# ---------------------------------------------------------------------------
# Result cache key policy
# ---------------------------------------------------------------------------


def build_result_cache_key(
    *,
    file_unique_id: str | None,
    kind: str,
    mode: str,
    video_strength: str = DEFAULT_STRENGTH,
    natural_polish: bool = DEFAULT_NATURAL_POLISH,
    clean_audio: bool = DEFAULT_CLEAN_AUDIO,
    photo_vendor: str = DEFAULT_VENDOR,
    camera_exif: str = DEFAULT_EXIF,
    photo_output: str = DEFAULT_PHOTO_OUT,
) -> str | None:
    """Build deterministic cache key for identical input + relevant settings."""
    if not file_unique_id or mode in {MODE_IDENTIFY, MODE_ERASE} or kind == "text_file":
        return None

    if kind == "image":
        if mode in {MODE_FULL_HD, MODE_FULL_FAST}:
            payload: dict[str, Any] = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "image",
                "m": "full",
                "np": bool(natural_polish),
                "pv": photo_vendor,
                "ex": camera_exif,
                "po": photo_output,
            }
        else:
            payload = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "image",
                "m": mode,
                "ex": camera_exif,
                "po": photo_output,
            }
    elif kind == "video":
        if mode in {MODE_FULL_HD, MODE_FULL_FAST}:
            payload = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "video",
                "m": mode,
                "vs": video_strength,
                "ca": bool(clean_audio),
                "np": bool(natural_polish) if mode == MODE_FULL_HD else False,
            }
        else:
            payload = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "video",
                "m": mode,
            }
    elif kind == "audio":
        payload = {
            "v": CACHE_SCHEMA_VERSION,
            "uid": file_unique_id,
            "k": "audio",
            "m": "full" if mode in {MODE_FULL_HD, MODE_FULL_FAST} else mode,
        }
    elif kind == "zip":
        if mode in {MODE_FULL_HD, MODE_FULL_FAST}:
            payload = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "zip",
                "m": "full",
                "np": bool(natural_polish),
                "pv": photo_vendor,
                "ex": camera_exif,
            }
        else:
            payload = {
                "v": CACHE_SCHEMA_VERSION,
                "uid": file_unique_id,
                "k": "zip",
                "m": mode,
                "ex": camera_exif,
            }
    else:
        return None

    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
    return f"rcache:{digest}"


# ---------------------------------------------------------------------------
# Usage stats & monthly budget policy
# ---------------------------------------------------------------------------


def current_month_key(now: dt.datetime | None = None) -> str:
    """Return UTC YYYY-MM key for monthly Modal credit accounting."""
    ts = now or dt.datetime.now(dt.UTC)
    return ts.strftime("%Y-%m")


def empty_stats(month: str | None = None) -> dict[str, Any]:
    return {
        "month": month or current_month_key(),
        "photos": 0,
        "videos_hd": 0,
        "videos_fast": 0,
        "audios": 0,
        "texts": 0,
        "zips": 0,
        "albums": 0,
        "visible_jobs": 0,
        "erase_jobs": 0,
        "c2pa_jobs": 0,
        "identify_jobs": 0,
        "cache_hits": 0,
        "l4_sec": 0.0,
        "h100_sec": 0.0,
        "cpu_sec": 0.0,
    }


def merge_stat_delta(
    current: Any,
    *,
    month: str,
    field: str | None,
    tier: str,
    seconds: float,
    count: int = 1,
) -> dict[str, Any]:
    """Accumulate one completed job into monthly usage stats."""
    stats = empty_stats(month)
    if isinstance(current, dict) and current.get("month") == month:
        for key in stats:
            if key in current and key != "month":
                stats[key] = current[key]
    if field and field in stats:
        stats[field] = int(stats[field]) + count
    sec = max(0.0, float(seconds))
    if tier == "h100":
        stats["h100_sec"] = round(float(stats["h100_sec"]) + sec, 2)
    elif tier == "l4":
        stats["l4_sec"] = round(float(stats["l4_sec"]) + sec, 2)
    else:
        stats["cpu_sec"] = round(float(stats["cpu_sec"]) + sec, 2)
    return stats


def estimate_spend_usd(stats: dict[str, Any]) -> float:
    l4 = float(stats.get("l4_sec", 0.0))
    h100 = float(stats.get("h100_sec", 0.0))
    cpu = float(stats.get("cpu_sec", 0.0))
    return l4 * RATE_L4_PER_SEC + h100 * RATE_H100_PER_SEC + cpu * RATE_CPU_PER_SEC


def check_budget_status(stats: dict[str, Any], guard_enabled: bool = True) -> tuple[str, float]:
    """Return ``(status, spend_usd)`` where status is 'ok' | 'warn' | 'blocked'."""
    spend = estimate_spend_usd(stats)
    if guard_enabled and spend >= BUDGET_HARD_LIMIT_USD:
        return "blocked", spend
    if spend >= BUDGET_WARN_USD:
        return "warn", spend
    return "ok", spend


# ---------------------------------------------------------------------------
# Filenames, URL parsing & Telegram media extraction
# ---------------------------------------------------------------------------


def sanitize_filename(name: str, default_stem: str, default_ext: str) -> str:
    """Return a filesystem-safe filename preserving a valid extension."""
    cleaned = Path(name).name.strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(cleaned).stem).strip("._") or default_stem
    ext = Path(cleaned).suffix.lower() or default_ext
    return f"{stem}{ext}"


def choose_output_filename(source_name: str, kind: str) -> str:
    """Build output filename with _clean suffix and a writable extension."""
    path = Path(source_name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or kind
    ext = path.suffix.lower()
    if kind == "image":
        if ext not in OPENCV_WRITABLE_IMAGE_EXTENSIONS:
            ext = ".png"
    elif kind == "video":
        if ext not in {".mp4", ".mov", ".m4v", ".mkv"}:
            ext = ".mp4"
    elif kind == "audio":
        if ext not in AUDIO_EXTENSIONS:
            ext = ".mp3"
    elif kind == "text_file":
        if ext not in TEXT_EXTENSIONS:
            ext = ".txt"
    elif kind == "zip":
        ext = ".zip"
    return f"{stem}_clean{ext}"


def extract_url_from_text(text: str) -> str | None:
    """Extract the first http(s) URL from a message if present."""
    match = _URL_RE.search(text or "")
    if not match:
        return None
    return match.group(1).rstrip(").,;!?")


def rewrite_cloud_download_url(url: str) -> str:
    """Convert common Google Drive / Dropbox share links into direct download URLs."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()

    if "drive.google.com" in host:
        file_id: str | None = None
        m = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
        if m:
            file_id = m.group(1)
        else:
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("id"):
                file_id = qs["id"][0]
        if file_id:
            return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"

    if "dropbox.com" in host:
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        qs["dl"] = ["1"]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    return url


def infer_kind_from_path_or_mime(filename: str, content_type: str | None = None) -> str | None:
    ext = Path(filename).suffix.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if ext == ".zip" or mime in {"application/zip", "application/x-zip-compressed"}:
        return "zip"
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    if ext in VIDEO_EXTENSIONS or mime.startswith("video/"):
        return "video"
    if ext in AUDIO_EXTENSIONS or mime.startswith("audio/"):
        return "audio"
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text_file"
    return None


def extract_media_from_message(message: dict[str, Any]) -> MediaItem | None:
    """Extract an image, video, audio, text file, or ZIP attachment from a Telegram message."""
    from nomark.domain.models import MediaItem

    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        best = max(photos, key=lambda item: (item.get("file_size") or 0, item.get("width") or 0))
        return MediaItem(
            kind="image",
            file_id=str(best["file_id"]),
            file_name="telegram_photo.jpg",
            file_size=best.get("file_size"),
            compressed_by_telegram=True,
            file_unique_id=str(best["file_unique_id"]) if best.get("file_unique_id") else None,
        )

    video = message.get("video")
    if isinstance(video, dict) and video.get("file_id"):
        mime = str(video.get("mime_type") or "video/mp4")
        guessed_ext = mimetypes.guess_extension(mime) or ".mp4"
        if guessed_ext == ".jpe":
            guessed_ext = ".mp4"
        raw_name = str(video.get("file_name") or f"telegram_video{guessed_ext}")
        return MediaItem(
            kind="video",
            file_id=str(video["file_id"]),
            file_name=sanitize_filename(raw_name, "telegram_video", ".mp4"),
            file_size=video.get("file_size"),
            compressed_by_telegram=False,
            file_unique_id=str(video["file_unique_id"]) if video.get("file_unique_id") else None,
        )

    audio = message.get("audio")
    if isinstance(audio, dict) and audio.get("file_id"):
        mime = str(audio.get("mime_type") or "audio/mpeg")
        guessed_ext = mimetypes.guess_extension(mime) or ".mp3"
        if guessed_ext == ".mpga":
            guessed_ext = ".mp3"
        raw_name = str(audio.get("file_name") or f"telegram_audio{guessed_ext}")
        return MediaItem(
            kind="audio",
            file_id=str(audio["file_id"]),
            file_name=sanitize_filename(raw_name, "telegram_audio", ".mp3"),
            file_size=audio.get("file_size"),
            compressed_by_telegram=False,
            file_unique_id=str(audio["file_unique_id"]) if audio.get("file_unique_id") else None,
        )

    voice = message.get("voice")
    if isinstance(voice, dict) and voice.get("file_id"):
        return MediaItem(
            kind="audio",
            file_id=str(voice["file_id"]),
            file_name="voice_message.ogg",
            file_size=voice.get("file_size"),
            compressed_by_telegram=False,
            file_unique_id=str(voice["file_unique_id"]) if voice.get("file_unique_id") else None,
        )

    doc = message.get("document")
    if isinstance(doc, dict) and doc.get("file_id"):
        mime = str(doc.get("mime_type") or "").lower()
        raw_name = str(doc.get("file_name") or "")
        kind = infer_kind_from_path_or_mime(raw_name, mime)
        if kind is not None:
            default_ext_map = {
                "image": ".png",
                "video": ".mp4",
                "audio": ".mp3",
                "text_file": ".txt",
                "zip": ".zip",
            }
            fallback_ext = mimetypes.guess_extension(mime) or default_ext_map[kind]
            if fallback_ext in {".jpe", ".mpga"}:
                fallback_ext = default_ext_map[kind]
            return MediaItem(
                kind=kind,
                file_id=str(doc["file_id"]),
                file_name=sanitize_filename(raw_name or f"{kind}{fallback_ext}", kind, fallback_ext),
                file_size=doc.get("file_size"),
                compressed_by_telegram=False,
                file_unique_id=str(doc["file_unique_id"]) if doc.get("file_unique_id") else None,
            )

    return None
