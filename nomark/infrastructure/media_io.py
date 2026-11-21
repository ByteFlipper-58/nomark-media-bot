"""Media I/O infrastructure: SSRF-safe URL download, ZIP extract/pack, Camera EXIF, FFmpeg helpers."""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import mimetypes
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import zipfile
from pathlib import Path

from nomark.config import (
    DOWNLOAD_LINK_TTL_SEC,
    EXIF_OFF,
    EXIF_SONY,
    IMAGE_EXTENSIONS,
    MAX_ZIP_IMAGES,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    URL_MAX_DOWNLOAD_BYTES,
    VALID_EXIF_PROFILES,
)
from nomark.domain.policies import (
    infer_kind_from_path_or_mime,
    rewrite_cloud_download_url,
    sanitize_filename,
)


def _validate_public_url(url: str) -> None:
    """Block non-HTTP schemes and private/loopback hosts (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// links are supported.")
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid URL.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError(f"Could not resolve host {host}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Access to private/local IP addresses is blocked.")


def download_url_safe(url: str, dest_dir: Path, max_bytes: int = URL_MAX_DOWNLOAD_BYTES) -> tuple[Path, str]:
    """Download a remote media file with SSRF guard, redirect checks, and size cap."""
    import httpx

    target_url = rewrite_cloud_download_url(url)
    _validate_public_url(target_url)

    dest_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=180.0, follow_redirects=True, max_redirects=6) as client:
        with client.stream("GET", target_url, headers={"User-Agent": "NoMarkBot/4.0"}) as resp:
            resp.raise_for_status()
            _validate_public_url(str(resp.url))

            content_len = resp.headers.get("content-length")
            if content_len and content_len.isdigit() and int(content_len) > max_bytes:
                mb = int(content_len) / (1024 * 1024)
                raise ValueError(f"Remote file is {mb:.1f} MB (limit: {max_bytes // (1024 * 1024)} MB).")

            content_type = resp.headers.get("content-type", "")
            cd = resp.headers.get("content-disposition", "")
            raw_name = ""
            m_star = re.search(r"filename\*=UTF-8''([^;\r\n]+)", cd, re.IGNORECASE)
            m_plain = re.search(r'filename="?([^";\r\n]+)"?', cd, re.IGNORECASE)
            if m_star:
                raw_name = urllib.parse.unquote(m_star.group(1))
            elif m_plain:
                raw_name = m_plain.group(1)
            if not raw_name:
                raw_name = Path(urllib.parse.unquote(urllib.parse.urlparse(str(resp.url)).path)).name

            if "text/html" in content_type.lower() and not raw_name.lower().endswith((".html", ".htm")):
                raise ValueError(
                    "URL returned an HTML page instead of a file. Make sure sharing is set to 'Anyone with the link'."
                )

            kind = infer_kind_from_path_or_mime(raw_name, content_type)
            if kind is None:
                guessed_ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower()) or ""
                if guessed_ext:
                    kind = infer_kind_from_path_or_mime(f"media{guessed_ext}", content_type)
            if kind is None:
                raise ValueError(f"Unsupported remote media type (Content-Type: {content_type or 'unknown'}).")

            default_ext_map = {"image": ".png", "video": ".mp4", "audio": ".mp3", "zip": ".zip", "text_file": ".txt"}
            safe_name = sanitize_filename(
                raw_name or f"remote_{kind}{default_ext_map[kind]}",
                f"remote_{kind}",
                default_ext_map[kind],
            )
            dest_path = dest_dir / safe_name

            total = 0
            with open(dest_path, "wb") as handle:
                for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Remote download exceeded {max_bytes // (1024 * 1024)} MB limit.")
                    handle.write(chunk)
            if total == 0:
                raise ValueError("Downloaded remote file is empty.")
            return dest_path, kind


def extract_images_from_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Safely extract supported images from a ZIP archive with zip-slip & zip-bomb guards."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total_bytes = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for idx, info in enumerate(zf.infolist()):
            if info.is_dir():
                continue
            member_path = Path(info.filename)
            if any(part == "__MACOSX" or part.startswith(".") for part in member_path.parts):
                continue
            if member_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if len(extracted) >= MAX_ZIP_IMAGES:
                raise ValueError(f"ZIP contains more than {MAX_ZIP_IMAGES} images (per-archive limit).")
            total_bytes += info.file_size
            if total_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"Uncompressed ZIP size exceeds {MAX_ZIP_UNCOMPRESSED_BYTES // (1024 * 1024)} MB limit."
                )

            safe_name = sanitize_filename(member_path.name, f"img_{idx:03d}", member_path.suffix.lower() or ".png")
            out_path = dest_dir / f"{idx:03d}_{safe_name}"
            with zf.open(info, "r") as src_stream, open(out_path, "wb") as dst_stream:
                while chunk := src_stream.read(1024 * 256):
                    dst_stream.write(chunk)
            extracted.append(out_path)

    return extracted


def pack_files_to_zip(files: list[tuple[Path, str]], out_zip: Path) -> Path:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in files:
            zf.write(file_path, arcname=arcname)
    return out_zip


def inject_camera_exif(image_path: Path, profile: str) -> Path:
    """Write neutral, realistic camera EXIF (no GPS, zero AI tags) onto a cleaned photo."""
    if profile == EXIF_OFF or profile not in VALID_EXIF_PROFILES:
        return image_path

    import piexif
    from PIL import Image

    now_str = dt.datetime.now(dt.UTC).strftime("%Y:%m:%d %H:%M:%S").encode("ascii")

    if profile == EXIF_SONY:
        zeroth = {
            piexif.ImageIFD.Make: b"SONY",
            piexif.ImageIFD.Model: b"ILCE-7M4",
            piexif.ImageIFD.Software: b"ILCE-7M4 v3.01",
            piexif.ImageIFD.DateTime: now_str,
            piexif.ImageIFD.Orientation: 1,
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: now_str,
            piexif.ExifIFD.DateTimeDigitized: now_str,
            piexif.ExifIFD.ExposureTime: (1, 320),
            piexif.ExifIFD.FNumber: (20, 10),
            piexif.ExifIFD.ISOSpeedRatings: 100,
            piexif.ExifIFD.FocalLength: (35, 1),
            piexif.ExifIFD.FocalLengthIn35mmFilm: 35,
            piexif.ExifIFD.LensMake: b"SONY",
            piexif.ExifIFD.LensModel: b"FE 35mm F1.4 GM",
            piexif.ExifIFD.ColorSpace: 1,
        }
    else:
        zeroth = {
            piexif.ImageIFD.Make: b"Apple",
            piexif.ImageIFD.Model: b"iPhone 16 Pro",
            piexif.ImageIFD.Software: b"18.2",
            piexif.ImageIFD.DateTime: now_str,
            piexif.ImageIFD.Orientation: 1,
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: now_str,
            piexif.ExifIFD.DateTimeDigitized: now_str,
            piexif.ExifIFD.ExposureTime: (1, 250),
            piexif.ExifIFD.FNumber: (178, 100),
            piexif.ExifIFD.ISOSpeedRatings: 64,
            piexif.ExifIFD.FocalLength: (6765, 1000),
            piexif.ExifIFD.FocalLengthIn35mmFilm: 24,
            piexif.ExifIFD.LensMake: b"Apple",
            piexif.ExifIFD.LensModel: b"iPhone 16 Pro back triple camera 6.765mm f/1.78",
            piexif.ExifIFD.ColorSpace: 1,
        }

    exif_bytes = piexif.dump({"0th": zeroth, "Exif": exif_ifd, "GPS": {}, "1st": {}, "thumbnail": None})

    if image_path.suffix.lower() in {".jpg", ".jpeg"}:
        piexif.insert(exif_bytes, str(image_path))
        return image_path

    jpg_out = image_path.with_suffix(".jpg")
    with Image.open(image_path) as im:
        im.convert("RGB").save(jpg_out, format="JPEG", quality=96, subsampling=0, exif=exif_bytes)
    return jpg_out


def ensure_video_mp4_if_needed(src: Path, work_dir: Path, needs_isobmff: bool) -> Path:
    allowed = {".mp4", ".mov", ".m4v"} if needs_isobmff else {".mp4", ".mov", ".m4v", ".mkv"}
    if src.suffix.lower() in allowed:
        return src
    converted = work_dir / f"{src.stem}_converted.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", str(converted),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return converted


def apply_natural_film_polish(src: Path, dst: Path) -> Path:
    """Apply subtle unsharp + natural temporal grain using fast high-fidelity x264."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-vf", "unsharp=5:5:0.45:3:3:0.0,noise=c0s=4:allf=t+u",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-threads", "0", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return dst


def cleanup_expired_dirs(base_dir: Path, max_age_sec: int = DOWNLOAD_LINK_TTL_SEC) -> None:
    if not base_dir.exists():
        return
    now = time.time()
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        expired = False
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                expired = now > float(meta.get("expires_at", 0))
            except Exception:
                expired = True
        else:
            try:
                expired = (now - child.stat().st_mtime) > max_age_sec
            except Exception:
                expired = False
        if expired:
            shutil.rmtree(child, ignore_errors=True)
