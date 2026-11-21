"""Unit tests for Domain models, deterministic policies, and media I/O utilities."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

from nomark.config import (
    EXIF_IPHONE,
    EXIF_OFF,
    EXIF_SONY,
    LANG_EN,
    LANG_RU,
    MODE_C2PA_ONLY,
    MODE_ERASE,
    MODE_FULL_FAST,
    MODE_FULL_HD,
    MODE_IDENTIFY,
    MODE_VISIBLE,
    PHOTO_OUT_DOCUMENT,
    PHOTO_OUT_PHOTO,
    STRENGTH_BALANCED,
    STRENGTH_SOFT,
    STRENGTH_STRONG,
    VENDOR_AUTO,
    VENDOR_GOOGLE,
    VENDOR_META,
    VENDOR_OPENAI,
)
from nomark.domain.models import UserSettings
from nomark.domain.policies import (
    build_result_cache_key,
    check_budget_status,
    choose_output_filename,
    clamp_custom_box,
    compute_corner_box,
    empty_stats,
    estimate_spend_usd,
    extract_media_from_message,
    extract_url_from_text,
    infer_lang_from_telegram_user,
    is_user_allowed,
    merge_stat_delta,
    normalize_lang,
    parse_allowed_user_ids,
    parse_box_coords,
    resolve_photo_vendor,
    rewrite_cloud_download_url,
    verify_webhook_secret,
)
from nomark.infrastructure.media_io import (
    extract_images_from_zip,
    inject_camera_exif,
    pack_files_to_zip,
)


class DomainModelTests(unittest.TestCase):
    def test_user_settings_defaults_and_cycles(self) -> None:
        s = UserSettings.from_raw(None)
        self.assertEqual(s.mode, MODE_FULL_HD)
        self.assertEqual(s.video_strength, STRENGTH_BALANCED)
        self.assertEqual(s.photo_vendor, VENDOR_AUTO)
        self.assertEqual(s.camera_exif, EXIF_OFF)
        self.assertTrue(s.clean_audio)
        self.assertTrue(s.natural_polish)
        self.assertEqual(s.photo_output, PHOTO_OUT_DOCUMENT)
        self.assertEqual(s.lang, LANG_RU)
        self.assertFalse(s.lang_chosen)

        self.assertEqual(s.next_strength(), STRENGTH_STRONG)
        self.assertEqual(s.with_updates(video_strength=STRENGTH_STRONG).next_strength(), STRENGTH_SOFT)
        self.assertEqual(s.next_vendor(), VENDOR_GOOGLE)
        self.assertEqual(s.with_updates(photo_vendor=VENDOR_META).next_vendor(), VENDOR_AUTO)
        self.assertEqual(s.next_exif(), EXIF_IPHONE)
        self.assertEqual(s.with_updates(camera_exif=EXIF_IPHONE).next_exif(), EXIF_SONY)
        self.assertEqual(s.with_updates(camera_exif=EXIF_SONY).next_exif(), EXIF_OFF)
        self.assertEqual(s.next_lang(), LANG_EN)
        self.assertEqual(s.with_updates(lang=LANG_EN).next_lang(), LANG_RU)

    def test_legacy_string_mode_migrates_cleanly(self) -> None:
        s = UserSettings.from_raw("visible", default_lang=LANG_EN)
        self.assertEqual(s.mode, MODE_VISIBLE)
        self.assertEqual(s.lang, LANG_EN)
        self.assertFalse(s.lang_chosen)

    def test_roundtrip_serialization_preserves_lang_chosen(self) -> None:
        s = UserSettings.from_raw(
            {"mode": MODE_FULL_FAST, "lang": "en", "lang_chosen": True, "camera_exif": EXIF_SONY}
        )
        restored = UserSettings.from_raw(s.to_dict())
        self.assertEqual(restored, s)


class PolicyTests(unittest.TestCase):
    def test_lang_normalization_and_inference(self) -> None:
        self.assertEqual(normalize_lang("ru"), LANG_RU)
        self.assertEqual(normalize_lang("uk-UA"), LANG_RU)
        self.assertEqual(normalize_lang("en-US"), LANG_EN)
        self.assertEqual(normalize_lang("de"), LANG_EN)
        self.assertEqual(infer_lang_from_telegram_user({"language_code": "en-GB"}), LANG_EN)
        self.assertEqual(infer_lang_from_telegram_user({"language_code": "ru"}), LANG_RU)
        self.assertEqual(infer_lang_from_telegram_user(None), LANG_EN)

    def test_webhook_secret_and_allowlist(self) -> None:
        self.assertTrue(verify_webhook_secret("abc123", "abc123"))
        self.assertFalse(verify_webhook_secret("wrong", "abc123"))
        self.assertFalse(verify_webhook_secret(None, "abc123"))
        self.assertTrue(verify_webhook_secret(None, None))

        self.assertEqual(parse_allowed_user_ids("111, 222;333\n444"), frozenset({111, 222, 333, 444}))
        self.assertTrue(is_user_allowed(999, None))
        self.assertTrue(is_user_allowed(222, "111,222"))
        self.assertFalse(is_user_allowed(999, "111,222"))
        self.assertFalse(is_user_allowed(None, "111,222"))

    def test_resolve_photo_vendor(self) -> None:
        self.assertEqual(resolve_photo_vendor(VENDOR_AUTO, "OpenAI ChatGPT"), ("openai", None))
        self.assertEqual(resolve_photo_vendor(VENDOR_AUTO, "Meta AI"), ("meta", 0.20))
        self.assertEqual(resolve_photo_vendor(VENDOR_AUTO, "Google Gemini"), ("google", None))
        self.assertEqual(resolve_photo_vendor(VENDOR_AUTO, None), ("google", None))
        self.assertEqual(resolve_photo_vendor(VENDOR_OPENAI, "Google Gemini"), ("openai", None))
        self.assertEqual(resolve_photo_vendor(VENDOR_META, None), ("meta", 0.20))

    def test_erase_corner_and_box_coords(self) -> None:
        for corner in ("tl", "tr", "bl", "br", "bc", "center"):
            x, y, bw, bh = compute_corner_box(1920, 1080, corner)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + bw, 1920)
            self.assertLessEqual(y + bh, 1080)

        self.assertEqual(parse_box_coords("100, 200, 300, 150", 1920, 1080), (100, 200, 300, 150))
        self.assertEqual(parse_box_coords("1800 1000 500 500", 1920, 1080), (1800, 1000, 120, 80))
        self.assertIsNone(parse_box_coords("not coords", 1920, 1080))
        self.assertEqual(clamp_custom_box((1800, 1000, 500, 500), 1920, 1080), (1800, 1000, 120, 80))
        self.assertIsNone(clamp_custom_box((2000, 100, 50, 50), 1920, 1080))

    def test_result_cache_key_semantics(self) -> None:
        k1 = build_result_cache_key(file_unique_id="u1", kind="image", mode=MODE_FULL_HD)
        k2 = build_result_cache_key(file_unique_id="u1", kind="image", mode=MODE_FULL_FAST)
        k3 = build_result_cache_key(file_unique_id="u1", kind="image", mode=MODE_FULL_HD, camera_exif=EXIF_IPHONE)
        self.assertIsNotNone(k1)
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

        v1 = build_result_cache_key(file_unique_id="v1", kind="video", mode=MODE_FULL_HD, video_strength=STRENGTH_SOFT)
        v2 = build_result_cache_key(file_unique_id="v1", kind="video", mode=MODE_FULL_HD, video_strength=STRENGTH_STRONG)
        self.assertNotEqual(v1, v2)

        self.assertIsNone(build_result_cache_key(file_unique_id="u1", kind="image", mode=MODE_IDENTIFY))
        self.assertIsNone(build_result_cache_key(file_unique_id="u1", kind="image", mode=MODE_ERASE))
        self.assertIsNone(build_result_cache_key(file_unique_id=None, kind="image", mode=MODE_FULL_HD))

    def test_stats_and_budget_guard(self) -> None:
        st = empty_stats("2026-11")
        st = merge_stat_delta(st, month="2026-11", field="photos", tier="l4", seconds=100.0)
        st = merge_stat_delta(st, month="2026-11", field="videos_hd", tier="h100", seconds=200.0)
        st = merge_stat_delta(st, month="2026-11", field="cache_hits", tier="cpu", seconds=0.0)
        self.assertEqual(st["photos"], 1)
        self.assertEqual(st["videos_hd"], 1)
        self.assertEqual(st["cache_hits"], 1)
        self.assertGreater(estimate_spend_usd(st), 0.2)

        st_warn = merge_stat_delta(None, month="2026-11", field="videos_hd", tier="h100", seconds=22500.0)
        self.assertEqual(check_budget_status(st_warn, guard_enabled=True)[0], "warn")

        st_block = merge_stat_delta(None, month="2026-11", field="videos_hd", tier="h100", seconds=26000.0)
        self.assertEqual(check_budget_status(st_block, guard_enabled=True)[0], "blocked")
        self.assertEqual(check_budget_status(st_block, guard_enabled=False)[0], "warn")

    def test_urls_filenames_and_media_extraction(self) -> None:
        self.assertEqual(
            extract_url_from_text("Clean this: https://drive.google.com/file/d/AbC_123/view?usp=sharing."),
            "https://drive.google.com/file/d/AbC_123/view?usp=sharing",
        )
        self.assertEqual(
            rewrite_cloud_download_url("https://drive.google.com/file/d/AbC_123/view?usp=sharing"),
            "https://drive.usercontent.google.com/download?id=AbC_123&export=download&confirm=t",
        )
        self.assertIn("dl=1", rewrite_cloud_download_url("https://www.dropbox.com/s/xyz/clip.mp4?dl=0"))
        self.assertEqual(choose_output_filename("pic.heic", "image"), "pic_clean.png")
        self.assertEqual(choose_output_filename("clip.webm", "video"), "clip_clean.mp4")

        photo_item = extract_media_from_message(
            {
                "photo": [
                    {"file_id": "small", "file_unique_id": "u_s", "file_size": 1000, "width": 100},
                    {"file_id": "big", "file_unique_id": "u_b", "file_size": 9000, "width": 1200},
                ]
            }
        )
        self.assertIsNotNone(photo_item)
        assert photo_item is not None
        self.assertEqual(photo_item.file_id, "big")
        self.assertEqual(photo_item.file_unique_id, "u_b")
        self.assertTrue(photo_item.compressed_by_telegram)

        zip_item = extract_media_from_message(
            {"document": {"file_id": "z1", "file_unique_id": "uz1", "file_name": "batch.zip", "mime_type": "application/zip"}}
        )
        self.assertIsNotNone(zip_item)
        assert zip_item is not None
        self.assertEqual(zip_item.kind, "zip")


class MediaIoTests(unittest.TestCase):
    def test_zip_extract_and_pack_filters_macosx_and_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_zip = root / "in.zip"
            with zipfile.ZipFile(src_zip, "w") as zf:
                zf.writestr("a.png", b"PNGDATA")
                zf.writestr("sub/b.jpg", b"JPGDATA")
                zf.writestr("__MACOSX/._a.png", b"JUNK")
                zf.writestr("notes.txt", b"IGNORED")

            extracted = extract_images_from_zip(src_zip, root / "ext")
            self.assertEqual(len(extracted), 2)

            out_zip = pack_files_to_zip([(p, p.name) for p in extracted], root / "out.zip")
            with zipfile.ZipFile(out_zip, "r") as zf:
                self.assertEqual(len(zf.namelist()), 2)

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None and importlib.util.find_spec("piexif") is not None,
        "Requires PIL + piexif",
    )
    def test_inject_camera_exif_writes_clean_camera_tags(self) -> None:
        import piexif
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "clean.png"
            Image.new("RGB", (64, 64), (100, 120, 140)).save(img_path)

            out_iphone = inject_camera_exif(img_path, EXIF_IPHONE)
            self.assertEqual(out_iphone.suffix.lower(), ".jpg")
            exif = piexif.load(str(out_iphone))
            self.assertEqual(exif["0th"][piexif.ImageIFD.Make], b"Apple")
            self.assertEqual(exif["0th"][piexif.ImageIFD.Model], b"iPhone 16 Pro")
            self.assertEqual(exif["GPS"], {})

            if importlib.util.find_spec("remove_ai_watermarks") is not None:
                from remove_ai_watermarks.metadata import get_ai_metadata

                self.assertEqual(get_ai_metadata(out_iphone), {})


if __name__ == "__main__":
    unittest.main()
